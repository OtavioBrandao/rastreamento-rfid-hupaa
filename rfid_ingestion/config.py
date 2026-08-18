"""Configuração da aplicação por variáveis de ambiente."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Mapping


DEFAULT_MQTT_HOST = "127.0.0.1"
DEFAULT_MQTT_PORT = 1883
DEFAULT_MQTT_TOPIC = "rfid/+/tags"
DEFAULT_MQTT_CLIENT_ID = "rfid-mvp-receiver"
DEFAULT_MQTT_QOS = 1
DEFAULT_EVENTS_FILE = Path("data/raw_events.jsonl")
DEFAULT_LOG_LEVEL = "INFO"
VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


def _optional_value(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    return value


def _integer_value(
    source: Mapping[str, str], name: str, default: int
) -> int:
    raw_value = source.get(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        return int(raw_value)
    except ValueError as error:
        raise ValueError(f"{name} deve ser um número inteiro") from error


@dataclass(frozen=True, slots=True)
class Settings:
    """Valores necessários para conectar ao broker e persistir eventos."""

    mqtt_host: str = DEFAULT_MQTT_HOST
    mqtt_port: int = DEFAULT_MQTT_PORT
    mqtt_topic: str = DEFAULT_MQTT_TOPIC
    mqtt_username: str | None = None
    mqtt_password: str | None = field(default=None, repr=False)
    mqtt_client_id: str = DEFAULT_MQTT_CLIENT_ID
    mqtt_qos: int = DEFAULT_MQTT_QOS
    events_file: Path = DEFAULT_EVENTS_FILE
    log_level: str = DEFAULT_LOG_LEVEL

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        source = os.environ if environ is None else environ
        events_file_value = source.get(
            "EVENTS_FILE", str(DEFAULT_EVENTS_FILE)
        ).strip()
        if not events_file_value:
            raise ValueError("EVENTS_FILE não pode estar vazio")
        settings = cls(
            mqtt_host=source.get("MQTT_HOST", DEFAULT_MQTT_HOST).strip(),
            mqtt_port=_integer_value(source, "MQTT_PORT", DEFAULT_MQTT_PORT),
            mqtt_topic=source.get("MQTT_TOPIC", DEFAULT_MQTT_TOPIC).strip(),
            mqtt_username=_optional_value(source.get("MQTT_USERNAME")),
            mqtt_password=_optional_value(source.get("MQTT_PASSWORD")),
            mqtt_client_id=source.get(
                "MQTT_CLIENT_ID", DEFAULT_MQTT_CLIENT_ID
            ).strip(),
            mqtt_qos=_integer_value(source, "MQTT_QOS", DEFAULT_MQTT_QOS),
            events_file=Path(events_file_value),
            log_level=source.get("LOG_LEVEL", DEFAULT_LOG_LEVEL).strip().upper(),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.mqtt_host:
            raise ValueError("MQTT_HOST não pode estar vazio")
        if not 1 <= self.mqtt_port <= 65535:
            raise ValueError("MQTT_PORT deve estar entre 1 e 65535")
        if not self.mqtt_topic or "\x00" in self.mqtt_topic:
            raise ValueError("MQTT_TOPIC é inválido")
        if not self.mqtt_client_id or "\x00" in self.mqtt_client_id:
            raise ValueError("MQTT_CLIENT_ID é inválido")
        if self.mqtt_qos not in (0, 1, 2):
            raise ValueError("MQTT_QOS deve ser 0, 1 ou 2")
        if self.log_level not in VALID_LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL inválido: {self.log_level}")
