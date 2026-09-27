"""Instantes da API em UTC; a apresentação hospitalar cabe ao cliente."""

from datetime import datetime, timezone


def em_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp sem fuso no banco")
    return value.astimezone(timezone.utc)
