from __future__ import annotations

import logging
import time
from threading import Thread
from unittest.mock import Mock, patch

import paho.mqtt.client as mqtt

from rfid_ingestion.config import Settings
from rfid_ingestion.mqtt_client import MqttReceiver


def reason(value: int, *, failure: bool) -> Mock:
    return Mock(value=value, is_failure=failure)


def receiver(**settings_changes) -> tuple[MqttReceiver, Mock]:
    values = {
        "mqtt_reconnect_initial_delay": 0.001,
        "mqtt_reconnect_max_delay": 0.002,
        "mqtt_reconnect_jitter": 0,
        **settings_changes,
    }
    settings = Settings(**values)
    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        instance = MqttReceiver(settings, Mock(), Mock(), random_source=lambda: 0.5)
    client = factory.return_value
    client.connect.return_value = mqtt.MQTT_ERR_SUCCESS
    client.subscribe.return_value = (mqtt.MQTT_ERR_SUCCESS, 1)
    return instance, client


def test_connect_and_reconnect_restore_subscription(caplog) -> None:
    instance, client = receiver()
    flags = Mock(session_present=True)

    with caplog.at_level(logging.INFO):
        instance._on_connect(client, None, flags, reason(0, failure=False), None)
        instance._on_subscribe(client, None, 1, [reason(1, failure=False)], None)
        instance._on_disconnect(client, None, Mock(), reason(7, failure=True), None)
        instance._recovering = True
        instance._mqtt_attempt = 2
        instance._on_connect(client, None, flags, reason(0, failure=False), None)
        instance._on_subscribe(client, None, 2, [reason(1, failure=False)], None)

    assert client.subscribe.call_count == 2
    assert instance.ready.is_set()
    assert '"event_type": "mqtt_recovered"' in caplog.text


def test_authentication_rejection_is_permanent() -> None:
    instance, client = receiver()

    instance._on_connect(client, None, Mock(), reason(4, failure=True), None)

    assert instance.failed.is_set()
    assert instance.failure_category == "permanent_configuration"
    client.disconnect.assert_called_once()


def test_server_unavailable_is_temporary() -> None:
    instance, _client = receiver()

    instance._on_connect(_client, None, Mock(), reason(3, failure=True), None)

    assert not instance.failed.is_set()
    assert instance.disconnected.is_set()


def test_unavailable_broker_retries_with_backoff_without_busy_loop() -> None:
    instance, client = receiver()
    client.connect.side_effect = OSError("secret must not be logged")
    waits: list[float] = []

    def controlled_wait(delay: float) -> bool:
        waits.append(delay)
        if len(waits) == 3:
            instance.shutdown.set()
            return True
        return False

    instance.shutdown.wait = controlled_wait
    instance._supervise()

    assert client.connect.call_count == 3
    assert waits == [0.001, 0.002, 0.002]


def test_shutdown_interrupts_broker_backoff() -> None:
    instance, client = receiver(
        mqtt_reconnect_initial_delay=60,
        mqtt_reconnect_max_delay=60,
    )
    client.connect.side_effect = OSError()
    worker = Thread(target=instance._supervise)
    worker.start()
    deadline = time.monotonic() + 1
    while client.connect.call_count == 0 and time.monotonic() < deadline:
        time.sleep(0.001)

    instance.request_shutdown()
    worker.join(timeout=1)

    assert not worker.is_alive()


def test_shutdown_during_normal_operation_stops_worker() -> None:
    instance, client = receiver()

    def loop(_timeout=0.2, **_kwargs):
        time.sleep(0.001)
        return mqtt.MQTT_ERR_SUCCESS

    client.loop.side_effect = loop
    instance._start_worker()
    deadline = time.monotonic() + 1
    while client.connect.call_count == 0 and time.monotonic() < deadline:
        time.sleep(0.001)
    instance.stop()

    assert instance.shutdown.is_set()
    assert instance._worker is not None
    assert not instance._worker.is_alive()


def test_reconnect_events_are_structured_and_hide_exception(caplog) -> None:
    instance, client = receiver()
    client.connect.side_effect = OSError("PRIVATE-PASSWORD")
    instance.shutdown.wait = lambda _delay: True

    with caplog.at_level(logging.INFO):
        instance._supervise()

    assert '"event_type": "mqtt_reconnect_attempt"' in caplog.text
    assert '"event_type": "mqtt_reconnect_scheduled"' in caplog.text
    assert "PRIVATE-PASSWORD" not in caplog.text
