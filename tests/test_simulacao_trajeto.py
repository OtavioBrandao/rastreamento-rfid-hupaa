"""Trajetos desenhados, relógio da simulação e estado ao vivo, pelo pipeline real.

Motor → payload MQTT → ingestor (normalização, gravação, debounce) → passagem →
direção → histórico/última zona. O relógio "real" é falso e controlado pelo teste,
para que trajeto, aceleração e avanço de tempo sejam reproduzíveis.

Planta do teste rápido HUPAA, portal Zona 1 ↔ Zona 2 em y = 15: antena A em
x = 45 (visada para a esquerda, lê x ≈ 41–46,4) e antena B em x = 57 (visada para a
direita, lê x ≈ 55,6–61). Entre 46,5 e 55,5 ninguém lê.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.router_equipamento import get_recency_context
from api.simulacao import relogio as relogio_sim
from api.simulacao import service, trajeto
from api.simulacao.geometria import antenas_do_layout, detectar
from api.simulacao.motor import MotorSimulacao
from api.simulacao.presets import ITENS_TESTE_RAPIDO
from db.models import Equipamento, HistoricoMovimentacao, LeituraBruta, Passagem
from rfid_location.recency import classify_recency, recency_threshold_from_env
from tests.test_simulacao import HABILITADO, T0, PublicadorCapturado, _receptor
from tests.test_simulacao import api as api  # noqa: F401  (fixture reaproveitada)


class RelogioFalso:
    """Relógio do computador sob controle do teste."""

    def __init__(self, inicio):
        self.agora = inicio

    def __call__(self):
        return self.agora


@contextmanager
def relogio_falso():
    relogio = RelogioFalso(T0)
    with patch("api.simulacao.relogio.real_agora", relogio), patch("api.simulacao.service._agora", relogio):
        yield relogio


@pytest.fixture
def hu(pg_engine):
    with relogio_falso() as relogio, Session(pg_engine) as session:
        sessao = service.teste_rapido(session, "hupaa", None)
        ids = {item["nome"]: item["id"] for item in sessao.itens}
        equipamentos = {nome: session.scalar(select(Equipamento.id).where(
            Equipamento.identificador_interno == f"LAB-RFID-{epc}"))
            for nome, epc in ((i["nome"], i["epc"]) for i in ITENS_TESTE_RAPIDO) if epc}
        for nome, x in (("Maca 01", 30), ("Cadeira de rodas 01", 30)):
            service.alterar_item(session, sessao.codigo, ids[nome], {"x": x, "y": 15})
        yield {"codigo": sessao.codigo, "itens": ids, "equipamentos": equipamentos,
               "zonas": dict(sessao.topologia["zonas"]), "relogio": relogio}


def _executar(pg_engine, hu, nome, pontos):
    with Session(pg_engine) as session:
        return service.executar_trajeto(session, hu["codigo"], hu["itens"][nome],
                                        [{"x": x, "y": y, "t": t} for x, y, t in pontos])


def _rodar(pg_engine, tmp_path, hu, segundos, *, passo=0.1, entregar=None, perder=None,
           finalizar=True, durante=None, producao=False):
    """Ciclos do motor com o relógio falso andando; cada publicação vai ao ingestor."""
    PublicadorCapturado.instancias.clear()
    motor = MotorSimulacao(HABILITADO, pg_engine, fabrica_publicador=PublicadorCapturado)
    receiver, client, factory = _receptor(pg_engine, tmp_path, producao=producao)
    relogio, mono, mid, atrasadas, publicadas = hu["relogio"], 0.0, 0, [], 0
    try:
        while mono < segundos:
            if durante:
                durante(mono)
            motor.ciclo(mono)
            mensagens = []
            if PublicadorCapturado.instancias:
                mensagens = list(PublicadorCapturado.instancias[0].mensagens)
                PublicadorCapturado.instancias[0].mensagens.clear()
            publicadas += len(mensagens)
            if perder and perder(mono):
                mensagens = []
            # Sem relógio acelerado o EZ700 não tem horário: vale o recebimento (aqui, o falso).
            mensagens = [(topico, corpo if "sim_lido_em" in corpo
                          else dict(corpo, timestamp=relogio.agora.isoformat().replace("+00:00", "Z")))
                         for topico, corpo in mensagens]
            if entregar:
                atrasadas.append(mensagens)
                mensagens = entregar(atrasadas)
            for topico, corpo in mensagens:
                mid += 1
                receiver._on_message(client, None, Mock(mid=mid, qos=1, retain=False, topic=topico,
                                                        payload=json.dumps(corpo).encode()))
            receiver._flush_pending()
            mono = round(mono + passo, 3)
            relogio.agora += timedelta(seconds=passo)
        if finalizar:
            receiver.flush_debounce()
            receiver.passage_service.flush()
    finally:
        factory.stop()
        motor.parar()
    return publicadas


def _estado(pg_engine, hu, nome):
    with Session(pg_engine) as session:
        equipamento = session.get(Equipamento, hu["equipamentos"][nome])
        historico = session.scalar(select(func.count()).select_from(HistoricoMovimentacao).where(
            HistoricoMovimentacao.equipamento_id == equipamento.id))
        return equipamento.ultima_zona_id, historico


def _passagens(pg_engine):
    with Session(pg_engine) as session:
        return session.execute(select(Passagem.direcao_status, Passagem.direcao)
                               .order_by(Passagem.id)).all()


ZONA_1_PARA_2 = [(30, 15, 0), (75, 15, 3)]
ZONA_2_PARA_1 = [(75, 15, 0), (30, 15, 3)]


def test_passagem_completa_e_no_sentido_inverso(pg_engine, hu, tmp_path):
    _executar(pg_engine, hu, "Maca 01", ZONA_1_PARA_2)
    _rodar(pg_engine, tmp_path, hu, 3.5)
    assert _estado(pg_engine, hu, "Maca 01") == (hu["zonas"]["zona-2"], 1)
    _executar(pg_engine, hu, "Maca 01", ZONA_2_PARA_1)
    _rodar(pg_engine, tmp_path, hu, 3.5)
    assert _estado(pg_engine, hu, "Maca 01") == (hu["zonas"]["zona-1"], 2)
    assert [tuple(p) for p in _passagens(pg_engine)] == [("confirmed", "a_para_b"), ("confirmed", "b_para_a")]


def test_leitura_parcial_retorno_e_permanencia_na_fronteira_nao_confirmam(pg_engine, hu, tmp_path):
    # Vai até a antena A, fica 5 s parado na fronteira e volta: só o lado A leu.
    _executar(pg_engine, hu, "Maca 01", [(30, 15, 0), (43, 15, 1), (43, 15, 6), (30, 15, 7)])
    publicadas = _rodar(pg_engine, tmp_path, hu, 7.5)
    assert publicadas >= 20
    assert _estado(pg_engine, hu, "Maca 01") == (None, 0)
    assert _passagens(pg_engine) == []


def test_movimento_rapido_nao_pula_antena(pg_engine, hu, tmp_path):
    # 45 unidades em 1 s com ciclos de 0,5 s: a faixa da antena A (~5 unidades) é
    # atravessada entre dois ciclos; sem amostrar o caminho ela nunca seria lida.
    _executar(pg_engine, hu, "Maca 01", [(30, 15, 0), (75, 15, 1)])
    _rodar(pg_engine, tmp_path, hu, 2.0, passo=0.5)
    assert _estado(pg_engine, hu, "Maca 01") == (hu["zonas"]["zona-2"], 1)


def test_travessia_rapida_demais_fica_sem_confirmacao(pg_engine, hu, tmp_path):
    # Em 0,15 s os dois lados são lidos a menos de 100 ms um do outro: pela regra do
    # sistema (RFID_DIRECTION_AMBIGUITY_MS) a direção é ambígua e nada muda de zona.
    _executar(pg_engine, hu, "Maca 01", [(30, 15, 0), (75, 15, 0.15)])
    _rodar(pg_engine, tmp_path, hu, 1.0)
    assert _estado(pg_engine, hu, "Maca 01") == (None, 0)
    assert all(status != "confirmed" for status, _ in _passagens(pg_engine))


def test_tempo_acelerado_le_no_relogio_da_simulacao_sem_pular_transicao(pg_engine, hu, tmp_path):
    with Session(pg_engine) as session:
        service.definir_relogio(session, fator=10)
    # 10 s de trajeto desenhado viram 1 s real; as leituras levam o instante simulado.
    _executar(pg_engine, hu, "Maca 01", [(30, 15, 0), (75, 15, 10)])
    _rodar(pg_engine, tmp_path, hu, 1.3)
    assert _estado(pg_engine, hu, "Maca 01") == (hu["zonas"]["zona-2"], 1)
    with Session(pg_engine) as session:
        leituras = session.execute(select(LeituraBruta.lido_em, LeituraBruta.dados_origem)
                                   .order_by(LeituraBruta.lido_em)).all()
    assert {linha.dados_origem["metadata"]["timestamp_format"] for linha in leituras} == {"sim_clock"}
    # Entre a primeira leitura em A (x≈41) e a última em B passam ~4 s simulados em ~0,4 s reais.
    assert (leituras[-1].lido_em - leituras[0].lido_em).total_seconds() >= 3


def test_leituras_repetidas_fora_de_ordem_e_atrasadas_confirmam_uma_vez(pg_engine, hu, tmp_path):
    _executar(pg_engine, hu, "Maca 01", ZONA_1_PARA_2)

    def bagunca(fila):
        # Entrega com 0,5 s de atraso, de trás para frente e duas vezes cada.
        if len(fila) < 5:
            return []
        lote = fila.pop(0)
        return list(reversed(lote)) * 2

    _rodar(pg_engine, tmp_path, hu, 4.5, entregar=bagunca)
    assert _estado(pg_engine, hu, "Maca 01") == (hu["zonas"]["zona-2"], 1)
    assert [tuple(p) for p in _passagens(pg_engine)] == [("confirmed", "a_para_b")]


def test_perda_de_comunicacao_nao_inventa_passagem_e_volta_ao_reconectar(pg_engine, hu, tmp_path):
    # Sem as leituras do lado A não há evidência da travessia: nada é confirmado.
    _executar(pg_engine, hu, "Maca 01", ZONA_1_PARA_2)
    _rodar(pg_engine, tmp_path, hu, 3.5, perder=lambda segundos: segundos < 1.6)
    assert _estado(pg_engine, hu, "Maca 01") == (None, 0)
    # Comunicação de volta: a próxima travessia completa é confirmada normalmente.
    _executar(pg_engine, hu, "Maca 01", [(75, 15, 0), (30, 15, 3), (75, 15, 6)])
    _rodar(pg_engine, tmp_path, hu, 6.5)
    zona, movimentos = _estado(pg_engine, hu, "Maca 01")
    assert zona == hu["zonas"]["zona-2"] and movimentos >= 1


def test_varios_equipamentos_em_movimento_ao_mesmo_tempo(pg_engine, hu, tmp_path):
    with Session(pg_engine) as session:
        service.alterar_item(session, hu["codigo"], hu["itens"]["Cadeira de rodas 01"], {"x": 75, "y": 15})
    _executar(pg_engine, hu, "Maca 01", ZONA_1_PARA_2)
    _executar(pg_engine, hu, "Cadeira de rodas 01", ZONA_2_PARA_1)
    _rodar(pg_engine, tmp_path, hu, 3.5)
    assert _estado(pg_engine, hu, "Maca 01") == (hu["zonas"]["zona-2"], 1)
    assert _estado(pg_engine, hu, "Cadeira de rodas 01") == (hu["zonas"]["zona-1"], 1)


def test_item_novo_surge_fora_das_zonas_e_sem_leitura(pg_engine, hu, tmp_path):
    with Session(pg_engine) as session:
        sessao = service.adicionar_item(session, hu["codigo"], nome="Maca 99", tipo="Maca",
                                        epc=None, gerar_epc=True, x=None, y=None)
        layout = sessao.layout
    novo = sessao.itens[-1]
    for zona in layout["zonas"]:
        area = zona["area"]
        if area:
            assert not (area["x"] <= novo["x"] <= area["x"] + area["largura"]
                        and area["y"] <= novo["y"] <= area["y"] + area["altura"]), zona["chave"]
    assert not detectar(novo["x"], novo["y"], antenas_do_layout(layout), float(layout["proporcao"]))
    assert _rodar(pg_engine, tmp_path, hu, 1.0) == 0  # ninguém no alcance: nenhuma leitura


def test_pausa_da_sessao_congela_o_trajeto_sem_teletransporte(pg_engine, hu, tmp_path):
    _executar(pg_engine, hu, "Maca 01", ZONA_1_PARA_2)
    _rodar(pg_engine, tmp_path, hu, 0.5, finalizar=False)
    with Session(pg_engine) as session:
        sessao = service.transicionar(session, hu["codigo"], "pausar")
        item = next(i for i in sessao.itens if i["id"] == hu["itens"]["Maca 01"])
        parado = trajeto.posicao(item, hu["relogio"].agora)
    hu["relogio"].agora += timedelta(seconds=30)  # 30 s pausado
    assert trajeto.posicao(item, hu["relogio"].agora) == parado
    assert _rodar(pg_engine, tmp_path, hu, 0.5) == 0  # pausada: nada publicado
    with Session(pg_engine) as session:
        sessao = service.transicionar(session, hu["codigo"], "retomar")
        item = next(i for i in sessao.itens if i["id"] == hu["itens"]["Maca 01"])
        assert trajeto.posicao(item, hu["relogio"].agora) == pytest.approx(parado, abs=0.01)
    _rodar(pg_engine, tmp_path, hu, 3.0)
    assert _estado(pg_engine, hu, "Maca 01") == (hu["zonas"]["zona-2"], 1)


def test_avancar_o_tempo_leva_a_atencao_pela_regra_de_recencia(pg_engine, hu, tmp_path):
    _executar(pg_engine, hu, "Maca 01", ZONA_1_PARA_2)
    with Session(pg_engine) as session, pytest.raises(service.SimulacaoRecusada) as recusa:
        service.definir_relogio(session, avancar_s=60)  # pularia as leituras do caminho
    assert recusa.value.codigo == "trajeto_em_execucao"
    _rodar(pg_engine, tmp_path, hu, 3.5)
    limiar = recency_threshold_from_env()
    with Session(pg_engine) as session:
        resumo = service.definir_relogio(session, avancar_s=limiar.total_seconds() + 60)
        assert resumo["acelerado"] and resumo["adiantado_s"] >= limiar.total_seconds()
        agora_sim = relogio_sim.do_banco(session).agora(hu["relogio"].agora)
        equipamento = session.get(Equipamento, hu["equipamentos"]["Maca 01"])
        assert classify_recency(equipamento.ultima_deteccao_em, agora_sim, limiar) == "desatualizada"
        painel = service.monitor(session, service.obter_sessao(session, hu["codigo"]), now=agora_sim)
        maca = next(e for e in painel["equipamentos"] if e["equipamento"] and e["equipamento"]["nome"] == "Maca 01")
        assert maca["estado"] == "atencao" and maca["zona_confirmada"] == "zona-2"
        # A API usa o mesmo relógio para a recência quando o simulador está ligado.
        with patch("api.simulacao.config.carregar", return_value=HABILITADO):
            agora_api, _ = get_recency_context(session)
        assert agora_api == agora_sim
    # Depois do avanço, uma nova travessia é aceita (não fica "no passado") e sai da atenção.
    _executar(pg_engine, hu, "Maca 01", ZONA_2_PARA_1)
    _rodar(pg_engine, tmp_path, hu, 3.5)
    assert _estado(pg_engine, hu, "Maca 01") == (hu["zonas"]["zona-1"], 2)
    with Session(pg_engine) as session:
        agora_sim = relogio_sim.do_banco(session).agora(hu["relogio"].agora)
        equipamento = session.get(Equipamento, hu["equipamentos"]["Maca 01"])
        assert classify_recency(equipamento.ultima_deteccao_em, agora_sim, limiar) == "recente"


def test_estado_ao_vivo_distingue_transito_confirmado_sem_confirmacao_e_fora_de_servico(
        pg_engine, hu, tmp_path):
    _executar(pg_engine, hu, "Maca 01", ZONA_1_PARA_2)
    _rodar(pg_engine, tmp_path, hu, 3.5)
    # Volta até a antena A e para: lida do lado da Zona 1, passagem ainda não confirmada.
    _executar(pg_engine, hu, "Maca 01", [(75, 15, 0), (43, 15, 2), (43, 15, 30)])
    with Session(pg_engine) as session:
        service.alterar_item(session, hu["codigo"], hu["itens"]["Monitor portátil"], {"x": 59, "y": 15})
    _rodar(pg_engine, tmp_path, hu, 2.5, finalizar=False)
    with Session(pg_engine) as session:
        agora = hu["relogio"].agora
        estados = {(e["equipamento"] or {}).get("nome", "?"): e for e in service.monitor(
            session, service.obter_sessao(session, hu["codigo"]), now=agora)["equipamentos"]}
        assert estados["Maca 01"]["estado"] == "em_transito"
        assert estados["Maca 01"]["zona_confirmada"] == "zona-2" and estados["Maca 01"]["zona_leitura"] == "zona-1"
        assert estados["?"]["estado"] == "sem_confirmacao"  # tag não cadastrada, sem zona
        assert "Cadeira de rodas 01" not in estados  # nunca lida nesta sessão
        session.get(Equipamento, hu["equipamentos"]["Maca 01"]).status = "inativo"
        session.commit()
        estados = {(e["equipamento"] or {}).get("nome", "?"): e for e in service.monitor(
            session, service.obter_sessao(session, hu["codigo"]), now=agora)["equipamentos"]}
        assert estados["Maca 01"]["estado"] == "fora_de_servico"
        assert "em_transito" in estados["Maca 01"]["condicoes"]  # os detalhes continuam acessíveis


def test_api_de_trajeto_e_relogio_valida_e_recusa_o_que_pularia_leituras(api):  # noqa: F811
    dashboard, controle, _ = api
    codigo = controle.post("/api/simulacao/teste-rapido", json={"cenario": "hupaa"}).json()["codigo"]
    item = controle.post(f"/api/simulacao/sessoes/{codigo}/itens",
                         json={"nome": "Maca 7", "tipo": "Maca", "gerar_epc": True}).json()["itens"][-1]
    base = f"/api/simulacao/sessoes/{codigo}/itens/{item['id']}/trajeto"
    assert controle.post(base, json={"pontos": [{"x": 10, "y": 10, "t": 2}, {"x": 20, "y": 10, "t": 1}]}).status_code == 422
    assert controle.post(base, json={"pontos": [{"x": 10, "y": 10, "t": 0}]}).status_code == 422
    assert controle.post(base, json={"pontos": [{"x": 10, "y": 10, "t": 0}, {"x": 120, "y": 10, "t": 1}]}).status_code == 422
    ok = controle.post(base, json={"pontos": [{"x": 0, "y": 0, "t": 0}, {"x": 60, "y": 60, "t": 20}]})
    assert ok.status_code == 200, ok.text
    executando = next(i for i in ok.json()["itens"] if i["id"] == item["id"])
    # O desenho começa onde o item está; a posição final já é a do fim do trajeto.
    assert (executando["trajeto"]["pontos"][0]["x"], executando["trajeto"]["pontos"][0]["y"]) == (item["x"], item["y"])
    assert (executando["x"], executando["y"]) == (60, 60)
    assert controle.post(base, json={"pontos": [{"x": 1, "y": 1, "t": 0}, {"x": 2, "y": 2, "t": 1}]}).status_code == 409
    assert controle.patch(f"/api/simulacao/sessoes/{codigo}/itens/{item['id']}", json={"x": 5}).status_code == 409
    assert dashboard.post("/api/simulacao/relogio", json={"avancar_s": 600}).status_code == 409
    assert dashboard.post("/api/simulacao/relogio", json={"fator": 7}).status_code == 422
    acelerado = dashboard.post("/api/simulacao/relogio", json={"fator": 10}).json()
    assert acelerado["fator"] == 10 and acelerado["acelerado"] is True
    # As duas pessoas (simulador e dashboard) leem o mesmo relógio.
    assert controle.get("/api/simulacao/relogio").json()["fator"] == 10
    assert dashboard.get(f"/api/simulacao/sessoes/{codigo}/monitor").json()["relogio"]["fator"] == 10
    assert dashboard.post(f"/api/simulacao/sessoes/{codigo}/encerrar").status_code == 200
    # Encerrada a sessão, o relógio volta ao ritmo real (adiantamento, se houver, fica).
    assert controle.get("/api/simulacao/relogio").json()["fator"] == 1


def test_area_restrita_com_uma_antena_marca_cada_entrada_uma_vez(pg_engine, hu, tmp_path):
    """Leitor 5 (uma antena, sem portal) na escada: a permanência tem um só início;
    sair e voltar depois de um silêncio gera uma nova entrada (nova notificação)."""
    def entradas():
        with Session(pg_engine) as session:
            painel = service.monitor(session, service.obter_sessao(session, hu["codigo"]), now=hu["relogio"].agora)
            return {a["entrada_em"] for a in painel["alertas_restritos"]}, painel["alertas_restritos"]

    _executar(pg_engine, hu, "Maca 01", [(30, 15, 0), (19, 27, 1), (6, 44, 2), (6, 44, 6)])
    _rodar(pg_engine, tmp_path, hu, 6.5)
    primeira, alertas = entradas()
    assert len(primeira) == 1 and alertas[0]["equipamento"]["nome"] == "Maca 01"
    _rodar(pg_engine, tmp_path, hu, 2.0)  # continua lá: mesma entrada
    assert entradas()[0] == primeira
    # Sai, fica longe mais que o silêncio de entrada e volta.
    _executar(pg_engine, hu, "Maca 01", [(6, 44, 0), (30, 15, 2), (30, 15, service.ENTRADA_SILENCIO_S + 5), (6, 44, service.ENTRADA_SILENCIO_S + 8)])
    _rodar(pg_engine, tmp_path, hu, service.ENTRADA_SILENCIO_S + 9, passo=0.5)
    segunda, _ = entradas()
    assert len(segunda) == 1 and segunda != primeira and max(segunda) > max(primeira)


def test_historico_mostra_visto_perto_sem_confirmar_zona(pg_engine, hu, tmp_path):
    """Leitura sem transição entra no histórico como "visto perto da Zona X" e não
    confirma zona; a transição confirma, e a leitura que é a evidência dela não se repete."""
    from api.service_vistos import visitas

    _executar(pg_engine, hu, "Maca 01", [(30, 15, 0), (43, 15, 1), (43, 15, 3), (30, 15, 4)])
    _rodar(pg_engine, tmp_path, hu, 4.5)
    assert _estado(pg_engine, hu, "Maca 01") == (None, 0)  # só leitura: zona não confirmada
    with Session(pg_engine) as session:
        [visto] = visitas(session, hu["equipamentos"]["Maca 01"])
    assert visto["zona"] == "Zona 1" and visto["zona_confirmada_no_momento"] is None and visto["leituras"] >= 3

    hu["relogio"].agora += timedelta(seconds=120)
    _executar(pg_engine, hu, "Maca 01", ZONA_1_PARA_2)
    _rodar(pg_engine, tmp_path, hu, 3.5)
    assert _estado(pg_engine, hu, "Maca 01") == (hu["zonas"]["zona-2"], 1)
    with Session(pg_engine) as session:
        zonas = [v["zona"] for v in visitas(session, hu["equipamentos"]["Maca 01"])]
    assert "Zona 2" not in zonas  # a leitura do lado B é a própria transição confirmada
    # Só a visita antiga: o lado A da travessia é evidência da passagem confirmada e não se repete.
    assert zonas.count("Zona 1") == 1
