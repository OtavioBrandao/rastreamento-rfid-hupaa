"""Unidades sem banco da ISS-026: configuração, logging da API e módulo de senha."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from argon2.low_level import Type
from fastapi.testclient import TestClient

from api import senhas
from api.config_auth import configuracao_auth_do_ambiente
from api.logging_config import configurar_logging_api, registrar_evento
from api.main import app

# ISS-027: login e cookie reais; sem o administrador de teste do conftest.
pytestmark = pytest.mark.autenticacao_real

RAIZ = Path(__file__).resolve().parent.parent

# --- configuração ---------------------------------------------------------------


def test_padroes_documentados():
    config = configuracao_auth_do_ambiente({})

    assert config.sessao_duracao == timedelta(minutes=480)
    assert config.login_max_tentativas == 5
    assert config.login_bloqueio == timedelta(minutes=15)
    assert config.cookie_seguro is True


def test_valores_validos_do_ambiente():
    config = configuracao_auth_do_ambiente({
        "SESSAO_DURACAO_MINUTOS": "60", "LOGIN_MAX_TENTATIVAS": " 3 ",
        "LOGIN_BLOQUEIO_MINUTOS": "1", "SESSAO_COOKIE_SEGURO": "FALSE",
    })

    assert (config.sessao_duracao, config.login_max_tentativas, config.login_bloqueio,
            config.cookie_seguro) == (timedelta(minutes=60), 3, timedelta(minutes=1), False)


@pytest.mark.parametrize("variavel", [
    "SESSAO_DURACAO_MINUTOS", "LOGIN_MAX_TENTATIVAS", "LOGIN_BLOQUEIO_MINUTOS",
])
@pytest.mark.parametrize("valor", ["0", "-5", "abc", "", "1.5"])
def test_inteiro_invalido_e_erro_nao_padrao(variavel, valor):
    with pytest.raises(ValueError, match=variavel):
        configuracao_auth_do_ambiente({variavel: valor})


@pytest.mark.parametrize("valor", ["", "sim", "1", "yes", "verdadeiro"])
def test_booleano_invalido_e_erro(valor):
    with pytest.raises(ValueError, match="SESSAO_COOKIE_SEGURO"):
        configuracao_auth_do_ambiente({"SESSAO_COOKIE_SEGURO": valor})


def test_subida_da_api_falha_com_configuracao_invalida(monkeypatch):
    monkeypatch.setenv("SESSAO_DURACAO_MINUTOS", "zero")

    with pytest.raises(ValueError, match="SESSAO_DURACAO_MINUTOS"):
        with TestClient(app):
            pass


# --- logging ------------------------------------------------------------------


def test_logging_da_api_e_idempotente_e_propaga():
    logger = configurar_logging_api({"LOG_LEVEL": "debug"})
    marcados = [h for h in logger.handlers if getattr(h, "_rfid_api_handler", False)]
    configurar_logging_api({"LOG_LEVEL": "INFO"})

    assert [h for h in logger.handlers if getattr(h, "_rfid_api_handler", False)] == marcados
    assert len(marcados) == 1
    assert logger.level == logging.INFO
    assert logger.propagate is True


def test_importar_a_api_configura_o_handler_que_o_uvicorn_nao_configura():
    """
    Em processo NOVO, como no uvicorn: o `caplog` capturaria o evento mesmo
    sem handler, então só a saída real prova que o INFO de `api.*` é emitido.
    """
    codigo = (
        "import logging, api.main\n"
        "from api.logging_config import registrar_evento\n"
        "registrar_evento(logging.getLogger('api.auth'), 'login_aceito', usuario_id=1)\n"
    )
    ambiente = {**os.environ, "LOG_LEVEL": "INFO"}

    processo = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, env=ambiente,
                              capture_output=True, text=True, timeout=60)

    assert processo.returncode == 0, processo.stderr
    assert 'api.auth: {"evento": "login_aceito", "usuario_id": 1}' in processo.stderr


def test_log_level_invalido_e_erro():
    with pytest.raises(ValueError, match="LOG_LEVEL"):
        configurar_logging_api({"LOG_LEVEL": "verboso"})


def test_evento_em_json(caplog):
    caplog.set_level(logging.INFO, logger="api")

    registrar_evento(logging.getLogger("api.auth"), "logout", usuario_id=7)

    assert caplog.records[-1].getMessage() == '{"evento": "logout", "usuario_id": 7}'


# --- senha --------------------------------------------------------------------


def test_hash_argon2id_e_verificacao():
    hash_gerado = senhas.gerar_hash("correta-123")

    assert hash_gerado.startswith("$argon2id$")
    assert senhas.verificar_senha(hash_gerado, "correta-123") is True
    assert senhas.verificar_senha(hash_gerado, "errada-123") is False


@pytest.mark.parametrize("hash_armazenado", [
    None, "", "texto", "$2b$12$abc", "$argon2id$v=19$m=1", PasswordHasher(type=Type.I).hash("x"),
])
def test_hash_nao_reconhecido_recusa_sem_excecao(hash_armazenado):
    assert senhas.hash_reconhecido(hash_armazenado) is False
    assert senhas.verificar_senha(hash_armazenado, "x") is False


@pytest.mark.parametrize("hash_armazenado", [
    PasswordHasher().hash("x").rsplit("$", 2)[0] + "$!!!!$!!!!",
    PasswordHasher().hash("x")[:-5],
])
def test_hash_com_corpo_corrompido_recusa_com_verificacao_completa(hash_armazenado, monkeypatch):
    """Passa pelo filtro de formato, mas o verify levanta: recusa e ainda verifica o fictício."""
    usados = []
    original = senhas._hasher.verify
    monkeypatch.setattr(senhas, "_hasher", type("Espiao", (), {
        "verify": staticmethod(lambda h, s: usados.append(h) or original(h, s)),
    })())

    assert senhas.verificar_senha(hash_armazenado, "x") is False
    assert usados[-1] == senhas.hash_ficticio()


@pytest.mark.parametrize("senha", ["curta", " " * 10, "x" * 129])
def test_politica_recusa_sem_ecoar(senha):
    with pytest.raises(senhas.SenhaForaDaPolitica) as erro:
        senhas.validar_politica(senha)
    assert senha.strip() == "" or senha not in str(erro.value)


def test_politica_aceita_limites():
    senhas.validar_politica("x" * 8)
    senhas.validar_politica("x" * 128)
