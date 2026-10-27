"""Ambiente de execução da aplicação: desenvolvimento, demonstração ou produção.

`APP_ENV` separa os três perfis sem depender do provedor de hospedagem:

- `development` (padrão): laboratório local, simulador permitido.
- `demo`: ambiente de apresentação, simulador permitido com banco próprio.
- `production`: dados operacionais do hospital. O simulador é BLOQUEADO
  (não sobe nem por engano) e o cookie de sessão precisa ser `Secure`.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

AMBIENTES = ("development", "demo", "production")
ALIASES = {"dev": "development", "desenvolvimento": "development", "demonstracao": "demo",
           "prod": "production", "producao": "production"}


def ambiente_atual(environ: Mapping[str, str] | None = None) -> str:
    """Lê `APP_ENV`; valor desconhecido é erro (não vira desenvolvimento em silêncio)."""
    source = os.environ if environ is None else environ
    valor = (source.get("APP_ENV") or "development").strip().lower()
    valor = ALIASES.get(valor, valor)
    if valor not in AMBIENTES:
        raise ValueError(f"APP_ENV deve ser um de {', '.join(AMBIENTES)}")
    return valor


def em_producao(environ: Mapping[str, str] | None = None) -> bool:
    """Atalho para as travas de produção."""
    return ambiente_atual(environ) == "production"
