"""Decisão temporal independente de processing time e do banco."""

from datetime import datetime, timedelta, timezone

from rfid_location.types import decide_projection

T = datetime(2026, 9, 22, 10, tzinfo=timezone.utc)


def test_projection_order_and_idempotency():
    assert decide_projection(T, None, 1, None) == "updated"
    assert decide_projection(T + timedelta(minutes=1), T, 2, 1) == "updated"
    assert decide_projection(T - timedelta(minutes=1), T, 2, 1) == "stale"
    assert decide_projection(T, T, 1, 1) == "duplicate"
    assert decide_projection(T, T, 2, 1) == "same_timestamp_conflict"
