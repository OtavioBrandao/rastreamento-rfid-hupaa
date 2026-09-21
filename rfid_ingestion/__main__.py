"""Ponto de entrada do receptor MQTT."""

from __future__ import annotations

import logging

from db.runtime import DatabaseConfigurationError, create_app_engine

from .config import Settings
from .logging_config import configure_logging
from .mqtt_client import MqttReceiver
from .persistence import JsonlEventStore
from .repository import RawReadingRepository


def main() -> int:
    try:
        settings = Settings.from_env()
    except ValueError as error:
        configure_logging("ERROR")
        logging.getLogger(__name__).error("Configuração inválida: %s", error)
        return 2

    configure_logging(settings.log_level)
    engine = None
    try:
        engine = create_app_engine()
        store = JsonlEventStore(settings.events_file)
        receiver = MqttReceiver(settings, store, RawReadingRepository(engine))
        return receiver.run()
    except DatabaseConfigurationError as error:
        logging.getLogger(__name__).error("Configuração inválida: %s", error)
        return 2
    except (OSError, ValueError):
        logging.getLogger(__name__).error("Falha ao preparar certificado ou arquivo JSONL")
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
