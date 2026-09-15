"""Conexão da aplicação, separada da credencial de migrations."""

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url


class DatabaseConfigurationError(ValueError):
    """Erro seguro de configuração, sem reproduzir a URL recebida."""


def create_app_engine() -> Engine:
    raw = os.environ.get("APP_DATABASE_URL", "")
    if not raw.strip():
        raise DatabaseConfigurationError("APP_DATABASE_URL é obrigatória para persistência PostgreSQL")
    try:
        url = make_url(raw)
        if url.get_backend_name() != "postgresql":
            raise ValueError
        return create_engine(url, hide_parameters=True, echo=False)
    except Exception:
        raise DatabaseConfigurationError("APP_DATABASE_URL inválida para PostgreSQL") from None
