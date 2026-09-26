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


def publicar(config: dict[str, str], reader_id: str, *, epcs: list[str],
             passagem: bool, intervalo: float, portal_id: str = "portal-01",
             mensagens: int = 100,
             timestamp_format: str = "counter") -> int:
    if not math.isfinite(intervalo) or intervalo < 0:
        raise ValueError("intervalo entre antenas deve ser finito e não negativo")
    if timestamp_format != "counter":
        raise ValueError("o JSON sintético do leitor exige timestamp no formato counter")
    if not epcs:
        raise ValueError("informe EPCs hexadecimais válidos")
    etapas = roteiro(mensagens, passagem)
    epcs = [normalizar_epc(epc) for epc in epcs]
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
    erro = []

    def on_connect(_client, _userdata, _flags, reason_code, _properties):
        if reason_code.is_failure:
            erro.append("conexão MQTT recusada")
        conectado.set()

    client.on_connect = on_connect
    try:
        client.connect(settings.mqtt_host, settings.mqtt_port, settings.mqtt_keepalive)
        client.loop_start()
        if not conectado.wait(10) or erro:
            raise RuntimeError("broker MQTT indisponível")
        total = 0
        contador = 1_000_000 + secrets.randbelow(8_000_000)
        for epc in epcs:
            for etapa in etapas:
                if etapa.porta == 2:
                    print(f"EPC {epc}: deslocamento até a antena 2 ({intervalo:g}s)",
                          flush=True)
                    time.sleep(intervalo)
                print(f"EPC {epc}: {etapa.nome}, {etapa.quantidade} mensagem(ns)",
                      flush=True)
                for indice in range(etapa.quantidade):
                    timestamp = str(contador + total)
                    fracao = indice / max(etapa.quantidade - 1, 1)
                    rssi = round(etapa.rssi_inicial
                                 + (etapa.rssi_final - etapa.rssi_inicial) * fracao)
                    payload = {
                        "epc": epc,
                        "rssi": rssi,
                        "antenna": etapa.porta,
                        "timestamp": timestamp,
                    }
                    result = client.publish(topic, json.dumps(payload, separators=(",", ":")),
                                            qos=1)
                    result.wait_for_publish(timeout=10)
                    if not result.is_published():
                        raise RuntimeError("broker não confirmou a leitura sintética")
                    total += 1
                    print(f"Mensagem {total}/{len(epcs) * mensagens}: EPC {epc}, "
                          f"antena {etapa.porta}, {etapa.nome}", flush=True)
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
