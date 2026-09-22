"""Regra de direção pura, sem PostgreSQL nem leitor físico."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from rfid_inference.direction import (
    DirectionContext,
    DirectionEvidence,
    DirectionMapping,
    infer_direction,
)
from rfid_inference.direction_service import DirectionInferenceService

T0 = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)


def context(
    first_side="a", second_side="b", delta_ms=101, *,
    first_antenna=10, second_antenna=20,
):
    first_zone = 1 if first_side == "a" else 2
    second_zone = 1 if second_side == "a" else 2
    return DirectionContext(
        passage_id=7, epc="EPC-1", portal_id=3, zone_a_id=1, zone_b_id=2,
        first=DirectionEvidence(
            first_antenna, 101, T0, "EPC-1", first_antenna,
            (DirectionMapping(3, first_side, first_zone),),
        ),
        second=DirectionEvidence(
            second_antenna, 102, T0 + timedelta(milliseconds=delta_ms),
            "EPC-1", second_antenna,
            (DirectionMapping(3, second_side, second_zone),),
        ),
    )


@pytest.mark.parametrize("sides,direction,zones", [
    (("a", "b"), "a_para_b", (1, 2)),
    (("b", "a"), "b_para_a", (2, 1)),
])
def test_confirmed_side_order_and_zones(sides, direction, zones):
    result = infer_direction(context(*sides), timedelta(milliseconds=100))
    assert result.status == result.confidence == "confirmed"
    assert result.direction == direction
    assert (result.origin_zone_id, result.destination_zone_id) == zones
    assert (result.origin_side, result.destination_side) == sides
    assert (result.origin_reading_id, result.destination_reading_id) == (101, 102)
    assert result.rule == "temporal_side_order_v1"


@pytest.mark.parametrize("delta", [0, 50, 100])
def test_equal_below_and_exact_boundary_are_ambiguous(delta):
    result = infer_direction(context(delta_ms=delta), timedelta(milliseconds=100))
    assert result.status == "ambiguous"
    assert result.direction == "indeterminada"
    assert result.origin_zone_id is result.destination_zone_id is None
    assert result.rule == "temporal_proximity_v1"


def test_zero_tolerance_only_rejects_tie():
    assert infer_direction(context(delta_ms=0), timedelta(0)).status == "ambiguous"
    assert infer_direction(context(delta_ms=1), timedelta(0)).status == "confirmed"


@pytest.mark.parametrize("side", ["a", "b"])
def test_same_side_never_confirmed(side):
    result = infer_direction(context(side, side), timedelta(milliseconds=100))
    assert result.status == "unknown"
    assert result.origin_zone_id is result.destination_zone_id is None


@pytest.mark.parametrize("antenna_a,antenna_b", [(10, 20), (11, 20), (10, 21), (11, 21)])
def test_multiple_antennas_and_reader_ids_are_irrelevant(antenna_a, antenna_b):
    result = infer_direction(
        context(first_antenna=antenna_a, second_antenna=antenna_b),
        timedelta(milliseconds=100),
    )
    assert result.direction == "a_para_b"


def test_rssi_is_not_an_input_to_direction():
    assert "rssi" not in DirectionEvidence.__dataclass_fields__
    assert infer_direction(context(), timedelta(milliseconds=100)).status == "confirmed"


@pytest.mark.parametrize("broken", [
    lambda c: replace(c, first=replace(c.first, mappings=())),
    lambda c: replace(c, first=replace(c.first, mappings=c.first.mappings * 2)),
    lambda c: replace(c, first=replace(c.first, epc="OTHER")),
    lambda c: replace(c, first=replace(c.first, reading_antenna_id=999)),
    lambda c: replace(c, second=replace(c.second, reading_id=None, observed_at=None)),
    lambda c: replace(c, first=replace(c.first, mappings=(DirectionMapping(4, "a", 1),))),
    lambda c: replace(c, first=replace(c.first, mappings=(DirectionMapping(3, "a", 2),))),
    lambda c: replace(c, first=replace(c.first, mappings=(DirectionMapping(3, "x", 1),))),
    lambda c: replace(c, second=replace(c.second, observed_at=T0 - timedelta(seconds=1))),
])
def test_unresolved_or_inconsistent_evidence_is_unknown(broken):
    result = infer_direction(broken(context()), timedelta(milliseconds=100))
    assert result.status == "unknown"
    assert result.direction == "indeterminada"
    assert result.destination_zone_id is None


def test_invalid_tolerance():
    with pytest.raises(ValueError):
        infer_direction(context(), timedelta(milliseconds=-1))


def test_service_recovers_pending_and_is_idempotent():
    class MemoryRepository:
        def __init__(self):
            self.pending = {7: context()}
            self.saved = None

        def pending_ids(self, limit=100):
            return tuple(self.pending)[:limit]

        def load(self, passage_id):
            return self.pending.get(passage_id)

        def persist(self, result):
            if result.passage_id not in self.pending:
                return False
            del self.pending[result.passage_id]
            self.saved = result
            return True

    repository = MemoryRepository()
    service = DirectionInferenceService(repository, 100)
    service.tick(1.0)  # recuperação após reinício, sem novo evento MQTT
    assert repository.saved.direction == "a_para_b"
    service.tick(6.0)
    assert service.process(7) is None
    assert service.counters.passages_processed == 1
    assert service.counters.directions_confirmed == 1
