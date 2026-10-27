"""Cenário padrão de demonstração do HU: 6 antes de iniciar, 9 ao iniciar, 11 no fim."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api import service_cadastro
from api.simulacao import cenario_demo, relogio, service
from api.simulacao.geometria import antenas_do_layout, detectar
from api.simulacao.presets import NOMES_PRESET
from api.simulacao.presets import teste_rapido as layout_hu
from db.models import Equipamento, HistoricoMovimentacao, SimulacaoSessao, TipoEquipamento
from rfid_location.recency import classify_recency, recency_threshold_from_env


def _ativos(session: Session) -> list[Equipamento]:
    return session.scalars(select(Equipamento).where(Equipamento.status == "ativo")).all()


@pytest.fixture
def layout_padrao(pg_engine):
    with Session(pg_engine) as session:
        registro = service.criar_layout(session, nome=NOMES_PRESET["hupaa"], cenario="hupaa",
                                        configuracao=layout_hu("hupaa"))
        return registro.id


def _dentro(area, x, y):
    return area["x"] <= x <= area["x"] + area["largura"] and area["y"] <= y <= area["y"] + area["altura"]


def test_seis_antes_nove_ao_iniciar_onze_depois_do_cadastro_e_reinicio_previsivel(pg_engine, layout_padrao):
    with Session(pg_engine) as session:
        cenario_demo.preparar(session)
        ativos = _ativos(session)
        assert len(ativos) == 6
        agora = relogio.do_banco(session).agora(datetime.now(UTC))
        limiar = recency_threshold_from_env()
        # Parados, em atenção pela regra de recência, dois por zona comum; a restrita vazia.
        assert {classify_recency(e.ultima_deteccao_em, agora, limiar) for e in ativos} == {"desatualizada"}
        por_zona = session.execute(select(Equipamento.ultima_zona_id, func.count())
                                   .where(Equipamento.status == "ativo").group_by(Equipamento.ultima_zona_id)).all()
        assert sorted(contagem for _, contagem in por_zona) == [2, 2, 2]
        assert session.scalar(select(func.count()).select_from(SimulacaoSessao)
                              .where(SimulacaoSessao.estado != "encerrada")) == 0

        sessao = cenario_demo.iniciar(session, None)
        assert len(_ativos(session)) == 9
        # Os três novos vieram de outro andar (elevador central): zona fora da planta, chegada recente.
        novos = [e for e in _ativos(session) if e.ultima_zona is not None and e.ultima_zona.nome == cenario_demo.ZONA_OUTRO_ANDAR]
        assert len(novos) == 3
        agora = relogio.do_banco(session).agora(datetime.now(UTC))
        assert {classify_recency(e.ultima_deteccao_em, agora, limiar) for e in novos} == {"recente"}
        layout = sessao.layout
        restrita = next(z for z in layout["zonas"] if z["restrita"])
        antenas = antenas_do_layout(layout)
        itens = {item["nome"]: item for item in sessao.itens}
        assert len(itens) == 9
        for nome, _, _ in cenario_demo.EQUIPAMENTOS_NOVOS:
            item = itens[nome]  # no centro, fora de toda zona e de todo alcance
            assert not any(z["area"] and _dentro(z["area"], item["x"], item["y"]) for z in layout["zonas"])
            assert not detectar(item["x"], item["y"], antenas, layout["proporcao"])
        for nome, _, _ in cenario_demo.EQUIPAMENTOS_ANTIGOS:
            item = itens[nome]
            assert not _dentro(restrita["area"], item["x"], item["y"])
            assert not detectar(item["x"], item["y"], antenas, layout["proporcao"])
        # Iniciar de novo, pausar e retomar não duplicam.
        assert cenario_demo.iniciar(session, None).codigo == sessao.codigo
        service.transicionar(session, sessao.codigo, "pausar")
        service.transicionar(session, sessao.codigo, "retomar")
        assert len(_ativos(session)) == 9

        # Dois itens acrescentados à mão, com etiqueta ainda sem cadastro: nada automático.
        for nome in ("Monitor extra", "Maca extra"):
            sessao = service.adicionar_item(session, sessao.codigo, nome=nome, tipo="Maca", epc=None,
                                            gerar_epc=True, x=None, y=None)
        assert len(_ativos(session)) == 9
        tipo = session.scalar(select(TipoEquipamento.id).limit(1))
        for item in sessao.itens[-2:]:
            service_cadastro.cadastrar(session, nome=item["nome"], tipo_id=tipo, epc=item["epc"])
        assert len(_ativos(session)) == 11

        # Os dois surgiram no centro (elevador): ao cadastrar, o histórico diz que vieram de outro andar.
        from api.simulacao.chegada import registrar_chegada
        for item in sessao.itens[-2:]:
            assert item["origem"] == "outro_andar"
            assert registrar_chegada(session, item["epc"].lower()) is True
        chegados = session.scalars(select(HistoricoMovimentacao).where(
            HistoricoMovimentacao.justificativa.like("Chegou de outro andar%"))).all()
        assert len(chegados) == 2 and all(h.origem_registro == "correcao_manual" for h in chegados)
        assert registrar_chegada(session, sessao.itens[-1]["epc"]) is False  # já tem histórico: não repete

        # Reiniciar: mesmo link, volta a nove, sem duplicar nem perder histórico.
        reiniciada = cenario_demo.reiniciar(session, sessao.codigo)
        assert reiniciada.codigo == sessao.codigo and len(reiniciada.itens) == 9
        ativos = _ativos(session)
        assert len(ativos) == 9
        assert sorted(e.nome for e in ativos) == sorted(
            nome for nome, _, _ in cenario_demo.EQUIPAMENTOS_ANTIGOS + cenario_demo.EQUIPAMENTOS_NOVOS)
        arquivados = session.scalars(select(Equipamento).where(Equipamento.status == "inativo")).all()
        assert len(arquivados) == 11 and all("-ARQ-" in (e.identificador_interno or "") for e in arquivados)

        cenario_demo.preparar(session)
        assert len(_ativos(session)) == 6
        assert cenario_demo.estado(session) == {"layout_id": layout_padrao, "layout": NOMES_PRESET["hupaa"],
                                                "sessao": None, "antigos": 6, "novos": 0}


def test_outros_layouts_continuam_iniciando_sem_cenario(pg_engine, layout_padrao):
    with Session(pg_engine) as session:
        outro = service.criar_layout(session, nome="Ensaio", cenario="easy")
        assert not cenario_demo.e_layout_padrao(session, outro.id)
        assert cenario_demo.e_layout_padrao(session, layout_padrao)
        assert service.iniciar_sessao(session, outro.id, None).itens == []
        assert len(_ativos(session)) == 0


def test_cada_execucao_comeca_na_demonstracao_padrao_uma_vez_so(pg_engine, layout_padrao, tmp_path, monkeypatch):
    """Toda subida do localhost volta ao padrão (6 parados + 3 no centro); recargas não."""
    monkeypatch.setattr(cenario_demo, "MARCAS", tmp_path)
    assert cenario_demo.restaurar_na_subida(pg_engine, "execucao-1") is True
    with Session(pg_engine) as session:
        sessao = session.scalar(select(SimulacaoSessao).where(SimulacaoSessao.estado != "encerrada"))
        assert len(sessao.itens) == 9 and len(_ativos(session)) == 9
        # Durante a apresentação: um item extra e um movimento.
        service.adicionar_item(session, sessao.codigo, nome="Extra", tipo="Maca", epc=None,
                               gerar_epc=True, x=None, y=None)
    assert cenario_demo.restaurar_na_subida(pg_engine, "execucao-1") is False  # recarga: mantém
    with Session(pg_engine) as session:
        assert len(session.scalar(select(SimulacaoSessao).where(SimulacaoSessao.estado != "encerrada")).itens) == 10
    assert cenario_demo.restaurar_na_subida(pg_engine, "execucao-2") is True  # nova execução: padrão
    with Session(pg_engine) as session:
        aberta = session.scalar(select(SimulacaoSessao).where(SimulacaoSessao.estado != "encerrada"))
        assert sorted(i["nome"] for i in aberta.itens) == sorted(
            nome for nome, _, _ in cenario_demo.EQUIPAMENTOS_ANTIGOS + cenario_demo.EQUIPAMENTOS_NOVOS)


def test_fora_de_servico_continua_no_painel_e_arquivado_nao(pg_engine, layout_padrao):
    from datetime import timedelta as td

    from api.service_busca_ativos import buscar
    from api.service_dashboard import resumo
    with Session(pg_engine) as session:
        cenario_demo.preparar(session)
        maca, monitor = session.scalars(select(Equipamento).where(Equipamento.status == "ativo").limit(2)).all()
        maca.status = "inativo"  # fora de serviço: a etiqueta continua vinculada
        cenario_demo._dar_baixa(session, monitor, datetime.now(UTC))  # arquivado: sem etiqueta
        session.commit()
        agora, limiar = datetime.now(UTC), td(minutes=30)
        pagina = buscar(session, now=agora, threshold=limiar, page_size=50, somente_ativos=True)
        nomes = {item.nome: item.status for item in pagina.items}
        assert nomes[maca.nome] == "fora_de_servico"
        assert monitor.nome not in nomes
        assert resumo(session, now=agora, threshold=limiar, somente_ativos=True)["fora_de_servico"] == 1
