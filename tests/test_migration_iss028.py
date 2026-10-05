"""
Migration da ISS-028 (trilha append-only) com dados LEGADOS, em banco
descartável próprio e alembic por subprocesso — mesmo padrão de
`tests/test_migration_iss026.py`.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from test_migration_iss012 import _alembic, _saida, _sql

REVISAO_ANTERIOR = "d026a1b2c3d4"  # ISS-026
REVISAO_ISS028 = "e028a1b2c3d4"


@pytest.fixture
def banco(engine):
    """URL de um banco novo e vazio, removido no final (exige CREATEDB)."""
    nome = f"rfid_mig28_{uuid.uuid4().hex[:10]}"
    admin = create_engine(engine.url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conexao:
        conexao.execute(text(f'CREATE DATABASE "{nome}"'))
    try:
        yield engine.url.set(database=nome)
    finally:
        with admin.connect() as conexao:
            conexao.execute(text(f'DROP DATABASE IF EXISTS "{nome}" WITH (FORCE)'))
        admin.dispose()


def _ok(url, *argumentos: str) -> None:
    processo = _alembic(url, *argumentos)
    assert processo.returncode == 0, _saida(processo)


def _tem_trigger(url) -> bool:
    return bool(_sql(url, "SELECT count(*) FROM pg_trigger "
                          "WHERE tgname = 'tg_auditorias_append_only'")[0][0])


def _colunas(url) -> set[str]:
    return {linha[0] for linha in _sql(
        url, "SELECT column_name FROM information_schema.columns WHERE table_name='auditorias'")}


def _versao(url) -> str:
    return _sql(url, "SELECT version_num FROM alembic_version")[0][0]


def _legado(url) -> None:
    """Trilha da ISS-026, em inglês, com e sem autor."""
    _ok(url, "upgrade", REVISAO_ANTERIOR)
    _sql(url, """
        INSERT INTO usuarios (id, nome, email, senha_hash, perfil_id)
            VALUES (1, 'Ana', 'ana@x.org', 'x', (SELECT id FROM perfis WHERE nome='administrador'));
        INSERT INTO auditorias (id, usuario_id, entidade, entidade_id, acao, dados_depois) VALUES
            (1, 1, 'usuarios', 2, 'create', '{"nome": "Bia"}'),
            (2, NULL, 'associacoes_tag_equipamento', 5, 'update', NULL),
            (3, NULL, 'associacoes_tag_equipamento', 5, 'delete', NULL),
            (4, 1, 'historico_movimentacoes', 9, 'correcao_manual', NULL);
    """)


def test_legado_traduzido_origem_preenchida_trigger_e_checks(banco):
    _legado(banco)

    _ok(banco, "upgrade", "head")

    assert _sql(banco, "SELECT id, acao, origem, usuario_id FROM auditorias ORDER BY id") == [
        (1, "criar", "usuario", 1), (2, "atualizar", "sistema", None),
        (3, "excluir", "sistema", None), (4, "correcao_manual", "usuario", 1)]
    assert {"origem", "motivo", "correlation_id"} <= _colunas(banco)
    assert _tem_trigger(banco)
    _ok(banco, "check")

    for sql in ("UPDATE auditorias SET motivo = 'x' WHERE id = 1",
                "DELETE FROM auditorias WHERE id = 2"):
        with pytest.raises(DBAPIError, match="append-only"):
            _sql(banco, sql)
    insere = ("INSERT INTO auditorias (usuario_id, origem, entidade, acao) "
              "VALUES ({usuario}, '{origem}', 'usuarios', '{acao}')")
    for usuario, origem, acao, constraint in (
        ("NULL", "sistema", "voar", "ck_auditoria_acao_valida"),
        ("NULL", "robo", "criar", "ck_auditoria_origem_valida"),
        ("NULL", "usuario", "criar", "ck_auditoria_autor_coerente"),
        ("1", "sistema", "criar", "ck_auditoria_autor_coerente"),
        ("1", "anonimo", "login_recusado", "ck_auditoria_autor_coerente"),
    ):
        with pytest.raises(IntegrityError, match=constraint):
            _sql(banco, insere.format(usuario=usuario, origem=origem, acao=acao))
    # Sem alvo é válido agora (login de conta inexistente).
    _sql(banco, insere.format(usuario="NULL", origem="anonimo", acao="login_recusado"))


def test_downgrade_devolve_vocabulario_antigo_e_reupgrade(banco):
    _legado(banco)
    _ok(banco, "upgrade", REVISAO_ISS028)  # downgrade testado é só o da ISS-028

    _ok(banco, "downgrade", REVISAO_ANTERIOR)

    assert _sql(banco, "SELECT id, acao FROM auditorias ORDER BY id") == [
        (1, "create"), (2, "update"), (3, "delete"), (4, "correcao_manual")]
    assert not _tem_trigger(banco)
    assert not {"origem", "motivo", "correlation_id"} & _colunas(banco)
    assert not _sql(banco, "SELECT count(*) FROM pg_proc WHERE proname='auditorias_append_only'"
                    )[0][0]
    with pytest.raises(IntegrityError, match="ck_auditoria_acao_valida"):
        _sql(banco, "INSERT INTO auditorias (entidade, entidade_id, acao) VALUES ('x', 1, 'criar')")

    _ok(banco, "upgrade", "head")
    assert _tem_trigger(banco)
    assert _sql(banco, "SELECT acao FROM auditorias WHERE id = 1") == [("criar",)]
    _ok(banco, "check")


@pytest.mark.parametrize(("descricao", "linha"), [
    ("login_recusado sem alvo",
     "(NULL, 'anonimo', 'usuarios', NULL, 'login_recusado')"),
    ("vincular_epc sem equivalente",
     "(NULL, 'sistema', 'associacoes_tag_equipamento', 3, 'vincular_epc')"),
], ids=["sem-alvo", "vincular-epc"])
def test_downgrade_recusado_mantem_trilha_e_trigger(banco, descricao, linha):
    _ok(banco, "upgrade", REVISAO_ISS028)  # downgrade testado é só o da ISS-028
    _sql(banco, "INSERT INTO auditorias (usuario_id, origem, entidade, entidade_id, acao) "
                f"VALUES {linha}")
    antes = _sql(banco, "SELECT * FROM auditorias ORDER BY id")

    processo = _alembic(banco, "downgrade", REVISAO_ANTERIOR)

    assert processo.returncode != 0, descricao
    assert "downgrade recusado" in _saida(processo)
    assert _versao(banco) == REVISAO_ISS028
    assert _sql(banco, "SELECT * FROM auditorias ORDER BY id") == antes
    assert _tem_trigger(banco)


def test_downgrade_preserva_motivo_e_correlation_id_em_iss028(banco):
    _ok(banco, "upgrade", REVISAO_ISS028)  # downgrade testado é só o da ISS-028
    _sql(banco, """
        INSERT INTO auditorias (id, origem, entidade, entidade_id, acao, motivo,
                                correlation_id, dados_depois) VALUES
            (1, 'sistema', 'usuarios', 1, 'criar', 'comando criar_admin', 'abc123', '{"nome": "Ana"}'),
            (2, 'sistema', 'usuarios', 2, 'criar', 'só motivo', NULL, NULL),
            (3, 'sistema', 'usuarios', 3, 'criar', NULL, NULL, '{"nome": "Cid"}');
    """)

    _ok(banco, "downgrade", REVISAO_ANTERIOR)

    assert _sql(banco, "SELECT id, dados_depois FROM auditorias ORDER BY id") == [
        (1, {"nome": "Ana", "_iss028": {"motivo": "comando criar_admin",
                                        "correlation_id": "abc123"}}),
        (2, {"_iss028": {"motivo": "só motivo"}}),
        (3, {"nome": "Cid"}),
    ]
