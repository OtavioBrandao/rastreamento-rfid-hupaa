"""Integração ISS-014: MQTT -> PostgreSQL -> debounce em memória."""

import json
import logging
from unittest.mock import Mock, patch

import paho.mqtt.client as mqtt
from sqlalchemy import func, select

from db.models import Antena, LeituraBruta
from rfid_ingestion.config import Settings
from rfid_ingestion.mqtt_client import MqttReceiver
from rfid_ingestion.persistence import JsonlEventStore
from rfid_ingestion.repository import PersistenceResult, RawReadingRepository


def mqtt_message(mid: int, antenna: int, timestamp: str) -> Mock:
    payload = {
        "epc": "EPC-INTEGRACAO",
        "antenna": antenna,
        "rssi": -3880,
        "timestamp": timestamp,
    }
    return Mock(
        mid=mid,
        qos=1,
        retain=False,
        topic="easy/test/hupaa/portal-01/reader-01/readings",
        payload=json.dumps(payload).encode(),
    )


def test_pipeline_preserves_raw_readings_and_only_debounces_insertions(
    pg_engine, topology, tmp_path
) -> None:
    with pg_engine.begin() as connection:
        second_antenna = connection.execute(
            Antena.__table__.insert().values(
                leitor_id=topology["reader"],
                porta_numero=2,
                zona_associada_id=topology["zone"],
                funcao="indefinido",
            ).returning(Antena.id)
        ).scalar_one()

    observations = []
    settings = Settings(
        rfid_debounce_window_ms=250,
        rfid_out_of_order_tolerance_ms=500,
    )
    messages = [
        mqtt_message(1, 1, "2026-09-22T12:00:00.000Z"),
        mqtt_message(2, 1, "2026-09-22T12:00:00.100Z"),
        mqtt_message(3, 1, "2026-09-22T12:00:00.200Z"),
        mqtt_message(4, 2, "2026-09-22T12:00:00.150Z"),
    ]

    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        client = factory.return_value
        client.ack.return_value = 0
        receiver = MqttReceiver(
            settings,
            JsonlEventStore(tmp_path / "events.jsonl"),
            RawReadingRepository(pg_engine),
            observation_handler=observations.append,
        )
        for message in (*messages, messages[1]):
            receiver._on_message(client, None, message)
            receiver._flush_pending()
        receiver.flush_debounce()

    with pg_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(LeituraBruta)) == 4

    assert client.ack.call_count == 5
    assert len(observations) == 2
    by_antenna = {item.antenna_id: item for item in observations}
    assert by_antenna[topology["antenna"]].reading_count == 3
    assert by_antenna[second_antenna].reading_count == 1
    assert receiver.debouncer.counters.readings_received == 4
    assert receiver.debouncer.counters.readings_incorporated == 2


def test_duplicate_persistence_result_never_increments_debounce(tmp_path) -> None:
    repository = Mock()
    repository.persist.side_effect = [
        PersistenceResult("inserted", 10, antenna_id=20),
        PersistenceResult("duplicate"),
    ]
    incoming = mqtt_message(1, 1, "2026-09-22T12:00:00.000Z")

    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        client = factory.return_value
        client.ack.return_value = 0
        receiver = MqttReceiver(
            Settings(),
            JsonlEventStore(tmp_path / "events.jsonl"),
            repository,
        )
        receiver._on_message(client, None, incoming)
        receiver._flush_pending()
        receiver._on_message(client, None, incoming)
        receiver._flush_pending()
        observation, = receiver.flush_debounce()

    assert observation.reading_count == 1
    assert receiver.debouncer.counters.readings_received == 1
    assert client.ack.call_count == 2


