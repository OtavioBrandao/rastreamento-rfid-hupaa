"""
Suporte compartilhado dos testes da ISS-026 (autenticação e usuários).

- `Relogio`: substitui a dependency `obter_agora`; os testes avançam o tempo
  sem `sleep`.
- `ajustes_auth`: substitui `obter_configuracao_auth` por um valor mutável.
- `api_auth`: fábrica de TestClients com `base_url="https://testserver"` — o
  cookie de sessão é `Secure` e não seria reenviado por HTTP puro.

Postgres real (fixture `engine`/`truncate_all` do conftest), nada de mock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from api import senhas
from api.config_auth import ConfiguracaoAuth, obter_agora, obter_configuracao_auth
from api.database import get_db
from api.main import app

INICIO = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
SENHA = "senha-correta-1"
BASE_URL = "https://testserver"


class Relogio:
    def __init__(self, agora: datetime = INICIO) -> None:
        self.agora = agora

    def avancar(self, **delta: float) -> datetime:
        self.agora += timedelta(**delta)
        return self.agora


@dataclass
class AjustesAuth:
    config: ConfiguracaoAuth


@lru_cache(maxsize=None)
def hash_de(senha: str) -> str:
    """Cache só para acelerar a preparação; o código sob teste gera os próprios."""
    return senhas.gerar_hash(senha)


def inserir_usuario(
    engine,
    email: str,
    *,
    senha: str = SENHA,
    perfil: str = "operacional",
    ativo: bool = True,
    deve_trocar_senha: bool = False,
    nome: str | None = None,
    senha_hash: str | None = None,
) -> int:
    with engine.begin() as conexao:
        return conexao.execute(
            text(
                "INSERT INTO usuarios (nome, email, senha_hash, perfil_id, ativo, "
                "deve_trocar_senha) VALUES (:nome, :email, :hash, "
                "(SELECT id FROM perfis WHERE nome = :perfil), :ativo, :troca) RETURNING id"
            ),
            {
                "nome": nome or email.split("@")[0], "email": email,
                "hash": senha_hash if senha_hash is not None else hash_de(senha),
                "perfil": perfil, "ativo": ativo, "troca": deve_trocar_senha,
            },
        ).scalar_one()


def consultar(engine, sql: str, **parametros):
    with engine.connect() as conexao:
        return conexao.execute(text(sql), parametros).all()


def executar(engine, sql: str, **parametros) -> None:
    with engine.begin() as conexao:
        conexao.execute(text(sql), parametros)


def logar(cliente: TestClient, email: str, senha: str = SENHA):
    return cliente.post("/auth/login", json={"email": email, "senha": senha})


def cliente_com_token(token: str) -> TestClient:
    cliente = TestClient(app, base_url=BASE_URL)
    cliente.cookies.set("rfid_sessao", token, domain="testserver", path="/")
    return cliente


@pytest.fixture
def relogio() -> Relogio:
    return Relogio()


@pytest.fixture
def ajustes_auth() -> AjustesAuth:
    return AjustesAuth(ConfiguracaoAuth(
        sessao_duracao=timedelta(minutes=480),
        login_max_tentativas=5,
        login_bloqueio=timedelta(minutes=15),
        cookie_seguro=True,
    ))


@pytest.fixture
def api_auth(engine, truncate_all, relogio, ajustes_auth):
    def get_db_de_teste():
        session = Session(bind=engine)
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = get_db_de_teste
    app.dependency_overrides[obter_agora] = lambda: relogio.agora
    app.dependency_overrides[obter_configuracao_auth] = lambda: ajustes_auth.config
    clientes: list[TestClient] = []

    def novo_cliente() -> TestClient:
        cliente = TestClient(app, base_url=BASE_URL)
        clientes.append(cliente)
        return cliente

    try:
        yield novo_cliente
    finally:
        for cliente in clientes:
            cliente.close()
        app.dependency_overrides.clear()


@pytest.fixture
def admin_logado(engine, api_auth):
    """(cliente com sessão de administrador liberada, id do administrador)."""
    admin_id = inserir_usuario(engine, "admin@hupaa.example", perfil="administrador")
    cliente = api_auth()
    assert logar(cliente, "admin@hupaa.example").status_code == 200
    return cliente, admin_id
