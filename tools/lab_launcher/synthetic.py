"""Publica leituras sintéticas no contrato MQTT existente."""

from __future__ import annotations

import json
import math
import secrets
import time
from dataclasses import dataclass
from threading import Event
from uuid import uuid4

import paho.mqtt.client as mqtt

from api.epc import normalizar_epc
from rfid_ingestion.config import Settings
from rfid_ingestion.connection import create_client
from rfid_ingestion.topics import reading_topic


@dataclass(frozen=True)
class Etapa:
    nome: str
    porta: int
    quantidade: int
    pausa: float
    rssi_inicial: int
    rssi_final: int


@dataclass(frozen=True)
class LeituraPlanejada:
    epc: str
    porta: int
    pausa_antes: float
    rssi: int


def programa_multitag(cenario: int, epcs: list[str], mensagens: int,
                      intervalo: float) -> tuple[LeituraPlanejada, ...]:
    """Percursos em fases; leituras de tags simultâneas são intercaladas."""
    if cenario not in (2, 3) or len(epcs) != 2:
        raise ValueError("roteiros 2 e 3 exigem exatamente dois EPCs")
    if not 10 <= mensagens <= 1000:
        raise ValueError("cada travessia exige entre 10 e 1000 mensagens por EPC")
    if not math.isfinite(intervalo) or intervalo < 0:
        raise ValueError("intervalo entre antenas deve ser finito e não negativo")
    a, b = epcs
    fases = (
        (((a, 1, 2),), ((a, 2, 1), (b, 1, 2)),
         ((a, 1, 2), (b, 2, 1))) if cenario == 2 else
        (((a, 1, 2), (b, 1, 2)), ((b, 2, 1),),
         ((b, 1, 2),), ((b, 2, 1),))
    )
    origem = mensagens // 2
    destino = mensagens - origem
    resultado: list[LeituraPlanejada] = []
    for indice_fase, fase in enumerate(fases):
        for indice in range(origem):
            for epc, porta_origem, _ in fase:
                pausa = 3.5 if indice_fase and indice == 0 and epc == fase[0][0] else 0.10
                resultado.append(LeituraPlanejada(epc, porta_origem, pausa, -6000))
        for indice in range(destino):
            for epc, _, porta_destino in fase:
                pausa = intervalo if indice == 0 and epc == fase[0][0] else 0.10
                resultado.append(LeituraPlanejada(epc, porta_destino, pausa, -5700))
    return tuple(resultado)


def roteiro(mensagens: int, passagem: bool) -> tuple[Etapa, ...]:
    """Cenário ilustrativo: aproximação, permanência e travessia do portal."""
    if passagem and mensagens < 10:
        raise ValueError("passagem sintética exige ao menos 10 mensagens por EPC")
    if mensagens < 1:
        raise ValueError("quantidade de mensagens deve ser positiva")
    if not passagem:
        aproximacao = max(1, round(mensagens * 0.2))
        return (
            Etapa("aproximação da antena 1", 1, aproximacao, 0.10, -6700, -5700),
            Etapa("parado na antena 1", 1, mensagens - aproximacao, 0.15, -5700, -5700),
        )
    aproximacao = round(mensagens * 0.15)
    permanencia = round(mensagens * 0.45)
    saida = round(mensagens * 0.10)
    travessia = mensagens - aproximacao - permanencia - saida
    return (
        Etapa("aproximação da antena 1", 1, aproximacao, 0.10, -6700, -5700),
        Etapa("parado na antena 1", 1, permanencia, 0.15, -5700, -5700),
        Etapa("saída da antena 1", 1, saida, 0.08, -5700, -6700),
        Etapa("passagem pela antena 2", 2, travessia, 0.10, -6700, -5700),
    )


def _falha_puback(topic: str, desconectado: bool) -> str:
    if desconectado:
        return (f"conexão MQTT encerrada antes do PUBACK para {topic}; confira se a "
                "credencial do publicador tem permissão Publish nesse tópico")
    return (f"sem PUBACK QoS 1 em 10 s para {topic}; confira conexão, permissão "
            "Publish e tópico da credencial do publicador")


def novo_contador(total: int) -> int:
    """Reserva um intervalo de sete dígitos para identificar este ensaio."""
    if total < 1 or total >= 9_000_000:
        raise ValueError("quantidade de mensagens excede o contador sintético de sete dígitos")
    return 1_000_000 + secrets.randbelow(9_000_000 - total)


