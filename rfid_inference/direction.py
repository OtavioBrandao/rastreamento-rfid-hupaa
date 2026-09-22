"""Inferência pura do sentido lógico de uma passagem já persistida."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class DirectionEvidence:
    antenna_id: int | None
    reading_id: int | None
    observed_at: datetime | None
    epc: str | None
    reading_antenna_id: int | None
    mappings: tuple[DirectionMapping, ...] = ()


@dataclass(frozen=True, slots=True)
class DirectionMapping:
    portal_id: int
    side: str
    zone_id: int


@dataclass(frozen=True, slots=True)
class DirectionContext:
    passage_id: int
    epc: str
    portal_id: int
    zone_a_id: int | None
    zone_b_id: int | None
    first: DirectionEvidence
    second: DirectionEvidence


@dataclass(frozen=True, slots=True)
class DirectionInferenceResult:
    passage_id: int
    epc: str
    portal_id: int
    status: str
    direction: str
    origin_side: str | None
    destination_side: str | None
    origin_zone_id: int | None
    destination_zone_id: int | None
    origin_antenna_id: int
    destination_antenna_id: int | None
    origin_reading_id: int | None
    destination_reading_id: int | None
    origin_observed_at: datetime | None
    destination_observed_at: datetime | None
    rule: str

    @property
    def confidence(self) -> str:
        """Confiança categórica; não há probabilidade calibrada em campo."""
        return self.status


def infer_direction(context: DirectionContext, ambiguity: timedelta) -> DirectionInferenceResult:
    """Exige topologia única e coerente; empate temporal é sempre ambíguo."""
    if ambiguity < timedelta(0):
        raise ValueError("tolerância de ambiguidade deve ser não negativa")
    first, second = context.first, context.second

    def result(status: str, rule: str, direction: str = "indeterminada") -> DirectionInferenceResult:
        confirmed = status == "confirmed"
        origin = first.mappings[0] if confirmed else None
        destination = second.mappings[0] if confirmed else None
        return DirectionInferenceResult(
            passage_id=context.passage_id, epc=context.epc, portal_id=context.portal_id,
            status=status, direction=direction,
            origin_side=origin.side if origin else None,
            destination_side=destination.side if destination else None,
            origin_zone_id=origin.zone_id if origin else None,
            destination_zone_id=destination.zone_id if destination else None,
            origin_antenna_id=first.antenna_id,
            destination_antenna_id=second.antenna_id,
            origin_reading_id=first.reading_id,
            destination_reading_id=second.reading_id,
            origin_observed_at=first.observed_at,
            destination_observed_at=second.observed_at,
            rule=rule,
        )

    if any(
        evidence.reading_id is None or evidence.observed_at is None
        or evidence.epc != context.epc
        or evidence.reading_antenna_id != evidence.antenna_id
        for evidence in (first, second)
    ):
        return result("unknown", "evidence_unresolved")
    if context.zone_a_id is None or context.zone_b_id is None or (
        context.zone_a_id == context.zone_b_id
    ):
        return result("unknown", "topology_unresolved")
    if any(len(evidence.mappings) != 1 for evidence in (first, second)):
        return result("unknown", "topology_unresolved")
    for evidence in (first, second):
        mapping = evidence.mappings[0]
        expected_zone = {"a": context.zone_a_id, "b": context.zone_b_id}.get(mapping.side)
        if mapping.portal_id != context.portal_id or expected_zone != mapping.zone_id:
            return result("unknown", "topology_unresolved")
    first_side, second_side = first.mappings[0].side, second.mappings[0].side
    if first_side == second_side:
        return result("unknown", "same_side")
    assert first.observed_at is not None and second.observed_at is not None
    if first.observed_at > second.observed_at:
        return result("unknown", "evidence_order_invalid")
    if second.observed_at - first.observed_at <= ambiguity:
        return result("ambiguous", "temporal_proximity_v1")
    return result("confirmed", "temporal_side_order_v1", f"{first_side}_para_{second_side}")
