"""Contrato de persistência e PostgreSQL real, com schema isolado por teste."""

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from db.models import LeituraBruta
from db.runtime import DatabaseConfigurationError, create_app_engine
from rfid_ingestion.config import Settings
from rfid_ingestion.parsing import build_event
from rfid_ingestion.repository import RawReadingRepository


def envelope(**changes):
    payload = {"epc": "EPC-TESTE", "antenna": 1, "rssi": -3880,
               "timestamp": "2026-09-01T10:00:00-03:00"} | changes
    return build_event(topic="easy/test/hupaa/portal-01/reader-01/readings",
                       qos=1, retain=False, payload=json.dumps(payload).encode(),
                       settings=Settings(),
                       received_at=datetime(2026, 9, 2, tzinfo=timezone.utc))


def test_basic_insert(pg_engine, topology):
    event = envelope()
    result = RawReadingRepository(pg_engine).persist(event)
    assert result.status == "inserted"
    with pg_engine.connect() as connection:
        row = connection.execute(select(LeituraBruta.__table__)).mappings().one()
    assert row["id"] == result.reading_id
    assert row["event_id"] == event["canonical_event"]["event_id"]
    assert row["antena_id"] == topology["antenna"]


@pytest.mark.parametrize("value", [None, "", "   ", "not-a-url-private", "sqlite://"])
def test_app_configuration_safe(monkeypatch, value):
    monkeypatch.setenv("DATABASE_URL", "migration-url-must-not-be-used")
    if value is None:
        monkeypatch.delenv("APP_DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("APP_DATABASE_URL", value)
    with pytest.raises(DatabaseConfigurationError, match="APP_DATABASE_URL") as error:
        create_app_engine()
    assert "private" not in str(error.value)
