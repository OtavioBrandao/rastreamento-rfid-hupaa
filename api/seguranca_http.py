"""Proteções HTTP independentes do provedor de hospedagem.

- Cabeçalhos de segurança em toda resposta da API (o proxy/TLS pode
  acrescentar HSTS; ver deploy/production/nginx.conf.template).
- Verificação de origem nas requisições que alteram estado: o cookie de
  sessão já é `SameSite=Strict`, mas um `Origin` de outro site é recusado
  também aqui (defesa em profundidade contra CSRF). Requisições sem `Origin`
  (curl, testes, mesmo site em navegadores antigos) seguem para a
  autenticação normal.
- CORS só quando `CORS_ORIGENS` lista origens confiáveis; o padrão é a mesma
  origem (frontend servido pelo mesmo domínio que a API).
- Em `APP_ENV=production`, o cookie de sessão sem `Secure` impede a subida.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.ambiente import ambiente_atual
from api.config_auth import configuracao_auth_do_ambiente

METODOS_SEGUROS = frozenset({"GET", "HEAD", "OPTIONS"})
CABECALHOS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def origens_confiaveis(environ: Mapping[str, str] | None = None) -> frozenset[str]:
    """`CORS_ORIGENS=https://painel.exemplo,https://outro` (sem barra final)."""
    source = os.environ if environ is None else environ
    return frozenset(item.strip().rstrip("/") for item in (source.get("CORS_ORIGENS") or "").split(",")
                     if item.strip())


def validar_producao(environ: Mapping[str, str] | None = None) -> None:
    """Configurações inseguras não sobem em produção."""
    source = os.environ if environ is None else environ
    if ambiente_atual(source) != "production":
        return
    if not configuracao_auth_do_ambiente(source).cookie_seguro:
        raise ValueError("APP_ENV=production exige SESSAO_COOKIE_SEGURO=true (HTTPS)")
    if any(origem.startswith("http://") for origem in origens_confiaveis(source)):
        raise ValueError("APP_ENV=production não aceita origens CORS sem HTTPS")


def origem_permitida(origem: str, host: str | None, confiaveis: frozenset[str]) -> bool:
    """Mesmo host (com porta) da requisição, ou origem explicitamente confiável."""
    if origem.rstrip("/") in confiaveis:
        return True
    partes = urlsplit(origem)
    return bool(host) and partes.netloc.lower() == host.lower()


def instalar(app: FastAPI) -> None:
    """Registra CORS (se configurado), verificação de origem e cabeçalhos."""
    confiaveis = origens_confiaveis()
    if confiaveis:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(CORSMiddleware, allow_origins=sorted(confiaveis),
                           allow_credentials=True, allow_methods=["*"],
                           allow_headers=["Content-Type", "X-Correlation-ID"])

    @app.middleware("http")
    async def protecoes(request: Request, call_next):
        """Recusa origem estranha em escrita e acrescenta cabeçalhos de segurança."""
        origem = request.headers.get("origin")
        if (request.method not in METODOS_SEGUROS and origem
                and not origem_permitida(origem, request.headers.get("host"), confiaveis)):
            resposta = JSONResponse(status_code=403, content={"detail": "origem_nao_permitida"})
        else:
            resposta = await call_next(request)
        for nome, valor in CABECALHOS.items():
            resposta.headers.setdefault(nome, valor)
        if request.url.path.startswith("/auth"):
            resposta.headers.setdefault("Cache-Control", "no-store")
        return resposta
