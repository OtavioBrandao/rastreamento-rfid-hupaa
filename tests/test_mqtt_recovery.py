import errno
import logging
import socket
import ssl
import time
from threading import Thread
from unittest.mock import Mock, patch

import paho.mqtt.client as mqtt
import pytest

from rfid_ingestion.config import Settings
from rfid_ingestion.mqtt_client import MqttReceiver
from rfid_ingestion.resilience import (
    FailureCategory,
    classify_connack_code,
    classify_connection_exception,
)


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
    assert instance.failure_reason == "authentication_failure"
    client.disconnect.assert_called_once()


def test_authorization_rejection_is_permanent() -> None:
    instance, client = receiver()

    instance._on_connect(client, None, Mock(), reason(5, failure=True), None)

    assert instance.failed.is_set()
    assert instance.failure_category == "permanent_configuration"
    assert instance.failure_reason == "authorization_failure"
    client.disconnect.assert_called_once()


def test_server_unavailable_is_temporary(caplog) -> None:
    instance, _client = receiver()

    with caplog.at_level(logging.WARNING):
        instance._on_connect(_client, None, Mock(), reason(3, failure=True), None)

    assert not instance.failed.is_set()
    assert instance.disconnected.is_set()
    assert '"reason": "broker_unavailable"' in caplog.text


def test_invalid_tls_certificate_is_permanent_and_not_retried() -> None:
    instance, client = receiver()
    client.connect.side_effect = ssl.SSLCertVerificationError(
        1, "PRIVATE certificate detail"
    )

    instance._network_session()

    assert instance.failed.is_set()
    assert instance.failure_category == "permanent_configuration"
    assert instance.failure_reason == "tls_certificate_failure"
    assert client.connect.call_count == 1


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


