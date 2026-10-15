"""Orquestra inferência idempotente e recuperação de passagens pendentes."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from .direction import DirectionInferenceResult, infer_direction
from .direction_repository import DirectionRepository

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class DirectionCounters:
    """Estrutura Direction Counters usada por rfid_inference.direction_service.

    Campos: passages_processed, directions_confirmed, directions_ambiguous, directions_unknown, retries."""
    passages_processed: int = 0
    directions_confirmed: int = 0
    directions_ambiguous: int = 0
    directions_unknown: int = 0
    retries: int = 0


class DirectionInferenceService:
    """Coordena direção, contadores, recuperação periódica e callback de localização."""
    def __init__(
        self, repository: DirectionRepository, ambiguity_ms: int, *,
        monotonic_clock: Callable[[], float] = time.monotonic,
        retry_interval_seconds: float = 5.0,
        confirmed_handler: Callable[[int], object] | None = None,
    ) -> None:
        """Inicializa DirectionInferenceService com as dependências e valores recebidos."""
        if type(ambiguity_ms) is not int or ambiguity_ms < 0:
            raise ValueError("ambiguidade deve ser inteiro não negativo")
        self.repository = repository
        self.ambiguity = timedelta(milliseconds=ambiguity_ms)
        self.monotonic_clock = monotonic_clock
        self.retry_interval_seconds = retry_interval_seconds
        self.confirmed_handler = confirmed_handler
        self._next_retry_at = 0.0
        self.counters = DirectionCounters()

    def process(self, passage_id: int) -> DirectionInferenceResult | None:
        """Infere e persiste a direção; dispara projeção apenas para confirmação bem-sucedida."""
        context = self.repository.load(passage_id)
        if context is None:
            return None
        result = infer_direction(context, self.ambiguity)
        if not self.repository.persist(result):
            return None
        self.counters.passages_processed += 1
        if result.status == "confirmed":
            self.counters.directions_confirmed += 1
        elif result.status == "ambiguous":
            self.counters.directions_ambiguous += 1
        else:
            self.counters.directions_unknown += 1
        LOGGER.info(json.dumps({
            "event_type": f"rfid_direction_{result.status}",
            "passage_id": result.passage_id, "epc": result.epc,
            "portal_id": result.portal_id, "direction": result.direction,
            "origin_zone_id": result.origin_zone_id,
            "destination_zone_id": result.destination_zone_id,
            "rule": result.rule,
        }))
        if result.rule == "topology_unresolved":
            LOGGER.warning(json.dumps({
                "event_type": "rfid_direction_topology_unresolved",
                "passage_id": result.passage_id, "epc": result.epc,
                "portal_id": result.portal_id, "reason": result.rule,
            }))
        if result.status == "confirmed" and self.confirmed_handler is not None:
            try:
                self.confirmed_handler(result.passage_id)
            except Exception:
                self.counters.retries += 1
                LOGGER.exception(json.dumps({
                    "event_type": "rfid_location_reconciliation_failed",
                    "passage_id": result.passage_id, "reason": "confirmed_handler_failed",
                }))
        return result

    def process_pending(self, *, limit: int = 100) -> None:
        """Reprocessa passagens sem direção e contabiliza falhas sem abortar o lote de recuperação."""
        try:
            pending = self.repository.pending_ids(limit)
        except Exception:
            self.counters.retries += 1
            LOGGER.error(json.dumps({
                "event_type": "rfid_direction_retry", "reason": "pending_query_failed",
            }))
            return
        for passage_id in pending:
            try:
                self.process(passage_id)
            except Exception:
                self.counters.retries += 1
                LOGGER.error(json.dumps({
                    "event_type": "rfid_direction_retry",
                    "passage_id": passage_id, "reason": "processing_failed",
                }))

    def tick(self, now_monotonic: float | None = None) -> None:
        """Executa recuperação periódica de direção quando o próximo prazo monotônico é atingido."""
        now = self.monotonic_clock() if now_monotonic is None else now_monotonic
        if now >= self._next_retry_at:
            self._next_retry_at = now + self.retry_interval_seconds
            self.process_pending()
