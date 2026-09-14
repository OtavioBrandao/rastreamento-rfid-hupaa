"""Conversão segura de mensagens MQTT em eventos persistíveis."""

from __future__ import annotations

import base64
import json
import math
from datetime import datetime, timezone
from typing import Any

from .config import Settings
from .normalization import normalize
from .topics import validate_topic


MAX_JSON_DEPTH = 64


def _check_json_depth(value):
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > MAX_JSON_DEPTH:
            raise ValueError("profundidade JSON não suportada")
        children = item.values() if isinstance(item, dict) else item if isinstance(item, list) else ()
        pending.extend((child, depth + 1) for child in children)


def _reject_non_standard_number(value: str) -> None:
    raise ValueError(f"número JSON não padronizado: {value}")


def _finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("número JSON fora do intervalo finito")
    return result


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("received_at deve conter fuso horário")
    utc_value = value.astimezone(timezone.utc)
    return utc_value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def build_event(
    *,
    topic: str,
    qos: int,
    retain: bool,
    payload: bytes,
    received_at: datetime | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Preserva auditoria e acrescenta evento canônico somente após validação."""

    settings = settings or Settings()
    event: dict[str, Any] = {
        "received_at_utc": _utc_timestamp(
            received_at or datetime.now(timezone.utc)
        ),
        "topic": topic,
        "qos": qos,
        "retain": bool(retain),
        "payload_original": "",
        "payload_encoding": "utf-8",
        "payload_json": None,
        "parse_error": None,
        "validation_errors": [],
        "canonical_event": None,
        "reader_id": None,
        "adapter": settings.normalization_adapter,
    }
    # Contexto conhecido mesmo quando os bytes não podem ser interpretados.
    try:
        validate_topic(topic)
        event["reader_id"] = topic.split("/")[4]
        event["adapter"] = settings.reader_adapters.get(event["reader_id"], settings.normalization_adapter)
    except ValueError:
        pass

    oversized = len(payload) > settings.max_payload_bytes
    if oversized:
        event["validation_errors"] = ["payload excede MQTT_MAX_PAYLOAD_BYTES"]

    try:
        text_payload = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        event["payload_original"] = base64.b64encode(payload).decode("ascii")
        event["payload_encoding"] = "base64"
        event["parse_error"] = (
            f"payload não é UTF-8 válido: byte {error.start}"
        )
        return event

    event["payload_original"] = text_payload
    if oversized:
        return event  # Evidência preservada; não materializar JSON acima do limite.
    try:
        event["payload_json"] = json.loads(
            text_payload, parse_constant=_reject_non_standard_number, parse_float=_finite_float
        )
        _check_json_depth(event["payload_json"])
    except (json.JSONDecodeError, ValueError, RecursionError) as error:
        event["payload_json"] = None
        if isinstance(error, json.JSONDecodeError):
            event["parse_error"] = (
                f"JSON inválido: {error.msg} "
                f"(linha {error.lineno}, coluna {error.colno})"
            )
        else:
            event["parse_error"] = "JSON inválido: número ou profundidade não suportados"

    if event["parse_error"] is None:
        (event["canonical_event"], event["validation_errors"],
         event["reader_id"], event["adapter"]) = normalize(event["payload_json"], topic, payload, settings)
    return event
