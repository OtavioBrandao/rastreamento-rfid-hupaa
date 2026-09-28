"""Comando `python -m api.criar_admin` (ISS-026), contra Postgres real."""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.orm import Session
from suporte_auth import consultar, inserir_usuario, logar

from api import criar_admin

RAIZ = Path(__file__).resolve().parent.parent
SENHA_ADMIN = "Senha-Do-Admin-2026"


@pytest.fixture
def rodar(engine, truncate_all, capsys):
    def executar(argv, *, entrada="", senhas_digitadas=()):
        digitadas = iter(senhas_digitadas)
        codigo = criar_admin.main(
            argv,
            session_factory=lambda: Session(bind=engine),
            entrada=io.StringIO(entrada),
            pedir_senha=lambda _prompt: next(digitadas),
        )
        saida = capsys.readouterr()
        return codigo, saida.out + saida.err
    return executar


BASE = ["--nome", "Admin Inicial", "--email", " Admin@HUPAA.example "]


def test_cria_admin_pelo_getpass_sem_troca_obrigatoria_e_audita(engine, rodar, api_auth):
    codigo, saida = rodar(BASE, senhas_digitadas=[SENHA_ADMIN, SENHA_ADMIN])

    assert codigo == 0, saida
    assert SENHA_ADMIN not in saida
    (usuario_id, email, perfil, troca, hash_salvo), = consultar(
        engine, "SELECT u.id, u.email, p.nome, u.deve_trocar_senha, u.senha_hash "
        "FROM usuarios u JOIN perfis p ON p.id = u.perfil_id")
    assert (email, perfil, troca) == ("admin@hupaa.example", "administrador", False)
    assert hash_salvo.startswith("$argon2id$")
    (autor, acao, depois), = consultar(
        engine, "SELECT usuario_id, acao, dados_depois FROM auditorias WHERE entidade_id=:id",
        id=usuario_id)
    assert (autor, acao, depois["operacao"]) == (None, "create", "criar_admin_terminal")
    assert SENHA_ADMIN not in str(depois) and "$argon2" not in str(depois)
    cliente = api_auth()
    assert logar(cliente, "admin@hupaa.example", SENHA_ADMIN).status_code == 200
    assert cliente.get("/usuarios").status_code == 200


def test_senha_stdin_para_automacao(engine, rodar):
    codigo, _ = rodar([*BASE, "--senha-stdin"], entrada=SENHA_ADMIN + "\n")

    assert codigo == 0
    assert consultar(engine, "SELECT count(*) FROM usuarios")[0][0] == 1


def test_senhas_digitadas_diferentes_nao_criam(engine, rodar):
    codigo, saida = rodar(BASE, senhas_digitadas=[SENHA_ADMIN, SENHA_ADMIN + "x"])

    assert codigo == 1
    assert "não conferem" in saida and SENHA_ADMIN not in saida
    assert consultar(engine, "SELECT count(*) FROM usuarios")[0][0] == 0


def test_senha_recusada_nao_e_ecoada(engine, rodar):
    curta = "Ab1-xyz"

    codigo, saida = rodar([*BASE, "--senha-stdin"], entrada=curta + "\n")

    assert codigo == 1
    assert "Senha recusada" in saida
    assert curta not in saida
    assert consultar(engine, "SELECT count(*) FROM usuarios")[0][0] == 0


def test_recusa_com_admin_ativo_salvo_recuperacao(engine, rodar):
    inserir_usuario(engine, "existente@hupaa.example", perfil="administrador")

    codigo, saida = rodar([*BASE, "--senha-stdin"], entrada=SENHA_ADMIN + "\n")
    assert codigo == 1 and "--recuperacao" in saida
    assert consultar(engine, "SELECT count(*) FROM usuarios")[0][0] == 1

    codigo, _ = rodar([*BASE, "--senha-stdin", "--recuperacao"], entrada=SENHA_ADMIN + "\n")
    assert codigo == 0
    assert consultar(engine, "SELECT count(*) FROM usuarios")[0][0] == 2
    assert consultar(engine, "SELECT dados_depois->>'recuperacao' FROM auditorias")[0][0] == "true"


def test_admin_inativo_nao_impede_bootstrap(engine, rodar):
    inserir_usuario(engine, "antigo@hupaa.example", perfil="administrador", ativo=False)

    codigo, _ = rodar([*BASE, "--senha-stdin"], entrada=SENHA_ADMIN + "\n")

    assert codigo == 0


def test_email_duplicado_e_email_invalido(engine, rodar):
    inserir_usuario(engine, "admin@hupaa.example", ativo=False)

    codigo, saida = rodar([*BASE, "--senha-stdin"], entrada=SENHA_ADMIN + "\n")
    assert codigo == 1 and "e-mail" in saida

    codigo, saida = rodar(["--nome", "X", "--email", "invalido", "--senha-stdin"],
                          entrada=SENHA_ADMIN + "\n")
    assert codigo == 1 and "email" in saida


def test_nao_existe_opcao_de_senha_na_linha_de_comando(rodar):
    with pytest.raises(SystemExit) as saida:
        rodar([*BASE, "--senha", SENHA_ADMIN])
    assert saida.value.code == 2


def test_entrypoint_real_por_subprocesso(engine, truncate_all):
    ambiente = {**os.environ, "DATABASE_URL": engine.url.render_as_string(hide_password=False)}

    processo = subprocess.run(
        [sys.executable, "-m", "api.criar_admin", *BASE, "--senha-stdin"],
        input=SENHA_ADMIN + "\n", cwd=RAIZ, env=ambiente, capture_output=True, text=True,
        timeout=120,
    )

    assert processo.returncode == 0, processo.stderr
    assert "Administrador criado" in processo.stdout
    assert SENHA_ADMIN not in processo.stdout + processo.stderr
    assert consultar(engine, "SELECT email FROM usuarios") == [("admin@hupaa.example",)]
