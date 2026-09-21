"""Contrato de persistência e PostgreSQL real, com schema isolado por teste."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import event as sql_event
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from db.models import Antena, LeituraBruta
from db.runtime import DatabaseConfigurationError, create_app_engine
from rfid_ingestion.config import Settings
from rfid_ingestion.parsing import build_event
from rfid_ingestion.repository import PersistenceError, RawReadingRepository


def envelope(*, reader_id="reader-01", **changes):
    payload = {"epc": "EPC-TESTE", "antenna": 1, "rssi": -3880,
               "timestamp": "2026-09-01T10:00:00-03:00"} | changes
    return build_event(topic=f"easy/test/hupaa/portal-01/{reader_id}/readings",
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


def rows(engine):
    with engine.connect() as connection:
        return connection.execute(select(LeituraBruta.__table__)).mappings().all()


def test_exact_duplicate(pg_engine, topology):
    repository = RawReadingRepository(pg_engine)
    event = envelope()
    assert [repository.persist(event).status for _ in range(3)] == ["inserted", "duplicate", "duplicate"]
    assert len(rows(pg_engine)) == 1


def test_concurrent_duplicate(pg_engine, topology):
    repository = RawReadingRepository(pg_engine)
    event = envelope()
    barrier = Barrier(8)

    def attempt(_):
        barrier.wait(timeout=10)
        return repository.persist(event).status

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))
    assert results.count("inserted") == 1
    assert results.count("duplicate") == 7
    assert len(rows(pg_engine)) == 1


def test_legitimate_consecutive_readings(pg_engine, topology):
    first = envelope()
    second = envelope(timestamp="2026-09-01T13:00:00.001Z")
    assert first["canonical_event"]["event_id"] != second["canonical_event"]["event_id"]
    repository = RawReadingRepository(pg_engine)
    assert repository.persist(first).status == "inserted"
    assert repository.persist(second).status == "inserted"
    saved = rows(pg_engine)
    assert len(saved) == 2
    assert {r["epc"] for r in saved} == {"EPC-TESTE"}


@pytest.mark.parametrize("changes,reason", [
    ({"reader_id": "unknown"}, "unknown_reader"),
    ({"reader_id": "serial-independente"}, "unknown_reader"),
    ({"antenna": 2}, "unknown_antenna"),
])
def test_unknown_topology(pg_engine, topology, changes, reason):
    result = RawReadingRepository(pg_engine).persist(envelope(**changes))
    assert result.status == "rejected"
    assert result.reason == reason
    assert rows(pg_engine) == []


def test_inactive_antenna_is_rejected_as_unknown(pg_engine, topology):
    with pg_engine.begin() as connection:
        connection.execute(
            Antena.__table__.update().where(Antena.id == topology["antenna"]).values(ativo=False)
        )
    result = RawReadingRepository(pg_engine).persist(envelope())
    assert result.status == "rejected"
    assert result.reason == "unknown_antenna"
    assert rows(pg_engine) == []


def test_antenna_replacement_topology_resolves_active_antenna(pg_engine, topology):
    """
    Cobre cenário de substituição de hardware da topologia ISS-012:
    1. Leitor reader-01 com Antena A na porta 1;
    2. Antena A é inativada no banco;
    3. Antena B é criada no mesmo leitor e mesma porta 1 (ativo=True);
    4. Antena A permanece presente e inativa no banco (histórico preservado);
    5. Leitura recebida para reader-01 / porta 1 persiste com sucesso;
    6. Leitura associa-se à Antena B;
    7. Nenhuma MultipleResultsFound ocorre.
    """
    antenna_a_id = topology["antenna"]
    reader_id = topology["reader"]
    zone_id = topology["zone"]

    with pg_engine.begin() as connection:
        connection.execute(
            Antena.__table__.update().where(Antena.id == antenna_a_id).values(ativo=False)
        )
        antenna_b_id = connection.execute(
            Antena.__table__.insert().values(
                leitor_id=reader_id,
                porta_numero=1,
                zona_associada_id=zone_id,
                funcao="entrada",
                ativo=True,
            ).returning(Antena.id)
        ).scalar_one()

    assert antenna_a_id != antenna_b_id

    event = envelope(reader_id="reader-01", antenna=1)
    repository = RawReadingRepository(pg_engine)
    result = repository.persist(event)

    assert result.status == "inserted"
    assert result.reading_id is not None

    with pg_engine.connect() as connection:
        reading = connection.execute(
            select(LeituraBruta.__table__).where(LeituraBruta.id == result.reading_id)
        ).mappings().one()
        assert reading["antena_id"] == antenna_b_id

        antenna_a_row = connection.execute(
            select(Antena.__table__).where(Antena.id == antenna_a_id)
        ).mappings().one()
        assert antenna_a_row["ativo"] is False

        antenna_b_row = connection.execute(
            select(Antena.__table__).where(Antena.id == antenna_b_id)
        ).mappings().one()
        assert antenna_b_row["ativo"] is True

        assert connection.scalar(select(func.count()).select_from(LeituraBruta)) == 1


def test_source_data_nullable_rssi_and_distinct_utc_timestamps(pg_engine, topology):
    original = envelope()
    RawReadingRepository(pg_engine).persist(original)
    row, = rows(pg_engine)
    assert row["rssi"] is None
    assert row["dados_origem"] == {"metadata": original["canonical_event"]["metadata"],
                                   **{k: original[k] for k in ("topic", "adapter", "qos", "retain")}}
    assert row["dados_origem"]["metadata"]["rssi_original"] == -3880
    assert row["dados_origem"]["metadata"]["rssi_unit"] == "unknown"
    assert row["lido_em"] == datetime(2026, 9, 1, 13, tzinfo=timezone.utc)
    assert row["recebido_em"] == datetime(2026, 9, 2, tzinfo=timezone.utc)
    assert row["lido_em"].utcoffset().total_seconds() == 0
    assert row["recebido_em"].utcoffset().total_seconds() == 0


def test_invalid_input_never_opens_database():
    engine = Mock()
    result = RawReadingRepository(engine).persist({"canonical_event": None})
    assert result.reason == "invalid_input"
    engine.begin.assert_not_called()


def test_commit_failure_is_not_success(pg_engine, topology):
    def fail_commit(connection):
        raise OperationalError("PRIVATE SQL", {}, Exception("PRIVATE PASSWORD"))

    sql_event.listen(pg_engine, "commit", fail_commit)
    try:
        with pytest.raises(PersistenceError) as error:
            RawReadingRepository(pg_engine).persist(envelope())
        assert "PRIVATE" not in str(error.value)
    finally:
        sql_event.remove(pg_engine, "commit", fail_commit)
    with pg_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(LeituraBruta)) == 0


def test_app_url_is_used_directly_without_migration_fallback(monkeypatch):
    monkeypatch.setenv("APP_DATABASE_URL", "postgresql+psycopg2://test:fake%40value@localhost/test")
    monkeypatch.setenv("DATABASE_URL", "ignored")
    with patch("db.runtime.create_engine") as factory:
        assert create_app_engine() is factory.return_value
    args, kwargs = factory.call_args
    assert args[0].password == "fake@value"
    assert kwargs == {"hide_parameters": True, "echo": False}
