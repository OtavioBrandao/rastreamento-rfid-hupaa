"""Fronteiras da regra de recência, com relógio explícito e fusos reais."""

from datetime import datetime, timedelta, timezone

import pytest

from rfid_location.recency import classify_recency, recency_threshold_from_env

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
THRESHOLD = timedelta(minutes=30)


@pytest.mark.parametrize(
    ("elapsed", "expected"),
    [
        (timedelta(seconds=1), "recente"),
        (THRESHOLD - timedelta(microseconds=1), "recente"),
        (THRESHOLD, "recente"),
        (THRESHOLD + timedelta(microseconds=1), "desatualizada"),
        (timedelta(days=1), "desatualizada"),
    ],
)
def test_limites_temporais(elapsed, expected):
    assert classify_recency(NOW - elapsed, NOW, THRESHOLD) == expected


def test_nunca_detectada():
    assert classify_recency(None, NOW, THRESHOLD) == "nunca_detectada"


def test_compara_instantes_com_fusos_diferentes():
    sao_paulo = timezone(timedelta(hours=-3))
    detection = datetime(2026, 9, 23, 8, 30, tzinfo=sao_paulo)
    assert classify_recency(detection, NOW, THRESHOLD) == "recente"


def test_rejeita_now_sem_fuso():
    with pytest.raises(ValueError, match="fuso horário"):
        classify_recency(None, datetime(2026, 9, 23, 12, 0), THRESHOLD)


def test_rejeita_deteccao_sem_fuso():
    with pytest.raises(ValueError, match="fuso horário"):
        classify_recency(datetime(2026, 9, 23, 11, 30), NOW, THRESHOLD)


def test_limite_configuravel():
    assert recency_threshold_from_env({}) == THRESHOLD
    assert recency_threshold_from_env({"RFID_RECENCY_THRESHOLD_MINUTES": "45"}) == timedelta(
        minutes=45
    )


@pytest.mark.parametrize("value", ["abc", "", "0", "-10", "1.5"])
def test_configuracao_invalida_falha(value):
    with pytest.raises(ValueError, match="RFID_RECENCY_THRESHOLD_MINUTES"):
        recency_threshold_from_env({"RFID_RECENCY_THRESHOLD_MINUTES": value})


def test_limite_nao_positivo_falha():
    with pytest.raises(ValueError, match="threshold"):
        classify_recency(None, NOW, timedelta(0))
