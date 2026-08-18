"""Cliente MQTT que transforma mensagens recebidas em eventos JSONL."""

from __future__ import annotations

import logging
from typing import Any

import paho.mqtt.client as mqtt

from .config import Settings
from .parsing import build_event
from .persistence import JsonlEventStore


LOGGER = logging.getLogger(__name__)


class MqttReceiver:
    """Mantém a assinatura MQTT e persiste cada mensagem recebida."""

    def __init__(self, settings: Settings, store: JsonlEventStore) -> None:
        self.settings = settings
        self.store = store
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=settings.mqtt_client_id,
            protocol=mqtt.MQTTv311,
            reconnect_on_failure=True,
        )
        self.client.on_connect = self._on_connect
        self.client.on_connect_fail = self._on_connect_fail
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client.enable_logger(logging.getLogger("paho.mqtt"))

        if settings.mqtt_username is not None:
            self.client.username_pw_set(
                settings.mqtt_username, settings.mqtt_password
            )

    def _on_connect(
        self,
        client: mqtt.Client,
        _userdata: Any,
        _flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        if reason_code.is_failure:
            LOGGER.error("Conexão MQTT recusada: %s", reason_code)
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
            LOGGER.error(
                "Falha ao assinar o tópico %s: código %s",
                self.settings.mqtt_topic,
                result,
            )
            return
        LOGGER.info(
            "Assinatura ativa: tópico=%s qos=%d",
            self.settings.mqtt_topic,
            self.settings.mqtt_qos,
        )

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
            LOGGER.exception(
                "Falha ao persistir mensagem do tópico %s; receptor continuará ativo",
                message.topic,
            )

    def run(self) -> None:
        LOGGER.info(
            "Iniciando receptor: broker=%s:%d tópico=%s arquivo=%s",
            self.settings.mqtt_host,
            self.settings.mqtt_port,
            self.settings.mqtt_topic,
            self.settings.events_file,
        )
        self.client.connect_async(
            self.settings.mqtt_host,
            self.settings.mqtt_port,
            keepalive=60,
        )
        try:
            self.client.loop_forever(retry_first_connection=True)
        except KeyboardInterrupt:
            LOGGER.info("Interrupção recebida; encerrando o receptor")
        finally:
            self.client.disconnect()