def publicar(config: dict[str, str], reader_id: str, *, epcs: list[str],
             passagem: bool, intervalo: float, portal_id: str = "portal-01",
             mensagens: int = 100,
             timestamp_format: str = "counter",
             contador_inicial: int | None = None, cenario: int = 1) -> int:
    if not math.isfinite(intervalo) or intervalo < 0:
        raise ValueError("intervalo entre antenas deve ser finito e não negativo")
    if timestamp_format != "counter":
        raise ValueError("o JSON sintético do leitor exige timestamp no formato counter")
    if not epcs:
        raise ValueError("informe EPCs hexadecimais válidos")
    etapas = roteiro(mensagens, passagem) if cenario == 1 else ()
    epcs = [normalizar_epc(epc) for epc in epcs]
    programa = programa_multitag(cenario, epcs, mensagens, intervalo) if cenario != 1 else ()
    total_esperado = len(programa) if programa else len(epcs) * mensagens
    contador = novo_contador(total_esperado) if contador_inicial is None else contador_inicial
    if contador < 1_000_000 or contador + total_esperado > 10_000_000:
        raise ValueError("intervalo do contador sintético deve ter sete dígitos")
    assinatura = config.get("MQTT_TOPIC", "easy/dev/hupaa/+/+/readings").split("/")
    ambiente = assinatura[1] if len(assinatura) == 6 and assinatura[1] != "+" else "dev"
    site = assinatura[2] if len(assinatura) == 6 and assinatura[2] != "+" else "hupaa"
    topic = reading_topic(reader_id, ambiente, site, portal_id)
    source = dict(config, MQTT_TOPIC=topic, MQTT_CLIENT_ID=f"lab-publisher-{uuid4().hex[:12]}")
    settings = Settings.from_env(source)
    if not mqtt.topic_matches_sub(config.get("MQTT_TOPIC", "easy/dev/hupaa/+/+/readings"),
                                  topic):
        raise ValueError("tópico sintético não corresponde à assinatura do ingestor")
    client = create_client(settings)
    conectado = Event()
    desconectado = Event()
    erro = []

    def on_connect(_client, _userdata, _flags, reason_code, _properties):
        if reason_code.is_failure:
            erro.append("conexão MQTT do publicador recusada; confira a credencial")
        conectado.set()

    def on_disconnect(_client, _userdata, _flags, _reason_code, _properties):
        desconectado.set()

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    try:
        client.connect(settings.mqtt_host, settings.mqtt_port, settings.mqtt_keepalive)
        client.loop_start()
        if not conectado.wait(10):
            raise RuntimeError("publicador não recebeu CONNACK do broker em 10 s")
        if erro:
            raise RuntimeError(erro[0])
        total = 0
        def emitir(epc: str, porta: int, rssi: int) -> None:
            nonlocal total
            payload = {"epc": epc, "rssi": rssi, "antenna": porta,
                       "timestamp": str(contador + total)}
            result = client.publish(topic, json.dumps(payload, separators=(",", ":")), qos=1)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(f"MQTT não enfileirou a leitura para {topic}: "
                                   f"{mqtt.error_string(result.rc)}")
            try:
                result.wait_for_publish(timeout=10)
            except RuntimeError:
                raise RuntimeError(_falha_puback(topic, desconectado.is_set())) from None
            if not result.is_published():
                raise RuntimeError(_falha_puback(topic, desconectado.is_set()))
            total += 1
            print(f"Mensagem {total}/{total_esperado}: EPC {epc}, antena {porta}", flush=True)

        if programa:
            for leitura in programa:
                time.sleep(leitura.pausa_antes)
                emitir(leitura.epc, leitura.porta, leitura.rssi)
            return total
        for epc in epcs:
            for etapa in etapas:
                if etapa.porta == 2:
                    print(f"EPC {epc}: deslocamento até a antena 2 ({intervalo:g}s)",
                          flush=True)
                    time.sleep(intervalo)
                print(f"EPC {epc}: {etapa.nome}, {etapa.quantidade} mensagem(ns)",
                      flush=True)
                for indice in range(etapa.quantidade):
                    fracao = indice / max(etapa.quantidade - 1, 1)
                    rssi = round(etapa.rssi_inicial
                                 + (etapa.rssi_final - etapa.rssi_inicial) * fracao)
                    emitir(epc, etapa.porta, rssi)
                    if indice + 1 < etapa.quantidade:
                        time.sleep(etapa.pausa)
        return total
    finally:
        client.disconnect()
        client.loop_stop()


def epcs_padrao(quantidade: int) -> list[str]:
    if quantidade < 1:
        raise ValueError("quantidade deve ser positiva")
    if quantidade > 0xFFFFFFFFFFFF:
        raise ValueError("quantidade excede o limite de EPCs sintéticos")
    return [f"E2804C414200{indice:012X}" for indice in range(1, quantidade + 1)]
