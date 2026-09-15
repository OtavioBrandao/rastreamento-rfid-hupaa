"""Cliente MQTT resiliente que transforma mensagens em JSONL e PostgreSQL."""

from __future__ import annotations

import json
import logging
import signal
import time
from threading import Event, Thread, current_thread, main_thread
from typing import Any, Callable

import paho.mqtt.client as mqtt

from .config import Settings
from .connection import create_client
from .parsing import build_event
from .persistence import JsonlEventStore
from .repository import PersistenceError, PersistenceResult, RawReadingRepository
from .resilience import Backoff, BackoffPolicy, FailureCategory

LOGGER = logging.getLogger(__name__)
PERMANENT_CONNACK_CODES = frozenset({1, 2, 4, 5})


def _reason_value(reason_code: Any) -> int | None:
    value = getattr(reason_code, "value", reason_code)
    return value if isinstance(value, int) else None


def _log(level: int, event_type: str, **fields: Any) -> None:
    LOGGER.log(level, json.dumps({"event_type": event_type, **fields}, sort_keys=True))


class MqttReceiver:
    """Mantém uma sessão MQTT 3.1.1 persistente e recupera quedas transitórias."""

    def __init__(
        self,
        settings: Settings,
        store: JsonlEventStore,
        repository: RawReadingRepository,
        *,
        random_source: Callable[[], float] | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.repository = repository
        self.ready = Event()
        self.failed = Event()
        self.shutdown = Event()
        self.disconnected = Event()
        self.failure: str | None = None
        self.failure_category: FailureCategory | None = None
        self._worker: Thread | None = None
        self._ever_ready = False
        self._recovering = False
        self._recovery_started_at: float | None = None
        self._mqtt_attempt = 0
        policy = BackoffPolicy(
            settings.mqtt_reconnect_initial_delay,
            settings.mqtt_reconnect_max_delay,
            settings.mqtt_reconnect_multiplier,
            settings.mqtt_reconnect_jitter,
        )
        options = {} if random_source is None else {"random_source": random_source}
        self._mqtt_backoff = Backoff(policy, **options)
        self.client = create_client(settings, persistent_session=True)
        self.client.manual_ack_set(True)
        self.client.on_connect = self._on_connect
        self.client.on_connect_fail = self._on_connect_fail
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.on_subscribe = self._on_subscribe

    def _fail(
        self,
        stage: str,
        category: FailureCategory = FailureCategory.PERMANENT_CONFIGURATION,
    ) -> None:
        if self.failed.is_set():
            return
        self.failure = stage
        self.failure_category = category
        self.failed.set()
        self.ready.clear()
        _log(
            logging.ERROR,
            "ingestor_failed",
            stage=stage,
            failure_category=category,
        )
        self.client.disconnect()

    def _on_subscribe(self, _client, _userdata, _mid, reason_codes, _properties):
        if not reason_codes or any(
            code.is_failure or code.value != self.settings.mqtt_qos
            for code in reason_codes
        ):
            self._fail("assinatura recusada ou QoS 1 não concedido")
            return
        self.ready.set()
        elapsed = (
            round(time.monotonic() - self._recovery_started_at, 3)
            if self._recovery_started_at is not None
            else 0.0
        )
        _log(
            logging.INFO,
            "mqtt_recovered" if self._recovering else "mqtt_connected",
            attempt=self._mqtt_attempt,
            elapsed_seconds=elapsed,
        )
        _log(
            logging.INFO,
            "mqtt_subscription_restored",
            topic=self.settings.mqtt_topic,
            qos=self.settings.mqtt_qos,
        )
        self._ever_ready = True
        self._recovering = False
        self._recovery_started_at = None
        self._mqtt_backoff.reset()

    def _on_connect(
        self,
        client: mqtt.Client,
        _userdata: Any,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        code = _reason_value(reason_code)
        if reason_code.is_failure:
            if code in PERMANENT_CONNACK_CODES:
                self._fail("conexão MQTT recusada")
            else:
                self.disconnected.set()
                _log(
                    logging.WARNING,
                    "mqtt_disconnected",
                    failure_category=FailureCategory.TEMPORARY_MQTT,
                    reason_code=code,
                )
            return

        self.disconnected.clear()
        _log(
            logging.INFO,
            "mqtt_session_established",
            session_present=bool(getattr(flags, "session_present", False)),
        )
        # Reassinar é idempotente e restaura o filtro mesmo se o broker perdeu
        # seu estado; não dependemos apenas do sinal session_present.
        result, _message_id = client.subscribe(
            self.settings.mqtt_topic, qos=self.settings.mqtt_qos
        )
        if result != mqtt.MQTT_ERR_SUCCESS:
            self._fail("envio de assinatura")

    def _on_connect_fail(self, _client: mqtt.Client, _userdata: Any) -> None:
        _log(
            logging.WARNING,
            "mqtt_disconnected",
            failure_category=FailureCategory.TEMPORARY_MQTT,
            reason="broker_unreachable",
        )

    def _on_disconnect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        self.ready.clear()
        self.disconnected.set()
        if self.shutdown.is_set() or self.failed.is_set():
            return
        if self._recovery_started_at is None:
            self._recovery_started_at = time.monotonic()
        _log(
            logging.WARNING,
            "mqtt_disconnected",
            failure_category=FailureCategory.TEMPORARY_MQTT,
            reason_code=_reason_value(reason_code),
        )

    def _on_message(
        self,
        _userdata_client: mqtt.Client,
        _userdata: Any,
        message: mqtt.MQTTMessage,
    ) -> None:
        if self.failed.is_set() or self.shutdown.is_set():
            return
        try:
            event = build_event(
                topic=message.topic,
                qos=message.qos,
                retain=message.retain,
                payload=message.payload,
                settings=self.settings,
            )
            self.store.append(event)
        except Exception:
            self._fail("persistência JSONL")
            return
        try:
            canonical = event["canonical_event"]
            result = (
                self.repository.persist(event)
                if canonical
                else PersistenceResult("rejected", reason="invalid_input")
            )
            # A auditoria original precede o banco. Rejeições de topologia
            # recebem um registro complementar, sem repetir o payload.
            outcome = {
                "event_type": "rfid_persistence",
                "status": result.status,
                "reason": result.reason,
                "event_id": canonical["event_id"] if canonical else None,
                "received_at_utc": event["received_at_utc"],
            }
            if canonical and result.status == "rejected":
                try:
                    self.store.append(outcome)
                except Exception:
                    self._fail("persistência JSONL")
                    return
            LOGGER.log(
                logging.WARNING if result.status == "rejected" else logging.INFO,
                json.dumps(outcome),
            )
            LOGGER.log(
                logging.INFO if canonical else logging.WARNING,
                json.dumps(
                    {
                        "event_type": "rfid_normalization",
                        "reader_id": event["reader_id"],
                        "adapter": event["adapter"],
                        "result": "accepted" if canonical else "rejected",
                        "reasons": (
                            [event["parse_error"]] if event["parse_error"] else []
                        )
                        + event["validation_errors"],
                        "event_id": canonical["event_id"] if canonical else None,
                    }
                ),
            )
        except PersistenceError:
            self._fail("persistência PostgreSQL")
            return
        except Exception:
            self._fail("processamento de persistência")
            return
        if message.qos == 1:
            try:
                if self.client.ack(message.mid, message.qos) != mqtt.MQTT_ERR_SUCCESS:
                    self._fail("envio de ACK")
            except Exception:
                self._fail("envio de ACK")

    def _network_session(self) -> None:
        self._mqtt_attempt += 1
        _log(
            logging.INFO,
            "mqtt_reconnect_attempt",
            attempt=self._mqtt_attempt,
            failure_category=FailureCategory.TEMPORARY_MQTT,
        )
        try:
            result = self.client.connect(
                self.settings.mqtt_host,
                self.settings.mqtt_port,
                keepalive=self.settings.mqtt_keepalive,
            )
        except OSError:
            self._on_connect_fail(self.client, None)
            return
        if result != mqtt.MQTT_ERR_SUCCESS:
            self._on_connect_fail(self.client, None)
            return

        self.disconnected.clear()
        while not self.shutdown.is_set() and not self.failed.is_set():
            result = self.client.loop(timeout=0.2)
            if result != mqtt.MQTT_ERR_SUCCESS or self.disconnected.is_set():
                break

    def _supervise(self) -> None:
        try:
            while not self.shutdown.is_set() and not self.failed.is_set():
                self._network_session()
                if self.shutdown.is_set() or self.failed.is_set():
                    break
                self.ready.clear()
                self._recovering = True
                if self._recovery_started_at is None:
                    self._recovery_started_at = time.monotonic()
                delay = self._mqtt_backoff.next_delay()
                _log(
                    logging.WARNING,
                    "mqtt_reconnect_scheduled",
                    attempt=self._mqtt_backoff.attempt + 1,
                    delay_seconds=round(delay, 3),
                    failure_category=FailureCategory.TEMPORARY_MQTT,
                )
                if self.shutdown.wait(delay):
                    break
        finally:
            self.ready.clear()

    def _start_worker(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self.shutdown.clear()
        self._worker = Thread(
            target=self._supervise,
            name=f"mqtt-supervisor-{self.settings.mqtt_client_id}",
        )
        self._worker.start()

    def start(self, timeout: float = 10) -> None:
        self._start_worker()
        deadline = time.monotonic() + timeout
        while not self.ready.wait(0.05):
            if self.failed.is_set():
                self.stop()
                raise RuntimeError("Conexão/assinatura MQTT recusada")
            if time.monotonic() >= deadline:
                self.stop()
                raise RuntimeError("Conexão/assinatura MQTT não confirmada")

    def request_shutdown(self) -> None:
        if self.shutdown.is_set():
            return
        _log(
            logging.INFO,
            "shutdown_requested",
            failure_category=FailureCategory.SHUTDOWN,
        )
        self.shutdown.set()
        self.ready.clear()
        self.client.disconnect()

    def stop(self) -> None:
        self.request_shutdown()
        worker = self._worker
        if worker is not None and worker is not current_thread():
            worker.join()
        _log(logging.INFO, "shutdown_complete")

    def run(self) -> int:
        _log(
            logging.INFO,
            "ingestor_started",
            broker_host=self.settings.mqtt_host,
            broker_port=self.settings.mqtt_port,
            topic=self.settings.mqtt_topic,
            events_file=str(self.settings.events_file),
        )
        previous_sigterm = None
        if current_thread() is main_thread():
            previous_sigterm = signal.getsignal(signal.SIGTERM)
            signal.signal(
                signal.SIGTERM,
                lambda _signum, _frame: self.request_shutdown(),
            )
        try:
            self._start_worker()
            while not self.shutdown.wait(0.2):
                if self.failed.is_set():
                    return 1
            return 0 if not self.failed.is_set() else 1
        except KeyboardInterrupt:
            self.request_shutdown()
            return 0
        finally:
            self.stop()
            if previous_sigterm is not None:
                signal.signal(signal.SIGTERM, previous_sigterm)
