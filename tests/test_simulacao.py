"""Simulador web: layout, topologia, sessão compartilhada, motor e pipeline real."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.database import get_db
from api.main import app
from api.router_simulacao import obter_config
from api.simulacao import config as config_simulador
from api.simulacao import service
from api.simulacao.esquema import Layout, avisos, ponto_unico
from api.simulacao.geometria import antenas_do_layout, detectar, distancia
from api.simulacao.motor import EstadoSessao, MotorSimulacao
from api.simulacao.presets import ITENS_TESTE_RAPIDO, POSICOES_TESTE_RAPIDO, preset
from api.simulacao.presets import teste_rapido as layout_teste_rapido
from api.simulacao.publicador import payload, topico_sintetico
from db.models import (
    Antena,
    AssociacaoTagEquipamento,
    Equipamento,
    HistoricoMovimentacao,
    Leitor,
    LeituraBruta,
    MapeamentoAntenaPortal,
    Passagem,
    Portal,
    SimulacaoLayout,
    Tag,
    TipoEquipamento,
    Zona,
)
from rfid_inference.direction_repository import DirectionRepository
from rfid_inference.direction_service import DirectionInferenceService
from rfid_inference.passage import PassageDetector
from rfid_inference.passage_repository import PassageRepository
from rfid_inference.passage_service import PassageInferenceService
from rfid_ingestion.config import Settings
from rfid_ingestion.mqtt_client import MqttReceiver
from rfid_ingestion.persistence import JsonlEventStore
from rfid_ingestion.repository import RawReadingRepository
from rfid_location.service import LocationProjectionService

HABILITADO = config_simulador.ConfigSimulador(True, "development", None, {"MQTT_MODE": "local"})
DESABILITADO = config_simulador.ConfigSimulador(False, "development", "desligado")
PRODUCAO = config_simulador.ConfigSimulador(False, "production", "bloqueado em produção")


# --- layout -----------------------------------------------------------------


def test_presets_sao_validos_e_hupaa_tem_quatro_leitores_sem_posicao():
    easy = Layout.model_validate(preset("easy"))
    assert [antena.zona for antena in easy.leitores[0].antenas] == ["zona-a", "zona-b"]
    hupaa = Layout.model_validate(preset("hupaa"))
    assert [(leitor.reader_id, leitor.modelo) for leitor in hupaa.leitores] == [
        ("sim-hupaa-01", "EZ700"), ("sim-hupaa-02", "EZ700"),
        ("sim-hupaa-03", "DR_MAX"), ("sim-hupaa-04", "DR_MAX")]
    assert all(leitor.posicao is None for leitor in hupaa.leitores)
    assert all(antena.posicao is None for leitor in hupaa.leitores for antena in leitor.antenas)
    escada = next(zona for zona in hupaa.zonas if zona.restrita)
    assert escada.area is None
    assert any("não foi posicionado" in aviso for aviso in avisos(hupaa))


@pytest.mark.parametrize("cenario", ["easy", "hupaa"])
def test_teste_rapido_vem_pronto_sem_alcances_sobrepostos(cenario):
    layout = Layout.model_validate(layout_teste_rapido(cenario)).model_dump(mode="json")
    assert avisos(Layout.model_validate(layout)) == []
    antenas = antenas_do_layout(layout)
    config = Layout.model_validate(layout)
    por_chave = {a.chave: a for leitor in config.leitores for a in leitor.antenas}
    for i, uma in enumerate(antenas):
        for outra in antenas[i + 1:]:
            if ponto_unico(por_chave[uma.chave], por_chave[outra.chave]):
                continue  # leitor da zona restrita: um só ponto de detecção
            assert distancia(uma.x, uma.y, outra.x, outra.y, layout["proporcao"]) >                 uma.alcance + outra.alcance, (uma.chave, outra.chave)
    # Equipamentos começam dentro da primeira zona e fora de qualquer área de leitura.
    primeira = layout["zonas"][0]["area"]
    for x, y in POSICOES_TESTE_RAPIDO[cenario]:
        assert detectar(x, y, antenas, layout["proporcao"]) == []
        assert primeira["x"] <= x <= primeira["x"] + primeira["largura"]
        assert primeira["y"] <= y <= primeira["y"] + primeira["altura"]


def test_preset_hupaa_padrao_continua_sem_posicoes():
    assert all(leitor["posicao"] is None for leitor in preset("hupaa")["leitores"])


@pytest.mark.parametrize("mudanca,trecho", [
    (lambda c: c["leitores"][0]["antenas"].extend(
        [dict(c["leitores"][0]["antenas"][0], chave=f"extra-{n}", porta=n) for n in (3, 4, 2)]),
     "de 1 a 4 antenas"),
    (lambda c: c["leitores"][0]["antenas"][1].update(porta=1), "porta do leitor"),
    (lambda c: c["leitores"][0]["antenas"][0].update(zona="zona-b"), "zona do lado A"),
    (lambda c: c["portais"][0].update(zona_b="zona-a"), "duas zonas diferentes"),
    (lambda c: c["leitores"][0].update(reader_id="reader-01"), "sim-"),
    (lambda c: c["leitores"][0]["antenas"][0].update(lado=None), "lado lógico"),
    (lambda c: c["leitores"][0]["antenas"][0].update(portal="nao-existe"), "portal inexistente"),
    (lambda c: c["zonas"][1].update(nome="zona a"), "nome de zona repetido"),
])
def test_layout_recusa_associacoes_impossiveis(mudanca, trecho):
    configuracao = preset("easy")
    mudanca(configuracao)
    with pytest.raises(service.SimulacaoRecusada) as erro:
        service.validar_layout(configuracao)
    assert trecho in str(erro.value)


def test_quatro_antenas_por_leitor_e_varios_portais_sao_aceitos():
    configuracao = preset("hupaa")
    leitor = configuracao["leitores"][0]
    leitor["antenas"] += [
        {"chave": "l1-a3", "nome": "Antena 3", "porta": 3, "posicao": {"x": 20, "y": 20},
         "alcance": 5, "portal": "portal-2-3", "lado": "a", "zona": None},
        {"chave": "l1-a4", "nome": "Antena 4", "porta": 4, "posicao": None, "alcance": 5,
         "portal": None, "lado": None, "zona": "zona-1"},
    ]
    layout = service.validar_layout(configuracao)
    assert len(layout.leitores[0].antenas) == 4
    assert layout.leitores[0].antenas[2].zona == "zona-2"
    assert len(layout.portais) == 4


# --- motor (sem banco) ----------------------------------------------------------


def _estado(itens: list[dict], configuracao: dict | None = None) -> EstadoSessao:
    layout = configuracao or preset("easy")
    return EstadoSessao(1, "abc", 1, "sim-l1", layout["proporcao"], antenas_do_layout(layout),
                        {"sim-easy-01": "easy/dev/hupaa/sim-l1/sim-easy-01/readings"}, itens)


def test_item_sem_epc_nao_produz_leitura_e_periodo_e_respeitado():
    sem_tag = {"id": "i1", "epc": None, "x": 28, "y": 66}
    com_tag = {"id": "i2", "epc": "E2804C41000000000000ABCD", "x": 72, "y": 66}
    estado = _estado([sem_tag, com_tag])
    leituras = estado.devidas(10.0, 0.2)
    assert [(porta, epc) for _, epc, porta, _ in leituras] == [(2, com_tag["epc"])]
    assert estado.no_alcance == {"i1": ["antena-a"], "i2": ["antena-b"]}
    assert estado.devidas(10.1, 0.2) == []
    assert len(estado.devidas(10.2, 0.2)) == 1
    fora = _estado([{"id": "i3", "epc": "E2804C41000000000000ABCE", "x": 50, "y": 20}])
    assert fora.devidas(10.0, 0.2) == []


def test_payload_e_topico_seguem_o_contrato_do_leitor():
    assert json.loads(payload("E2804C41000000000000ABCD", 2, -5900, 1234567)) == {
        "epc": "E2804C41000000000000ABCD", "rssi": -5900, "antenna": 2, "timestamp": "1234567"}
    assert topico_sintetico({"MQTT_TOPIC": "easy/dev/hupaa/+/+/readings"}, "sim-easy-01",
                            "sim-l3") == "easy/dev/hupaa/sim-l3/sim-easy-01/readings"
    with pytest.raises(ValueError):
        topico_sintetico({"MQTT_TOPIC": "easy/dev/hupaa/+/reader-01/readings"}, "sim-easy-01", "x")


def test_configuracao_bloqueia_producao_e_exige_credencial_propria():
    with pytest.raises(ValueError):
        config_simulador.carregar({"APP_ENV": "production", "SIMULADOR_HABILITADO": "true"})
    assert not config_simulador.carregar({"APP_ENV": "production"}).habilitado
    assert not config_simulador.carregar({}).habilitado
    local = config_simulador.carregar({"SIMULADOR_HABILITADO": "true", "MQTT_HOST": "localhost"})
    assert local.habilitado and local.mqtt["MQTT_HOST"] == "localhost"
    nuvem = config_simulador.carregar({"SIMULADOR_HABILITADO": "true", "MQTT_MODE": "cloud",
                                       "MQTT_USERNAME": "ingestor"})
    assert not nuvem.habilitado and "credencial" in nuvem.motivo
    mesma = config_simulador.carregar({"SIMULADOR_HABILITADO": "true", "MQTT_MODE": "cloud",
                                       "MQTT_USERNAME": "x", "SIMULADOR_MQTT_USERNAME": "x"})
    assert not mesma.habilitado
    propria = config_simulador.carregar({
        "SIMULADOR_HABILITADO": "true", "MQTT_MODE": "cloud", "MQTT_USERNAME": "ingestor",
        "MQTT_PASSWORD": "segredo-ingestor", "SIMULADOR_MQTT_USERNAME": "publicador",
        "SIMULADOR_MQTT_PASSWORD": "segredo-publicador"})
    assert propria.habilitado
    assert propria.mqtt["MQTT_USERNAME"] == "publicador"
    assert propria.mqtt["MQTT_PASSWORD"] == "segredo-publicador"
    assert "segredo" not in json.dumps(propria.publico())


# --- topologia no banco ---------------------------------------------------------


def _layout(db: Session, cenario: str = "easy", configuracao: dict | None = None) -> SimulacaoLayout:
    return service.criar_layout(db, nome=None, cenario=cenario, configuracao=configuracao)


def test_aplicar_easy_cria_leitor_virtual_no_portal_do_laboratorio(db):
    sessao = service.iniciar_sessao(db, _layout(db).id, None)
    leitor = db.scalar(select(Leitor).where(Leitor.reader_id == "sim-easy-01"))
    assert leitor.identificador_serial.startswith("SIM-L")
    portal = db.get(Portal, sessao.topologia["portais"]["portal-easy"])
    assert portal.nome == "Portal de teste RFID"
    zonas = {db.get(Zona, zona_id).referencia_planta
             for zona_id in sessao.topologia["zonas"].values()}
    assert zonas == {"sala-a", "sala-b"}
    mapeamentos = db.scalars(select(MapeamentoAntenaPortal).where(
        MapeamentoAntenaPortal.fim.is_(None))).all()
    assert sorted((m.lado, m.funcao) for m in mapeamentos) == [("a", "entrada"), ("b", "saida")]
    # Reaplicar sem mudança não abre mapeamento novo.
    service.transicionar(db, sessao.codigo, "reiniciar")
    assert db.scalar(select(func.count()).select_from(MapeamentoAntenaPortal)) == 2


def test_reaplicar_versiona_mapeamento_e_inativa_porta_removida(db):
    registro = _layout(db)
    sessao = service.iniciar_sessao(db, registro.id, None)
    configuracao = copy.deepcopy(registro.configuracao)
    antenas = configuracao["leitores"][0]["antenas"]
    antenas[0].update(lado="b", zona=None)
    antenas[1].update(lado="a", zona=None)
    service.atualizar_layout(db, registro.id, nome=None, configuracao=configuracao,
                             versao_esperada=registro.versao)
    service.transicionar(db, sessao.codigo, "reiniciar")
    assert db.scalar(select(func.count()).select_from(MapeamentoAntenaPortal)) == 4
    ativos = db.scalars(select(MapeamentoAntenaPortal).where(
        MapeamentoAntenaPortal.fim.is_(None))).all()
    porta = {m.antena_id: m.lado for m in ativos}
    assert porta[sessao.topologia["antenas"]["antena-a"]] == "b"

    configuracao = copy.deepcopy(db.get(SimulacaoLayout, registro.id).configuracao)
    configuracao["leitores"][0]["antenas"].pop()
    configuracao["portais"] = []
    for antena in configuracao["leitores"][0]["antenas"]:
        antena.update(portal=None, lado=None, zona="zona-a")
    service.atualizar_layout(db, registro.id, nome=None, configuracao=configuracao,
                             versao_esperada=db.get(SimulacaoLayout, registro.id).versao)
    service.transicionar(db, sessao.codigo, "reiniciar")
    antenas_ativas = db.scalars(select(Antena).join(Leitor).where(
        Leitor.reader_id == "sim-easy-01", Antena.ativo.is_(True))).all()
    assert [antena.porta_numero for antena in antenas_ativas] == [1]
    assert db.scalar(select(func.count()).select_from(MapeamentoAntenaPortal).where(
        MapeamentoAntenaPortal.fim.is_(None))) == 0


def test_reader_id_de_leitor_fisico_ou_outro_layout_e_recusado(db):
    db.add(Leitor(reader_id="sim-easy-01", fabricante="Identix", modelo="EZ700",
                  identificador_serial="FISICO-1"))
    db.commit()
    with pytest.raises(service.SimulacaoRecusada) as erro:
        service.iniciar_sessao(db, _layout(db).id, None)
    assert "leitor físico" in str(erro.value)


def test_hupaa_usa_andar_proprio_e_dois_layouts_nao_compartilham_leitor(db):
    configuracao = preset("hupaa")
    sessao = service.iniciar_sessao(db, _layout(db, "hupaa", configuracao).id, None)
    zona = db.get(Zona, sessao.topologia["zonas"]["zona-1"])
    assert zona.setor.andar.nome == "Simulação HUPAA"
    assert db.scalar(select(func.count()).select_from(Leitor).where(
        Leitor.identificador_serial.like("SIM-%"))) == 4
    with pytest.raises(service.SimulacaoRecusada) as erro:
        service.iniciar_sessao(db, _layout(db, "hupaa", configuracao).id, None)
    assert "já é usado pelo layout “Hospital HUPAA (padrão)”" in str(erro.value)


def test_layout_excluido_libera_os_leitores_para_o_proximo(db):
    """Caso real: o teste rápido antigo ficou dono de sim-hupaa-03/04 e travava o layout do vídeo."""
    antigo = _layout(db, "hupaa", preset("hupaa"))
    service.iniciar_sessao(db, antigo.id, None)
    novo = _layout(db, "hupaa", preset("hupaa"))
    with pytest.raises(service.SimulacaoRecusada):
        service.iniciar_sessao(db, novo.id, None)

    db.rollback()
    service.transicionar(db, service.listar_sessoes(db)[0].codigo, "encerrar")
    service.arquivar_layout(db, antigo.id)
    leitores = db.scalars(select(Leitor).where(Leitor.identificador_serial.like("SIM-%"))).all()
    assert leitores and not any(leitor.ativo for leitor in leitores)
    assert db.scalar(select(func.count()).select_from(MapeamentoAntenaPortal).where(
        MapeamentoAntenaPortal.fim.is_(None))) == 0

    sessao = service.iniciar_sessao(db, novo.id, None)
    assumidos = db.scalars(select(Leitor).where(Leitor.reader_id.like("sim-hupaa-%"))).all()
    assert {leitor.identificador_serial for leitor in assumidos} == {
        f"SIM-L{novo.id}-sim-hupaa-{n:02d}" for n in range(1, 5)}
    assert all(leitor.ativo for leitor in assumidos)
    # Cada antena aponta só para os portais do layout novo.
    ativos = db.scalars(select(MapeamentoAntenaPortal.portal_id).where(
        MapeamentoAntenaPortal.fim.is_(None))).all()
    assert set(ativos) <= set(sessao.topologia["portais"].values())


def test_teste_rapido_nao_disputa_leitor_com_layout_do_usuario(db):
    meu = _layout(db, "hupaa", Layout.model_validate(layout_teste_rapido("hupaa")).model_dump(mode="json")
                  | {"leitores": preset("hupaa")["leitores"]})
    service.iniciar_sessao(db, meu.id, None)
    rapido = service.teste_rapido(db, "hupaa", None)
    assert rapido.estado == "em_execucao"
    assert {leitor["reader_id"] for leitor in rapido.layout["leitores"]} == {f"sim-demo-hupaa-{n:02d}" for n in range(1, 5)}
    assert len(service.listar_sessoes(db)) == 2


def test_ponto_unico_da_zona_restrita_e_aceito_mas_outros_avisos_continuam():
    configuracao = layout_teste_rapido("hupaa")
    restrito = configuracao["leitores"][3]
    assert restrito["nome"] == "Leitor 4 · zona restrita (escada)"
    assert [a["nome"] for a in restrito["antenas"]] == ["Entrada pela Zona 3", "Entrada pela Zona 1"]
    # Leitor 4: as duas antenas no mesmo ponto (lado B de portais diferentes) é válido.
    assert restrito["antenas"][0]["posicao"] == restrito["antenas"][1]["posicao"]
    assert avisos(Layout.model_validate(configuracao)) == []
    # Mesmo ponto com lados diferentes, ou lados A/B sobrepostos, continuam avisando.
    leitor_1 = configuracao["leitores"][0]["antenas"]
    leitor_1[1]["posicao"] = dict(restrito["antenas"][0]["posicao"])  # lado A no ponto do B
    configuracao["leitores"][1]["antenas"][0]["posicao"] = {"x": 48, "y": 15}  # B do portal 1-2
    textos = avisos(Layout.model_validate(configuracao))
    assert any("estão no mesmo ponto" in texto for texto in textos)
    assert any("lados A e B se sobrepõem" in texto for texto in textos)


# --- API e sincronização entre abas ----------------------------------------------


@pytest.fixture
def api(engine, truncate_all):
    def get_db_de_teste():
        session = Session(bind=engine)
        try:
            yield session
        finally:
            session.close()

    estado = {"config": HABILITADO}
    app.dependency_overrides[get_db] = get_db_de_teste
    app.dependency_overrides[obter_config] = lambda: estado["config"]
    try:
        with TestClient(app) as dashboard, TestClient(app) as controle:
            yield dashboard, controle, estado
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(obter_config, None)


def test_duas_abas_compartilham_a_mesma_sessao(api):
    dashboard, controle, _ = api
    layout = dashboard.post("/api/simulacao/layouts", json={"cenario": "easy"}).json()
    assert layout["configuracao"]["leitores"][0]["reader_id"] == "sim-easy-01"
    sessao = dashboard.post("/api/simulacao/sessoes", json={"layout_id": layout["id"]})
    assert sessao.status_code == 201, sessao.text
    codigo = sessao.json()["codigo"]

    criado = controle.post(f"/api/simulacao/sessoes/{codigo}/itens",
                           json={"nome": "Maca", "tipo": "Maca", "gerar_epc": True}).json()
    item = criado["itens"][0]
    assert item["epc"].startswith("E2804C41")
    controle.post(f"/api/simulacao/sessoes/{codigo}/itens",
                  json={"nome": "Cadeira de rodas", "tipo": "Cadeira"})
    movido = controle.patch(f"/api/simulacao/sessoes/{codigo}/itens/{item['id']}",
                            json={"x": 28, "y": 66}).json()

    visto = dashboard.get(f"/api/simulacao/sessoes/{codigo}").json()
    assert visto["versao"] == movido["versao"]
    assert visto["itens"][0]["x"] == 28 and visto["itens"][1]["epc"] is None
    inalterada = dashboard.get(f"/api/simulacao/sessoes/{codigo}",
                               params={"desde_versao": visto["versao"]}).json()
    assert inalterada["inalterada"] is True

    # Recarregar a página = nova leitura do banco: nada se perde.
    with TestClient(app) as recarregada:
        assert recarregada.get(f"/api/simulacao/sessoes/{codigo}").json()["itens"] == visto["itens"]

    assert dashboard.post(f"/api/simulacao/sessoes/{codigo}/pausar").json()["estado"] == "pausada"
    assert controle.get(f"/api/simulacao/sessoes/{codigo}").json()["estado"] == "pausada"
    reiniciada = controle.post(f"/api/simulacao/sessoes/{codigo}/reiniciar").json()
    assert reiniciada["estado"] == "em_execucao"
    assert reiniciada["itens"][0]["x"] == item["x0"]
    etiquetado = controle.patch(f"/api/simulacao/sessoes/{codigo}/itens/{item['id']}",
                                json={"epc": visto["itens"][0]["epc"]})
    assert etiquetado.status_code == 200
    repetido = controle.patch(
        f"/api/simulacao/sessoes/{codigo}/itens/{visto['itens'][1]['id']}",
        json={"epc": visto["itens"][0]["epc"]})
    assert repetido.status_code == 409
    assert dashboard.post(f"/api/simulacao/sessoes/{codigo}/encerrar").json()["estado"] == "encerrada"
    assert controle.patch(f"/api/simulacao/sessoes/{codigo}/itens/{item['id']}",
                          json={"x": 1}).status_code == 409


def test_sessoes_de_layouts_diferentes_ficam_isoladas(api):
    dashboard, _, _ = api
    easy = dashboard.post("/api/simulacao/layouts", json={"cenario": "easy"}).json()
    hupaa = dashboard.post("/api/simulacao/layouts", json={"cenario": "hupaa"}).json()
    s1 = dashboard.post("/api/simulacao/sessoes", json={"layout_id": easy["id"]}).json()
    s2 = dashboard.post("/api/simulacao/sessoes", json={"layout_id": hupaa["id"]}).json()
    dashboard.post(f"/api/simulacao/sessoes/{s1['codigo']}/itens", json={"nome": "Maca"})
    assert dashboard.get(f"/api/simulacao/sessoes/{s2['codigo']}").json()["itens"] == []
    abertas = {item["codigo"] for item in dashboard.get("/api/simulacao/sessoes").json()}
    assert abertas == {s1["codigo"], s2["codigo"]}
    # Nova sessão do mesmo layout encerra a anterior e herda os itens.
    s3 = dashboard.post("/api/simulacao/sessoes", json={"layout_id": easy["id"]}).json()
    assert [item["nome"] for item in s3["itens"]] == ["Maca"]
    assert dashboard.get(f"/api/simulacao/sessoes/{s1['codigo']}").json()["estado"] == "encerrada"


def test_layout_com_versao_antiga_e_simulador_desligado(api):
    dashboard, _, estado = api
    layout = dashboard.post("/api/simulacao/layouts", json={"cenario": "easy"}).json()
    salvo = dashboard.put(f"/api/simulacao/layouts/{layout['id']}", json={
        "nome": "EASY editado", "configuracao": layout["configuracao"], "versao": layout["versao"]})
    assert salvo.status_code == 200 and salvo.json()["versao"] == 2
    antigo = dashboard.put(f"/api/simulacao/layouts/{layout['id']}", json={
        "configuracao": layout["configuracao"], "versao": layout["versao"]})
    assert antigo.status_code == 409
    invalido = copy.deepcopy(layout["configuracao"])
    invalido["leitores"][0]["antenas"][1]["porta"] = 1
    assert dashboard.put(f"/api/simulacao/layouts/{layout['id']}", json={
        "configuracao": invalido, "versao": 2}).status_code == 422
    restaurado = dashboard.post(f"/api/simulacao/layouts/{layout['id']}/restaurar-preset").json()
    assert restaurado["configuracao"] == Layout.model_validate(preset("easy")).model_dump(mode="json")

    estado["config"] = DESABILITADO
    resposta = dashboard.post("/api/simulacao/sessoes", json={"layout_id": layout["id"]})
    assert resposta.status_code == 409
    assert resposta.json()["detail"]["codigo"] == "simulador_desabilitado"
    estado["config"] = PRODUCAO
    assert dashboard.post("/api/simulacao/sessoes",
                          json={"layout_id": layout["id"]}).status_code == 404
    assert dashboard.post("/api/simulacao/layouts", json={"cenario": "easy"}).status_code == 404
    assert dashboard.get("/api/simulacao/config").json()["habilitado"] is False


def test_teste_rapido_cria_tudo_e_reaproveita_na_segunda_vez(api):
    dashboard, _, estado = api
    primeira = dashboard.post("/api/simulacao/teste-rapido", json={"cenario": "hupaa"})
    assert primeira.status_code == 201, primeira.text
    sessao = primeira.json()
    assert sessao["estado"] == "em_execucao"
    assert [item["nome"] for item in sessao["itens"]] == [item["nome"] for item in ITENS_TESTE_RAPIDO]
    layouts = dashboard.get("/api/simulacao/layouts", params={"cenario": "hupaa"}).json()
    assert len(layouts) == 1 and layouts[0]["avisos"] == []
    cadastrados = dashboard.get("/api/cadastro/equipamentos").json()["items"]
    assert sorted(item["identificador_interno"] for item in cadastrados) == [
        f"LAB-RFID-{item['epc']}" for item in ITENS_TESTE_RAPIDO if item["cadastrar"]]

    # Segunda vez: mesmo layout, nova sessão com os itens herdados, sem cadastro duplicado.
    dashboard.patch(f"/api/simulacao/sessoes/{sessao['codigo']}/itens/{sessao['itens'][0]['id']}",
                    json={"x": 40, "y": 10})
    segunda = dashboard.post("/api/simulacao/teste-rapido", json={"cenario": "hupaa"}).json()
    assert segunda["layout_id"] == sessao["layout_id"] and segunda["codigo"] != sessao["codigo"]
    assert len(segunda["itens"]) == len(ITENS_TESTE_RAPIDO)
    assert len(dashboard.get("/api/cadastro/equipamentos").json()["items"]) == 2

    estado["config"] = DESABILITADO
    assert dashboard.post("/api/simulacao/teste-rapido", json={"cenario": "easy"}).status_code == 409


def test_remover_todos_os_itens_e_apagar_tudo_do_cenario(api):
    dashboard, controle, estado = api
    sessao = dashboard.post("/api/simulacao/teste-rapido", json={"cenario": "easy"}).json()
    outro = dashboard.post("/api/simulacao/layouts", json={"cenario": "easy"}).json()
    hupaa = dashboard.post("/api/simulacao/layouts", json={"cenario": "hupaa"}).json()
    vazia = controle.delete(f"/api/simulacao/sessoes/{sessao['codigo']}/itens").json()
    assert vazia["itens"] == [] and vazia["versao"] > sessao["versao"]

    resultado = dashboard.post("/api/simulacao/apagar-tudo", json={"cenario": "easy"}).json()
    assert resultado == {"sessoes_encerradas": 1, "layouts_arquivados": 2}
    assert dashboard.get("/api/simulacao/layouts", params={"cenario": "easy"}).json() == []
    assert dashboard.get(f"/api/simulacao/sessoes/{sessao['codigo']}").json()["estado"] == "encerrada"
    # Outro cenário não é tocado.
    assert [item["id"] for item in dashboard.get(
        "/api/simulacao/layouts", params={"cenario": "hupaa"}).json()] == [hupaa["id"]]
    assert outro["id"] != hupaa["id"]
    estado["config"] = PRODUCAO
    assert dashboard.post("/api/simulacao/apagar-tudo", json={"cenario": "easy"}).status_code == 404


# --- pipeline real: motor -> MQTT (capturado) -> ingestor -> inferência ------------


class PublicadorCapturado:
    """Mesma interface do publicador real; guarda as mensagens em vez de enviar."""

    instancias: list[PublicadorCapturado] = []

    def __init__(self, mqtt, *, assinatura, permitido=None):
        self.assinatura = assinatura
        self.mensagens: list[tuple[str, dict]] = []
        self.destino = "mqtt://capturado"
        self.pendentes = 0
        PublicadorCapturado.instancias.append(self)

    def topico(self, reader_id, portal_id):
        return topico_sintetico({"MQTT_TOPIC": self.assinatura}, reader_id, portal_id)

    def conectar(self):
        pass

    def emitir(self, topico, epc, porta, rssi):
        self.mensagens.append((topico, json.loads(payload(epc, porta, rssi, 1_000_000))))

    def conferir(self):
        pass

    def fechar(self):
        pass


# No futuro: o monitor só conta leituras posteriores ao início da sessão.
T0 = datetime.now(UTC).replace(microsecond=0) + timedelta(hours=1)
EPC_MACA = "E2804C4100000000000000A1"


def _receptor(pg_engine, tmp_path):
    location = LocationProjectionService(pg_engine)
    direction = DirectionInferenceService(DirectionRepository(pg_engine), 100,
                                          confirmed_handler=location.process_passage)
    passage = PassageInferenceService(PassageDetector(timedelta(seconds=3)),
                                      PassageRepository(pg_engine),
                                      passage_persisted=direction.process_pending)
    factory = patch("rfid_ingestion.mqtt_client.create_client")
    client = factory.start().return_value
    client.ack.return_value = 0
    receiver = MqttReceiver(Settings(mqtt_topic="easy/dev/hupaa/+/+/readings"),
                            JsonlEventStore(tmp_path / "events.jsonl"),
                            RawReadingRepository(pg_engine),
                            observation_handler=passage.handle_observation,
                            observation_tick_handler=passage.tick)
    return receiver, client, factory


def _simular(pg_engine, tmp_path, sessao_codigo, percurso, inicio=0.0):
    """Move o item pelo percurso (x, y, segundos) e entrega cada publicação ao ingestor."""
    PublicadorCapturado.instancias.clear()
    motor = MotorSimulacao(HABILITADO, pg_engine, fabrica_publicador=PublicadorCapturado)
    receiver, client, factory = _receptor(pg_engine, tmp_path)
    mid = 0
    try:
        relogio = inicio
        for x, y, duracao in percurso:
            with Session(pg_engine) as session:
                sessao = service.obter_sessao(session, sessao_codigo)
                item = sessao.itens[0]["id"]
                service.alterar_item(session, sessao_codigo, item, {"x": x, "y": y})
            fim = relogio + duracao
            while relogio < fim:
                motor.ciclo(relogio)
                for topico, corpo in PublicadorCapturado.instancias[0].mensagens:
                    mid += 1
                    instante = T0 + timedelta(seconds=relogio)
                    corpo = dict(corpo, timestamp=instante.isoformat().replace("+00:00", "Z"))
                    receiver._on_message(client, None, Mock(
                        mid=mid, qos=1, retain=False, topic=topico,
                        payload=json.dumps(corpo).encode()))
                PublicadorCapturado.instancias[0].mensagens.clear()
                receiver._flush_pending()
                relogio = round(relogio + 0.1, 3)
        receiver.flush_debounce()
    finally:
        factory.stop()
        motor.parar()
    return mid


@pytest.fixture
def cenario_easy(pg_engine):
    with Session(pg_engine) as session:
        registro = service.criar_layout(session, nome=None, cenario="easy")
        sessao = service.iniciar_sessao(session, registro.id, None)
        service.adicionar_item(session, sessao.codigo, nome="Maca", tipo="Maca", epc=EPC_MACA,
                               gerar_epc=False, x=10, y=90)
        tipo = TipoEquipamento(nome="Maca", nome_normalizado="maca")
        session.add(tipo)
        session.flush()
        equipamento = Equipamento(nome="Maca hospitalar", tipo_id=tipo.id,
                                  identificador_interno="SIM-1",
                                  identificador_interno_normalizado="sim-1")
        session.add(equipamento)
        session.flush()
        tag = Tag(epc=EPC_MACA)
        session.add(tag)
        session.flush()
        session.add(AssociacaoTagEquipamento(tag_id=tag.id, equipamento_id=equipamento.id,
                                             inicio=T0 - timedelta(days=1)))
        session.commit()
        return {"codigo": sessao.codigo, "equipamento": equipamento.id,
                "zonas": dict(sessao.topologia["zonas"])}


def _projecao(pg_engine, equipamento_id):
    with Session(pg_engine) as session:
        return (session.get(Equipamento, equipamento_id).ultima_zona_id,
                session.scalar(select(func.count()).select_from(HistoricoMovimentacao)),
                session.scalars(select(Passagem.direcao_status)).all())


def test_pipeline_a_para_b_e_b_para_a(pg_engine, cenario_easy, tmp_path):
    a, b = (28, 66), (72, 66)
    _simular(pg_engine, tmp_path, cenario_easy["codigo"],
             [(*a, 0.6), (50, 90, 0.4), (*b, 0.6), (50, 90, 0.3)])
    zona, movimentos, estados = _projecao(pg_engine, cenario_easy["equipamento"])
    assert zona == cenario_easy["zonas"]["zona-b"]
    assert movimentos == 1 and estados == ["confirmed"]
    with Session(pg_engine) as session:
        leitor = session.scalar(select(Leitor.reader_id).join(Antena).join(LeituraBruta).limit(1))
        assert leitor == "sim-easy-01"
    _simular(pg_engine, tmp_path, cenario_easy["codigo"],
             [(*b, 0.6), (50, 90, 0.4), (*a, 0.6), (50, 90, 0.3)], inicio=10.0)
    zona, movimentos, _ = _projecao(pg_engine, cenario_easy["equipamento"])
    assert zona == cenario_easy["zonas"]["zona-a"] and movimentos == 2


def test_leitura_isolada_nao_muda_zona(pg_engine, cenario_easy, tmp_path):
    publicadas = _simular(pg_engine, tmp_path, cenario_easy["codigo"],
                          [(28, 66, 1.0), (50, 90, 0.5)])
    assert publicadas >= 4
    zona, movimentos, estados = _projecao(pg_engine, cenario_easy["equipamento"])
    assert (zona, movimentos, estados) == (None, 0, [])


def test_alcances_sobrepostos_nao_confirmam_movimento(pg_engine, cenario_easy, tmp_path):
    with Session(pg_engine) as session:
        sessao = service.obter_sessao(session, cenario_easy["codigo"], travar=True)
        layout = copy.deepcopy(sessao.layout)
        for antena in layout["leitores"][0]["antenas"]:
            antena["alcance"] = 30  # as duas antenas leem o centro ao mesmo tempo
        sessao.layout = layout
        sessao.versao += 1
        session.commit()
    _simular(pg_engine, tmp_path, cenario_easy["codigo"], [(50, 66, 1.5), (50, 100, 0.4)])
    zona, movimentos, estados = _projecao(pg_engine, cenario_easy["equipamento"])
    assert zona is None and movimentos == 0
    assert all(estado != "confirmed" for estado in estados)


def test_epc_desconhecido_aparece_na_descoberta_sem_localizacao(pg_engine, tmp_path):
    with Session(pg_engine) as session:
        registro = service.criar_layout(session, nome=None, cenario="easy")
        sessao = service.iniciar_sessao(session, registro.id, None)
        service.adicionar_item(session, sessao.codigo, nome="Maca nova", tipo="Maca",
                               epc=EPC_MACA, gerar_epc=False, x=10, y=90)
        service.adicionar_item(session, sessao.codigo, nome="Cadeira", tipo="Cadeira",
                               epc=None, gerar_epc=False, x=12, y=90)
        codigo = sessao.codigo
    _simular(pg_engine, tmp_path, codigo, [(28, 66, 0.6), (50, 90, 0.4), (72, 66, 0.6)])
    from api.service_cadastro import epcs_detectados
    with Session(pg_engine) as session:
        descoberta = epcs_detectados(session, now=T0 + timedelta(seconds=2),
                                     janela=timedelta(minutes=5), recente=timedelta(minutes=1))
        assert [item["epc"] for item in descoberta["items"]] == [EPC_MACA]
        assert descoberta["items"][0]["situacao"] == "desconhecido"
        assert descoberta["items"][0]["ultima_antena"]["origem"] == "simulado"
        # A passagem existe, mas não há equipamento para mover.
        assert session.scalar(select(func.count()).select_from(HistoricoMovimentacao)) == 0
        sessao = service.obter_sessao(session, codigo)
        painel = service.monitor(session, sessao, now=T0 + timedelta(seconds=3))
        assert painel["tags"][0]["equipamento"] is None
        assert painel["leituras_total"] >= 4
        assert all(not item for item in painel["zonas"].values())


def test_teste_rapido_hupaa_confirma_passagem_pelo_pipeline(pg_engine, tmp_path):
    with Session(pg_engine) as session:
        sessao = service.teste_rapido(session, "hupaa", None)
        codigo, zonas = sessao.codigo, dict(sessao.topologia["zonas"])
        maca = session.scalar(select(Equipamento.id).where(
            Equipamento.identificador_interno == f"LAB-RFID-{ITENS_TESTE_RAPIDO[0]['epc']}"))
    # Maca 01 da Zona 1 para a Zona 2 pelo portal 1 ↔ 2 (antenas em x 44 e 58).
    _simular(pg_engine, tmp_path, codigo, [(44, 15, 0.6), (51, 15, 0.4), (58, 15, 0.6), (70, 15, 0.3)])
    zona, movimentos, estados = _projecao(pg_engine, maca)
    assert zona == zonas["zona-2"] and movimentos == 1 and estados == ["confirmed"]
