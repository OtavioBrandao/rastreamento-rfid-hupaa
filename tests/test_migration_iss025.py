"""
Migration da ISS-025 (versão otimista e referência da correção) com dados
LEGADOS, em banco descartável próprio e alembic por subprocesso — mesmo
padrão de `tests/test_migration_iss028.py`.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from test_migration_iss012 import _alembic, _saida, _sql

REVISAO_ANTERIOR = "e028a1b2c3d4"  # ISS-028
REVISAO_ISS025 = "b025a1b2c3d4"


@pytest.fixture
def banco(engine):
    """URL de um banco novo e vazio, removido no final (exige CREATEDB)."""
    nome = f"rfid_mig25_{uuid.uuid4().hex[:10]}"
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


def _legado(url) -> None:
    """Equipamento e uma correção manual anteriores à ISS-025."""
    _ok(url, "upgrade", REVISAO_ANTERIOR)
    _sql(url, """
        INSERT INTO tipos_equipamento (id, nome, nome_normalizado) VALUES (1, 'Maca', 'maca');
        INSERT INTO andares (id, nome, nome_normalizado) VALUES (1, 'a', 'a');
        INSERT INTO setores (id, andar_id, nome, nome_normalizado) VALUES (1, 1, 's', 's');
        INSERT INTO zonas (id, setor_id, nome, nome_normalizado) VALUES (1, 1, 'z1', 'z1'),
            (2, 1, 'z2', 'z2');
        INSERT INTO equipamentos (id, nome, tipo_id, identificador_interno,
            identificador_interno_normalizado) VALUES (1, 'Maca', 1, 'PAT-1', 'pat-1'),
            (2, 'Maca', 1, 'PAT-2', 'pat-2');
        INSERT INTO historico_movimentacoes (id, equipamento_id, zona_destino_id, origem_registro,
            justificativa, movimentada_em) VALUES
            (1, 1, 1, 'correcao_manual', 'vista na sala', '2026-09-28 10:00:00+00');
    """)


def test_legado_recebe_versao_1_checks_e_alembic_check(banco):
    _legado(banco)

    _ok(banco, "upgrade", REVISAO_ISS025)

    assert _sql(banco, "SELECT id, versao FROM equipamentos ORDER BY id") == [(1, 1), (2, 1)]
    assert _sql(banco, "SELECT referencia FROM historico_movimentacoes") == [(None,)]
    with pytest.raises(IntegrityError, match="ck_equipamentos_versao_positiva"):
        _sql(banco, "UPDATE equipamentos SET versao = 0 WHERE id = 1")
    with pytest.raises(IntegrityError, match="ck_historico_referencia_so_manual"):
        _sql(banco, "UPDATE historico_movimentacoes SET referencia = '   ' WHERE id = 1")
    _sql(banco, "UPDATE historico_movimentacoes SET referencia = 'OS-9' WHERE id = 1")

    _ok(banco, "upgrade", "head")
    _ok(banco, "check")


def test_downgrade_preserva_referencia_na_justificativa_e_reupgrade(banco):
    _legado(banco)
    _ok(banco, "upgrade", REVISAO_ISS025)
    _sql(banco, """
        UPDATE historico_movimentacoes SET referencia = 'OS-123' WHERE id = 1;
        INSERT INTO historico_movimentacoes (id, equipamento_id, zona_destino_id, origem_registro,
            justificativa, movimentada_em, registro_anterior_id, zona_origem_id)
            VALUES (2, 1, 2, 'correcao_manual', 'sem referência', '2026-09-28 11:00:00+00', 1, 1);
        UPDATE equipamentos SET versao = 7 WHERE id = 1;
    """)

    _ok(banco, "downgrade", REVISAO_ANTERIOR)

    assert _sql(banco, "SELECT id, justificativa FROM historico_movimentacoes ORDER BY id") == [
        (1, "vista na sala [referência: OS-123]"), (2, "sem referência")]
    colunas = {linha[0] for linha in _sql(banco, """
        SELECT table_name || '.' || column_name FROM information_schema.columns
        WHERE table_name IN ('equipamentos', 'historico_movimentacoes')""")}
    assert not {"equipamentos.versao", "historico_movimentacoes.referencia"} & colunas

    _ok(banco, "upgrade", REVISAO_ISS025)
    assert _sql(banco, "SELECT id, versao FROM equipamentos ORDER BY id") == [(1, 1), (2, 1)]
    _ok(banco, "upgrade", "head")
    _ok(banco, "check")
