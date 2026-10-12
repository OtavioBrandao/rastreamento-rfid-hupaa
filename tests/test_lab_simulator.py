"""Simulador visual: regras de detecção, publicação MQTT e cadastro dos itens."""

from __future__ import annotations

import json
import math
import random
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from db.models import AssociacaoTagEquipamento, Equipamento, Tag
from rfid_ingestion.config import Settings
from rfid_ingestion.parsing import build_event
from tools.lab_launcher import synthetic
from tools.lab_launcher.seed import TIPO_SINTETICO, semear, semear_equipamentos
from tools.lab_simulator import modelo

LOCAL = {"MQTT_HOST": "localhost", "MQTT_PORT": "1883", "MQTT_MODE": "local"}


class Resultado:
    rc = synthetic.mqtt.MQTT_ERR_SUCCESS

    def __init__(self, confirmado: bool = True) -> None:
        self.confirmado = confirmado

    def is_published(self):
        return self.confirmado


class Cliente:
    def __init__(self, confirmado: bool = True, desconecta: bool = False) -> None:
        self.publicados: list[tuple[str, str, int]] = []
        self.confirmado = confirmado
        self.desconecta = desconecta

    def connect(self, host, port, keepalive):
        assert (host, port) == ("localhost", 1883)

    def loop_start(self):
        self.on_connect(self, None, None, SimpleNamespace(is_failure=False), None)

    def publish(self, topic, payload, qos):
        self.publicados.append((topic, payload, qos))
        if self.desconecta:
            self.on_disconnect(self, None, None, None, None)
        return Resultado(self.confirmado)

    def disconnect(self):
        pass

    def loop_stop(self):
        pass


def test_publicador_mantem_contrato_do_leitor(monkeypatch):
    cliente = Cliente()
    monkeypatch.setattr(synthetic, "create_client", lambda settings: cliente)
    publicador = synthetic.Publicador(LOCAL, "reader-01", contador_inicial=1_234_567)
    publicador.conectar()
    publicador.emitir("e2801190a502006016c32f62", 1, -6100)
    publicador.emitir("E2801190A502006016C32F62", 2, -5700)
    publicador.fechar()

    assert publicador.publicadas == publicador.confirmadas == 2
    assert [topic for topic, _, _ in cliente.publicados] == [
        "easy/dev/hupaa/portal-01/reader-01/readings"] * 2
    assert all(qos == 1 for _, _, qos in cliente.publicados)
    brutos = [payload for _, payload, _ in cliente.publicados]
    assert brutos[0] == ('{"epc":"E2801190A502006016C32F62","rssi":-6100,'
                         '"antenna":1,"timestamp":"1234567"}')
    assert json.loads(brutos[1])["timestamp"] == "1234568"
    settings = Settings.from_env({"EZ700_TIMESTAMP_FORMAT": "counter"})
    for topic, payload, _ in cliente.publicados:
        evento = build_event(topic=topic, qos=1, retain=False, payload=payload.encode(),
                             settings=settings, received_at=datetime.now(timezone.utc))
        assert evento["validation_errors"] == []
        assert evento["canonical_event"]["metadata"]["timestamp_format"] == "received_at_utc"


def test_publicador_usa_ambiente_e_site_da_assinatura():
    config = dict(LOCAL, MQTT_TOPIC="easy/prod/outro/portal-01/reader-01/readings")
    assert synthetic.topico_sintetico(config, "reader-01", "portal-01") == (
        "easy/prod/outro/portal-01/reader-01/readings")
    with pytest.raises(ValueError, match="assinatura do ingestor"):
        synthetic.topico_sintetico(config, "reader-02", "portal-01")


def test_publicador_indica_falta_de_puback_apos_desconexao(monkeypatch):
    cliente = Cliente(confirmado=False, desconecta=True)
    monkeypatch.setattr(synthetic, "create_client", lambda settings: cliente)
    publicador = synthetic.Publicador(LOCAL, "reader-01")
    publicador.conectar()
    with pytest.raises(RuntimeError, match="credencial do publicador tem permissão Publish"):
        publicador.emitir(modelo.PREFIXO_EPC + "0" * 16, 1, -6000)


