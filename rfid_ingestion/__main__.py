"""Ponto de entrada do receptor MQTT."""

from __future__ import annotations

import logging
from datetime import timedelta

from db.runtime import DatabaseConfigurationError, create_app_engine
from rfid_inference.debounce import DebounceProcessor
from rfid_inference.direction_repository import DirectionRepository
from rfid_inference.direction_service import DirectionInferenceService
from rfid_inference.passage import PassageDetector
from rfid_inference.passage_repository import PassageRepository
from rfid_inference.passage_service import PassageInferenceService
from rfid_location.service import LocationProjectionService

from .config import Settings
from .logging_config import configure_logging
from .mqtt_client import MqttReceiver
from .persistence import JsonlEventStore
from .repository import RawReadingRepository


def main() -> int:
    """Executa a entrada de linha de comando de rfid_ingestion.__main__; devolve o código de saída quando aplicável."""
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
        location_service = LocationProjectionService(engine)
        direction_service = DirectionInferenceService(
            DirectionRepository(engine), settings.rfid_direction_ambiguity_ms,
            confirmed_handler=location_service.process_passage,
        )
        direction_service.process_pending()
        location_service.process_pending()
        passage_repository = PassageRepository(engine)
        overlap_grace = timedelta(milliseconds=settings.rfid_passage_overlap_grace_ms)
        origin_hold = timedelta(milliseconds=settings.rfid_passage_origin_hold_ms)
        passage_service = PassageInferenceService(
            PassageDetector(
                timedelta(milliseconds=settings.rfid_passage_max_interval_ms),
                silence_grace=timedelta(milliseconds=(
                    settings.rfid_debounce_window_ms
                    + settings.rfid_out_of_order_tolerance_ms
                )),
                refractory=timedelta(milliseconds=settings.rfid_passage_refractory_ms),
                origin_active=lambda origin, destination: passage_repository.origin_active(
                    origin, destination, grace=overlap_grace, hold=origin_hold),
            ),
            passage_repository,
            passage_persisted=direction_service.process_pending,
        )
        def inference_tick(now_monotonic: float) -> None:
            """Avança recuperação de passagem, direção e projeção com o mesmo relógio de inferência."""
            passage_service.tick(now_monotonic)
            direction_service.tick(now_monotonic)
            location_service.tick(now_monotonic)

        receiver = MqttReceiver(
            settings,
            store,
            RawReadingRepository(engine),
            debouncer=debouncer,
            observation_handler=passage_service.handle_observation,
            observation_tick_handler=inference_tick,
        )
        # Mesmo relógio do debounce: a inferência pode estar atrás da rede.
        passage_service.monotonic_clock = receiver.relogio_inferencia
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
