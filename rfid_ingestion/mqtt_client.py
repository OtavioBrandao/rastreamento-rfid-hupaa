"""Cliente MQTT resiliente que transforma mensagens em JSONL e PostgreSQL."""

from __future__ import annotations

import json
import logging
import queue
import signal
import ssl
import time
from collections import deque
from datetime import datetime, timezone
from threading import Event, Lock, Thread, current_thread, main_thread
from typing import Any, Callable

import paho.mqtt.client as mqtt

from rfid_inference.debounce import (
    ConsolidatedObservation,
    DebounceProcessor,
    DebounceReading,
)

from .config import Settings
from .connection import create_client
from .parsing import build_event
from .persistence import JsonlEventStore
from .reader_status import ReaderMonitor, StatusPolicy, contacts, heartbeat_event
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
    """Extrai o código inteiro de um ReasonCode Paho; devolve None se não for numérico."""
    value = getattr(reason_code, "value", reason_code)
    return value if isinstance(value, int) else None


def _log(level: int, event_type: str, **fields: Any) -> None:
    """Registra evento estruturado de processamento no logger do módulo."""
    LOGGER.log(level, json.dumps({"event_type": event_type, **fields}, sort_keys=True))


class MqttReceiver:
    """Mantém uma sessão MQTT 3.1.1 persistente e recupera quedas transitórias."""

    # Leituras por transação. Com banco remoto, cada ida e volta custa mais que
    # gravar várias linhas; o lote evita que a fila cresça com o leitor ativo.
    BATCH_MAX = 200
    PROCESS_POLL_SECONDS = 0.2

    def __init__(
        self,
        settings: Settings,
        store: JsonlEventStore,
        repository: RawReadingRepository,
        *,
        random_source: Callable[[], float] | None = None,
        debouncer: DebounceProcessor | None = None,
        observation_handler: Callable[[ConsolidatedObservation], None] | None = None,
        observation_tick_handler: Callable[[float], None] | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
        reader_monitor: ReaderMonitor | None = None,
    ) -> None:
        """Inicializa MqttReceiver com as dependências e valores recebidos."""
        self.settings = settings
        self.store = store
        self.repository = repository
        self.reader_monitor = reader_monitor
        self.debouncer = debouncer or DebounceProcessor.from_milliseconds(
            settings.rfid_debounce_window_ms,
            settings.rfid_out_of_order_tolerance_ms,
        )
        self.observation_handler = observation_handler
        self.observation_tick_handler = observation_tick_handler
        self._monotonic_clock = monotonic_clock
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
        self._debounce_flushed = False
        # Rede e banco em threads separadas: o horário de recebimento (único
        # horário das leituras com contador) não pode esperar o banco remoto.
        self._fila: queue.Queue[tuple[int, mqtt.MQTTMessage, dict[str, Any], float]] = (
            queue.Queue()
        )
        self._sessao = 0
        self._processor: Thread | None = None
        # PUBACKs e desconexões pedidos por outras threads; a rede os executa.
        self._acks: queue.Queue[tuple[mqtt.MQTTMessage, int]] = queue.Queue()
        self._desconexao_pedida = Event()
        # Inferência (debounce, passagem, direção, zona) consulta o banco várias
        # vezes por passagem; em thread própria, não segura gravação nem ACK.
        self._fila_inferencia: queue.Queue[tuple[dict[str, Any], PersistenceResult, float]] = (
            queue.Queue()
        )
        self._inferencia: Thread | None = None
        # Chegadas ainda sem inferência, em ordem. O relógio da inferência não
        # passa da mais antiga: com a inferência atrasada pelo banco, o debounce
        # e o detector não tratam como silêncio leituras que já chegaram.
        self._em_transito: deque[float] = deque()
        self._transito_lock = Lock()
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
        """Marca falha terminal, limpa prontidão e solicita desconexão ao supervisor."""
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
        self._desconectar()

    def _pode_usar_socket(self) -> bool:
        """Só a thread de rede lê e escreve no socket.

        Com loop manual, o paho escreve no socket na própria thread de quem chama
        ``ack``/``disconnect``. Em TLS, leitura e escrita simultâneas de threads
        diferentes corrompem a sessão SSL e o broker derruba a conexão.
        """
        worker = self._worker
        return worker is None or not worker.is_alive() or current_thread() is worker

    def _desconectar(self) -> None:
        """Desconecta na thread de rede ou sinaliza a ela um pedido de desconexão."""
        if self._pode_usar_socket():
            self.client.disconnect()
        else:
            self._desconexao_pedida.set()

    def _on_subscribe(self, _client, _userdata, _mid, reason_codes, _properties):
        """Confirma prontidão somente após SUBACK com QoS 1 e reinicia o backoff MQTT."""
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
        """Classifica CONNACK e assina o tópico; recusa falhas permanentes de autenticação ou protocolo."""
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
        topics = ([(self.settings.mqtt_topic, self.settings.mqtt_qos),
                   (self.settings.mqtt_heartbeat_topic, self.settings.mqtt_qos)]
                  if self.settings.mqtt_heartbeat_topic else self.settings.mqtt_topic)
        result, _message_id = client.subscribe(topics, qos=self.settings.mqtt_qos)
        if result != mqtt.MQTT_ERR_SUCCESS:
            self._fail("envio de assinatura")

    def _on_connect_fail(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        *,
        reason: str = "broker_unavailable",
    ) -> None:
        """Registra falha transitória de conexão para recuperação pelo supervisor."""
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
        """Limpa prontidão e registra o início da recuperação de uma sessão interrompida."""
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
        """Monta e audita o envelope JSONL na recepção e o enfileira com o relógio monotônico.

        Não espera a gravação no PostgreSQL. O PUBACK fica a cargo da etapa de
        persistência; falha no JSONL encerra o receptor sem confirmar a mensagem."""
        if (
            self.failed.is_set()
            or self.shutdown.is_set()
            or self.database_unavailable.is_set()
        ):
            return
        try:
            if self.settings.mqtt_heartbeat_topic and mqtt.topic_matches_sub(
                    self.settings.mqtt_heartbeat_topic, message.topic):
                event = heartbeat_event(message.topic, message.payload, message.retain,
                                        self.reader_monitor.policy if self.reader_monitor else
                                        StatusPolicy.from_env())
            else:
                event = build_event(
                    topic=message.topic, qos=message.qos, retain=message.retain,
                    payload=message.payload, settings=self.settings,
                )
            self.store.append(event)
        except Exception:
            self._fail("persistência JSONL")
            return
        # O horário de recebimento já está no evento; banco, debounce e ACK
        # ficam para o processador, que grava em lote.
        chegada = self._monotonic_clock()
        with self._transito_lock:
            self._em_transito.append(chegada)
        self._fila.put((self._sessao, message, event, chegada))

    def relogio_inferencia(self) -> float:
        """Agora, para a inferência: nunca além da leitura mais antiga pendente."""
        with self._transito_lock:
            if self._em_transito:
                return self._em_transito[0]
        return self._monotonic_clock()

    def _concluir(self, chegada: float) -> None:
        """Retira a chegada concluída da lista que limita o relógio da inferência."""
        with self._transito_lock:
            try:
                self._em_transito.remove(chegada)
            except ValueError:
                pass

    def _flush_pending(self, primeiro=None) -> None:
        """Grava o lote numa transação e só então processa e confirma cada mensagem.

        Nenhum PUBACK é enviado antes do commit; numa falha temporária do banco o
        lote inteiro fica sem ACK e o broker o reentrega na sessão persistente.
        Mensagens de uma sessão MQTT anterior são descartadas sem ACK: o broker
        as reentrega e o ``event_id`` evita efeito duplicado.
        """
        itens = [] if primeiro is None else [primeiro]
        while len(itens) < self.BATCH_MAX:
            try:
                itens.append(self._fila.get_nowait())
            except queue.Empty:
                break
        if self.failed.is_set() or self.database_unavailable.is_set():
            for _sessao, _message, _event, chegada in itens:
                self._concluir(chegada)
            return
        pendentes = []
        for sessao, message, event, chegada in itens:
            if sessao == self._sessao:
                pendentes.append((message, event, chegada))
            else:
                self._concluir(chegada)
        if not pendentes:
            return
        sessao = self._sessao
        envelopes = [event for _message, event, _chegada in pendentes]
        try:
            readings = [event for event in envelopes if event.get("event_type") != "reader_heartbeat"]
            # Na classe: repositórios de teste (Mock) não têm persist_many real.
            em_lote = hasattr(type(self.repository), "persist_many")
            resultados = (
                (self.repository.persist_many(readings) if readings else [])
                if em_lote
                else [
                    self.repository.persist(event)
                    if event["canonical_event"]
                    else PersistenceResult("rejected", reason="invalid_input")
                    for event in readings
                ]
            )
            reading_results = iter(resultados)
            resultados = [PersistenceResult("inserted" if event.get("heartbeat") else "rejected",
                                            reason=event.get("reason"))
                          if event.get("event_type") == "reader_heartbeat" else next(reading_results)
                          for event in envelopes]
            if self.reader_monitor is not None:
                self.reader_monitor.observe(contacts(envelopes))
        except PersistenceError as error:
            self._falha_banco(error)
            for _message, _event, chegada in pendentes:
                self._concluir(chegada)
            return
        lote = list(zip(pendentes, resultados, strict=True))
        # Auditoria completa antes de qualquer ACK: rejeições de topologia
        # recebem um registro complementar, sem repetir o payload.
        for (_message, event, _chegada), result in lote:
            if event["canonical_event"] and result.status == "rejected":
                try:
                    self.store.append(self._resultado(event, result))
                except Exception:
                    self._fail("persistência JSONL")
                    return
        # ACK logo após o commit: a leitura gravada é o que a entrega exige. A
        # inferência abaixo consulta o banco e, se viesse antes, seguraria a
        # janela de QoS 1 do broker e atrasaria o horário das próximas leituras.
        for (message, _event, _chegada), _result in lote:
            self._ack(message, sessao)
        for (_message, event, chegada), result in lote:
            if event.get("event_type") == "reader_heartbeat":
                _log(logging.INFO if event.get("heartbeat") else logging.WARNING,
                     "reader_heartbeat_processed", status=result.status, reason=result.reason)
                self._concluir(chegada)
            elif self._inferencia is not None:
                self._fila_inferencia.put((event, result, chegada))
            else:
                self._registrar_resultado(event, result, chegada)

    def _falha_banco(self, error: PersistenceError) -> None:
        """Suspende ACK e solicita recuperação também quando o monitor perde o banco."""
        if error.category == FailureCategory.TEMPORARY_DATABASE:
            self.ready.clear()
            self.database_unavailable.set()
            self._recovering = True
            self._db_recovery_started_at = time.monotonic()
            _log(logging.ERROR, "database_unavailable", failure_category=error.category)
            self._desconectar()
        else:
            self._fail("persistência PostgreSQL", FailureCategory.PERMANENT_CONFIGURATION)

    @staticmethod
    def _resultado(event: dict[str, Any], result: PersistenceResult) -> dict[str, Any]:
        """Monta o resumo de persistência com status, motivo, event_id e instante de recepção."""
        canonical = event["canonical_event"]
        return {
            "event_type": "rfid_persistence",
            "status": result.status,
            "reason": result.reason,
            "event_id": canonical["event_id"] if canonical else None,
            "received_at_utc": event["received_at_utc"],
        }

    def _registrar_resultado(
        self, event: dict[str, Any], result: PersistenceResult, chegada: float
    ) -> None:
        """Registra normalização/persistência e encaminha leituras inseridas ao debounce."""
        canonical = event["canonical_event"]
        outcome = self._resultado(event, result)
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
        try:
            if canonical:
                self._process_debounce(canonical, result, chegada)
        finally:
            self._concluir(chegada)

    def _ack(self, message: mqtt.MQTTMessage, sessao: int) -> None:
        """Encaminha PUBACK QoS 1 à thread de rede depois da decisão de persistência."""
        if message.qos != 1:
            return
        if self._pode_usar_socket():
            self._enviar_ack(message, sessao)
        else:
            self._acks.put((message, sessao))

    def _enviar_acks(self) -> None:
        """Drena os pedidos de PUBACK na thread que possui o socket MQTT."""
        while True:
            try:
                message, sessao = self._acks.get_nowait()
            except queue.Empty:
                return
            self._enviar_ack(message, sessao)

    def _enviar_ack(self, message: mqtt.MQTTMessage, sessao: int) -> None:
        """Envia PUBACK somente para a sessão corrente e trata perda de conexão."""
        if sessao != self._sessao or self.disconnected.is_set():
            # A conexão caiu entre a leitura e o commit: o broker reentrega e a
            # leitura volta como duplicata, sem novo efeito no debounce. O mid
            # não vale numa conexão nova.
            _log(logging.WARNING, "mqtt_ack_skipped_disconnected", mid=message.mid)
            return
        try:
            resultado = self.client.ack(message.mid, message.qos)
        except Exception:
            self._fail("envio de ACK")
            return
        if resultado in (mqtt.MQTT_ERR_NO_CONN, mqtt.MQTT_ERR_CONN_LOST):
            # Queda de conexão é temporária: o loop reconecta e o broker reentrega.
            _log(logging.WARNING, "mqtt_ack_skipped_disconnected", mid=message.mid)
        elif resultado != mqtt.MQTT_ERR_SUCCESS:
            self._fail("envio de ACK")

    def _process_debounce(
        self,
        canonical: dict[str, Any],
        result: PersistenceResult,
        received_at_monotonic: float | None = None,
    ) -> None:
        """Converte leitura inserida em DebounceReading; duplicatas e rejeições não alimentam a inferência."""
        if result.status == "duplicate":
            _log(
                logging.INFO,
                "rfid_debounce_duplicate_ignored",
                event_id=canonical["event_id"],
            )
            return
        if result.status != "inserted":
            return
        if result.reading_id is None or result.antenna_id is None:
            # Compatibilidade com repositórios injetados por consumidores
            # anteriores à ISS-014. O repositório de produção sempre fornece
            # as duas identidades para resultados inserted.
            return
        try:
            observed_at = datetime.fromisoformat(
                canonical["timestamp"].replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            debounce_result = self.debouncer.add(
                DebounceReading(
                    event_id=canonical["event_id"],
                    reading_id=result.reading_id,
                    epc=canonical["epc"],
                    antenna_id=result.antenna_id,
                    observed_at=observed_at,
                    rssi=canonical["rssi"],
                ),
                received_at_monotonic=(
                    self._monotonic_clock()
                    if received_at_monotonic is None
                    else received_at_monotonic
                ),
            )
        except Exception:
            _log(
                logging.ERROR,
                "rfid_debounce_failed",
                event_id=canonical.get("event_id"),
                reason="invalid_internal_reading",
            )
            return

        counters = self.debouncer.counters
        _log(
            logging.WARNING if debounce_result.late else logging.INFO,
            "rfid_debounce_late_event" if debounce_result.late else "rfid_debounce_reading",
            event_id=canonical["event_id"],
            antenna_id=result.antenna_id,
            accepted=debounce_result.accepted,
            incorporated=debounce_result.incorporated,
            readings_received=counters.readings_received,
            readings_incorporated=counters.readings_incorporated,
            observations_finalized=counters.observations_finalized,
            late_events=counters.late_events,
        )
        self._emit_observations(debounce_result.finalized)

    def _emit_observations(
        self, observations: tuple[ConsolidatedObservation, ...]
    ) -> None:
        """Registra observações consolidadas e invoca o handler de passagem, isolando falhas."""
        for observation in observations:
            _log(
                logging.INFO,
                "rfid_debounce_observation",
                epc=observation.epc,
                antenna_id=observation.antenna_id,
                first_seen_at=observation.first_seen_at.isoformat(),
                last_seen_at=observation.last_seen_at.isoformat(),
                reading_count=observation.reading_count,
                first_reading_id=observation.first_reading_id,
                last_reading_id=observation.last_reading_id,
                rssi_min=observation.rssi_min,
                rssi_max=observation.rssi_max,
                rssi_mean=observation.rssi_mean,
            )
            if self.observation_handler is not None:
                try:
                    self.observation_handler(observation)
                except Exception:
                    _log(
                        logging.ERROR,
                        "rfid_observation_handler_failed",
                        antenna_id=observation.antenna_id,
                        first_reading_id=observation.first_reading_id,
                        last_reading_id=observation.last_reading_id,
                    )

    def flush_debounce(self) -> tuple[ConsolidatedObservation, ...]:
        """Finaliza e emite observações pendentes uma única vez durante o encerramento."""
        if self._debounce_flushed:
            return ()
        observations = self.debouncer.flush()
        self._emit_observations(observations)
        self._debounce_flushed = True
        counters = self.debouncer.counters
        _log(
            logging.INFO,
            "rfid_debounce_flushed",
            observations_flushed=len(observations),
            readings_received=counters.readings_received,
            readings_incorporated=counters.readings_incorporated,
            observations_finalized=counters.observations_finalized,
            late_events=counters.late_events,
        )
        return observations

    def _poll_debounce(self) -> None:
        """Finaliza janelas de debounce com o relógio limitado pela leitura ainda pendente."""
        try:
            observations = self.debouncer.advance_time(self.relogio_inferencia())
        except Exception:
            _log(
                logging.ERROR,
                "rfid_debounce_failed",
                reason="automatic_finalization_failed",
            )
            return
        if observations:
            self._emit_observations(observations)
            counters = self.debouncer.counters
            _log(
                logging.INFO,
                "rfid_debounce_automatic_finalization",
                finalized_in_poll=len(observations),
                readings_received=counters.readings_received,
                readings_incorporated=counters.readings_incorporated,
                observations_finalized=counters.observations_finalized,
                late_events=counters.late_events,
            )

    def _processar_uma_vez(self, primeiro=None) -> None:
        """Processa pendências e avança debounce e serviços de inferência no mesmo relógio."""
        self._flush_pending(primeiro)
        self._poll_debounce()
        if self.observation_tick_handler is not None:
            try:
                self.observation_tick_handler(self.relogio_inferencia())
            except Exception:
                _log(logging.ERROR, "rfid_observation_tick_failed")

    def _processar(self) -> None:
        """Thread de gravação: lotes e ACK, sem bloquear a rede nem esperar a inferência."""
        while not self.shutdown.is_set() and not self.failed.is_set():
            if self.reader_monitor is not None and not self.database_unavailable.is_set():
                try:
                    self.reader_monitor.sweep()
                except PersistenceError as error:
                    self._falha_banco(error)
            try:
                primeiro = self._fila.get(timeout=self.PROCESS_POLL_SECONDS)
            except queue.Empty:
                continue
            self._flush_pending(primeiro)

    def _inferir(self) -> None:
        """Thread de inferência: debounce e serviços na ordem de chegada.

        Ao encerrar, consome o que a gravação já confirmou antes de sair.
        """
        while True:
            parar = self.shutdown.is_set() or self.failed.is_set()
            gravacao_ativa = self._processor is not None and self._processor.is_alive()
            try:
                itens = [self._fila_inferencia.get(timeout=self.PROCESS_POLL_SECONDS)]
            except queue.Empty:
                itens = []
            while True:
                try:
                    itens.append(self._fila_inferencia.get_nowait())
                except queue.Empty:
                    break
            # Todas as leituras já chegadas entram no debounce antes da
            # finalização por tempo, para não partir observações.
            for event, result, chegada in itens:
                self._registrar_resultado(event, result, chegada)
            self._poll_debounce()
            if self.observation_tick_handler is not None:
                try:
                    self.observation_tick_handler(self.relogio_inferencia())
                except Exception:
                    _log(logging.ERROR, "rfid_observation_tick_failed")
            if parar and not gravacao_ativa and not itens:
                return

    def _network_session(self) -> None:
        """Executa uma tentativa de sessão MQTT e trata TLS, reconexão, ACKs e desligamento."""
        self._sessao += 1
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
        # Com as threads, o loop volta logo para enviar os PUBACKs da gravação.
        espera = 0.2 if self._processor is None else 0.05
        while not self.shutdown.is_set() and not self.failed.is_set():
            result = self.client.loop(timeout=espera)
            if self._processor is None:
                # Uso direto do loop, sem as threads de gravação e inferência.
                self._processar_uma_vez()
            else:
                self._enviar_acks()
            if self._desconexao_pedida.is_set():
                self._desconexao_pedida.clear()
                self.client.disconnect()
            if (
                result != mqtt.MQTT_ERR_SUCCESS
                or self.disconnected.is_set()
                or self.database_unavailable.is_set()
            ):
                break
        if self._desconexao_pedida.is_set():
            self._desconexao_pedida.clear()
            self.client.disconnect()

    def _recover_database(self) -> bool:
        """Aplica backoff, sonda PostgreSQL e libera consumo quando o banco volta a responder."""
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
        """Alterna sessões MQTT e recuperação de banco até falha permanente ou solicitação de parada."""
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
        """Inicia threads de persistência, inferência e supervisão uma única vez."""
        if self._worker is not None and self._worker.is_alive():
            return
        self.shutdown.clear()
        self._processor = Thread(
            target=self._processar,
            name=f"rfid-processor-{self.settings.mqtt_client_id}",
        )
        self._inferencia = Thread(
            target=self._inferir,
            name=f"rfid-inference-{self.settings.mqtt_client_id}",
        )
        self._processor.start()
        self._inferencia.start()
        self._worker = Thread(
            target=self._supervise,
            name=f"mqtt-supervisor-{self.settings.mqtt_client_id}",
        )
        self._worker.start()

    def start(self, timeout: float = 10) -> None:
        """Inicia as threads e aguarda SUBACK até o timeout; falha ou prazo encerram o receptor."""
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
        """Sinaliza encerramento cooperativo e solicita desconexão sem bloquear a thread chamadora."""
        if self.shutdown.is_set():
            return
        _log(
            logging.INFO,
            "shutdown_requested",
            failure_category=FailureCategory.SHUTDOWN,
        )
        self.shutdown.set()
        self.ready.clear()
        self._desconectar()

    def stop(self) -> None:
        """Solicita parada, aguarda workers e finaliza o debounce pendente."""
        self.request_shutdown()
        for thread in (self._worker, self._processor, self._inferencia):
            if thread is not None and thread is not current_thread():
                thread.join()
        self.flush_debounce()
        if not self._shutdown_complete_logged:
            _log(logging.INFO, "shutdown_complete")
            self._shutdown_complete_logged = True

    def run(self) -> int:
        """Executa o receptor até Ctrl+C/SIGTERM e devolve código 0 para parada ou 1 para falha."""
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
