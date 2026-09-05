"""Configuração da aplicação por variáveis de ambiente."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import ipaddress
import re
from pathlib import Path
from typing import Mapping


DEFAULT_MQTT_HOST = "127.0.0.1"
DEFAULT_MQTT_PORT = 1883
DEFAULT_MQTT_TOPIC = "easy/+/+/+/+/readings"
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
    mqtt_username: str | None = field(default=None, repr=False)
    mqtt_password: str | None = field(default=None, repr=False)
    mqtt_client_id: str = DEFAULT_MQTT_CLIENT_ID
    mqtt_qos: int = DEFAULT_MQTT_QOS
    events_file: Path = DEFAULT_EVENTS_FILE
    log_level: str = DEFAULT_LOG_LEVEL
    mqtt_mode: str = "local"
    mqtt_tls_enabled: bool = False
    mqtt_ca_cert: str | None = field(default=None, repr=False)
    mqtt_keepalive: int = 60

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        source = os.environ if environ is None else environ
        mode = source.get("MQTT_MODE", "local")
        tls = source.get("MQTT_TLS_ENABLED", "true" if mode == "cloud" else "false")
        if tls not in ("true", "false"):
            raise ValueError("MQTT_TLS_ENABLED deve ser true ou false")
        if mode == "cloud":
            for name in ("MQTT_HOST", "MQTT_USERNAME", "MQTT_PASSWORD", "MQTT_CLIENT_ID"):
                if not source.get(name, "").strip():
                    raise ValueError(f"{name} é obrigatório no modo cloud")
        events_file_value = source.get(
            "EVENTS_FILE", str(DEFAULT_EVENTS_FILE)
        ).strip()
        if not events_file_value:
            raise ValueError("EVENTS_FILE não pode estar vazio")
        settings = cls(
            mqtt_host=source.get("MQTT_HOST", DEFAULT_MQTT_HOST).strip(),
            mqtt_port=_integer_value(source, "MQTT_PORT", 8883 if mode == "cloud" else DEFAULT_MQTT_PORT),
            mqtt_topic=source.get("MQTT_TOPIC", DEFAULT_MQTT_TOPIC).strip(),
            mqtt_username=_optional_value(source.get("MQTT_USERNAME")),
            mqtt_password=_optional_value(source.get("MQTT_PASSWORD")),
            mqtt_client_id=source.get(
                "MQTT_CLIENT_ID", DEFAULT_MQTT_CLIENT_ID
            ).strip(),
            mqtt_qos=_integer_value(source, "MQTT_QOS", DEFAULT_MQTT_QOS),
            events_file=Path(events_file_value),
            log_level=source.get("LOG_LEVEL", DEFAULT_LOG_LEVEL).strip().upper(),
            mqtt_mode=mode,
            mqtt_tls_enabled=tls == "true",
            mqtt_ca_cert=_optional_value(source.get("MQTT_CA_CERT")),
            mqtt_keepalive=_integer_value(source, "MQTT_KEEPALIVE", 60),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.mqtt_mode not in ("local", "cloud"):
            raise ValueError("MQTT_MODE deve ser local ou cloud")
        if not re.fullmatch(r"[A-Za-z0-9.:-]+", self.mqtt_host):
            raise ValueError("MQTT_HOST deve ser um hostname ou IP, sem URL ou credenciais")
        if self.mqtt_mode == "cloud" and (
            not self.mqtt_tls_enabled or self.mqtt_port != 8883
            or not self.mqtt_username or not self.mqtt_password
        ):
            raise ValueError("Modo cloud exige TLS, porta 8883, usuário e senha")
        if self.mqtt_mode == "local":
            try:
                address = ipaddress.ip_address(self.mqtt_host)
                local = address.is_loopback or any(address in network for network in (
                    ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("172.16.0.0/12"),
                    ipaddress.ip_network("192.168.0.0/16"), ipaddress.ip_network("fc00::/7"),
                ) if address.version == network.version)
            except ValueError:
                local = self.mqtt_host == "localhost"
            if not local:
                raise ValueError("Modo local exige IP privado/loopback ou localhost; use cloud para broker externo")
        if bool(self.mqtt_username) != bool(self.mqtt_password):
            raise ValueError("MQTT_USERNAME e MQTT_PASSWORD devem ser definidos juntos")
        if not 1 <= self.mqtt_keepalive <= 65535:
            raise ValueError("MQTT_KEEPALIVE deve estar entre 1 e 65535")
        if not self.mqtt_host:
            raise ValueError("MQTT_HOST não pode estar vazio")
        if not 1 <= self.mqtt_port <= 65535:
            raise ValueError("MQTT_PORT deve estar entre 1 e 65535")
        from .topics import validate_topic
        validate_topic(self.mqtt_topic, subscription=True)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self.mqtt_client_id):
            raise ValueError("MQTT_CLIENT_ID é inválido")
        if self.mqtt_qos != 1:
            raise ValueError("MQTT_QOS deve ser 1 neste contrato")
        if self.log_level not in VALID_LOG_LEVELS:
            raise ValueError("LOG_LEVEL inválido")
