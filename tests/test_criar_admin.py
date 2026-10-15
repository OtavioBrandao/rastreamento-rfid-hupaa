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

# ISS-027: login e cookie reais; sem o administrador de teste do conftest.
pytestmark = pytest.mark.autenticacao_real

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
    (autor, acao, origem, motivo, depois), = consultar(
        engine, "SELECT usuario_id, acao, origem, motivo, dados_depois FROM auditorias "
        "WHERE entidade = 'usuarios' AND entidade_id = :id AND acao = 'criar'",
        id=usuario_id)
    assert (autor, acao, origem, motivo) == (None, "criar", "sistema", "comando criar_admin")
    assert (depois["perfil"], depois["deve_trocar_senha"]) == ("administrador", False)
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
    assert consultar(engine, "SELECT origem, motivo FROM auditorias WHERE acao = 'criar'") == [
        ("sistema", "comando criar_admin (recuperação de acesso)")]


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


@pytest.mark.parametrize("usar_arquivo", [False, True])
def test_entrypoint_real_por_subprocesso(engine, truncate_all, tmp_path, usar_arquivo):
    ambiente = {**os.environ, "DATABASE_URL": engine.url.render_as_string(hide_password=False)}
    argumentos = []
    if usar_arquivo:
        arquivo = tmp_path / "banco.env"
        arquivo.write_text('DATABASE_URL="' + ambiente["DATABASE_URL"] + '"\n', encoding="utf-8")
        ambiente["DATABASE_URL"] = "postgresql://ambiente-invalido/nao-usar"
        argumentos = ["--env-file", str(arquivo)]

    processo = subprocess.run(
        [sys.executable, "-m", "api.criar_admin", *BASE, *argumentos, "--senha-stdin"],
        input=SENHA_ADMIN + "\n", cwd=RAIZ, env=ambiente, capture_output=True, text=True,
        timeout=120,
    )

    assert processo.returncode == 0, processo.stderr
    assert "Administrador criado" in processo.stdout
    assert SENHA_ADMIN not in processo.stdout + processo.stderr
    assert consultar(engine, "SELECT email FROM usuarios") == [("admin@hupaa.example",)]


def test_arquivo_explicito_prevalece_sobre_ambiente(tmp_path, monkeypatch):
    arquivo = tmp_path / "banco.env"
    arquivo.write_text("DATABASE_URL=postgresql://localhost/arquivo\n", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/ambiente")

    criar_admin._carregar_ambiente(str(arquivo))

    assert os.environ["DATABASE_URL"] == "postgresql://localhost/arquivo"


@pytest.mark.parametrize("arquivo_inexistente", [False, True])
def test_configuracao_invalida_avisa_antes_de_pedir_senha(
    tmp_path, monkeypatch, capsys, arquivo_inexistente,
):
    arquivo = tmp_path / "banco.env"
    if not arquivo_inexistente:
        arquivo.write_text("OUTRA_VARIAVEL=valor\n", encoding="utf-8")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    def nao_pedir_senha(_prompt):
        pytest.fail("Configuração inválida deve falhar antes de pedir senha")

    codigo = criar_admin.main(
        [*BASE, "--env-file", str(arquivo)], pedir_senha=nao_pedir_senha,
    )

    assert codigo == 1
    erro = capsys.readouterr().err
    assert "--env-file" in erro
    assert "Traceback" not in erro
