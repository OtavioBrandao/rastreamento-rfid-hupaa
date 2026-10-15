"""
Configuração da autenticação (ISS-026), lida do ambiente do processo da API.

Mesmo critério de `rfid_location.recency`: valor ausente usa o padrão
documentado; valor presente e inválido é ERRO explícito, nunca um padrão
silencioso — uma sessão de 480 minutos virando outra coisa por um erro de
digitação no `.env` não pode passar despercebida.

`obter_configuracao_auth` e `obter_agora` são dependencies do FastAPI de
propósito: os testes trocam as duas por `app.dependency_overrides` e
avançam o relógio sem `sleep`.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

SESSAO_DURACAO_ENV = "SESSAO_DURACAO_MINUTOS"
LOGIN_MAX_TENTATIVAS_ENV = "LOGIN_MAX_TENTATIVAS"
LOGIN_BLOQUEIO_ENV = "LOGIN_BLOQUEIO_MINUTOS"
COOKIE_SEGURO_ENV = "SESSAO_COOKIE_SEGURO"

PADRAO_SESSAO_DURACAO_MINUTOS = 480
PADRAO_LOGIN_MAX_TENTATIVAS = 5
PADRAO_LOGIN_BLOQUEIO_MINUTOS = 15
PADRAO_COOKIE_SEGURO = True


@dataclass(frozen=True)
class ConfiguracaoAuth:
    """Estrutura Configuracao Auth usada por api.config_auth.

    Campos: sessao_duracao, login_max_tentativas, login_bloqueio, cookie_seguro."""
    sessao_duracao: timedelta
    login_max_tentativas: int
    login_bloqueio: timedelta
    cookie_seguro: bool


def _inteiro_positivo(source: Mapping[str, str], nome: str, padrao: int) -> int:
    """Lê inteiro positivo do ambiente, aplicando o padrão e recusando valores inválidos."""
    bruto = source.get(nome)
    if bruto is None:
        return padrao
    try:
        valor = int(bruto.strip())
    except ValueError as erro:
        raise ValueError(f"{nome} deve ser inteiro positivo") from erro
    if valor <= 0:
        raise ValueError(f"{nome} deve ser inteiro positivo")
    return valor


def _booleano(source: Mapping[str, str], nome: str, padrao: bool) -> bool:
    """Converte opção textual de ambiente em booleano ou rejeita configuração inválida."""
    bruto = source.get(nome)
    if bruto is None:
        return padrao
    valor = bruto.strip().lower()
    if valor == "true":
        return True
    if valor == "false":
        return False
    raise ValueError(f"{nome} deve ser 'true' ou 'false'")


def configuracao_auth_do_ambiente(environ: Mapping[str, str] | None = None) -> ConfiguracaoAuth:
    """Lê e valida parâmetros de sessão, cookie e bloqueio sem acessar o banco."""
    source = os.environ if environ is None else environ
    return ConfiguracaoAuth(
        sessao_duracao=timedelta(minutes=_inteiro_positivo(
            source, SESSAO_DURACAO_ENV, PADRAO_SESSAO_DURACAO_MINUTOS)),
        login_max_tentativas=_inteiro_positivo(
            source, LOGIN_MAX_TENTATIVAS_ENV, PADRAO_LOGIN_MAX_TENTATIVAS),
        login_bloqueio=timedelta(minutes=_inteiro_positivo(
            source, LOGIN_BLOQUEIO_ENV, PADRAO_LOGIN_BLOQUEIO_MINUTOS)),
        cookie_seguro=_booleano(source, COOKIE_SEGURO_ENV, PADRAO_COOKIE_SEGURO),
    )


def obter_configuracao_auth() -> ConfiguracaoAuth:
    """Dependency do FastAPI."""
    return configuracao_auth_do_ambiente()


def obter_agora() -> datetime:
    """Dependency do FastAPI: um único instante UTC por request."""
    return datetime.now(timezone.utc)
