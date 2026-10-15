"""Configuração da aplicação por variáveis de ambiente."""

from __future__ import annotations

import ipaddress
import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

DEFAULT_MQTT_HOST = "127.0.0.1"
DEFAULT_MQTT_PORT = 1883
DEFAULT_MQTT_TOPIC = "easy/+/+/+/+/readings"
DEFAULT_MQTT_CLIENT_ID = "rfid-mvp-receiver"
DEFAULT_MQTT_QOS = 1
DEFAULT_EVENTS_FILE = Path("data/raw_events.jsonl")
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_MAX_PAYLOAD_BYTES = 65536
DEFAULT_RETRY_INITIAL_DELAY = 1.0
DEFAULT_RETRY_MAX_DELAY = 30.0
DEFAULT_RETRY_MULTIPLIER = 2.0
DEFAULT_RETRY_JITTER = 0.2
DEFAULT_RFID_DEBOUNCE_WINDOW_MS = 250
DEFAULT_RFID_OUT_OF_ORDER_TOLERANCE_MS = 1000
DEFAULT_RFID_PASSAGE_MAX_INTERVAL_MS = 3000
# Calibrados com o ensaio físico de 05/10/2026 (vai e vem contínuo no portal EASY).
DEFAULT_RFID_PASSAGE_REFRACTORY_MS = 1000
DEFAULT_RFID_PASSAGE_OVERLAP_GRACE_MS = 300
DEFAULT_RFID_PASSAGE_ORIGIN_HOLD_MS = 1000
DEFAULT_RFID_DIRECTION_AMBIGUITY_MS = 100
VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
LOCAL_MQTT_HOSTNAMES = frozenset({"localhost", "mosquitto"})


def _optional_value(value: str | None) -> str | None:
  """Obtém texto opcional de configuração, usando o padrão quando ausente."""
  if value is None or value == "":
      return None
  return value


def _integer_value(
  source: Mapping[str, str], name: str, default: int
) -> int:
  """Lê e converte configuração inteira, com erro contextual para valor inválido."""
  raw_value = source.get(name)
  if raw_value is None or not raw_value.strip():
      return default
  try:
      return int(raw_value)
  except ValueError as error:
      raise ValueError(f"{name} deve ser um número inteiro") from error


