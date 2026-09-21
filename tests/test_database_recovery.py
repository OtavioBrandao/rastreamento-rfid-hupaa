from __future__ import annotations

import time
from threading import Thread
from unittest.mock import Mock, patch

from rfid_ingestion.config import Settings
from rfid_ingestion.mqtt_client import MqttReceiver
from rfid_ingestion.repository import PersistenceError
from rfid_ingestion.resilience import FailureCategory


def receiver(repository=None, **changes):
    values = {
        "db_retry_initial_delay": 0.001,
        "db_retry_max_delay": 0.002,
        "db_retry_jitter": 0,
        **changes,
    }
    with patch("rfid_ingestion.mqtt_client.create_client"):
        instance = MqttReceiver(
            Settings(**values),
            Mock(),
            repository or Mock(),
            random_source=lambda: 0.5,
        )
    instance.database_unavailable.set()
    instance._db_recovery_started_at = time.monotonic()
    return instance


def test_database_retries_then_recovers_and_resets_backoff() -> None:
    repository = Mock()
    repository.check_available.side_effect = [
        PersistenceError("private"),
        None,
    ]
    instance = receiver(repository)

    assert instance._recover_database()
    assert instance.database_unavailable.is_set()
    assert instance._recover_database()

    assert not instance.database_unavailable.is_set()
    assert repository.check_available.call_count == 2
    assert instance._db_backoff.attempt == 0


def test_permanent_database_failure_stops_recovery() -> None:
    repository = Mock()
    repository.check_available.side_effect = PersistenceError(
        "private",
        FailureCategory.PERMANENT_CONFIGURATION,
    )
    instance = receiver(repository)

    assert not instance._recover_database()
    assert instance.failed.is_set()
    assert instance.failure_category == FailureCategory.PERMANENT_CONFIGURATION


def test_shutdown_interrupts_database_backoff() -> None:
    instance = receiver(
        db_retry_initial_delay=60,
        db_retry_max_delay=60,
    )
    worker = Thread(target=instance._recover_database)
    worker.start()
    time.sleep(0.01)

    instance.request_shutdown()
    worker.join(timeout=1)

    assert not worker.is_alive()
    instance.repository.check_available.assert_not_called()
