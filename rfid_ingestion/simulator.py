"""Publicador sintético nos formatos EZ700 e simulator, com transporte único."""

from __future__ import annotations

import argparse
import json
import logging
import os
import math
from datetime import datetime, timezone
from threading import Event
import time
from typing import Any, Sequence

import paho.mqtt.client as mqtt

from .config import Settings
from .connection import create_client
from .topics import reading_topic, validate_topic
from .logging_config import configure_logging


LOGGER = logging.getLogger(__name__)
SAMPLE_EPC = "E2801190A502006016C32F62"
SAMPLE_TID = "E280119020004F62B6190300"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publica eventos RFID simulados em um broker MQTT."
    )
    parser.add_argument("--host", default=os.getenv("MQTT_HOST"))
    parser.add_argument(
        "--port", type=int, default=None
    )
    parser.add_argument("--topic", default=os.getenv("MQTT_TOPIC"), help="Tópico de publicação")
    parser.add_argument("--reader-id", default="reader-01")
    parser.add_argument("--environment", default="dev")
    parser.add_argument("--site-id", default="hupaa")
    parser.add_argument("--portal-id", default="portal-01")
    parser.add_argument("--timestamp", help="Timestamp fixo para reprodução determinística")
    parser.add_argument("--format", choices=("ez700", "simulator"), default="ez700")
    parser.add_argument("--invalid", choices=("json", "missing"))
    parser.add_argument("--antenna", type=int, default=1)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--epc", default=SAMPLE_EPC)
    parser.add_argument(
        "--client-id",
        default=os.getenv("MQTT_CLIENT_ID"),
    )
    return parser


def _payload(args: argparse.Namespace) -> dict[str, Any]:
    timestamp = args.timestamp or datetime.now(timezone.utc).isoformat()
    if args.format == "simulator":
        return {"tag": args.epc, "port": args.antenna, "observed_at": timestamp,
                "signal": {"value": -38.8, "unit": "dBm"}, "reader_id": args.reader_id}
    return {
        "epc": args.epc,
        "tid": SAMPLE_TID,
        "timestamp": timestamp,
        "rssi": -3880,
        "phase": 49,
        "channel": 906250,
        "antenna": args.antenna,
        "readerid": args.reader_id,
    }


def _validate(args: argparse.Namespace, parser: argparse.ArgumentParser) -> str:
    try:
        topic = args.topic or reading_topic(args.reader_id, args.environment, args.site_id, args.portal_id)
        validate_topic(topic)
        if topic.split("/")[4] != args.reader_id:
            parser.error("--reader-id deve corresponder ao leitor do tópico")
    except ValueError:
        parser.error("Tópico de publicação inválido")
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error("--port deve estar entre 1 e 65535")
    if not args.reader_id or "\x00" in args.reader_id:
        parser.error("--reader-id inválido")
    if not topic or "\x00" in topic or "+" in topic or "#" in topic:
        parser.error("--topic deve ser um tópico de publicação sem curingas")
    if args.antenna < 1:
        parser.error("--antenna deve ser maior que zero")
    if args.count < 1:
        parser.error("--count deve ser maior que zero")
    if not math.isfinite(args.interval) or args.interval < 0:
        parser.error("--interval não pode ser negativo")
    return topic


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    topic = _validate(args, parser)
    source = dict(os.environ, MQTT_TOPIC=topic)
    if args.host is not None:
        source["MQTT_HOST"] = args.host
    if args.port is not None:
        source["MQTT_PORT"] = str(args.port)
    if args.client_id:
        source["MQTT_CLIENT_ID"] = args.client_id
    elif source.get("MQTT_MODE", "local") == "local":
        source["MQTT_CLIENT_ID"] = f"rfid-simulator-{os.getpid()}"
    try:
        settings = Settings.from_env(source)
    except ValueError as error:
        parser.error(str(error))
    try:
        client = create_client(settings)
    except (ValueError, OSError):
        parser.error("Configuração MQTT inválida; confira modo, TLS, certificado e variáveis obrigatórias")
    configure_logging(settings.log_level)

    connected = Event()
    connection_error: list[str] = []

    def on_connect(
        _client: mqtt.Client,
        _userdata: Any,
        _flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        if reason_code.is_failure:
            connection_error.append(str(reason_code))
        connected.set()

    def on_connect_fail(_client: mqtt.Client, _userdata: Any) -> None:
        connection_error.append("broker indisponível")

    client.on_connect = on_connect
    client.on_connect_fail = on_connect_fail

    LOGGER.info("Conectando ao broker %s:%d client_id=%s", settings.mqtt_host,
                settings.mqtt_port, settings.mqtt_client_id)
    try:
        client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=settings.mqtt_keepalive)
        client.loop_start()
        if not connected.wait(timeout=10) or connection_error:
            detail = connection_error[-1] if connection_error else "timeout"
            raise RuntimeError(f"conexão MQTT não estabelecida: {detail}")

        for index in range(args.count):
            payload = _payload(args)
            if args.invalid == "missing":
                del payload["tag" if args.format == "simulator" else "epc"]
            serialized = "{" if args.invalid == "json" else json.dumps(payload, separators=(",", ":"))
            publish_result = client.publish(topic, serialized, qos=1, retain=False)
            if publish_result.rc != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(
                    f"publicação rejeitada com código {publish_result.rc}"
                )
            publish_result.wait_for_publish(timeout=10)
            if not publish_result.is_published():
                raise TimeoutError("broker não confirmou a publicação")
            LOGGER.info(
                "Mensagem %d/%d publicada: tópico=%s readerid=%s antena=%d",
                index + 1,
                args.count,
                topic,
                args.reader_id,
                args.antenna,
            )
            if index + 1 < args.count:
                time.sleep(args.interval)
    except (OSError, RuntimeError, TimeoutError):
        LOGGER.error("Falha no simulador: conexão ou publicação não confirmada")
        return 1
    except KeyboardInterrupt:
        LOGGER.info("Simulador interrompido")
        return 130
    finally:
        client.disconnect()
        client.loop_stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
