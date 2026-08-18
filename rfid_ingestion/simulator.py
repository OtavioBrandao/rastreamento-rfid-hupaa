"""Simulador de publicações no formato documentado do Identix EZ700."""

from __future__ import annotations

import argparse
import json
import logging
import os
from threading import Event
import time
from typing import Any, Sequence

import paho.mqtt.client as mqtt

from .config import VALID_LOG_LEVELS
from .logging_config import configure_logging


LOGGER = logging.getLogger(__name__)
SAMPLE_EPC = "E2801190A502006016C32F62"
SAMPLE_TID = "E280119020004F62B6190300"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publica eventos RFID simulados em um broker MQTT."
    )
    parser.add_argument("--host", default=os.getenv("MQTT_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=os.getenv("MQTT_PORT", "1883")
    )
    parser.add_argument("--topic", help="Tópico de publicação")
    parser.add_argument("--reader-id", default="EZ700-SIM-01")
    parser.add_argument("--antenna", type=int, default=1)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--epc", default=SAMPLE_EPC)
    parser.add_argument(
        "--client-id",
        default=f"rfid-mvp-simulator-{os.getpid()}",
    )
    return parser


def _payload(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "epc": args.epc,
        "tid": SAMPLE_TID,
        "timestamp": str(int(time.time() * 1000)),
        "rssi": -3880,
        "phase": 49,
        "channel": 906250,
        "antenna": args.antenna,
        "readerid": args.reader_id,
    }


def _validate(args: argparse.Namespace, parser: argparse.ArgumentParser) -> str:
    topic = args.topic or f"rfid/{args.reader_id}/tags"
    if not args.host:
        parser.error("--host não pode estar vazio")
    if not 1 <= args.port <= 65535:
        parser.error("--port deve estar entre 1 e 65535")
    if not args.reader_id or "\x00" in args.reader_id:
        parser.error("--reader-id inválido")
    if not topic or "\x00" in topic or "+" in topic or "#" in topic:
        parser.error("--topic deve ser um tópico de publicação sem curingas")
    if args.antenna < 1:
        parser.error("--antenna deve ser maior que zero")
    if args.count < 1:
        parser.error("--count deve ser maior que zero")
    if args.interval < 0:
        parser.error("--interval não pode ser negativo")
    return topic


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    topic = _validate(args, parser)
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    if log_level not in VALID_LOG_LEVELS:
        parser.error(f"LOG_LEVEL inválido: {log_level}")
    configure_logging(log_level)

    connected = Event()
    connection_error: list[str] = []
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=args.client_id,
        protocol=mqtt.MQTTv311,
    )

    username = os.getenv("MQTT_USERNAME") or None
    password = os.getenv("MQTT_PASSWORD") or None
    if username is not None:
        client.username_pw_set(username, password)

    def on_connect(
        _client: mqtt.Client,
        _userdata: Any,
        _flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        if reason_code.is_failure:
            connection_error.append(str(reason_code))
        else:
            connected.set()

    def on_connect_fail(_client: mqtt.Client, _userdata: Any) -> None:
        connection_error.append("broker indisponível")

    client.on_connect = on_connect
    client.on_connect_fail = on_connect_fail
    client.enable_logger(logging.getLogger("paho.mqtt"))

    LOGGER.info("Conectando ao broker %s:%d", args.host, args.port)
    try:
        client.connect(args.host, args.port, keepalive=60)
        client.loop_start()
        if not connected.wait(timeout=10):
            detail = connection_error[-1] if connection_error else "timeout"
            raise RuntimeError(f"conexão MQTT não estabelecida: {detail}")

        for index in range(args.count):
            serialized = json.dumps(_payload(args), separators=(",", ":"))
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
    except (OSError, RuntimeError, TimeoutError) as error:
        LOGGER.error("Falha no simulador: %s", error)
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
