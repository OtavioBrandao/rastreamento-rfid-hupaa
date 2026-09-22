"""Ponto de entrada do receptor MQTT."""

from __future__ import annotations

import logging
from datetime import timedelta

from db.runtime import DatabaseConfigurationError, create_app_engine
from rfid_inference.debounce import DebounceProcessor
from rfid_inference.passage import PassageDetector
from rfid_inference.passage_repository import PassageRepository
from rfid_inference.passage_service import PassageInferenceService

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
        debouncer = DebounceProcessor.from_milliseconds(
            settings.rfid_debounce_window_ms,
            settings.rfid_out_of_order_tolerance_ms,
        )
        passage_service = PassageInferenceService(
            PassageDetector(
                timedelta(milliseconds=settings.rfid_passage_max_interval_ms),
                silence_grace=timedelta(milliseconds=(
                    settings.rfid_debounce_window_ms
                    + settings.rfid_out_of_order_tolerance_ms
                )),
            ),
            PassageRepository(engine),
        )
        receiver = MqttReceiver(
            settings,
            store,
            RawReadingRepository(engine),
            debouncer=debouncer,
            observation_handler=passage_service.handle_observation,
            observation_tick_handler=passage_service.tick,
        )
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
