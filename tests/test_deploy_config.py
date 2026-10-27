"""Preparação para deploy: readiness, cabeçalhos, origem, produção, pool e artefatos."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from api import seguranca_http
from api.ambiente import ambiente_atual
from api.database import get_db, opcoes_pool
from api.logging_config import FormatoJson
from api.main import app

RAIZ = Path(__file__).resolve().parents[1]


class SessaoQuebrada:
    def execute(self, *_args, **_kwargs):
        raise OperationalError("SELECT 1", {}, Exception("senha=segredo host=db"))


def test_health_e_readiness_sem_vazar_conexao():
    app.dependency_overrides[get_db] = lambda: SessaoQuebrada()
    try:
        with TestClient(app) as cliente:
            assert cliente.get("/health").json() == {"status": "ok"}
            pronto = cliente.get("/health/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert pronto.status_code == 503
    assert "segredo" not in pronto.text and "host" not in pronto.text


@pytest.mark.autenticacao_real
def test_cabecalhos_de_seguranca_e_origem_estranha_recusada():
    app.dependency_overrides[get_db] = lambda: SessaoQuebrada()
    try:
        _verificar_cabecalhos_e_origem()
    finally:
        app.dependency_overrides.pop(get_db, None)


def _verificar_cabecalhos_e_origem():
    with TestClient(app) as cliente:
        resposta = cliente.get("/health")
        assert resposta.headers["X-Content-Type-Options"] == "nosniff"
        assert resposta.headers["X-Frame-Options"] == "DENY"
        recusada = cliente.post("/auth/login", json={"email": "a@b.c", "senha": "x" * 8},
                                headers={"Origin": "https://site-malicioso.example"})
        assert recusada.status_code == 403
        assert recusada.json() == {"detail": "origem_nao_permitida"}
        mesma = cliente.post("/health", headers={"Origin": "http://testserver"})
        assert mesma.status_code == 405  # passou pela verificação de origem
        assert cliente.get("/auth/me").headers["Cache-Control"] == "no-store"


def test_origem_permitida_por_host_ou_lista():
    confiaveis = frozenset({"https://painel.hupaa.example"})
    assert seguranca_http.origem_permitida("https://painel.hupaa.example/", None, confiaveis)
    assert seguranca_http.origem_permitida("http://localhost:5173", "localhost:5173", frozenset())
    assert not seguranca_http.origem_permitida("http://localhost:5173", "127.0.0.1:8010", frozenset())
    assert seguranca_http.origens_confiaveis({"CORS_ORIGENS": " https://a.example/ ,https://b.example"}) \
        == frozenset({"https://a.example", "https://b.example"})


def test_producao_recusa_configuracao_insegura():
    seguranca_http.validar_producao({"APP_ENV": "development", "SESSAO_COOKIE_SEGURO": "false"})
    with pytest.raises(ValueError, match="SESSAO_COOKIE_SEGURO"):
        seguranca_http.validar_producao({"APP_ENV": "production", "SESSAO_COOKIE_SEGURO": "false"})
    with pytest.raises(ValueError, match="HTTPS"):
        seguranca_http.validar_producao({"APP_ENV": "production", "CORS_ORIGENS": "http://x.example"})
    seguranca_http.validar_producao({"APP_ENV": "production", "CORS_ORIGENS": "https://x.example"})
    assert ambiente_atual({"APP_ENV": "producao"}) == "production"
    with pytest.raises(ValueError):
        ambiente_atual({"APP_ENV": "qualquer"})


def test_pool_configuravel():
    assert opcoes_pool({}) == {}
    assert opcoes_pool({"DB_POOL_SIZE": "5", "DB_MAX_OVERFLOW": "2", "DB_POOL_RECYCLE_S": "300",
                        "DB_CONNECT_TIMEOUT_S": "5"}) == {
        "pool_size": 5, "max_overflow": 2, "pool_recycle": 300,
        "connect_args": {"connect_timeout": 5}}
    with pytest.raises(ValueError):
        opcoes_pool({"DB_POOL_SIZE": "-1"})


def test_log_json_estruturado():
    registro = logging.LogRecord("api.auth", logging.INFO, __file__, 1,
                                 json.dumps({"evento": "login_aceito"}), None, None)
    linha = json.loads(FormatoJson().format(registro))
    assert linha["msg"] == {"evento": "login_aceito"} and linha["nivel"] == "INFO"


def test_artefatos_de_producao_sem_segredos():
    exemplo = (RAIZ / "config/environments/.env.production.example").read_text(encoding="utf-8")
    assert "APP_ENV=production" in exemplo
    assert "SIMULADOR_HABILITADO=false" in exemplo
    assert "SESSAO_COOKIE_SEGURO=true" in exemplo
    for linha in exemplo.splitlines():
        if linha.startswith(("MQTT_PASSWORD=", "POSTGRES_PASSWORD=")):
            assert linha.split("=", 1)[1] in ("", "troque-no-cofre-de-segredos")
    backend = (RAIZ / "deploy/production/Dockerfile.backend").read_text(encoding="utf-8")
    assert "USER app" in backend and "COPY api ./api" in backend and "HEALTHCHECK" in backend
    frontend = (RAIZ / "deploy/production/Dockerfile.frontend").read_text(encoding="utf-8")
    assert "npm ci" in frontend and "nginx-unprivileged" in frontend
    nginx = (RAIZ / "deploy/production/nginx.conf.template").read_text(encoding="utf-8")
    for rota in ("/api/", "/auth/", "equipamentos", "health", "usuarios"):
        assert rota in nginx
    assert "limit_req" in nginx and "Content-Security-Policy" in nginx
