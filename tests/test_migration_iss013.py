"""
Tests for ISS-013 migration (68e5a26c2e17), verifying schema evolution,
partial unique index, backfill derivation, and fail-fast guards.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

RAIZ = Path(__file__).resolve().parent.parent
REVISAO_ANTERIOR = "da436f7c75b3"
REVISAO_ISS013 = "68e5a26c2e17"


@pytest.fixture
def banco(engine):
    """Disposable temporary test database."""
    nome = f"rfid_mig_13_{uuid.uuid4().hex[:10]}"
    admin = create_engine(engine.url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conexao:
        conexao.execute(text(f'CREATE DATABASE "{nome}"'))
    try:
        yield engine.url.set(database=nome)
    finally:
        with admin.connect() as conexao:
            conexao.execute(text(f'DROP DATABASE IF EXISTS "{nome}" WITH (FORCE)'))
        admin.dispose()


def _alembic(url, *argumentos: str) -> subprocess.CompletedProcess:
    ambiente = {**os.environ, "DATABASE_URL": url.render_as_string(hide_password=False)}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *argumentos],
        cwd=RAIZ,
        env=ambiente,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _saida(processo: subprocess.CompletedProcess) -> str:
    return processo.stdout + processo.stderr


def _upgrade(url, alvo: str) -> None:
    processo = _alembic(url, "upgrade", alvo)
    assert processo.returncode == 0, _saida(processo)


def _downgrade(url, alvo: str) -> None:
    processo = _alembic(url, "downgrade", alvo)
    assert processo.returncode == 0, _saida(processo)


def _sql(url, instrucoes: str, **parametros):
    motor = create_engine(url)
    try:
        with motor.begin() as conexao:
            resultado = conexao.execute(text(instrucoes), parametros)
            return resultado.fetchall() if resultado.returns_rows else None
    finally:
        motor.dispose()


def _colunas(url, tabela: str) -> set[str]:
    linhas = _sql(
        url,
        "SELECT column_name FROM information_schema.columns WHERE table_name = :t",
        t=tabela,
    )
    return {linha[0] for linha in linhas}


def _revisao_atual(url) -> str:
    return _sql(url, "SELECT version_num FROM alembic_version")[0][0]


def test_upgrade_e_downgrade_roundtrip_vazio(banco):
    """Verifies clean migration upgrade, downgrade, and re-upgrade on empty schema."""
    _upgrade(banco, REVISAO_ANTERIOR)
    assert _revisao_atual(banco) == REVISAO_ANTERIOR

    _upgrade(banco, REVISAO_ISS013)
    assert _revisao_atual(banco) == REVISAO_ISS013
    assert {
        "id",
        "antena_id",
        "portal_id",
        "lado",
        "zona_id",
        "funcao",
        "inicio",
        "fim",
        "created_at",
    } <= _colunas(banco, "mapeamentos_antena_portal")

    # Downgrade
    _downgrade(banco, REVISAO_ANTERIOR)
    assert _revisao_atual(banco) == REVISAO_ANTERIOR
    assert _colunas(banco, "mapeamentos_antena_portal") == set()

    # Re-upgrade
    _upgrade(banco, REVISAO_ISS013)
    assert _revisao_atual(banco) == REVISAO_ISS013


def test_upgrade_backfill_antenas_existentes_validas(banco):
    """
    Antennas associated with portals in the previous revision are derived:
    Antenna 1 (zona 1 == portal.zona_a_id) -> side 'a'
    Antenna 2 (zona 2 == portal.zona_b_id) -> side 'b'
    Antenna 3 (sem portal) -> remains unmapped
    Antenna 4 (inativa) -> remains unmapped
    """
    _upgrade(banco, REVISAO_ANTERIOR)
    _sql(
        banco,
        """
        INSERT INTO andares (id, nome, nome_normalizado) VALUES (1, 'Andar 1', 'andar 1');
        INSERT INTO setores (id, andar_id, nome, nome_normalizado) VALUES (1, 1, 'Setor 1', 'setor 1');
        INSERT INTO zonas (id, setor_id, nome, nome_normalizado)
            VALUES (1, 1, 'Z1', 'z1'), (2, 1, 'Z2', 'z2'), (3, 1, 'Z3', 'z3');
        INSERT INTO portais (id, nome, zona_a_id, zona_b_id) VALUES (1, 'P1', 1, 2);
        INSERT INTO leitores (id, reader_id, fabricante, modelo, identificador_serial)
            VALUES (1, 'R1', 'Identix', 'EZ700', 'SN-1');
        INSERT INTO antenas (id, leitor_id, porta_numero, zona_associada_id, funcao, portal_id, ativo)
            VALUES (1, 1, 1, 1, 'entrada', 1, true),
                   (2, 1, 2, 2, 'saida', 1, true),
                   (3, 1, 3, 3, 'entrada', NULL, true),
                   (4, 1, 4, 1, 'entrada', 1, false);
        """,
    )

    _upgrade(banco, REVISAO_ISS013)

    mapeamentos = _sql(
        banco,
        """
        SELECT antena_id, portal_id, lado, zona_id, funcao, fim IS NULL AS ativo
        FROM mapeamentos_antena_portal
        ORDER BY antena_id
        """,
    )
    assert mapeamentos == [
        (1, 1, "a", 1, "entrada", True),
        (2, 1, "b", 2, "saida", True),
    ]


def test_upgrade_aborta_com_zona_incompativel(banco):
    """
    Fail-fast check: if an existing active antenna references a zone not belonging
    to the portal, migration must abort with a descriptive error.
    """
    _upgrade(banco, REVISAO_ANTERIOR)
    _sql(
        banco,
        """
        INSERT INTO andares (id, nome, nome_normalizado) VALUES (1, 'Andar 1', 'andar 1');
        INSERT INTO setores (id, andar_id, nome, nome_normalizado) VALUES (1, 1, 'Setor 1', 'setor 1');
        INSERT INTO zonas (id, setor_id, nome, nome_normalizado)
            VALUES (1, 1, 'Z1', 'z1'), (2, 1, 'Z2', 'z2'), (3, 1, 'Z3', 'z3');
        INSERT INTO portais (id, nome, zona_a_id, zona_b_id) VALUES (1, 'P1', 1, 2);
        INSERT INTO leitores (id, reader_id, fabricante, modelo, identificador_serial)
            VALUES (1, 'R1', 'Identix', 'EZ700', 'SN-1');
        -- Antenna 1 is tied to Portal 1 (zones 1, 2), but its zona_associada is 3!
        INSERT INTO antenas (id, leitor_id, porta_numero, zona_associada_id, funcao, portal_id, ativo)
            VALUES (1, 1, 1, 3, 'entrada', 1, true);
        """,
    )

    proc = _alembic(banco, "upgrade", REVISAO_ISS013)
    assert proc.returncode != 0
    saida = _saida(proc)
    assert "Falha na migracao ISS-013" in saida
    assert "zona_associada_id=3" in saida


def test_upgrade_aborta_com_funcao_indefinida(banco):
    """
    Fail-fast check: if an existing active antenna tied to a portal has funcao='indefinido',
    migration must abort because active inference topology requires unambiguous function.
    """
    _upgrade(banco, REVISAO_ANTERIOR)
    _sql(
        banco,
        """
        INSERT INTO andares (id, nome, nome_normalizado) VALUES (1, 'Andar 1', 'andar 1');
        INSERT INTO setores (id, andar_id, nome, nome_normalizado) VALUES (1, 1, 'Setor 1', 'setor 1');
        INSERT INTO zonas (id, setor_id, nome, nome_normalizado)
            VALUES (1, 1, 'Z1', 'z1'), (2, 1, 'Z2', 'z2');
        INSERT INTO portais (id, nome, zona_a_id, zona_b_id) VALUES (1, 'P1', 1, 2);
        INSERT INTO leitores (id, reader_id, fabricante, modelo, identificador_serial)
            VALUES (1, 'R1', 'Identix', 'EZ700', 'SN-1');
        INSERT INTO antenas (id, leitor_id, porta_numero, zona_associada_id, funcao, portal_id, ativo)
            VALUES (1, 1, 1, 1, 'indefinido', 1, true);
        """,
    )

    proc = _alembic(banco, "upgrade", REVISAO_ISS013)
    assert proc.returncode != 0
    saida = _saida(proc)
    assert "Falha na migracao ISS-013" in saida
    assert "funcao='indefinido'" in saida