def test_late_event_is_logged_and_does_not_change_finalized_observation(
    tmp_path, caplog
) -> None:
    repository = Mock()
    repository.persist.side_effect = [
        PersistenceResult("inserted", reading_id, antenna_id=20)
        for reading_id in (1, 2, 3)
    ]
    observations = []
    settings = Settings(
        rfid_debounce_window_ms=100,
        rfid_out_of_order_tolerance_ms=100,
    )

    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        client = factory.return_value
        client.ack.return_value = 0
        receiver = MqttReceiver(
            settings,
            JsonlEventStore(tmp_path / "events.jsonl"),
            repository,
            observation_handler=observations.append,
        )
        receiver._on_message(
            client, None, mqtt_message(1, 1, "2026-09-22T12:00:00.000Z")
        )
        receiver._flush_pending()
        receiver._on_message(
            client, None, mqtt_message(2, 1, "2026-09-22T12:00:01.000Z")
        )
        receiver._flush_pending()
        receiver._on_message(
            client, None, mqtt_message(3, 1, "2026-09-22T12:00:00.050Z")
        )
        receiver._flush_pending()
        receiver.flush_debounce()

    events = [json.loads(record.message) for record in caplog.records]
    late, = [item for item in events if item.get("event_type") == "rfid_debounce_late_event"]
    assert late["accepted"] is False
    assert late["late_events"] == 1
    assert [item.reading_count for item in observations] == [1, 1]


def test_debounce_failure_does_not_break_post_commit_ack(tmp_path, caplog) -> None:
    repository = Mock(
        persist=Mock(return_value=PersistenceResult("inserted", 10, antenna_id=20))
    )
    debouncer = Mock()
    debouncer.add.side_effect = RuntimeError("PRIVATE")

    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        client = factory.return_value
        client.ack.return_value = 0
        receiver = MqttReceiver(
            Settings(),
            JsonlEventStore(tmp_path / "events.jsonl"),
            repository,
            debouncer=debouncer,
        )
        receiver._on_message(
            client, None, mqtt_message(1, 1, "2026-09-22T12:00:00.000Z")
        )
        receiver._flush_pending()

    client.ack.assert_called_once_with(1, 1)
    assert "rfid_debounce_failed" in caplog.text
    assert "PRIVATE" not in caplog.text


def test_network_loop_emits_a_then_b_without_shutdown_flush(tmp_path, caplog) -> None:
    clock = [0.0]
    repository = Mock()
    repository.persist.side_effect = [
        PersistenceResult("inserted", reading_id, antenna_id=antenna_id)
        for reading_id, antenna_id in ((1, 20), (2, 20), (3, 20), (4, 21), (5, 21))
    ]
    observations = []
    settings = Settings(
        rfid_debounce_window_ms=250,
        rfid_out_of_order_tolerance_ms=1000,
    )
    deliveries = [
        (0.0, mqtt_message(1, 1, "2026-09-22T12:00:00.000Z")),
        (0.05, mqtt_message(2, 1, "2026-09-22T12:00:00.050Z")),
        (0.1, mqtt_message(3, 1, "2026-09-22T12:00:00.100Z")),
        (1.351, None),  # A fica pronta durante o silêncio, antes da primeira B.
        (1.36, mqtt_message(4, 2, "2026-09-22T12:00:01.360Z")),
        (1.41, mqtt_message(5, 2, "2026-09-22T12:00:01.410Z")),
        (2.661, None),  # B fica pronta sem nova leitura nessa chave.
    ]

    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        client = factory.return_value
        client.connect.return_value = mqtt.MQTT_ERR_SUCCESS
        client.ack.return_value = mqtt.MQTT_ERR_SUCCESS
        receiver = MqttReceiver(
            settings,
            JsonlEventStore(tmp_path / "events.jsonl"),
            repository,
            observation_handler=observations.append,
            monotonic_clock=lambda: clock[0],
        )

        def loop(*, timeout):
            if not deliveries:
                return mqtt.MQTT_ERR_CONN_LOST
            clock[0], incoming = deliveries.pop(0)
            if incoming is not None:
                receiver._on_message(client, None, incoming)
                receiver._flush_pending()
            return mqtt.MQTT_ERR_SUCCESS

        client.loop.side_effect = loop
        with caplog.at_level(logging.INFO, logger="rfid_ingestion.mqtt_client"):
            receiver._network_session()

    assert [item.antenna_id for item in observations] == [20, 21]
    assert [item.reading_count for item in observations] == [3, 2]
    assert receiver.debouncer.counters.readings_received == 5
    assert receiver.debouncer.counters.readings_incorporated == 3
    assert receiver.debouncer.counters.observations_finalized == 2
    assert client.ack.call_count == 5
    assert "rfid_debounce_automatic_finalization" in caplog.text
