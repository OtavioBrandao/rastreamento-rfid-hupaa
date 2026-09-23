"""Histórico e última zona persistidos em uma única transação PostgreSQL."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from sqlalchemy.engine import Engine

from rfid_movement import repository as movement_repository
from rfid_movement.service import append_automatic_movement, append_manual_correction

from . import repository
from .types import LocationProjectionResult, decide_projection

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class LocationCounters:
    processed: int = 0
    updated: int = 0
    stale: int = 0
    duplicate: int = 0
    conflicts: int = 0
    unresolved: int = 0
    retries: int = 0


class LocationProjectionService:
    def __init__(
        self, engine: Engine, *, monotonic_clock: Callable[[], float] = time.monotonic,
        retry_interval_seconds: float = 5.0,
    ) -> None:
        self.engine = engine
        self.monotonic_clock = monotonic_clock
        self.retry_interval_seconds = retry_interval_seconds
        self._next_retry_at = 0.0
        self._pending_after_id = 0
        self.counters = LocationCounters()

    def _log(self, result: LocationProjectionResult) -> None:
        LOGGER.info(json.dumps({
            "event_type": f"rfid_location_{result.status}",
            "equipment_id": result.equipment_id, "passage_id": result.passage_id,
            "movement_id": result.movement_id,
            "previous_zone_id": result.previous_zone_id,
            "destination_zone_id": result.destination_zone_id,
            "previous_detected_at": result.previous_detected_at.isoformat()
            if result.previous_detected_at else None,
            "movement_at": result.movement_at.isoformat() if result.movement_at else None,
            "status": result.status,
        }))

    def _count(self, result: LocationProjectionResult) -> None:
        self.counters.processed += 1
        if result.status == "updated":
            self.counters.updated += 1
        elif result.status == "stale":
            self.counters.stale += 1
        elif result.status == "duplicate":
            self.counters.duplicate += 1
        elif result.status == "same_timestamp_conflict":
            self.counters.conflicts += 1
        elif result.status in ("unresolved_epc", "ambiguous_association"):
            self.counters.unresolved += 1

    def process_passage(self, passage_id: int) -> LocationProjectionResult:
        with self.engine.begin() as connection:
            written = append_automatic_movement(connection, passage_id)
            if written.status not in ("recorded", "duplicate"):
                result = LocationProjectionResult(written.status, passage_id=passage_id)
            else:
                movement = movement_repository.get_movement(connection, written.movement_id)
                equipment = repository.lock_equipment(connection, movement["equipamento_id"])
                if equipment is None:
                    result = LocationProjectionResult(
                        "equipment_missing", movement_id=written.movement_id,
                        passage_id=passage_id,
                    )
                else:
                    status = decide_projection(
                        movement["movimentada_em"], equipment.ultima_deteccao_em,
                        movement["id"], equipment.ultima_movimentacao_id,
                    )
                    if status == "updated":
                        repository.update_location(
                            connection, equipment.id,
                            zone_id=movement["zona_destino_id"],
                            movement_at=movement["movimentada_em"],
                            passage_id=movement["passagem_id"], movement_id=movement["id"],
                        )
                    result = LocationProjectionResult(
                        status, equipment.id, movement["id"], passage_id,
                        equipment.ultima_zona_id, movement["zona_destino_id"],
                        equipment.ultima_deteccao_em, movement["movimentada_em"],
                    )
        self._count(result)
        self._log(result)
        return result

    def apply_manual_location_correction(
        self, *, equipment_id: int, destination_zone_id: int,
        movimentada_em: datetime, justificativa: str,
    ) -> LocationProjectionResult:
        """Serviço interno: o chamador futuro deve autorizar o usuário antes da chamada."""
        if movimentada_em.tzinfo is None or movimentada_em.utcoffset() is None:
            raise ValueError("movimentada_em exige fuso horário")
        with self.engine.begin() as connection:
            equipment = repository.lock_equipment(connection, equipment_id)
            if equipment is None:
                raise ValueError("equipamento inexistente")
            if equipment.ultima_deteccao_em is not None:
                if movimentada_em < equipment.ultima_deteccao_em:
                    raise ValueError("correção manual anterior à última localização")
                if movimentada_em == equipment.ultima_deteccao_em:
                    raise ValueError("correção manual conflita com timestamp existente")
            written = append_manual_correction(
                connection, equipamento_id=equipment_id,
                zona_origem_id=equipment.ultima_zona_id,
                zona_destino_id=destination_zone_id,
                movimentada_em=movimentada_em, justificativa=justificativa,
                registro_anterior_id=equipment.ultima_movimentacao_id,
            )
            repository.update_location(
                connection, equipment_id, zone_id=destination_zone_id,
                movement_at=movimentada_em, passage_id=None,
                movement_id=written.movement_id,
            )
            result = LocationProjectionResult(
                "updated", equipment_id, written.movement_id, None,
                equipment.ultima_zona_id, destination_zone_id,
                equipment.ultima_deteccao_em, movimentada_em,
            )
        self._count(result)
        self._log(result)
        return result

    def process_pending(self, *, limit: int = 100) -> None:
        try:
            ids = repository.pending_ids(
                self.engine, limit=limit, after_id=self._pending_after_id
            )
            if not ids and self._pending_after_id:
                self._pending_after_id = 0
                ids = repository.pending_ids(self.engine, limit=limit)
        except Exception:
            self.counters.retries += 1
            LOGGER.exception(json.dumps({"event_type": "rfid_location_reconciliation_failed",
                                         "reason": "pending_query_failed"}))
            return
        for passage_id in ids:
            self._pending_after_id = passage_id
            try:
                self.process_passage(passage_id)
            except Exception:
                self.counters.retries += 1
                LOGGER.exception(json.dumps({
                    "event_type": "rfid_location_reconciliation_failed",
                    "passage_id": passage_id, "reason": "processing_failed",
                }))

    def tick(self, now_monotonic: float | None = None) -> None:
        now = self.monotonic_clock() if now_monotonic is None else now_monotonic
        if now >= self._next_retry_at:
            self._next_retry_at = now + self.retry_interval_seconds
            self.process_pending()
