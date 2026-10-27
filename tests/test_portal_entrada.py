"""Portal de entrada da zona e itens que surgem juntos (falhas do teste local de 26/10/2026).

Falha 1: a cadeira foi lida pelas duas antenas do Leitor 1, mas a zona 1 não foi
confirmada: a Antena 2 não pertencia a nenhum portal e o "portal" da Antena 1 tinha o
outro lado em outro leitor. Regra: um leitor com duas antenas na entrada da zona é o
portal dela, com a Antena 1 na circulação: 1 → 2 entra na zona, 2 → 1 sai para a
circulação (a regra "qualquer ordem" de 26/10 foi substituída em 27/10).

Falha 2: a Maca HU-07 "passou" da Zona 2 para a Zona 3 sem ser movida de propósito: o
trajeto foi executado nela porque surgiu a 3 unidades (≈16 px) da Cadeira HU-08 e os
marcadores se sobrepunham. Itens novos agora surgem afastados na escala da tela.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from api import service_cadastro
from api.service_tipos_equipamento import criar as criar_tipo
from api.simulacao import service
from api.simulacao.presets import teste_rapido as layout_hu
from db.models import LeituraBruta, Passagem, Portal
from rfid_inference.direction import (
    DirectionContext,
    DirectionEvidence,
    DirectionMapping,
    infer_direction,
)
from rfid_location.service import corrigir_localizacao
from tests.test_simulacao_trajeto import T0, _estado, _executar, relogio_falso
from tests.test_simulacao_trajeto import _rodar as _rodar_teste

EPC_CADEIRA = "E2804C41000000000000B108"
EPC_MACA = "E2804C41000000000000B107"


def _rodar(*args, **kwargs):
    """Pipeline com o detector do ingestor real (janela de confirmação, origem ativa)."""
    return _rodar_teste(*args, producao=True, **kwargs)


def _layout_portal_zona_1() -> dict:
    """HU de teste com o Leitor 1 como portal da Zona 1: duas antenas na entrada dela,
    com os alcances sobrepostos (as duas leem juntas na porta, como no teste local)."""
    config = layout_hu("hupaa")
    config["zonas"].append({"chave": "circulacao", "nome": "Circulação", "cor": "#888888", "area": None,
                            "referencia_planta": None, "restrita": False})
    config["portais"] = [p for p in config["portais"] if p["chave"] != "portal-1-2"]
    config["portais"].append({"chave": "portal-zona-1", "nome": "Portal para Zona 1", "zona_a": "circulacao",
                              "zona_b": "zona-1", "posicao": {"x": 45, "y": 15}, "modo": "entrada"})
    leitor_1 = next(leitor for leitor in config["leitores"] if leitor["chave"] == "leitor-1")
    base = leitor_1["antenas"][0]
    leitor_1["antenas"] = [
        {**base, "chave": "l1-a1", "nome": "Antena 1", "porta": 1, "posicao": {"x": 46, "y": 15}, "orientacao": 0,
         "portal": "portal-zona-1", "lado": "a", "zona": "circulacao"},
        {**base, "chave": "l1-a2", "nome": "Antena 2", "porta": 2, "posicao": {"x": 44, "y": 15}, "orientacao": 180,
         "portal": "portal-zona-1", "lado": "b", "zona": "zona-1"},
    ]
    for leitor in config["leitores"]:  # o antigo lado B do portal 1 ↔ 2 fica sem portal
        for antena in leitor["antenas"]:
            if antena.get("portal") == "portal-1-2":
                antena.update(portal=None, lado=None, zona="zona-2")
    return config


@pytest.fixture
def portal_entrada(pg_engine):
    with relogio_falso() as relogio, Session(pg_engine) as session:
        registro = service.criar_layout(session, nome="HU portal de entrada", cenario="hupaa",
                                        configuracao=_layout_portal_zona_1())
        sessao = service.iniciar_sessao(session, registro.id, None)
        tipo = criar_tipo(session, "Cadeira de rodas teste").id
        equipamentos, itens = {}, {}
        for nome, epc, x in (("Cadeira", EPC_CADEIRA, 52), ("Maca", EPC_MACA, 30)):
            equipamento, _ = service_cadastro.cadastrar(session, nome=nome, tipo_id=tipo, epc=epc)
            equipamentos[nome] = equipamento.id
            sessao = service.adicionar_item(session, sessao.codigo, nome=nome, tipo="Cadeira", epc=epc,
                                            gerar_epc=False, x=x, y=15)
            itens[nome] = sessao.itens[-1]["id"]
        zonas = dict(sessao.topologia["zonas"])
        # Ponto de partida conhecido: os dois estavam confirmados na Zona 2 há uma hora.
        for nome in equipamentos:
            corrigir_localizacao(session.connection(), equipment_id=equipamentos[nome], destination_zone_id=zonas["zona-2"],
                                 movimentada_em=T0 - timedelta(hours=1), justificativa="estado inicial do teste")
        session.commit()
        yield {"codigo": sessao.codigo, "itens": itens, "equipamentos": equipamentos, "zonas": zonas,
               "relogio": relogio, "portal": registro.vinculos["portais"]["portal-zona-1"]}


def _passagens(pg_engine, epc):
    with Session(pg_engine) as session:
        return session.execute(select(Passagem.direcao_status, Passagem.direcao_regra, Passagem.zona_destino_id)
                               .where(Passagem.epc == epc).order_by(Passagem.id)).all()


def test_portal_de_entrada_fica_gravado_no_cadastro(pg_engine, portal_entrada):
    with Session(pg_engine) as session:
        assert session.get(Portal, portal_entrada["portal"]).modo == "entrada"


def test_antena_1_depois_2_confirma_a_entrada_na_zona_1(pg_engine, portal_entrada, tmp_path):
    # Vem da circulação (x 52), passa pela Antena 1 (lado de fora) e depois pela 2 (dentro).
    _executar(pg_engine, portal_entrada, "Cadeira", [(52, 15, 0), (30, 15, 5)])
    _rodar(pg_engine, tmp_path, portal_entrada, 6)
    assert _estado(pg_engine, portal_entrada, "Cadeira") == (portal_entrada["zonas"]["zona-1"], 2)
    assert _passagens(pg_engine, EPC_CADEIRA) == [("confirmed", "entry_portal_order_v1",
                                                   portal_entrada["zonas"]["zona-1"])]


def test_antena_2_depois_1_e_saida_para_a_circulacao(pg_engine, portal_entrada, tmp_path):
    # A maca está do lado de dentro (x 30) e atravessa a porta para fora: lê 2 e depois 1.
    _executar(pg_engine, portal_entrada, "Maca", [(30, 15, 0), (52, 15, 5)])
    _rodar(pg_engine, tmp_path, portal_entrada, 6)
    with Session(pg_engine) as session:
        ordem = [linha for linha in session.scalars(select(LeituraBruta.antena_id).where(
            LeituraBruta.epc == EPC_MACA).order_by(LeituraBruta.lido_em))]
    assert ordem[0] != ordem[-1]  # leu as duas antenas, a de dentro primeiro
    assert _estado(pg_engine, portal_entrada, "Maca") == (portal_entrada["zonas"]["circulacao"], 2)
    assert _passagens(pg_engine, EPC_MACA) == [("confirmed", "entry_portal_order_v1",
                                                portal_entrada["zonas"]["circulacao"])]


def test_parado_na_porta_com_as_duas_antenas_e_volta_nao_entra(pg_engine, portal_entrada, tmp_path):
    """Alcances sobrepostos: fica na porta, lido pelas duas antenas, e volta para fora.
    A Antena 1 continua lendo enquanto a 2 lê: não é entrada (nem saída e entrada falsas)."""
    _executar(pg_engine, portal_entrada, "Cadeira", [(52, 15, 0), (45, 15, 2), (45, 15.01, 8), (52, 15, 10)])
    _rodar(pg_engine, tmp_path, portal_entrada, 11)
    with Session(pg_engine) as session:
        lidas = set(session.scalars(select(LeituraBruta.antena_id).where(LeituraBruta.epc == EPC_CADEIRA)))
    assert len(lidas) == 2  # as duas antenas leram
    assert _estado(pg_engine, portal_entrada, "Cadeira") == (portal_entrada["zonas"]["zona-2"], 1)


def test_parado_na_porta_e_depois_entra_confirma_uma_entrada_so(pg_engine, portal_entrada, tmp_path):
    """Fica na porta (as duas antenas alternando) e depois entra: uma entrada só, sem
    saídas e entradas falsas durante a parada."""
    _executar(pg_engine, portal_entrada, "Cadeira", [(52, 15, 0), (45, 15, 2), (45, 15.01, 8), (30, 15, 11)])
    _rodar(pg_engine, tmp_path, portal_entrada, 12)
    assert _estado(pg_engine, portal_entrada, "Cadeira") == (portal_entrada["zonas"]["zona-1"], 2)
    assert _passagens(pg_engine, EPC_CADEIRA) == [("confirmed", "entry_portal_order_v1",
                                                   portal_entrada["zonas"]["zona-1"])]


def test_leitura_de_uma_antena_so_continua_sem_confirmar(pg_engine, portal_entrada, tmp_path):
    # Encosta só na Antena 1 (lado de fora) e volta: aproximação, sem passagem.
    _executar(pg_engine, portal_entrada, "Cadeira", [(52, 15, 0), (48.5, 15, 1), (48.5, 15, 3), (52, 15, 4)])
    _rodar(pg_engine, tmp_path, portal_entrada, 5)
    assert _estado(pg_engine, portal_entrada, "Cadeira") == (portal_entrada["zonas"]["zona-2"], 1)
    assert _passagens(pg_engine, EPC_CADEIRA) == []


def test_ordem_decide_o_destino_nos_dois_modos():
    """Direcional (EASY, portais entre zonas) e de entrada: B → A vai para A; só muda a regra."""
    agora = datetime(2026, 10, 27, tzinfo=UTC)

    def evidencia(antena, leitura, lado, zona, segundos):
        return DirectionEvidence(antenna_id=antena, reading_id=leitura, observed_at=agora + timedelta(seconds=segundos),
                                 epc="E", reading_antenna_id=antena, reader_id=1,
                                 mappings=(DirectionMapping(portal_id=9, side=lado, zone_id=zona),))
    contexto = DirectionContext(passage_id=1, epc="E", portal_id=9, zone_a_id=10, zone_b_id=20,
                                first=evidencia(2, 1, "b", 20, 0), second=evidencia(1, 2, "a", 10, 2))
    assert infer_direction(contexto, timedelta(milliseconds=100)).destination_zone_id == 10
    entrada = DirectionContext(passage_id=1, epc="E", portal_id=9, zone_a_id=10, zone_b_id=20,
                               first=contexto.first, second=contexto.second, entry_portal=True)
    resultado = infer_direction(entrada, timedelta(milliseconds=100))
    assert (resultado.status, resultado.destination_zone_id, resultado.rule) == ("confirmed", 10, "entry_portal_order_v1")


def test_itens_novos_surgem_afastados_e_trajeto_de_um_nao_le_o_outro(pg_engine, portal_entrada, tmp_path):
    """HU-07: dois itens que surgem juntos não podem ficar sobrepostos na tela, e o
    trajeto executado num item nunca gera leitura (nem passagem) no outro."""
    with Session(pg_engine) as session:
        for nome in ("Maca HU-07", "Cadeira HU-08"):
            sessao = service.adicionar_item(session, portal_entrada["codigo"], nome=nome, tipo="Maca", epc=None,
                                            gerar_epc=True, x=None, y=None)
        proporcao = float(sessao.layout["proporcao"])
        maca, cadeira = sessao.itens[-2], sessao.itens[-1]
    assert service.distancia_na_tela((maca["x"], maca["y"]), (cadeira["x"], cadeira["y"]), proporcao) >= 4
    _executar_item(pg_engine, portal_entrada, cadeira["id"], [(cadeira["x"], cadeira["y"], 0), (cadeira["x"], 95, 6)])
    _rodar(pg_engine, tmp_path, portal_entrada, 7)
    with Session(pg_engine) as session:
        assert session.scalar(select(LeituraBruta.id).where(LeituraBruta.epc == maca["epc"])) is None
        assert session.scalar(select(Passagem.id).where(Passagem.epc == maca["epc"])) is None


def _executar_item(pg_engine, contexto, item_id, pontos):
    with Session(pg_engine) as session:
        return service.executar_trajeto(session, contexto["codigo"], item_id,
                                        [{"x": x, "y": y, "t": t} for x, y, t in pontos])
