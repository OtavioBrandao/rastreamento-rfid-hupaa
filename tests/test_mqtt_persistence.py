"""ACK somente após auditoria e resultado definitivo de persistência."""

import json
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import func, select

from db.models import LeituraBruta
from rfid_ingestion.config import Settings
from rfid_ingestion.mqtt_client import MqttReceiver
from rfid_ingestion.persistence import JsonlEventStore
from rfid_ingestion.repository import PersistenceError, PersistenceResult, RawReadingRepository


def message(payload=None):
    return Mock(mid=42, qos=1, retain=False,
                topic="easy/test/hupaa/portal-01/reader-01/readings",
                payload=payload if payload is not None else json.dumps({
                    "epc": "PRIVATE-EPC", "antenna": 1, "rssi": -3880,
                    "timestamp": "2026-09-01T13:00:00Z"}).encode())


@pytest.mark.parametrize("status", ["inserted", "duplicate"])
def test_ack_after_audit_and_database(tmp_path, status):
    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        client = factory.return_value
        client.ack.return_value = 0
        path = tmp_path / "audit.jsonl"

        def persist(event):
            assert json.loads(path.read_text())["canonical_event"] == event["canonical_event"]
            client.ack.assert_not_called()
            return PersistenceResult(status)

        receiver = MqttReceiver(Settings(), JsonlEventStore(path), Mock(persist=persist))
        receiver._on_message(client, None, message())
        client.manual_ack_set.assert_called_once_with(True)
        client.ack.assert_called_once_with(42, 1)
        assert not receiver.failed.is_set()


def test_database_failure_no_ack_and_no_secrets(tmp_path, caplog):
    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        repository = Mock(persist=Mock(side_effect=PersistenceError("PRIVATE-CONNECTION")))
        receiver = MqttReceiver(Settings(), JsonlEventStore(tmp_path / "audit.jsonl"), repository)
        receiver._on_message(factory.return_value, None, message())
        factory.return_value.ack.assert_not_called()
        assert receiver.database_unavailable.is_set()
        assert not receiver.failed.is_set()
        assert "PRIVATE" not in caplog.text
        factory.return_value.disconnect.assert_called_once()


@pytest.mark.parametrize("kind,reason", [
    ("invalid", "invalid_input"), ("reader", "unknown_reader"),
    ("antenna", "unknown_antenna"),
])
def test_permanent_rejection_audited_and_acked(pg_engine, topology, tmp_path, kind, reason):
    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        client = factory.return_value
        client.ack.return_value = 0
        path = tmp_path / "audit.jsonl"
        receiver = MqttReceiver(Settings(), JsonlEventStore(path), RawReadingRepository(pg_engine))
        incoming = message()
        if kind == "invalid":
            incoming.payload = b"{invalid"
        elif kind == "reader":
            incoming.topic = incoming.topic.replace("reader-01", "unknown")
        else:
            payload = json.loads(incoming.payload)
            payload["antenna"] = 2
            incoming.payload = json.dumps(payload).encode()
        receiver._on_message(client, None, incoming)
        client.ack.assert_called_once_with(42, 1)
        assert not receiver.failed.is_set()
        audit = [json.loads(line) for line in path.read_text().splitlines()]
        assert audit[0]["payload_original"] == incoming.payload.decode()
        if kind == "invalid":
            assert len(audit) == 1
            assert audit[0]["canonical_event"] is None
            assert audit[0]["parse_error"]
        else:
            assert len(audit) == 2
            assert audit[1]["status"] == "rejected"
            assert audit[1]["reason"] == reason
        with pg_engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(LeituraBruta)) == 0


@pytest.mark.parametrize("append_number", [1, 2])
def test_audit_failure_never_acks(append_number):
    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        store = Mock()
        store.append.side_effect = [OSError("PRIVATE")] if append_number == 1 else [None, OSError("PRIVATE")]
        repository = Mock(persist=Mock(return_value=PersistenceResult("rejected", reason="unknown_reader")))
        receiver = MqttReceiver(Settings(), store, repository)
        receiver._on_message(factory.return_value, None, message())
        factory.return_value.ack.assert_not_called()
        assert receiver.failure == "persistência JSONL"
        if append_number == 1:
            repository.persist.assert_not_called()


def test_messages_after_failure_are_not_processed_or_acked(tmp_path):
    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        repository = Mock(persist=Mock(side_effect=PersistenceError("falha")))
        receiver = MqttReceiver(Settings(), JsonlEventStore(tmp_path / "audit.jsonl"), repository)
        for _ in range(2):
            receiver._on_message(factory.return_value, None, message())
        repository.persist.assert_called_once()
        factory.return_value.ack.assert_not_called()


def test_ack_send_failure_is_fatal(tmp_path):
    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        factory.return_value.ack.return_value = 4
        receiver = MqttReceiver(Settings(), JsonlEventStore(tmp_path / "audit.jsonl"),
                                Mock(persist=Mock(return_value=PersistenceResult("inserted", 1))))
        receiver._on_message(factory.return_value, None, message())
        assert receiver.failure == "envio de ACK"
        factory.return_value.ack.assert_called_once_with(42, 1)


def test_missing_app_url_fails_before_mqtt(monkeypatch, caplog):
    from rfid_ingestion.__main__ import main

    monkeypatch.delenv("APP_DATABASE_URL", raising=False)
    with patch("rfid_ingestion.__main__.MqttReceiver") as receiver:
        assert main() == 2
        receiver.assert_not_called()
    assert "APP_DATABASE_URL" in caplog.text
