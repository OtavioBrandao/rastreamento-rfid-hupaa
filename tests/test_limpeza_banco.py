"""Limpeza segura: prévia sem efeito, remoção do experimental, preservação e travas."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from suporte_auth import hash_de

from api.service_cadastro import cadastrar
from api.simulacao import service as simulacao
from db.models import (
    Antena,
    Auditoria,
    Equipamento,
    HistoricoMovimentacao,
    Leitor,
    LeituraBruta,
    Passagem,
    SimulacaoLayout,
    Tag,
    TipoEquipamento,
    Usuario,
    Zona,
)
from tools import limpeza_banco
from tools.lab_launcher.seed import TIPO_SINTETICO, semear, semear_equipamentos

T0 = datetime(2026, 10, 20, 12, tzinfo=UTC)
EPC_REAL = "E2000017221101441890A001"
EPC_LAB = "E2804C41AAAAAAAAAAAAAAAA"


@pytest.fixture
def base_experimental(pg_engine):
    """Banco com usuário, auditoria, cadastro real, laboratório, simulação e telemetria."""
    with Session(pg_engine) as db:
        db.execute(text(
            "INSERT INTO usuarios (nome, email, senha_hash, perfil_id) VALUES ('Ana', "
            "'ana@hupaa.example', :h, (SELECT id FROM perfis WHERE nome = 'administrador'))"),
            {"h": hash_de("senha-correta-1")})
        db.add(Auditoria(origem="sistema", entidade="teste", acao="criar"))
        db.commit()
        semear(db)
        semear_equipamentos(db, [(EPC_LAB, "Bomba de laboratório")], TIPO_SINTETICO)
        tipo = TipoEquipamento(nome="Maca", nome_normalizado="maca")
        db.add(tipo)
        db.commit()
        real, _ = cadastrar(db, nome="Maca hospitalar", tipo_id=tipo.id, epc=EPC_REAL)
        sem_tag, _ = cadastrar(db, nome="Cadeira de rodas", tipo_id=tipo.id)
        easy = simulacao.criar_layout(db, nome=None, cenario="easy")
        simulacao.iniciar_sessao(db, easy.id, None)
        hupaa = simulacao.criar_layout(db, nome=None, cenario="hupaa")
        simulacao.iniciar_sessao(db, hupaa.id, None)
        fisica = db.scalar(select(Antena.id).join(Leitor).where(Leitor.reader_id == "reader-01"))
        virtual = db.scalar(select(Antena.id).join(Leitor).where(Leitor.reader_id == "sim-easy-01"))
        leituras = []
        for indice, (antena, epc) in enumerate(((fisica, EPC_REAL), (virtual, EPC_REAL),
                                               (virtual, EPC_LAB))):
            leitura = LeituraBruta(event_id=f"limpeza-{indice}", antena_id=antena, epc=epc,
                                   lido_em=T0 + timedelta(seconds=indice))
            db.add(leitura)
            db.flush()
            leituras.append(leitura)
        portal = db.scalar(select(Antena.portal_id).where(Antena.id == fisica))
        passagem = Passagem(epc=EPC_REAL, portal_id=portal, antena_origem_id=fisica,
                            antena_destino_id=virtual, leitura_origem_id=leituras[0].id,
                            leitura_destino_id=leituras[1].id, detectada_em=T0)
        db.add(passagem)
        db.flush()
        zona = db.get(Antena, virtual).zona_associada_id
        movimento = HistoricoMovimentacao(
            equipamento_id=real.id, zona_destino_id=zona, movimentada_em=T0,
            justificativa="correção de teste", origem_registro="correcao_manual")
        db.add(movimento)
        db.flush()
        db.execute(text("UPDATE equipamentos SET ultima_zona_id = :z, ultima_deteccao_em = :t, "
                        "ultima_movimentacao_id = :m WHERE id = :e"),
                   {"z": zona, "t": T0, "m": movimento.id, "e": real.id})
        db.execute(text("UPDATE leitores SET ultimo_contato_em = :t"), {"t": T0})
        db.commit()
        return {"real": real.id, "sem_tag": sem_tag.id}


def _totais(engine) -> dict[str, int]:
    with engine.connect() as conexao:
        return {tabela: conexao.scalar(text(f"SELECT count(*) FROM {tabela}")) for tabela in (
            "leituras_brutas", "passagens", "historico_movimentacoes", "equipamentos", "tags",
            "associacoes_tag_equipamento", "leitores", "antenas", "mapeamentos_antena_portal",
            "portais", "zonas", "andares", "simulacao_sessoes", "simulacao_layouts", "usuarios",
            "perfis", "auditorias", "sessoes")}


def test_previa_nao_altera_nada(pg_engine, base_experimental):
    antes = _totais(pg_engine)
    with pg_engine.connect() as conexao, conexao.begin():
        resultado = dict((etapa.descricao, total) for etapa, total in
                         limpeza_banco.previa(conexao, limpeza_banco.planejar(limpeza_banco.ESCOPOS)))
    assert resultado["Leituras brutas"] == 3
    assert resultado["Passagens"] == 1
    assert resultado["Leitores virtuais (serial SIM-*)"] == 6  # 1 do EASY + 5 do HUPAA
    assert resultado["Equipamentos de teste"] == 1
    assert _totais(pg_engine) == antes


def test_previa_roda_em_transacao_somente_leitura(pg_engine, base_experimental):
    with pg_engine.connect() as conexao, conexao.begin():
        limpeza_banco.previa(conexao, [])
        with pytest.raises(DBAPIError):
            conexao.execute(text("DELETE FROM leituras_brutas"))


def test_executar_remove_experimental_e_preserva_usuarios_auditoria_e_cadastros(
        pg_engine, base_experimental):
    antes = _totais(pg_engine)
    with pg_engine.begin() as conexao:
        limpeza_banco.executar(conexao, limpeza_banco.planejar(limpeza_banco.ESCOPOS))
    depois = _totais(pg_engine)
    for tabela in ("leituras_brutas", "passagens", "historico_movimentacoes", "simulacao_sessoes"):
        assert depois[tabela] == 0, tabela
    assert depois["usuarios"] == antes["usuarios"] == 1
    assert depois["perfis"] == antes["perfis"]
    assert depois["auditorias"] == antes["auditorias"] + 1  # a própria limpeza
    assert depois["simulacao_layouts"] == 2  # configurações ficam
    with Session(pg_engine) as db:
        nomes = set(db.scalars(select(Equipamento.nome)))
        assert nomes == {"Maca hospitalar", "Cadeira de rodas"}
        real = db.get(Equipamento, base_experimental["real"])
        assert (real.ultima_zona_id, real.ultima_movimentacao_id, real.ultima_deteccao_em) == (
            None, None, None)
        assert set(db.scalars(select(Tag.epc))) == {EPC_REAL}
        assert set(db.scalars(select(Leitor.reader_id))) == {"reader-01"}
        leitor = db.scalar(select(Leitor))
        assert leitor.ultimo_contato_em is None and leitor.status == "nunca_conectado"
        assert db.scalar(select(func.count()).select_from(Zona).where(
            Zona.nome.in_(("Zona A", "Zona B")))) == 2  # cadastro EASY de referência
        assert db.scalar(text("SELECT count(*) FROM andares WHERE nome = 'Simulação HUPAA'")) == 0
        assert all(layout.vinculos is None for layout in db.scalars(select(SimulacaoLayout)))
        assert db.scalar(select(Usuario.email)) == "ana@hupaa.example"
        registro = db.scalar(select(Auditoria).where(Auditoria.entidade == "limpeza_banco"))
        assert registro.dados_depois["Leituras brutas"] == 3
    with pg_engine.connect() as conexao:
        assert all(ok for _, ok, _ in limpeza_banco.verificar(conexao))
    # Repetível: rodar de novo não encontra mais nada para remover.
    with pg_engine.connect() as conexao, conexao.begin():
        restantes = limpeza_banco.previa(conexao, limpeza_banco.planejar(limpeza_banco.ESCOPOS))
    assert sum(total for etapa, total in restantes if etapa.escopo != "telemetria") == 0


def test_auditoria_continua_imutavel_apos_limpeza(pg_engine, base_experimental):
    with pg_engine.begin() as conexao:
        limpeza_banco.executar(conexao, limpeza_banco.planejar(limpeza_banco.ESCOPOS))
    with pytest.raises(DBAPIError):
        with pg_engine.begin() as conexao:
            conexao.execute(text("DELETE FROM auditorias"))


def test_escopo_telemetria_sozinho_mantem_equipamentos_e_simulacao(pg_engine, base_experimental):
    with pg_engine.begin() as conexao:
        limpeza_banco.executar(conexao, limpeza_banco.planejar(["telemetria"]))
    totais = _totais(pg_engine)
    assert totais["leituras_brutas"] == 0
    assert totais["equipamentos"] == 3 and totais["simulacao_sessoes"] == 2


def test_equipamento_cadastrado_so_sai_com_id_explicito(pg_engine, base_experimental):
    plano = limpeza_banco.planejar(["telemetria"], equipamentos=[base_experimental["sem_tag"]])
    with pg_engine.begin() as conexao:
        limpeza_banco.executar(conexao, plano)
    with Session(pg_engine) as db:
        assert set(db.scalars(select(Equipamento.nome))) == {"Maca hospitalar", "Bomba de laboratório"}


def test_planejamento_recusa_combinacao_que_quebraria_fks():
    with pytest.raises(ValueError, match="telemetria"):
        limpeza_banco.planejar(["simulacao"])
    with pytest.raises(ValueError, match="desconhecido"):
        limpeza_banco.planejar(["usuarios"])


@pytest.mark.parametrize("ambiente,url,args,trecho", [
    ({"APP_ENV": "production"}, "postgresql+psycopg2://u:p@localhost/rfid", ["--confirmar", "rfid"],
     "produção"),
    ({}, "postgresql+psycopg2://u:p@ep-x.neon.tech/rfid", ["--confirmar", "rfid"], "não é local"),
    ({}, "postgresql+psycopg2://u:p@localhost/rfid", [], "--confirmar rfid"),
    ({}, "postgresql+psycopg2://u:p@localhost/rfid", ["--confirmar", "outro"], "--confirmar rfid"),
])
def test_travas_impedem_execucao_acidental(monkeypatch, capsys, ambiente, url, args, trecho):
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.delenv("APP_ENV", raising=False)
    for chave, valor in ambiente.items():
        monkeypatch.setenv(chave, valor)
    assert limpeza_banco.main(["executar", *args]) == 2
    saida = capsys.readouterr()
    assert trecho in saida.err
    assert "p@" not in saida.out  # senha nunca aparece
