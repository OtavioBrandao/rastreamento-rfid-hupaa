"""Configuração central de logging."""

from __future__ import annotations

import logging
import os


class SecretFilter(logging.Filter):
    def __init__(self, secrets):
        super().__init__()
        self.secrets = sorted((s for s in secrets if s), key=len, reverse=True)

    def filter(self, record):
        message = record.getMessage()
        for secret in self.secrets:
            message = message.replace(secret, "[REDACTED]")
        record.msg, record.args = message, ()
        return True


def configure_logging(level: str, secrets=None) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    values = secrets if secrets is not None else [os.getenv("MQTT_USERNAME"), os.getenv("MQTT_PASSWORD")]
    for handler in logging.getLogger().handlers:
        handler.addFilter(SecretFilter(values))
