"""
Engine, sessão e dependency do FastAPI.

A URL vem do mesmo `db/url.py` usado pelas migrations (`alembic/env.py`),
para não existirem duas fontes de verdade sobre "qual banco é este".

Engine e sessionmaker são criados sob demanda (não no import do módulo)
porque `get_database_url()` levanta RuntimeError quando não há
DATABASE_URL — e isso tornaria impossível até importar `api.main` sem
ambiente configurado (coleta de teste, `--help`, geração de OpenAPI).
"""

import os
from collections.abc import Iterator, Mapping
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from db.url import get_database_url


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    # Mesmo `config/environments/.env` que o alembic/env.py carrega.
    """Cria e reutiliza o engine sob demanda, carregando o perfil genérico sem sobrescrever o ambiente."""
    load_dotenv(Path(__file__).resolve().parents[1] / "config/environments/.env")
    # pool_pre_ping: o Neon (e qualquer pooler) derruba conexão ociosa; sem
    # isso a primeira request depois de um período parado morre com
    # "server closed the connection unexpectedly".
    return create_engine(get_database_url(), pool_pre_ping=True, future=True, **opcoes_pool())


def opcoes_pool(environ: Mapping[str, str] | None = None) -> dict:
    """Pool ajustável por ambiente (padrões do SQLAlchemy quando ausentes).

    `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` limitam conexões por processo — some os
    workers ao dimensionar contra o limite do provedor; `DB_POOL_RECYCLE_S`
    renova conexões antes do corte por ociosidade de poolers gerenciados;
    `DB_CONNECT_TIMEOUT_S` evita requisições presas com o banco fora do ar.
    """
    source = os.environ if environ is None else environ
    opcoes: dict = {}
    for nome, chave in (("DB_POOL_SIZE", "pool_size"), ("DB_MAX_OVERFLOW", "max_overflow"),
                        ("DB_POOL_RECYCLE_S", "pool_recycle"), ("DB_POOL_TIMEOUT_S", "pool_timeout")):
        valor = (source.get(nome) or "").strip()
        if valor:
            numero = int(valor)
            if numero < (-1 if chave == "pool_recycle" else 0):
                raise ValueError(f"{nome} inválido")
            opcoes[chave] = numero
    timeout = (source.get("DB_CONNECT_TIMEOUT_S") or "").strip()
    if timeout:
        opcoes["connect_args"] = {"connect_timeout": int(timeout)}
    return opcoes


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker:
    """Devolve a fábrica de sessões vinculada ao engine compartilhado da API."""
    return sessionmaker(bind=get_engine(), autocommit=False, autoflush=False)


# Alias com o nome convencional do FastAPI. É a factory de sessão, então
# `SessionLocal()` continua funcionando como em qualquer projeto FastAPI —
# só que resolvendo o engine na primeira chamada, não no import.
def SessionLocal() -> Session:  # noqa: N802 - nome convencional do ecossistema
    """Abre uma sessão SQLAlchemy; o chamador é responsável por fechá-la."""
    return get_sessionmaker()()


def get_db() -> Iterator[Session]:
    """Dependency do FastAPI: uma sessão por request, sempre fechada."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
