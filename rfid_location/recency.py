"""Classificação temporal da última detecção, sem acesso ao banco ou relógio."""

import os
from datetime import datetime, timedelta
from typing import Literal, Mapping

RecencyStatus = Literal["recente", "desatualizada", "nunca_detectada"]

RECENCY_THRESHOLD_ENV = "RFID_RECENCY_THRESHOLD_MINUTES"
# Configuração provisória do MVP; o limite operacional depende do HUPAA.
DEFAULT_RECENCY_THRESHOLD_MINUTES = 30


def recency_threshold_from_env(environ: Mapping[str, str] | None = None) -> timedelta:
    """Lê o limite positivo em minutos; configuração inválida falha explicitamente."""
    source = os.environ if environ is None else environ
    raw = source.get(RECENCY_THRESHOLD_ENV, str(DEFAULT_RECENCY_THRESHOLD_MINUTES))
    try:
        minutes = int(raw)
    except ValueError as error:
        raise ValueError(f"{RECENCY_THRESHOLD_ENV} deve ser inteiro positivo") from error
    if minutes <= 0:
        raise ValueError(f"{RECENCY_THRESHOLD_ENV} deve ser inteiro positivo")
    return timedelta(minutes=minutes)


def classify_recency(
    last_detection_at: datetime | None, now: datetime, threshold: timedelta,
) -> RecencyStatus:
    """É recente até o limite inclusivo; depois dele fica desatualizada."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now deve conter fuso horário")
    if threshold <= timedelta(0):
        raise ValueError("threshold deve ser positivo")
    if last_detection_at is None:
        return "nunca_detectada"
    if last_detection_at.tzinfo is None or last_detection_at.utcoffset() is None:
        raise ValueError("last_detection_at deve conter fuso horário")
    return "recente" if now - last_detection_at <= threshold else "desatualizada"
