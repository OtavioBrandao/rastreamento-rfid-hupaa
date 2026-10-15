"""Orquestra observações, topologia histórica, detector e persistência."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Callable

from rfid_inference.debounce import ConsolidatedObservation

from .passage import DetectedPassage, PassageDetector
from .passage_repository import PassageRepository

LOGGER = logging.getLogger(__name__)


def _event(level: int, name: str, **fields: object) -> None:
    """Emite evento estruturado de inferência com os identificadores de contexto."""
    LOGGER.log(level, json.dumps({"event_type": name, **fields}))


@dataclass(slots=True)
class ServiceCounters:
    """Estrutura Service Counters usada por rfid_inference.passage_service.

    Campos: topology_unresolved, persistence_failures."""
    topology_unresolved: int = 0
    persistence_failures: int = 0


class PassageInferenceService:
    """Coordena detector e repositório, conservando propostas até a confirmação da gravação."""
    def __init__(
        self,
        detector: PassageDetector,
        repository: PassageRepository,
        *,
        monotonic_clock: Callable[[], float] = time.monotonic,
        passage_persisted: Callable[[], None] | None = None,
    ) -> None:
        """Inicializa PassageInferenceService com as dependências e valores recebidos."""
        self.detector = detector
        self.repository = repository
        self.monotonic_clock = monotonic_clock
        self.counters = ServiceCounters()
        self.passage_persisted = passage_persisted

    def handle_observation(self, observation: ConsolidatedObservation) -> None:
        """Resolve topologia histórica, tenta propostas pendentes e entrega a observação ao detector."""
        try:
            resolved = self.repository.resolve(observation)
        except Exception:
            self.counters.topology_unresolved += 1
            _event(logging.ERROR, "rfid_passage_topology_unresolved",
                   epc=observation.epc, antenna_id=observation.antenna_id,
                   reason="database_error")
            return
        if resolved is None:
            self.counters.topology_unresolved += 1
            _event(logging.WARNING, "rfid_passage_topology_unresolved",
                   epc=observation.epc, antenna_id=observation.antenna_id,
                   reason="ambiguous_or_missing")
            return
        self.retry_pending()
        proposal = self.detector.add(
            resolved, received_at_monotonic=self.monotonic_clock()
        )
        if proposal is not None:
            self._persist(proposal)

    def _persist(self, passage: DetectedPassage) -> None:
        """Persiste a passagem antes de confirmá-la no detector e disparar a inferência de direção."""
        try:
            inserted = self.repository.persist(passage)
        except Exception:
            self.counters.persistence_failures += 1
            _event(logging.ERROR, "rfid_passage_persistence_failed",
                   epc=passage.epc, portal_id=passage.portal_id)
            return
        self.detector.mark_persisted(passage, duplicate=not inserted)
        if self.passage_persisted is not None:
            try:
                self.passage_persisted()
            except Exception:
                _event(logging.ERROR, "rfid_direction_retry",
                       epc=passage.epc, portal_id=passage.portal_id)

    def retry_pending(self) -> None:
        """Reexecuta persistência das propostas conservadas pelo detector após falhas."""
        for proposal in self.detector.pending():
            self._persist(proposal)

    def tick(self, now_monotonic: float | None = None) -> None:
        """Tenta propostas pendentes e expira candidatos no relógio da inferência."""
        self.retry_pending()
        self.detector.advance_time(
            self.monotonic_clock() if now_monotonic is None else now_monotonic
        )
