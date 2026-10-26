"""Laboratório: publicador sintético, equivalência do simulador web com o Flet e cadastro."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from api.simulacao.geometria import RSSI_LONGE, RSSI_PERTO, antenas_do_layout, detectar
from api.simulacao.motor import EstadoSessao
from api.simulacao.presets import preset
from api.simulacao.service import PREFIXO_EPC
from db.models import AssociacaoTagEquipamento, Equipamento, Tag
from rfid_ingestion.config import Settings
from rfid_ingestion.parsing import build_event
from tools.lab_launcher import synthetic
from tools.lab_launcher.seed import TIPO_SINTETICO, semear, semear_equipamentos

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
        publicador.emitir(PREFIXO_EPC + "0" * 16, 1, -6000)


def test_publicador_falha_quando_puback_demora(monkeypatch):
    relogio = SimpleNamespace(agora=100.0)
    monkeypatch.setattr(synthetic.time, "monotonic", lambda: relogio.agora)
    monkeypatch.setattr(synthetic, "create_client", lambda settings: Cliente(confirmado=False))
    publicador = synthetic.Publicador(LOCAL, "reader-01")
    publicador.conectar()
    publicador.emitir(PREFIXO_EPC + "0" * 16, 1, -6000)
    assert publicador.pendentes == 1
    relogio.agora += synthetic.LIMITE_PUBACK_S + 1
    with pytest.raises(RuntimeError, match="sem PUBACK"):
        publicador.conferir()


# Preset EASY: mesma proporção 880 x 560 e período de 0,2 s do simulador Flet removido;
# desde o hotfix, antenas direcionais (visada 270° = para cima, para dentro das salas),
# alcance 11 na frente e 35% atrás.
PRESET_EASY = preset("easy")
ANTENAS = antenas_do_layout(PRESET_EASY)
PROPORCAO = PRESET_EASY["proporcao"]


def test_alcance_das_antenas_e_rssi_por_distancia():
    antena_a, antena_b = ANTENAS
    assert (antena_a.x, antena_a.y, antena_a.alcance, antena_a.orientacao) == (28, 66, 11, 270)
    assert [(a.porta, valor) for a, valor in detectar(antena_a.x, antena_a.y, ANTENAS, PROPORCAO)] == [
        (1, RSSI_PERTO)]
    # Borda da visada direta (para cima): o mesmo raio em pixels vale mais unidades em y.
    frente_y = antena_b.alcance * PROPORCAO
    borda = detectar(antena_b.x, antena_b.y - frente_y, ANTENAS, PROPORCAO)
    assert [(a.porta, valor) for a, valor in borda] == [(2, RSSI_LONGE)]
    assert detectar(50, 20, ANTENAS, PROPORCAO) == []
    assert [a.porta for a, _ in detectar(antena_a.x, antena_a.y - frente_y + 0.5, ANTENAS, PROPORCAO)] == [1]
    assert detectar(antena_a.x, antena_a.y - frente_y - 0.5, ANTENAS, PROPORCAO) == []
    # Atrás da antena (para baixo) o alcance é só 35% do da frente.
    tras_y = antena_a.alcance * antena_a.fator_traseiro * PROPORCAO
    assert [a.porta for a, _ in detectar(antena_a.x, antena_a.y + tras_y - 0.3, ANTENAS, PROPORCAO)] == [1]
    assert detectar(antena_a.x, antena_a.y + tras_y + 0.5, ANTENAS, PROPORCAO) == []
    assert math.hypot(antena_a.x - antena_b.x, antena_a.y - antena_b.y) > 2 * antena_a.alcance


def test_leituras_seguem_o_periodo_e_a_antena_do_alcance():
    antena_a, antena_b = ANTENAS
    item = {"id": "i1", "epc": PREFIXO_EPC + "1" * 16, "x": antena_a.x, "y": antena_a.y}
    estado = EstadoSessao(1, "x", 1, "sim-l1", PROPORCAO, ANTENAS,
                          {"sim-easy-01": "easy/dev/hupaa/sim-l1/sim-easy-01/readings"}, [item])
    assert [(porta, rssi) for _, _, porta, rssi, _, _ in estado.devidas(10.0, 0.2)] == [(1, RSSI_PERTO)]
    assert estado.devidas(10.1, 0.2) == []
    assert len(estado.devidas(10.2, 0.2)) == 1
    item.update(x=antena_b.x, y=antena_b.y)
    assert [porta for _, _, porta, _, _, _ in estado.devidas(10.5, 0.2)] == [2]
    item.update(x=50, y=20)
    assert estado.devidas(11.0, 0.2) == []


def test_tags_do_laboratorio_viram_equipamentos_nomeados(db):
    semear(db)
    pares = [(PREFIXO_EPC + "A" * 16, "Bomba de infusão 01"), (PREFIXO_EPC + "B" * 16, "Monitor 02")]
    primeiro = semear_equipamentos(db, pares, TIPO_SINTETICO)
    segundo = semear_equipamentos(db, pares, TIPO_SINTETICO)
    assert all("equipamento criado" in valor for valor in primeiro.values())
    assert all("vínculo existente" in valor for valor in segundo.values())
    nomes = set(db.scalars(select(Equipamento.nome)))
    assert nomes == {"Bomba de infusão 01", "Monitor 02"}
    assert db.scalar(select(func.count()).select_from(Tag)) == 2
    assert db.scalar(select(func.count()).select_from(AssociacaoTagEquipamento)) == 2