@pytest.mark.parametrize(
    "exception,expected_category,expected_reason",
    [
        (socket.gaierror(-2, "Name or service not known"), FailureCategory.TEMPORARY_MQTT, "dns_failure"),
        (ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused"), FailureCategory.TEMPORARY_MQTT, "broker_unavailable"),
        (TimeoutError("Connection timed out"), FailureCategory.TEMPORARY_MQTT, "network_timeout"),
        (socket.timeout("timed out"), FailureCategory.TEMPORARY_MQTT, "network_timeout"),
        (OSError(errno.ENETUNREACH, "Network is unreachable"), FailureCategory.TEMPORARY_MQTT, "network_unreachable"),
        (OSError(errno.EHOSTUNREACH, "No route to host"), FailureCategory.TEMPORARY_MQTT, "network_unreachable"),
        (OSError(errno.ENETDOWN, "Network is down"), FailureCategory.TEMPORARY_MQTT, "network_unreachable"),
        (OSError(errno.EPIPE, "Broken pipe"), FailureCategory.TEMPORARY_MQTT, "network_error"),
        (ssl.SSLCertVerificationError(1, "certificate verify failed"), FailureCategory.PERMANENT_CONFIGURATION, "tls_certificate_failure"),
    ],
)
def test_classify_connection_exception(exception, expected_category, expected_reason) -> None:
    category, reason_str = classify_connection_exception(exception)
    assert category == expected_category
    assert reason_str == expected_reason


@pytest.mark.parametrize(
    "code,expected_category,expected_reason",
    [
        (1, FailureCategory.PERMANENT_CONFIGURATION, "protocol_rejected"),
        (2, FailureCategory.PERMANENT_CONFIGURATION, "client_id_rejected"),
        (3, FailureCategory.TEMPORARY_MQTT, "broker_unavailable"),
        (4, FailureCategory.PERMANENT_CONFIGURATION, "authentication_failure"),
        (5, FailureCategory.PERMANENT_CONFIGURATION, "authorization_failure"),
        (132, FailureCategory.PERMANENT_CONFIGURATION, "protocol_rejected"),
        (133, FailureCategory.PERMANENT_CONFIGURATION, "client_id_rejected"),
        (134, FailureCategory.PERMANENT_CONFIGURATION, "authentication_failure"),
        (135, FailureCategory.PERMANENT_CONFIGURATION, "authorization_failure"),
        (136, FailureCategory.TEMPORARY_MQTT, "broker_unavailable"),
    ],
)
def test_classify_connack_code(code, expected_category, expected_reason) -> None:
    category, reason_str = classify_connack_code(code)
    assert category == expected_category
    assert reason_str == expected_reason


@pytest.mark.parametrize(
    "exception,expected_reason",
    [
        (socket.gaierror("PRIVATE-DNS-HOST"), "dns_failure"),
        (ConnectionRefusedError("PRIVATE-REFUSED-TARGET"), "broker_unavailable"),
        (OSError(errno.ENETUNREACH, "PRIVATE-ROUTE-UNREACHABLE"), "network_unreachable"),
        (TimeoutError("PRIVATE-TIMEOUT-DETAIL"), "network_timeout"),
        (socket.timeout("PRIVATE-SOCKET-TIMEOUT"), "network_timeout"),
        (OSError(errno.ECONNRESET, "PRIVATE-RESET"), "network_error"),
    ],
)
def test_temporary_connection_failures_are_classified_and_hide_details(
    caplog, exception, expected_reason
) -> None:
    instance, client = receiver()
    client.connect.side_effect = exception
    waits: list[float] = []

    def controlled_wait(delay: float) -> bool:
        waits.append(delay)
        if len(waits) == 2:
            instance.shutdown.set()
            return True
        return False

    instance.shutdown.wait = controlled_wait
    with caplog.at_level(logging.WARNING):
        instance._supervise()

    # Reconnection attempts with exponential backoff occur without busy loop
    assert client.connect.call_count == 2
    assert waits == [0.001, 0.002]
    assert f'"reason": "{expected_reason}"' in caplog.text
    assert '"failure_category": "temporary_mqtt"' in caplog.text
    # Ensure sensitive exception details are not leaked to logs
    for arg in exception.args:
        if isinstance(arg, str) and "PRIVATE-" in arg:
            assert arg not in caplog.text


def test_permanent_authentication_failure_stops_supervisor_without_infinite_loop(caplog) -> None:
    instance, client = receiver()

    def simulate_connect(*_args, **_kwargs) -> int:
        instance._on_connect(client, None, Mock(), reason(4, failure=True), None)
        return mqtt.MQTT_ERR_SUCCESS

    client.connect.side_effect = simulate_connect
    with caplog.at_level(logging.ERROR):
        instance._supervise()

    assert instance.failed.is_set()
    assert instance.failure_category == FailureCategory.PERMANENT_CONFIGURATION
    assert instance.failure_reason == "authentication_failure"
    assert '"reason": "authentication_failure"' in caplog.text
    # Supervisor must halt immediately on permanent failure without retrying
    assert client.connect.call_count == 1


def test_permanent_authorization_failure_stops_supervisor_without_infinite_loop(caplog) -> None:
    instance, client = receiver()

    def simulate_connect(*_args, **_kwargs) -> int:
        instance._on_connect(client, None, Mock(), reason(5, failure=True), None)
        return mqtt.MQTT_ERR_SUCCESS

    client.connect.side_effect = simulate_connect
    with caplog.at_level(logging.ERROR):
        instance._supervise()

    assert instance.failed.is_set()
    assert instance.failure_category == FailureCategory.PERMANENT_CONFIGURATION
    assert instance.failure_reason == "authorization_failure"
    assert '"reason": "authorization_failure"' in caplog.text
    assert client.connect.call_count == 1


def test_tls_certificate_failure_stops_supervisor_and_hides_private_detail(caplog) -> None:
    instance, client = receiver()
    client.connect.side_effect = ssl.SSLCertVerificationError(1, "PRIVATE_KEY_CERT_DETAIL")

    with caplog.at_level(logging.ERROR):
        instance._supervise()

    assert instance.failed.is_set()
    assert instance.failure_category == FailureCategory.PERMANENT_CONFIGURATION
    assert instance.failure_reason == "tls_certificate_failure"
    assert client.connect.call_count == 1
    assert '"reason": "tls_certificate_failure"' in caplog.text
    assert "PRIVATE_KEY_CERT_DETAIL" not in caplog.text
