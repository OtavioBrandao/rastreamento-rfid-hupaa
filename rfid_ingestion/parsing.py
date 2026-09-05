"""Conversão segura de mensagens MQTT em eventos persistíveis."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
from typing import Any


def _reject_non_standard_number(value: str) -> None:
    raise ValueError(f"número JSON não padronizado: {value}")


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
) -> dict[str, Any]:
    """Cria um evento sem impor um esquema rígido ao JSON do leitor."""

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
    }

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
    try:
        event["payload_json"] = json.loads(
            text_payload, parse_constant=_reject_non_standard_number
        )
    except (json.JSONDecodeError, ValueError) as error:
        if isinstance(error, json.JSONDecodeError):
            event["parse_error"] = (
                f"JSON inválido: {error.msg} "
                f"(linha {error.lineno}, coluna {error.colno})"
            )
        else:
            event["parse_error"] = f"JSON inválido: {error}"

    if event["parse_error"] is None:
        event["validation_errors"] = validate_payload(event["payload_json"])
    return event


def validate_payload(payload: Any) -> list[str]:
    """Valida o contrato mínimo; preserva eventos inválidos e campos extras."""
    if not isinstance(payload, dict):
        return ["payload deve ser objeto JSON"]
    errors = []
    for key in ("epc", "timestamp"):
        if not isinstance(payload.get(key), str) or not payload[key].strip():
            errors.append(f"{key} deve ser texto não vazio")
    if type(payload.get("antenna")) is not int or payload["antenna"] < 1:
        errors.append("antenna deve ser inteiro positivo")
    if type(payload.get("rssi")) not in (int, float):
        errors.append("rssi deve ser numérico")
    return errors