def _float_value(
    source: Mapping[str, str], name: str, default: float
) -> float:
    """Lê configuração numérica e recusa valores não finitos."""
    raw_value = source.get(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        return float(raw_value)
    except ValueError as error:
        raise ValueError(f"{name} deve ser um número") from error


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
  # Opt-in explícito de laboratório: broker externo sem TLS (ex.: leitor sem mqtts).
  mqtt_insecure_lab: bool = False
  mqtt_ca_cert: str | None = field(default=None, repr=False)
  mqtt_keepalive: int = 60
  max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES
  normalization_adapter: str = "ez700"
  reader_adapters: dict[str, str] = field(default_factory=dict)
  ez700_timestamp_format: str = "rfc3339"
  mqtt_reconnect_initial_delay: float = DEFAULT_RETRY_INITIAL_DELAY
  mqtt_reconnect_max_delay: float = DEFAULT_RETRY_MAX_DELAY
  mqtt_reconnect_multiplier: float = DEFAULT_RETRY_MULTIPLIER
  mqtt_reconnect_jitter: float = DEFAULT_RETRY_JITTER
  db_retry_initial_delay: float = DEFAULT_RETRY_INITIAL_DELAY
  db_retry_max_delay: float = DEFAULT_RETRY_MAX_DELAY
  db_retry_multiplier: float = DEFAULT_RETRY_MULTIPLIER
  db_retry_jitter: float = DEFAULT_RETRY_JITTER
  rfid_debounce_window_ms: int = DEFAULT_RFID_DEBOUNCE_WINDOW_MS
  rfid_out_of_order_tolerance_ms: int = DEFAULT_RFID_OUT_OF_ORDER_TOLERANCE_MS
  rfid_passage_max_interval_ms: int = DEFAULT_RFID_PASSAGE_MAX_INTERVAL_MS
  rfid_passage_refractory_ms: int = DEFAULT_RFID_PASSAGE_REFRACTORY_MS
  rfid_passage_overlap_grace_ms: int = DEFAULT_RFID_PASSAGE_OVERLAP_GRACE_MS
  rfid_passage_origin_hold_ms: int = DEFAULT_RFID_PASSAGE_ORIGIN_HOLD_MS
  rfid_direction_ambiguity_ms: int = DEFAULT_RFID_DIRECTION_AMBIGUITY_MS

  @classmethod
  def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
      """Constrói Settings com as variáveis fornecidas ou com o ambiente do processo."""
      source = os.environ if environ is None else environ
      mode = source.get("MQTT_MODE", "local")
      tls = source.get("MQTT_TLS_ENABLED", "true" if mode == "cloud" else "false")
      if tls not in ("true", "false"):
          raise ValueError("MQTT_TLS_ENABLED deve ser true ou false")
      insecure_lab = source.get("MQTT_INSECURE_LAB", "false")
      if insecure_lab not in ("true", "false"):
          raise ValueError("MQTT_INSECURE_LAB deve ser true ou false")
      if mode == "cloud":
          obrigatorios = ("MQTT_HOST", "MQTT_CLIENT_ID") if insecure_lab == "true" else (
              "MQTT_HOST", "MQTT_USERNAME", "MQTT_PASSWORD", "MQTT_CLIENT_ID")
          for name in obrigatorios:
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
          mqtt_insecure_lab=insecure_lab == "true",
          mqtt_ca_cert=_optional_value(source.get("MQTT_CA_CERT")),
          mqtt_keepalive=_integer_value(source, "MQTT_KEEPALIVE", 60),
          max_payload_bytes=_integer_value(source, "MQTT_MAX_PAYLOAD_BYTES", DEFAULT_MAX_PAYLOAD_BYTES),
          normalization_adapter=source.get("RFID_DEFAULT_ADAPTER", "ez700"),
          reader_adapters=json.loads(source.get("RFID_READER_ADAPTERS", "{}")),
          ez700_timestamp_format=source.get("EZ700_TIMESTAMP_FORMAT", "rfc3339"),
          mqtt_reconnect_initial_delay=_float_value(
              source, "MQTT_RECONNECT_INITIAL_DELAY", DEFAULT_RETRY_INITIAL_DELAY
          ),
          mqtt_reconnect_max_delay=_float_value(
              source, "MQTT_RECONNECT_MAX_DELAY", DEFAULT_RETRY_MAX_DELAY
          ),
          mqtt_reconnect_multiplier=_float_value(
              source, "MQTT_RECONNECT_MULTIPLIER", DEFAULT_RETRY_MULTIPLIER
          ),
          mqtt_reconnect_jitter=_float_value(
              source, "MQTT_RECONNECT_JITTER", DEFAULT_RETRY_JITTER
          ),
          db_retry_initial_delay=_float_value(
              source, "DB_RETRY_INITIAL_DELAY", DEFAULT_RETRY_INITIAL_DELAY
          ),
          db_retry_max_delay=_float_value(
              source, "DB_RETRY_MAX_DELAY", DEFAULT_RETRY_MAX_DELAY
          ),
          db_retry_multiplier=_float_value(
              source, "DB_RETRY_MULTIPLIER", DEFAULT_RETRY_MULTIPLIER
          ),
          db_retry_jitter=_float_value(
              source, "DB_RETRY_JITTER", DEFAULT_RETRY_JITTER
          ),
          rfid_debounce_window_ms=_integer_value(
              source, "RFID_DEBOUNCE_WINDOW_MS", DEFAULT_RFID_DEBOUNCE_WINDOW_MS
          ),
          rfid_out_of_order_tolerance_ms=_integer_value(
              source,
              "RFID_OUT_OF_ORDER_TOLERANCE_MS",
              DEFAULT_RFID_OUT_OF_ORDER_TOLERANCE_MS,
          ),
          rfid_passage_max_interval_ms=_integer_value(
              source, "RFID_PASSAGE_MAX_INTERVAL_MS", DEFAULT_RFID_PASSAGE_MAX_INTERVAL_MS
          ),
          rfid_passage_refractory_ms=_integer_value(
              source, "RFID_PASSAGE_REFRACTORY_MS", DEFAULT_RFID_PASSAGE_REFRACTORY_MS
          ),
          rfid_passage_overlap_grace_ms=_integer_value(
              source, "RFID_PASSAGE_OVERLAP_GRACE_MS", DEFAULT_RFID_PASSAGE_OVERLAP_GRACE_MS
          ),
          rfid_passage_origin_hold_ms=_integer_value(
              source, "RFID_PASSAGE_ORIGIN_HOLD_MS", DEFAULT_RFID_PASSAGE_ORIGIN_HOLD_MS
          ),
          rfid_direction_ambiguity_ms=_integer_value(
              source, "RFID_DIRECTION_AMBIGUITY_MS", DEFAULT_RFID_DIRECTION_AMBIGUITY_MS
          ),
      )
      settings.validate()
      return settings

  def validate(self) -> None:
      """Valida transporte, credenciais, tópico, limites e parâmetros temporais da ingestão."""
      if type(self.max_payload_bytes) is not int or self.max_payload_bytes < 1:
          raise ValueError("MQTT_MAX_PAYLOAD_BYTES deve ser inteiro positivo")
      if self.ez700_timestamp_format not in ("rfc3339", "epoch_ms", "counter"):
          raise ValueError("EZ700_TIMESTAMP_FORMAT deve ser rfc3339, epoch_ms ou counter")
      if not isinstance(self.normalization_adapter, str) or not self.normalization_adapter:
          raise ValueError("RFID_DEFAULT_ADAPTER deve ser texto não vazio")
      if not isinstance(self.reader_adapters, dict) or any(
          not re.fullmatch(r"[A-Za-z0-9_-]+", k) or not isinstance(v, str) or not v
          for k, v in self.reader_adapters.items()
      ):
          raise ValueError("RFID_READER_ADAPTERS deve mapear reader_id para nome de adapter")
      if type(self.rfid_debounce_window_ms) is not int or self.rfid_debounce_window_ms < 1:
          raise ValueError("RFID_DEBOUNCE_WINDOW_MS deve ser inteiro positivo")
      if type(self.rfid_passage_max_interval_ms) is not int or self.rfid_passage_max_interval_ms < 1:
          raise ValueError("RFID_PASSAGE_MAX_INTERVAL_MS deve ser inteiro positivo")
      for name in ("refractory", "overlap_grace", "origin_hold"):
          value = getattr(self, f"rfid_passage_{name}_ms")
          if type(value) is not int or value < 0:
              raise ValueError(f"RFID_PASSAGE_{name.upper()}_MS deve ser inteiro não negativo")
      if type(self.rfid_direction_ambiguity_ms) is not int or self.rfid_direction_ambiguity_ms < 0:
          raise ValueError("RFID_DIRECTION_AMBIGUITY_MS deve ser inteiro não negativo")
      if (
          type(self.rfid_out_of_order_tolerance_ms) is not int
          or self.rfid_out_of_order_tolerance_ms < 0
      ):
          raise ValueError(
              "RFID_OUT_OF_ORDER_TOLERANCE_MS deve ser inteiro não negativo"
          )
      if self.mqtt_mode not in ("local", "cloud"):
          raise ValueError("MQTT_MODE deve ser local ou cloud")
      if not re.fullmatch(r"[A-Za-z0-9.:-]+", self.mqtt_host):
          raise ValueError("MQTT_HOST deve ser um hostname ou IP, sem URL ou credenciais")
      if self.mqtt_insecure_lab and (self.mqtt_mode != "cloud" or self.mqtt_tls_enabled):
          raise ValueError("MQTT_INSECURE_LAB exige MQTT_MODE=cloud e MQTT_TLS_ENABLED=false")
      if self.mqtt_mode == "cloud" and not self.mqtt_insecure_lab and (
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
              local = self.mqtt_host in LOCAL_MQTT_HOSTNAMES
          if not local:
              raise ValueError(
                  "Modo local exige IP privado/loopback, localhost ou o serviço "
                  "mosquitto do Compose; use cloud para broker externo"
              )
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
      self._validate_backoff(
          "MQTT_RECONNECT",
          self.mqtt_reconnect_initial_delay,
          self.mqtt_reconnect_max_delay,
          self.mqtt_reconnect_multiplier,
          self.mqtt_reconnect_jitter,
      )
      self._validate_backoff(
          "DB_RETRY",
          self.db_retry_initial_delay,
          self.db_retry_max_delay,
          self.db_retry_multiplier,
          self.db_retry_jitter,
      )

  @staticmethod
  def _validate_backoff(
      prefix: str,
      initial_delay: float,
      max_delay: float,
      multiplier: float,
      jitter: float,
  ) -> None:
      """Verifica atraso inicial, teto, multiplicador e jitter da política de recuperação."""
      values = (initial_delay, max_delay, multiplier, jitter)
      if not all(math.isfinite(value) for value in values):
          raise ValueError(f"{prefix} exige valores finitos")
      if initial_delay <= 0 or max_delay < initial_delay:
          raise ValueError(
              f"{prefix} exige atraso inicial positivo e máximo não menor"
          )
      if multiplier < 1:
          raise ValueError(f"{prefix}_MULTIPLIER deve ser pelo menos 1")
      if not 0 <= jitter <= 1:
          raise ValueError(f"{prefix}_JITTER deve estar entre 0 e 1")
