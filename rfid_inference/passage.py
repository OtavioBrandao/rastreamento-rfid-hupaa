"""Detecção de passagem por evidências consolidadas, sem ORM ou transporte."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

LOGGER = logging.getLogger(__name__)


def _event(name: str, epc: str, portal_id: int) -> None:
    """Emite evento estruturado de inferência com os identificadores de contexto."""
    LOGGER.info(json.dumps({"event_type": name, "epc": epc, "portal_id": portal_id}))


@dataclass(frozen=True, slots=True)
class PortalObservation:
    """Estrutura Portal Observation usada por rfid_inference.passage.

    Campos: epc, portal_id, antenna_id, side, zone_id, mapping_id, first_seen_at, last_seen_at, first_reading_id, last_reading_id, first_event_id, last_event_id."""
    epc: str
    portal_id: int
    antenna_id: int
    side: str
    zone_id: int
    mapping_id: int
    first_seen_at: datetime
    last_seen_at: datetime
    first_reading_id: int
    last_reading_id: int
    first_event_id: str
    last_event_id: str

    def __post_init__(self) -> None:
        """Valida as invariantes dos campos após a construção da estrutura."""
        if self.side not in ("a", "b") or self.first_seen_at > self.last_seen_at:
            raise ValueError("observação de portal inválida")
        if self.first_seen_at.tzinfo is None or self.last_seen_at.tzinfo is None:
            raise ValueError("observação exige timestamps com fuso")


@dataclass(frozen=True, slots=True)
class DetectedPassage:
    """Estrutura Detected Passage usada por rfid_inference.passage.

    Campos: epc, portal_id, first_side, second_side, first_antenna_id, second_antenna_id, first_reading_id, second_reading_id, first_observed_at, second_observed_at, detected_at."""
    epc: str
    portal_id: int
    first_side: str
    second_side: str
    first_antenna_id: int
    second_antenna_id: int
    first_reading_id: int
    second_reading_id: int
    first_observed_at: datetime
    second_observed_at: datetime
    detected_at: datetime


@dataclass(slots=True)
class PassageCounters:
    """Estrutura Passage Counters usada por rfid_inference.passage.

    Campos: observations_received, candidates_started, candidates_expired, same_side_observations, passages_confirmed, passages_duplicates, activity_suppressed, origin_still_active."""
    observations_received: int = 0
    candidates_started: int = 0
    candidates_expired: int = 0
    same_side_observations: int = 0
    passages_confirmed: int = 0
    passages_duplicates: int = 0
    activity_suppressed: int = 0
    origin_still_active: int = 0


@dataclass(slots=True)
class _State:
    """Estrutura _State usada por rfid_inference.passage.

    Campos: candidate, confirmed, last_event_at, last_received_monotonic, proposed, anchor, proposed_anchor, last_passage_at."""
    candidate: PortalObservation | None = None
    confirmed: bool = False
    last_event_at: datetime | None = None
    last_received_monotonic: float = 0.0
    proposed: DetectedPassage | None = None
    # Última observação do lado de destino: referência para a próxima passagem.
    anchor: PortalObservation | None = None
    proposed_anchor: PortalObservation | None = None
    last_passage_at: datetime | None = None


def _order(item: PortalObservation) -> tuple[datetime, int, str]:
    """Produz desempate determinístico por primeiro instante, antena e identidade do evento."""
    return item.first_seen_at, item.antenna_id, item.first_event_id


class PassageDetector:
    """Estado independente por (EPC, portal), com confirmação em duas fases.

    A proposta permanece recuperável até o serviço confirmar a persistência.
    Após uma passagem, leituras no lado de destino apenas renovam a âncora; uma
    observação no lado oposto, posterior à âncora e fora do período refratário,
    inicia a próxima passagem sem exigir silêncio da tag.

    ``origin_active(origem, destino)`` informa se a antena de origem continuou
    lendo a tag durante a observação de destino (após a tolerância de
    sobreposição). Nesse caso a tag não saiu da origem: é reflexão/sobreposição
    de antenas e a passagem é descartada.

    ``max_interval=None`` não limita o tempo entre os lados: a tag vista num lado
    e depois no outro atravessou o portal, mesmo que devagar ou fora do alcance
    da antena de destino. O estado de cada EPC/portal é mantido e não expira.
    """

    def __init__(self, max_interval: timedelta | None, *,
                 silence_grace: timedelta = timedelta(0),
                 refractory: timedelta = timedelta(0),
                 origin_active: Callable[[PortalObservation, PortalObservation], bool]
                 | None = None):
        """Inicializa PassageDetector com as dependências e valores recebidos."""
        if ((max_interval is not None and max_interval <= timedelta(0))
                or silence_grace < timedelta(0) or refractory < timedelta(0)):
            raise ValueError("intervalos inválidos")
        self.max_interval = max_interval
        self.silence_grace = silence_grace
        self.refractory = refractory
        self.origin_active = origin_active
        self.states: dict[tuple[str, int], _State] = {}
        self.counters = PassageCounters()

    def add(
        self, observation: PortalObservation, *, received_at_monotonic: float | None = None
    ) -> DetectedPassage | None:
        """Incorpora evidência por EPC/portal e propõe passagem entre lados opostos.

        Rejeita origem ainda ativa, evidências sobrepostas e período refratário.
        A proposta permanece pendente até mark_persisted confirmar sua gravação."""
        if received_at_monotonic is None:
            received_at_monotonic = time.monotonic()
        self.counters.observations_received += 1
        key = observation.epc, observation.portal_id
        state = self.states.setdefault(key, _State())
        state.last_received_monotonic = received_at_monotonic
        if state.proposed is not None:
            return state.proposed
        if state.confirmed:
            assert state.last_event_at is not None and state.anchor is not None
            anchor = state.anchor
            same_side = observation.side == anchor.side
            # Lado oposto que começou antes da âncora é sobreposição entre antenas;
            # dentro do período refratário, ruído logo após a travessia.
            noise = not same_side and (
                _order(observation) < _order(anchor)
                or (state.last_passage_at is not None
                    and observation.first_seen_at - state.last_passage_at < self.refractory)
            )
            if same_side or noise:
                if same_side:
                    state.anchor = max((anchor, observation), key=_order)
                state.last_event_at = max(state.last_event_at, observation.last_seen_at)
                self.counters.activity_suppressed += 1
                _event("rfid_passage_activity_suppressed", *key)
                return None
            state.confirmed = False
            state.candidate = anchor

        candidate = state.candidate
        if candidate is not None:
            first, second = sorted((candidate, observation), key=_order)
            gap = max(timedelta(0), second.first_seen_at - first.last_seen_at)
            if self.max_interval is not None and gap > self.max_interval:
                self.counters.candidates_expired += 1
                _event("rfid_passage_candidate_expired", *key)
                state.candidate = observation
                self.counters.candidates_started += 1
                return None
            if candidate.side == observation.side:
                state.candidate = max((candidate, observation), key=_order)
                self.counters.same_side_observations += 1
                _event("rfid_passage_same_side", *key)
                return None
            if self.origin_active is not None and self.origin_active(first, second):
                # A origem segue lendo a tag: mantém a origem como referência.
                self.counters.origin_still_active += 1
                _event("rfid_passage_origin_still_active", *key)
                if state.anchor is not None and first is state.anchor:
                    state.confirmed = True
                    state.candidate = None
                else:
                    state.candidate = first
                return None
            detected = DetectedPassage(
                epc=observation.epc,
                portal_id=observation.portal_id,
                first_side=first.side,
                second_side=second.side,
                first_antenna_id=first.antenna_id,
                second_antenna_id=second.antenna_id,
                first_reading_id=first.last_reading_id,
                second_reading_id=second.first_reading_id,
                first_observed_at=first.last_seen_at,
                second_observed_at=second.first_seen_at,
                detected_at=max(first.last_seen_at, second.last_seen_at),
            )
            state.proposed = detected
            state.proposed_anchor = second
            state.last_event_at = max(first.last_seen_at, second.last_seen_at)
            return detected
        state.candidate = observation
        self.counters.candidates_started += 1
        _event("rfid_passage_candidate_started", *key)
        return None

    def mark_persisted(self, passage: DetectedPassage, *, duplicate: bool) -> None:
        """Confirma a proposta após persistência e conserva a observação de destino como âncora."""
        key = passage.epc, passage.portal_id
        state = self.states[key]
        if state.proposed != passage:
            raise ValueError("proposta de passagem diferente do estado pendente")
        state.proposed = None
        state.candidate = None
        state.confirmed = True
        state.anchor = state.proposed_anchor
        state.proposed_anchor = None
        state.last_passage_at = passage.second_observed_at
        if duplicate:
            self.counters.passages_duplicates += 1
            _event("rfid_passage_duplicate", *key)
        else:
            self.counters.passages_confirmed += 1
            _event("rfid_passage_confirmed", *key)

    def knows(self, epc: str, portal_id: int) -> bool:
        """Indica se há estado em memória para o EPC/portal."""
        return (epc, portal_id) in self.states

    def seed(self, observation: PortalObservation) -> None:
        """Restaura a última evidência conhecida (ex.: após reinício) como candidato."""
        key = observation.epc, observation.portal_id
        if key not in self.states:
            self.states[key] = _State(candidate=observation)

    def pending(self) -> tuple[DetectedPassage, ...]:
        """Devolve propostas que ainda aguardam confirmação de persistência."""
        return tuple(state.proposed for state in self.states.values() if state.proposed)

    def advance_time(self, now_monotonic: float) -> None:
        """Expira estados de observação conforme o relógio monotônico e as janelas configuradas."""
        if self.max_interval is None:
            return  # sem limite: o último lado de cada tag nunca expira
        silence = (self.max_interval + self.silence_grace).total_seconds()
        for key, state in tuple(self.states.items()):
            if state.proposed is not None:
                continue  # falha de banco: manter proposta para retry no próximo tick
            if now_monotonic - state.last_received_monotonic > silence:
                if state.candidate is not None:
                    self.counters.candidates_expired += 1
                    _event("rfid_passage_candidate_expired", *key)
                del self.states[key]