def test_publicador_falha_quando_puback_demora(monkeypatch):
    relogio = SimpleNamespace(agora=100.0)
    monkeypatch.setattr(synthetic.time, "monotonic", lambda: relogio.agora)
    monkeypatch.setattr(synthetic, "create_client", lambda settings: Cliente(confirmado=False))
    publicador = synthetic.Publicador(LOCAL, "reader-01")
    publicador.conectar()
    publicador.emitir(modelo.PREFIXO_EPC + "0" * 16, 1, -6000)
    assert publicador.pendentes == 1
    relogio.agora += synthetic.LIMITE_PUBACK_S + 1
    with pytest.raises(RuntimeError, match="sem PUBACK"):
        publicador.conferir()


def test_alcance_das_antenas_e_rssi_por_distancia():
    antena_a, antena_b = modelo.ANTENAS
    assert [(a.porta, valor) for a, valor in modelo.detectar(antena_a.x, antena_a.y)] == [
        (1, modelo.RSSI_PERTO)]
    borda = modelo.detectar(antena_b.x + modelo.RAIO, antena_b.y)
    assert [(a.porta, valor) for a, valor in borda] == [(2, modelo.RSSI_LONGE)]
    assert modelo.detectar(50, 20) == []
    # Alcance circular na tela: o mesmo raio em pixels vale mais unidades em y.
    raio_y = modelo.RAIO / modelo.PROPORCAO_Y
    assert [a.porta for a, _ in modelo.detectar(antena_a.x, antena_a.y - raio_y + 0.5)] == [1]
    assert modelo.detectar(antena_a.x, antena_a.y - raio_y - 0.5) == []
    assert math.hypot(antena_a.x - antena_b.x, antena_a.y - antena_b.y) > 2 * modelo.RAIO


def test_itens_tem_epcs_unicos_e_surgem_fora_do_alcance():
    rng = random.Random(7)
    itens = modelo.criar_itens(["Bomba 01", "Monitor", "Cadeira", "Oxímetro"], rng)
    assert len({item.epc for item in itens}) == 4
    assert all(len(item.epc) == 24 and item.epc.startswith(modelo.PREFIXO_EPC)
               for item in itens)
    assert all(not modelo.detectar(item.x, item.y) for item in itens)
    outra = modelo.criar_itens(["Bomba 01", "Monitor", "Cadeira", "Oxímetro"],
                               random.Random(8))
    assert [(i.x, i.y) for i in itens] != [(i.x, i.y) for i in outra]
    with pytest.raises(ValueError, match="diferentes"):
        modelo.criar_itens(["Bomba", "bomba"], rng)
    with pytest.raises(ValueError, match="nome"):
        modelo.criar_itens(["Bomba", " "], rng)
    with pytest.raises(ValueError, match="de 1 a"):
        modelo.gerar_epcs(modelo.MAX_ITENS + 1, rng)


def test_leituras_seguem_o_periodo_e_a_antena_do_alcance():
    antena_a, antena_b = modelo.ANTENAS
    item = modelo.Item("Bomba", modelo.PREFIXO_EPC + "1" * 16, antena_a.x, antena_a.y)
    assert [(a.porta, v) for _, a, v in modelo.leituras_devidas([item], 10.0)] == [
        (1, modelo.RSSI_PERTO)]
    assert modelo.leituras_devidas([item], 10.0 + modelo.PERIODO_LEITURA_S / 2) == []
    assert len(modelo.leituras_devidas([item], 10.0 + modelo.PERIODO_LEITURA_S)) == 1
    item.x, item.y = antena_b.x, antena_b.y
    assert [a.porta for _, a, _ in modelo.leituras_devidas([item], 10.5)] == [2]
    item.x, item.y = 50, 20
    assert modelo.leituras_devidas([item], 11.0) == []
    assert modelo.limitar(-10, 150) == (modelo.MARGEM, 100 - modelo.MARGEM)


def test_itens_do_simulador_viram_equipamentos_nomeados(db):
    semear(db)
    itens = modelo.criar_itens(["Bomba de infusão 01", "Monitor 02"], random.Random(3))
    pares = [(item.epc, item.nome) for item in itens]
    primeiro = semear_equipamentos(db, pares, TIPO_SINTETICO)
    segundo = semear_equipamentos(db, pares, TIPO_SINTETICO)
    assert all("equipamento criado" in valor for valor in primeiro.values())
    assert all("vínculo existente" in valor for valor in segundo.values())
    nomes = set(db.scalars(select(Equipamento.nome)))
    assert nomes == {"Bomba de infusão 01", "Monitor 02"}
    assert db.scalar(select(func.count()).select_from(Tag)) == 2
    assert db.scalar(select(func.count()).select_from(AssociacaoTagEquipamento)) == 2
