"""Cliente MQTT resiliente que transforma mensagens em JSONL e PostgreSQL."""

from __future__ import annotations

import json
import logging
import signal
import ssl
import time
from threading import Event, Thread, current_thread, main_thread
from typing import Any, Callable

import paho.mqtt.client as mqtt

from .config import Settings
from .connection import create_client
from .parsing import build_event
from .persistence import JsonlEventStore
from .repository import PersistenceError, PersistenceResult, RawReadingRepository
from .resilience import (
    Backoff,
    BackoffPolicy,
    FailureCategory,
    classify_connack_code,
    classify_connection_exception,
)

LOGGER = logging.getLogger(__name__)


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
        self.database_unavailable = Event()
        self.failure: str | None = None
        self.failure_category: FailureCategory | None = None
        self.failure_reason: str | None = None
        self._worker: Thread | None = None
        self._shutdown_complete_logged = False
        self._ever_ready = False
        self._recovering = False
        self._recovery_started_at: float | None = None
        self._mqtt_attempt = 0
        mqtt_policy = BackoffPolicy(
            settings.mqtt_reconnect_initial_delay,
            settings.mqtt_reconnect_max_delay,
            settings.mqtt_reconnect_multiplier,
            settings.mqtt_reconnect_jitter,
        )
        db_policy = BackoffPolicy(
            settings.db_retry_initial_delay,
            settings.db_retry_max_delay,
            settings.db_retry_multiplier,
            settings.db_retry_jitter,
        )
        options = {} if random_source is None else {"random_source": random_source}
        self._mqtt_backoff = Backoff(mqtt_policy, **options)
        self._db_backoff = Backoff(db_policy, **options)
        self._db_recovery_started_at: float | None = None
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
        *,
        reason: str | None = None,
    ) -> None:
        if self.failed.is_set():
            return
        self.failure = stage
        self.failure_category = category
        self.failure_reason = reason
        self.failed.set()
        self.ready.clear()
        fields: dict[str, Any] = {
            "stage": stage,
            "failure_category": category,
        }
        if reason is not None:
            fields["reason"] = reason
        _log(
            logging.ERROR,
            "ingestor_failed",
            **fields,
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
            category, reason_str = classify_connack_code(code)
            if category == FailureCategory.PERMANENT_CONFIGURATION:
                stage = {
                    "authentication_failure": "autenticação MQTT recusada",
                    "authorization_failure": "autorização MQTT recusada",
                    "client_id_rejected": "identificador do cliente MQTT recusado",
                    "protocol_rejected": "versão do protocolo MQTT recusada",
                }.get(reason_str, "conexão MQTT recusada")
                self._fail(stage, category, reason=reason_str)
            else:
                self.disconnected.set()
                _log(
                    logging.WARNING,
                    "mqtt_disconnected",
                    failure_category=category,
                    reason=reason_str,
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

    def _on_connect_fail(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        *,
        reason: str = "broker_unavailable",
    ) -> None:
        _log(
            logging.WARNING,
            "mqtt_disconnected",
            failure_category=FailureCategory.TEMPORARY_MQTT,
            reason=reason,
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
        if (
            self.shutdown.is_set()
            or self.failed.is_set()
            or self.database_unavailable.is_set()
        ):
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
        if (
            self.failed.is_set()
            or self.shutdown.is_set()
            or self.database_unavailable.is_set()
        ):
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
        except PersistenceError as error:
            if error.category == FailureCategory.TEMPORARY_DATABASE:
                self.ready.clear()
                self.database_unavailable.set()
                self._recovering = True
                self._db_recovery_started_at = time.monotonic()
                _log(
                    logging.ERROR,
                    "database_unavailable",
                    failure_category=FailureCategory.TEMPORARY_DATABASE,
                )
                # Sem PUBACK. A sessão persistente mantém o trabalho pendente
                # no broker enquanto a aplicação espera o banco voltar.
                self.client.disconnect()
            else:
                self._fail(
                    "persistência PostgreSQL",
                    FailureCategory.PERMANENT_CONFIGURATION,
                )
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
        except ssl.SSLCertVerificationError:
            self._fail(
                "validação do certificado MQTT",
                FailureCategory.PERMANENT_CONFIGURATION,
                reason="tls_certificate_failure",
            )
            return
        except OSError as exc:
            category, reason_str = classify_connection_exception(exc)
            if category == FailureCategory.PERMANENT_CONFIGURATION:
                self._fail(
                    "validação do certificado MQTT",
                    category,
                    reason=reason_str,
                )
            else:
                self._on_connect_fail(self.client, None, reason=reason_str)
            return
        except ValueError:
            self._fail(
                "configuração da conexão MQTT",
                FailureCategory.PERMANENT_CONFIGURATION,
                reason="configuration_error",
            )
            return
        if result != mqtt.MQTT_ERR_SUCCESS:
            if result == mqtt.MQTT_ERR_TLS:
                self._fail(
                    "validação do certificado MQTT",
                    FailureCategory.PERMANENT_CONFIGURATION,
                    reason="tls_certificate_failure",
                )
            elif result in {mqtt.MQTT_ERR_AUTH, mqtt.MQTT_ERR_ACL_DENIED}:
                self._fail(
                    "autenticação MQTT recusada",
                    FailureCategory.PERMANENT_CONFIGURATION,
                    reason="authentication_failure",
                )
            else:
                self._on_connect_fail(self.client, None, reason="broker_unavailable")
            return

        self.disconnected.clear()
        while not self.shutdown.is_set() and not self.failed.is_set():
            result = self.client.loop(timeout=0.2)
            if (
                result != mqtt.MQTT_ERR_SUCCESS
                or self.disconnected.is_set()
                or self.database_unavailable.is_set()
            ):
                break

    def _recover_database(self) -> bool:
        delay = self._db_backoff.next_delay()
        _log(
            logging.WARNING,
            "database_retry_scheduled",
            attempt=self._db_backoff.attempt,
            delay_seconds=round(delay, 3),
            failure_category=FailureCategory.TEMPORARY_DATABASE,
        )
        if self.shutdown.wait(delay):
            return False
        _log(
            logging.INFO,
            "database_retry_attempt",
            attempt=self._db_backoff.attempt,
            failure_category=FailureCategory.TEMPORARY_DATABASE,
        )
        try:
            self.repository.check_available()
        except PersistenceError as error:
            if error.category == FailureCategory.PERMANENT_CONFIGURATION:
                self._fail(
                    "recuperação PostgreSQL",
                    FailureCategory.PERMANENT_CONFIGURATION,
                )
                return False
            return True

        elapsed = (
            round(time.monotonic() - self._db_recovery_started_at, 3)
            if self._db_recovery_started_at is not None
            else 0.0
        )
        successful_attempt = self._db_backoff.attempt
        self.database_unavailable.clear()
        self._db_recovery_started_at = None
        self._db_backoff.reset()
        _log(
            logging.INFO,
            "database_recovered",
            attempt=successful_attempt,
            elapsed_seconds=elapsed,
        )
        return True

    def _supervise(self) -> None:
        try:
            while not self.shutdown.is_set() and not self.failed.is_set():
                if self.database_unavailable.is_set():
                    if not self._recover_database():
                        break
                    continue
                self._network_session()
                if self.shutdown.is_set() or self.failed.is_set():
                    break
                if self.database_unavailable.is_set():
                    continue
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
        if not self._shutdown_complete_logged:
            _log(logging.INFO, "shutdown_complete")
            self._shutdown_complete_logged = True

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
