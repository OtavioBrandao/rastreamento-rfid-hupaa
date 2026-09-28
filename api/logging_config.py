"""
Logging da API (ISS-026).

O uvicorn configura apenas os loggers `uvicorn.*`; sem isto, todo INFO de
`api.*` é descartado no servidor real (o root fica em WARNING sem handler),
embora o `caplog` dos testes capture de qualquer jeito. Aqui o logger `api`
ganha um handler próprio, UMA vez só (reimportar ou chamar de novo não
duplica linhas), e continua com `propagate` ligado para o `caplog` enxergar.
"""

import json
import logging
import os
import sys
from collections.abc import Mapping

LOG_LEVEL_ENV = "LOG_LEVEL"
_MARCA_HANDLER = "_rfid_api_handler"
NIVEIS_VALIDOS = ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG")


def nivel_do_ambiente(environ: Mapping[str, str] | None = None) -> str:
    source = os.environ if environ is None else environ
    nivel = source.get(LOG_LEVEL_ENV, "INFO").strip().upper()
    if nivel not in NIVEIS_VALIDOS:
        raise ValueError(f"{LOG_LEVEL_ENV} deve ser um de {', '.join(NIVEIS_VALIDOS)}")
    return nivel


def configurar_logging_api(environ: Mapping[str, str] | None = None) -> logging.Logger:
    logger = logging.getLogger("api")
    logger.setLevel(nivel_do_ambiente(environ))
    logger.propagate = True
    if not any(getattr(handler, _MARCA_HANDLER, False) for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%dT%H:%M:%S%z"
        ))
        setattr(handler, _MARCA_HANDLER, True)
        logger.addHandler(handler)
    return logger


def registrar_evento(logger: logging.Logger, evento: str, **campos: object) -> None:
    """Uma linha JSON por evento. Quem chama nunca passa senha, hash ou token."""
    logger.info(json.dumps({"evento": evento, **campos}, ensure_ascii=False, sort_keys=True))
