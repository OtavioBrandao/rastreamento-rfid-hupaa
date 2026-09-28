"""
Migration da ISS-026 com DADOS LEGADOS, em banco descartável próprio (mesmo
padrão de `tests/test_migration_iss012.py`: CREATE DATABASE por teste e
alembic por subprocesso).

`_migrar` de lá só faz downgrade para "base"; aqui o downgrade até uma
revisão é chamado explicitamente com `_alembic(url, "downgrade", ...)`.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from test_migration_iss012 import _alembic, _saida, _sql

REVISAO_ANTERIOR = "c032b1a2d3e4"  # ISS-032B
REVISAO_ISS026 = "d026a1b2c3d4"
HASH_LEGADO = "$2b$12$KbQiTBn8lh0mD0xGGlO2UuB2bYh0x7xqSbq5WnS1ZC7iD9j8m5T4e"


@pytest.fixture
def banco(engine):
    """URL de um banco novo e vazio, removido no final (exige CREATEDB)."""
    nome = f"rfid_mig26_{uuid.uuid4().hex[:10]}"
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


def _colunas_usuarios(url) -> set[str]:
    return {linha[0] for linha in _sql(
        url, "SELECT column_name FROM information_schema.columns WHERE table_name='usuarios'")}


def _tem_sessoes(url) -> bool:
    return bool(_sql(url, "SELECT to_regclass('public.sessoes') IS NOT NULL")[0][0])


def _perfis(url) -> list[str]:
    return [linha[0] for linha in _sql(url, "SELECT nome FROM perfis ORDER BY nome")]


def test_dados_legados_upgrade_downgrade_upgrade_e_check(banco):
    _ok(banco, "upgrade", REVISAO_ANTERIOR)
    # Legado: só o perfil administrador existia; e-mails com maiúscula e espaço.
    _sql(banco, f"""
        INSERT INTO perfis (id, nome) VALUES (10, 'administrador');
        INSERT INTO usuarios (id, nome, email, senha_hash, perfil_id) VALUES
            (1, 'Maria', '  Maria@HUPAA.org ', '{HASH_LEGADO}', 10),
            (2, 'João', 'joao@hupaa.org', '{HASH_LEGADO}', 10);
    """)

    _ok(banco, "upgrade", "head")

    assert _sql(banco, "SELECT id, email, deve_trocar_senha, tentativas_falhas, "
                "bloqueado_ate, ultimo_login_em, updated_at IS NOT NULL "
                "FROM usuarios ORDER BY id") == [
        (1, "maria@hupaa.org", False, 0, None, None, True),
        (2, "joao@hupaa.org", False, 0, None, None, True),
    ]
    assert _perfis(banco) == ["administrador", "operacional"]
    assert _sql(banco, "SELECT id FROM perfis WHERE nome='administrador'") == [(10,)]
    assert _tem_sessoes(banco)
    with pytest.raises(IntegrityError, match="ck_usuarios_email_normalizado"):
        _sql(banco, "UPDATE usuarios SET email = 'Maria@hupaa.org' WHERE id = 1")
    with pytest.raises(IntegrityError, match="ck_usuarios_tentativas_nao_negativas"):
        _sql(banco, "UPDATE usuarios SET tentativas_falhas = -1 WHERE id = 1")
    _ok(banco, "check")

    _ok(banco, "downgrade", REVISAO_ANTERIOR)

    assert not _tem_sessoes(banco)
    assert not {"deve_trocar_senha", "tentativas_falhas", "bloqueado_ate", "ultimo_login_em",
                "updated_at"} & _colunas_usuarios(banco)
    # 'administrador' é referenciado e fica; 'operacional' semeado e sem uso sai.
    assert _perfis(banco) == ["administrador"]
    assert _sql(banco, "SELECT count(*) FROM usuarios")[0][0] == 2
    _sql(banco, "INSERT INTO usuarios (id, nome, email, senha_hash, perfil_id) "
         "VALUES (3, 'Livre', 'Livre@X.org', 'x', 10)")  # a CHECK saiu junto

    _ok(banco, "upgrade", "head")
    assert _perfis(banco) == ["administrador", "operacional"]
    assert _sql(banco, "SELECT email FROM usuarios ORDER BY id")[-1] == ("livre@x.org",)
    _ok(banco, "check")


def test_colisao_de_email_aborta_listando_ids_sem_alterar_nada(banco):
    _ok(banco, "upgrade", REVISAO_ANTERIOR)
    _sql(banco, f"""
        INSERT INTO perfis (id, nome) VALUES (1, 'administrador');
        INSERT INTO usuarios (id, nome, email, senha_hash, perfil_id) VALUES
            (3, 'A', 'ana@x.org', '{HASH_LEGADO}', 1),
            (5, 'B', 'Unico@X.org', '{HASH_LEGADO}', 1),
            (7, 'C', ' ANA@x.org', '{HASH_LEGADO}', 1),
            (8, 'D', 'bia@x.org', '{HASH_LEGADO}', 1),
            (9, 'E', 'BIA@X.ORG ', '{HASH_LEGADO}', 1);
    """)
    antes = _sql(banco, "SELECT id, email FROM usuarios ORDER BY id")

    processo = _alembic(banco, "upgrade", "head")

    assert processo.returncode != 0
    saida = _saida(processo)
    assert "3, 7" in saida and "8, 9" in saida
    assert "ana@x.org" not in saida.lower() and "bia@x.org" not in saida.lower()
    assert _sql(banco, "SELECT id, email FROM usuarios ORDER BY id") == antes
    assert _perfis(banco) == ["administrador"]
    assert not _tem_sessoes(banco)
    assert "deve_trocar_senha" not in _colunas_usuarios(banco)
    assert _sql(banco, "SELECT version_num FROM alembic_version") == [(REVISAO_ANTERIOR,)]


def test_banco_sem_perfis_recebe_os_dois_e_semeadura_e_idempotente(banco):
    _ok(banco, "upgrade", REVISAO_ANTERIOR)
    assert _perfis(banco) == []

    _ok(banco, "upgrade", "head")
    assert _perfis(banco) == ["administrador", "operacional"]

    _ok(banco, "downgrade", REVISAO_ANTERIOR)
    assert _perfis(banco) == []
    _sql(banco, "INSERT INTO perfis (nome) VALUES ('operacional')")
    _ok(banco, "upgrade", "head")
    assert _perfis(banco) == ["administrador", "operacional"]


def test_downgrade_com_sessoes_e_perfis_em_uso(banco):
    _ok(banco, "upgrade", "head")
    _sql(banco, """
        INSERT INTO usuarios (id, nome, email, senha_hash, perfil_id)
            VALUES (1, 'Op', 'op@x.org', 'x', (SELECT id FROM perfis WHERE nome='operacional'));
        INSERT INTO sessoes (usuario_id, token_hash, criada_em, expira_em) VALUES
            (1, repeat('a', 64), now(), now() + interval '1 hour');
    """)
    for invalida in (
        "INSERT INTO sessoes (usuario_id, token_hash, criada_em, expira_em) "
        "VALUES (1, 'TOKEN-EM-CLARO', now(), now() + interval '1 hour')",
        "INSERT INTO sessoes (usuario_id, token_hash, criada_em, expira_em) "
        "VALUES (1, repeat('b', 64), now(), now())",
        "UPDATE sessoes SET revogada_em = now()",
        "UPDATE sessoes SET revogada_em = now(), motivo_revogacao = 'expirou'",
        "INSERT INTO sessoes (usuario_id, token_hash, criada_em, expira_em) "
        "VALUES (1, repeat('a', 64), now(), now() + interval '1 hour')",
    ):
        with pytest.raises(IntegrityError):
            _sql(banco, invalida)

    _ok(banco, "downgrade", REVISAO_ANTERIOR)

    assert not _tem_sessoes(banco)
    assert _perfis(banco) == ["operacional"]
