"""Criação única da conexão para ingestor, simulador e diagnósticos."""

import ssl
import paho.mqtt.client as mqtt
from .config import Settings


def tls_context(settings: Settings) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=settings.mqtt_ca_cert)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def create_client(settings: Settings, *, protocol=mqtt.MQTTv311) -> mqtt.Client:
    settings.validate()
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                         client_id=settings.mqtt_client_id, protocol=protocol,
                         reconnect_on_failure=True)
    if settings.mqtt_username:
        client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
    if settings.mqtt_tls_enabled:
        client.tls_set_context(tls_context(settings))
    # Não habilitar logging de protocolo: CONNECT pode conter identidades.
    return client
