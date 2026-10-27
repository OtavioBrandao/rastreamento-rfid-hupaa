"""Sentido nos portais de entrada das zonas e histórico em percursos, pelo pipeline real.

Planta e leitores do layout local da demonstração do HU (``fixtures/layout_hu_demo_entradas.json``):
em cada portal de entrada, a Antena 1 fica na circulação e a Antena 2 dentro da zona.
Na linha y = 29: a Antena 2 da Zona 1 lê x ≈ 35–41, a Antena 1 da Zona 1 lê x ≈ 45–51;
entre 52 e 53 ninguém lê (circulação); a Antena 1 da Zona 2 lê x ≈ 54–60 e a Antena 2
da Zona 2 lê x ≈ 64–70.

- Antena 1 → 2: ``Circulação → Zona X`` (entrou).
- Antena 2 → 1: ``Zona X → Circulação`` (saiu); parado, continua na circulação.
- Só a Antena 1: "visto perto da Zona X", sem deslocamento.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from api import service_cadastro
from api.service_percursos import percursos
from api.simulacao import cenario_demo, service
from api.simulacao.presets import NOMES_PRESET
from db.models import (
    Antena,
    AssociacaoTagEquipamento,
    Equipamento,
    HistoricoMovimentacao,
    Leitor,
    LeituraBruta,
    Passagem,
    Portal,
    TipoEquipamento,
    Zona,
)
from tests.test_simulacao_trajeto import _rodar as _rodar_teste
from tests.test_simulacao_trajeto import relogio_falso

LAYOUT = json.loads((Path(__file__).parent / "fixtures" / "layout_hu_demo_entradas.json").read_text(encoding="utf-8"))
Y = 29
DENTRO_Z1, CIRCULACAO, DENTRO_Z2 = 30, 52.5, 75


@pytest.fixture
def demo(pg_engine):
    with relogio_falso() as relogio, Session(pg_engine) as session:
        service.criar_layout(session, nome=NOMES_PRESET["hupaa"], cenario="hupaa", configuracao=LAYOUT)
        cenario_demo.preparar(session)
        sessao = cenario_demo.iniciar(session, None)
        itens = {item["nome"]: item for item in sessao.itens}
        equipamentos = {e.nome: e.id for e in session.scalars(select(Equipamento))}
        zonas = {z.nome: z.id for z in session.scalars(select(Zona))}
        yield {"codigo": sessao.codigo, "itens": {nome: item["id"] for nome, item in itens.items()},
               "posicoes": {nome: (item["x"], item["y"]) for nome, item in itens.items()},
               "equipamentos": equipamentos, "zonas": zonas, "relogio": relogio}


def _rodar(*args, **kwargs):
    """Pipeline com o detector do ingestor real (janela de confirmação, origem ativa)."""
    return _rodar_teste(*args, producao=True, **kwargs)


def _por(pg_engine, demo, nome, *pontos):
    """Leva o item pelos pontos (x, y), um segundo a cada 4,5 unidades."""
    trajeto, t = [], 0.0
    for indice, (x, y) in enumerate(pontos):
        if indice:
            ax, ay = pontos[indice - 1]
            t += max(1.0, round(((x - ax) ** 2 + (y - ay) ** 2) ** 0.5 / 4.5, 1))
        trajeto.append({"x": x, "y": y, "t": t})
    with Session(pg_engine) as session:
        service.executar_trajeto(session, demo["codigo"], demo["itens"][nome], trajeto)
    return t


def _andar(pg_engine, tmp_path, demo, nome, *pontos, parado=2.0):
    duracao = _por(pg_engine, demo, nome, *pontos)
    _rodar(pg_engine, tmp_path, demo, duracao + parado)


def _colocar(pg_engine, demo, nome, x, y):
    with Session(pg_engine) as session:
        service.alterar_item(session, demo["codigo"], demo["itens"][nome], {"x": x, "y": y})


def _zona(pg_engine, demo, nome):
    with Session(pg_engine) as session:
        equipamento = session.get(Equipamento, demo["equipamentos"][nome])
        return session.get(Zona, equipamento.ultima_zona_id).nome if equipamento.ultima_zona_id else None


def _etapas(pg_engine, demo, nome):
    with Session(pg_engine) as session:
        origem, destino = Zona.__table__.alias(), Zona.__table__.alias()
        return [(o, d) for o, d in session.execute(
            select(origem.c.nome, destino.c.nome)
            .join_from(HistoricoMovimentacao, destino, destino.c.id == HistoricoMovimentacao.zona_destino_id)
            .outerjoin(origem, origem.c.id == HistoricoMovimentacao.zona_origem_id)
            .where(HistoricoMovimentacao.equipamento_id == demo["equipamentos"][nome],
                   HistoricoMovimentacao.origem_registro == "passagem_automatica")
            .order_by(HistoricoMovimentacao.movimentada_em))]


def _historico(pg_engine, demo, nome):
    with Session(pg_engine) as session:
        return percursos(session, demo["equipamentos"][nome])


CIRC = "Circulação (fora das zonas)"


def test_saida_parada_na_circulacao_entrada_em_outra_zona_e_volta(pg_engine, demo, tmp_path):
    nome = "Bomba de infusão HU-01"  # parada na Zona 1 desde o preparo
    assert _zona(pg_engine, demo, nome) == "Zona 1"
    _colocar(pg_engine, demo, nome, DENTRO_Z1, Y)

    # Zona 1 → circulação (antenas 2 → 1) e para: continua na circulação.
    _andar(pg_engine, tmp_path, demo, nome, (DENTRO_Z1, Y), (CIRCULACAO, Y))
    assert _zona(pg_engine, demo, nome) == CIRC
    demo["relogio"].agora += timedelta(seconds=40)
    _rodar(pg_engine, tmp_path, demo, 3)  # parado: nenhuma leitura, nada muda
    assert _etapas(pg_engine, demo, nome) == [("Zona 1", CIRC)]
    with Session(pg_engine) as session:
        regra = session.execute(select(Passagem.direcao, Passagem.direcao_regra)
                                .order_by(Passagem.id.desc()).limit(1)).one()
    assert tuple(regra) == ("b_para_a", "entry_portal_order_v1")
    historico = _historico(pg_engine, demo, nome)
    assert historico["em_circulacao"] is True
    saida = historico["items"][0]
    assert (saida["titulo"], saida["completo"]) == ("Zona 1 → Circulação", False)
    assert saida["etapas"][0]["ordem"] == "2 → 1" and saida["etapas"][0]["portal"] == "Portal para Zona 1"

    # Circulação → Zona 2 (antenas 1 → 2): percurso resumido Zona 1 → Zona 2.
    _andar(pg_engine, tmp_path, demo, nome, (CIRCULACAO, Y), (DENTRO_Z2, Y))
    assert _zona(pg_engine, demo, nome) == "Zona 2"
    historico = _historico(pg_engine, demo, nome)
    percurso = historico["items"][0]
    assert (percurso["titulo"], percurso["completo"]) == ("Zona 1 → Zona 2", True)
    assert [(e["de"], e["para"], e["ordem"]) for e in percurso["etapas"]] == [
        ("Zona 1", "Circulação", "2 → 1"), ("Circulação", "Zona 2", "1 → 2")]
    assert percurso["tempo_na_circulacao_s"] >= 40
    assert all(a["lido_em"] is not None for e in percurso["etapas"] for a in e["antenas"])
    assert historico["em_circulacao"] is False

    # Volta: 2 → 1 na Zona 2 e 1 → 2 na Zona 1, num trajeto só.
    demo["relogio"].agora += timedelta(seconds=10)
    _andar(pg_engine, tmp_path, demo, nome, (DENTRO_Z2, Y), (DENTRO_Z1, Y))
    assert _zona(pg_engine, demo, nome) == "Zona 1"
    assert _etapas(pg_engine, demo, nome) == [("Zona 1", CIRC), (CIRC, "Zona 2"), ("Zona 2", CIRC), (CIRC, "Zona 1")]
    titulos = [e["titulo"] for e in _historico(pg_engine, demo, nome)["items"] if e["tipo"] == "percurso"]
    assert titulos[:2] == ["Zona 2 → Zona 1", "Zona 1 → Zona 2"]


def test_leituras_repetidas_de_uma_antena_nao_criam_movimentacao(pg_engine, demo, tmp_path):
    nome = "Monitor multiparamétrico HU-02"
    _colocar(pg_engine, demo, nome, DENTRO_Z1, Y)
    # Fica 20 s no alcance da Antena 2 (dentro da Zona 1) e volta para o fundo da zona.
    _por(pg_engine, demo, nome, (DENTRO_Z1, Y), (38, Y))
    _rodar(pg_engine, tmp_path, demo, 20)
    assert _etapas(pg_engine, demo, nome) == []
    assert _zona(pg_engine, demo, nome) == "Zona 1"


def test_elevador_visto_perto_sem_entrar_e_depois_entra(pg_engine, demo, tmp_path):
    nome = "Maca HU-07"  # chegou de outro andar e está no centro
    assert _zona(pg_engine, demo, nome) == cenario_demo.ZONA_OUTRO_ANDAR
    centro = demo["posicoes"][nome]
    # Encosta só na Antena 1 da Zona 1 e volta: observação, sem deslocamento.
    _andar(pg_engine, tmp_path, demo, nome, centro, (CIRCULACAO, Y), (48, Y), (48, Y + 0.01), (CIRCULACAO, Y))
    assert _zona(pg_engine, demo, nome) == cenario_demo.ZONA_OUTRO_ANDAR
    assert _etapas(pg_engine, demo, nome) == []
    historico = _historico(pg_engine, demo, nome)
    observacao = historico["items"][0]
    assert observacao["tipo"] == "observacao" and observacao["titulo"] == "Visto perto da Zona 1"
    assert observacao["zona_confirmada_no_momento"] == cenario_demo.ZONA_OUTRO_ANDAR
    assert historico["ultima_observacao"]["zona"] == "Zona 1" and historico["ultima_observacao"]["porta"] == 1

    # Agora passa 1 → 2: confirma a Zona 1; a origem é a última localização confirmada.
    demo["relogio"].agora += timedelta(seconds=15)  # logo depois: a observação não some
    _andar(pg_engine, tmp_path, demo, nome, (CIRCULACAO, Y), (DENTRO_Z1, Y))
    assert _zona(pg_engine, demo, nome) == "Zona 1"
    assert _etapas(pg_engine, demo, nome) == [(CIRC, "Zona 1")]
    percurso = next(e for e in _historico(pg_engine, demo, nome)["items"] if e["tipo"] == "percurso")
    assert percurso["titulo"] == f"{cenario_demo.ZONA_OUTRO_ANDAR} → Zona 1"
    assert percurso["saida_registrada"] is False and percurso["etapas"][0]["ordem"] == "1 → 2"
    tipos = [e["tipo"] for e in _historico(pg_engine, demo, nome)["items"]]
    assert tipos[:2] == ["percurso", "observacao"]


def test_sem_origem_conhecida_nao_inventa_zona_anterior(pg_engine, demo, tmp_path):
    with Session(pg_engine) as session:
        sessao = service.adicionar_item(session, demo["codigo"], nome="Maca extra", tipo="Maca", epc=None,
                                        gerar_epc=True, x=CIRCULACAO, y=Y + 3)
        item = sessao.itens[-1]
        tipo = session.scalar(select(TipoEquipamento.id).limit(1))
        equipamento_id = service_cadastro.cadastrar(session, nome="Maca extra", tipo_id=tipo, epc=item["epc"])[0].id
        # Sem chegada de outro andar: este equipamento nunca teve localização confirmada.
        session.query(Equipamento).filter_by(id=equipamento_id).update({"ultima_zona_id": None, "ultima_movimentacao_id": None})
        session.query(HistoricoMovimentacao).filter_by(equipamento_id=equipamento_id).delete()
        session.commit()
    demo["itens"]["Maca extra"], demo["equipamentos"]["Maca extra"] = item["id"], equipamento_id
    _andar(pg_engine, tmp_path, demo, "Maca extra", (CIRCULACAO, Y + 3), (CIRCULACAO, Y), (DENTRO_Z1, Y))
    assert _zona(pg_engine, demo, "Maca extra") == "Zona 1"
    percurso = _historico(pg_engine, demo, "Maca extra")["items"][0]
    assert percurso["titulo"] == "Origem desconhecida → Zona 1" and percurso["origem"] is None


def test_reinicio_nao_usa_leitura_da_rodada_anterior(pg_engine, demo, tmp_path):
    """O ingestor lembra a última antena da rodada anterior; com o equipamento recriado,
    o par (leitura antiga, leitura nova) não vira saída falsa."""
    nome = "Bomba de infusão HU-01"
    _colocar(pg_engine, demo, nome, DENTRO_Z1, Y)
    _andar(pg_engine, tmp_path, demo, nome, (DENTRO_Z1, Y), (CIRCULACAO, Y), (DENTRO_Z1, Y))
    assert _etapas(pg_engine, demo, nome) == [("Zona 1", CIRC), (CIRC, "Zona 1")]
    demo["relogio"].agora += timedelta(seconds=30)
    with Session(pg_engine) as session:
        sessao = cenario_demo.reiniciar(session, demo["codigo"])
        demo["equipamentos"][nome] = session.scalar(select(Equipamento.id).where(Equipamento.nome == nome))
        demo["itens"] = {item["nome"]: item["id"] for item in sessao.itens}
    _colocar(pg_engine, demo, nome, CIRCULACAO, Y)
    demo["relogio"].agora += timedelta(seconds=5)
    _andar(pg_engine, tmp_path, demo, nome, (CIRCULACAO, Y), (DENTRO_Z1, Y))
    assert _etapas(pg_engine, demo, nome) == [(CIRC, "Zona 1")]


def test_passagem_com_leitura_anterior_ao_vinculo_nao_vira_movimentacao(pg_engine, demo):
    """Proteção direta: a primeira evidência é de antes do vínculo atual da etiqueta."""
    from rfid_location.repository import pending_ids
    from rfid_location.service import LocationProjectionService

    nome = "Bomba de infusão HU-01"
    epc = cenario_demo.EQUIPAMENTOS_ANTIGOS[0][2]
    with Session(pg_engine) as session:
        inicio = session.scalar(select(AssociacaoTagEquipamento.inicio).where(
            AssociacaoTagEquipamento.equipamento_id == demo["equipamentos"][nome],
            AssociacaoTagEquipamento.fim.is_(None)))
        antenas = dict(session.execute(select(Antena.porta_numero, Antena.id).join(Leitor, Leitor.id == Antena.leitor_id)
                                       .where(Leitor.reader_id == "sim-hupaa-09")).all())
        leituras = []
        for porta, em, chave in ((2, inicio - timedelta(minutes=5), "antiga"), (1, inicio + timedelta(seconds=5), "nova")):
            leitura = LeituraBruta(event_id=f"teste-vinculo-{chave}", antena_id=antenas[porta], epc=epc, lido_em=em)
            session.add(leitura)
            session.flush()
            leituras.append(leitura.id)
        portal = session.scalar(select(Portal.id).where(Portal.nome == "Portal para Zona 1"))
        passagem = Passagem(epc=epc, portal_id=portal, antena_origem_id=antenas[2], antena_destino_id=antenas[1],
                            leitura_origem_id=leituras[0], leitura_destino_id=leituras[1],
                            detectada_em=inicio + timedelta(seconds=5), direcao="b_para_a", direcao_status="confirmed", direcao_regra="entry_portal_order_v1",
                            zona_origem_id=demo["zonas"]["Zona 1"], zona_destino_id=demo["zonas"][CIRC])
        session.add(passagem)
        session.commit()
        passagem_id = passagem.id
    assert LocationProjectionService(pg_engine).process_passage(passagem_id).status == "unresolved_epc"
    assert passagem_id not in pending_ids(pg_engine)  # e não fica voltando a cada ciclo
    assert _zona(pg_engine, demo, nome) == "Zona 1"
