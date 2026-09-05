"""Cliente MQTT que transforma mensagens recebidas em eventos JSONL."""

from __future__ import annotations

import logging
import time
from typing import Any
from threading import Event

import paho.mqtt.client as mqtt

from .config import Settings
from .connection import create_client
from .parsing import build_event
from .persistence import JsonlEventStore


LOGGER = logging.getLogger(__name__)


class MqttReceiver:
    """Mantém a assinatura MQTT e persiste cada mensagem recebida."""

    def __init__(self, settings: Settings, store: JsonlEventStore) -> None:
        self.settings = settings
        self.store = store
        self.ready = Event()
        self.failed = Event()
        self.failure: str | None = None
        self.client = create_client(settings)
        self.client.on_connect = self._on_connect
        self.client.on_connect_fail = self._on_connect_fail
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.on_subscribe = self._on_subscribe
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)

    def _fail(self, stage: str) -> None:
        self.failure = stage
        self.failed.set()
        self.ready.clear()
        LOGGER.error("Falha MQTT: %s", stage)
        self.client.disconnect()

    def _on_subscribe(self, _client, _userdata, _mid, reason_codes, _properties):
        if not reason_codes or any(code.is_failure or code.value != 1 for code in reason_codes):
            self._fail("assinatura recusada ou QoS 1 não concedido")
            return
        self.ready.set()
        LOGGER.info("Assinatura ativa: tópico=%s qos=1 client_id=%s",
                    self.settings.mqtt_topic, self.settings.mqtt_client_id)

    def _on_connect(
        self,
        client: mqtt.Client,
        _userdata: Any,
        _flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        if reason_code.is_failure:
            self._fail("conexão recusada")
            return

        LOGGER.info(
            "Conectado ao broker MQTT em %s:%d",
            self.settings.mqtt_host,
            self.settings.mqtt_port,
        )
        result, _message_id = client.subscribe(
            self.settings.mqtt_topic, qos=self.settings.mqtt_qos
        )
        if result != mqtt.MQTT_ERR_SUCCESS:
            self._fail("envio de assinatura")
            return

    def _on_connect_fail(
        self, _client: mqtt.Client, _userdata: Any
    ) -> None:
        LOGGER.warning(
            "Não foi possível alcançar o broker; nova tentativa será feita"
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
        if reason_code.is_failure:
            LOGGER.warning(
                "Conexão MQTT perdida (%s); aguardando reconexão", reason_code
            )
        else:
            LOGGER.info("Conexão MQTT encerrada")

    def _on_message(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        message: mqtt.MQTTMessage,
    ) -> None:
        try:
            event = build_event(
                topic=message.topic,
                qos=message.qos,
                retain=message.retain,
                payload=message.payload,
            )
            self.store.append(event)
            if event["parse_error"] is None:
                LOGGER.info(
                    "Mensagem persistida: tópico=%s qos=%d retain=%s",
                    message.topic,
                    message.qos,
                    message.retain,
                )
            else:
                LOGGER.warning(
                    "Mensagem persistida com erro de parsing: tópico=%s erro=%s",
                    message.topic,
                    event["parse_error"],
                )
        except Exception:
            self._fail("persistência JSONL")

    def start(self, timeout: float = 10) -> None:
        self.client.connect(self.settings.mqtt_host, self.settings.mqtt_port,
                            keepalive=self.settings.mqtt_keepalive)
        self.client.loop_start()
        deadline = time.monotonic() + timeout
        while not self.ready.wait(0.05):
            if self.failed.is_set() or time.monotonic() >= deadline:
                self.stop()
                raise RuntimeError("Conexão/assinatura MQTT não confirmada")

    def stop(self) -> None:
        self.client.disconnect()
        self.client.loop_stop()

    def run(self) -> int:
        LOGGER.info(
            "Iniciando receptor: broker=%s:%d tópico=%s arquivo=%s",
            self.settings.mqtt_host,
            self.settings.mqtt_port,
            self.settings.mqtt_topic,
            self.settings.events_file,
        ) 
        try:
            self.start()
            self.failed.wait()
            return 1
        except (OSError, ValueError, RuntimeError):
            LOGGER.error("Falha de conexão/assinatura MQTT; verifique rede, TLS e permissões")
            return 1
        except KeyboardInterrupt:
            LOGGER.info("Interrupção recebida; encerrando o receptor")
            return 0
        finally:
            self.stop()
