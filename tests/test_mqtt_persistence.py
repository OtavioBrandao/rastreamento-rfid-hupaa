"""ACK somente após auditoria e resultado definitivo de persistência."""

import json
from unittest.mock import Mock, patch

import pytest

from rfid_ingestion.config import Settings
from rfid_ingestion.mqtt_client import MqttReceiver
from rfid_ingestion.persistence import JsonlEventStore
from rfid_ingestion.repository import PersistenceError, PersistenceResult


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
        assert receiver.failed.is_set()
        assert receiver.failure == "persistência PostgreSQL"
        assert "PRIVATE" not in caplog.text
        with patch.object(receiver, "start"), patch.object(receiver, "stop"):
            assert receiver.run() == 1
