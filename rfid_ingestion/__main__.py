"""Ponto de entrada do receptor MQTT."""

from __future__ import annotations

import logging

from .config import Settings
from .logging_config import configure_logging
from .mqtt_client import MqttReceiver
from .persistence import JsonlEventStore


def main() -> int:
    try:
        settings = Settings.from_env()
    except ValueError as error:
        configure_logging("ERROR")
        logging.getLogger(__name__).error("Configuração inválida: %s", error)
        return 2

    configure_logging(settings.log_level)
    try:
        store = JsonlEventStore(settings.events_file)
        receiver = MqttReceiver(settings, store)
        return receiver.run()
    except (OSError, ValueError):
        logging.getLogger(__name__).error("Falha ao preparar certificado ou arquivo JSONL")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
