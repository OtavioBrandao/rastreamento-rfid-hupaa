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

    return event
