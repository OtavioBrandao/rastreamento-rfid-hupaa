"""Inferência pura do sentido lógico de uma passagem já persistida."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class DirectionEvidence:
    """Estrutura Direction Evidence usada por rfid_inference.direction.

    Campos: antenna_id, reading_id, observed_at, epc, reading_antenna_id, mappings, reader_id."""
    antenna_id: int | None
    reading_id: int | None
    observed_at: datetime | None
    epc: str | None
    reading_antenna_id: int | None
    mappings: tuple[DirectionMapping, ...] = ()
    # Leitor físico da antena; mesmo leitor implica ordem de chegada confiável.
    reader_id: int | None = None


@dataclass(frozen=True, slots=True)
class DirectionMapping:
    """Estrutura Direction Mapping usada por rfid_inference.direction.

    Campos: portal_id, side, zone_id."""
    portal_id: int
    side: str
    zone_id: int


@dataclass(frozen=True, slots=True)
class DirectionContext:
    """Estrutura Direction Context usada por rfid_inference.direction.

    Campos: passage_id, epc, portal_id, zone_a_id, zone_b_id, first, second."""
    passage_id: int
    epc: str
    portal_id: int
    zone_a_id: int | None
    zone_b_id: int | None
    first: DirectionEvidence
    second: DirectionEvidence
    # Portal de entrada da zona B (lado A = circulação): a ordem das antenas decide,
    # 1 → 2 entra em B e 2 → 1 sai para a circulação; muda só o nome da regra.
    entry_portal: bool = False


@dataclass(frozen=True, slots=True)
class DirectionInferenceResult:
    """Estrutura Direction Inference Result usada por rfid_inference.direction.

    Campos: passage_id, epc, portal_id, status, direction, origin_side, destination_side, origin_zone_id, destination_zone_id, origin_antenna_id, destination_antenna_id, origin_reading_id, destination_reading_id, origin_observed_at, destination_observed_at, rule."""
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
    """Exige topologia única e coerente; desempata proximidade pela ordem de chegada.

    Com o horário de recebimento, leituras entregues na mesma rajada QoS 1
    ficam a poucos milissegundos umas das outras, mas a ordem de publicação de
    um mesmo leitor é preservada pelo MQTT e pela sequência de gravação. Nesse
    caso a ordem dos IDs decide; leitores diferentes continuam ambíguos.
    """
    if ambiguity < timedelta(0):
        raise ValueError("tolerância de ambiguidade deve ser não negativa")
    first, second = context.first, context.second

    def result(status: str, rule: str, direction: str = "indeterminada") -> DirectionInferenceResult:
        """Constrói o resultado da direção com a regra aplicada e suas evidências."""
        confirmed = status == "confirmed"
        if confirmed and context.entry_portal:
            rule = "entry_portal_order_v1"
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
        same_reader = first.reader_id is not None and first.reader_id == second.reader_id
        assert first.reading_id is not None and second.reading_id is not None
        if same_reader and first.reading_id < second.reading_id:
            return result("confirmed", "arrival_order_v1", f"{first_side}_para_{second_side}")
        return result("ambiguous", "temporal_proximity_v1")
    return result("confirmed", "temporal_side_order_v1", f"{first_side}_para_{second_side}")
