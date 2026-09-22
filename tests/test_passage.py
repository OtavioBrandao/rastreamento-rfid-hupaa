"""Regra pura da ISS-015, incluindo limites e limpeza sem sleep."""

from datetime import datetime, timedelta, timezone

import pytest

from rfid_inference.passage import PassageDetector, PortalObservation
from rfid_inference.passage_service import PassageInferenceService

T0 = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
WINDOW = timedelta(seconds=3)


def observation(side, seconds, *, epc="X", portal=1, antenna=None, reading=None):
    antenna = antenna or (10 if side == "a" else 11)
    reading = reading or antenna * 100 + round(seconds * 10)
    instant = T0 + timedelta(seconds=seconds)
    return PortalObservation(
        epc, portal, antenna, side, 1 if side == "a" else 2, antenna,
        instant, instant, reading, reading, str(reading), str(reading),
    )


@pytest.mark.parametrize("first,second", [("a", "b"), ("b", "a")])
def test_opposite_sides_confirm_once(first, second):
    detector = PassageDetector(WINDOW)
    assert detector.add(observation(first, 0), received_at_monotonic=0) is None
    passage = detector.add(observation(second, 3), received_at_monotonic=3)
    assert passage is not None
    assert (passage.first_side, passage.second_side) == (first, second)
    assert passage.detected_at == T0 + WINDOW
    assert passage.first_reading_id == observation(first, 0).last_reading_id
    assert passage.second_reading_id == observation(second, 3).first_reading_id
    detector.mark_persisted(passage, duplicate=False)
    assert detector.add(observation(first, 3.1), received_at_monotonic=3.1) is None
    assert detector.counters.passages_confirmed == 1
    assert detector.counters.activity_suppressed == 1


@pytest.mark.parametrize("side", ["a", "b"])
def test_same_side_even_different_antennas(side):
    detector = PassageDetector(WINDOW)
    detector.add(observation(side, 0), received_at_monotonic=0)
    assert detector.add(observation(side, 1, antenna=20), received_at_monotonic=1) is None
    assert detector.counters.same_side_observations == 1
    assert detector.add(observation("b" if side == "a" else "a", 2)) is not None


def test_above_limit_expires_and_restarts_candidate():
    detector = PassageDetector(WINDOW)
    detector.add(observation("a", 0), received_at_monotonic=0)
    assert detector.add(observation("b", 3.001), received_at_monotonic=3.001) is None
    assert detector.counters.candidates_expired == 1
    assert detector.add(observation("a", 4)) is not None


def test_silent_candidate_expires_and_next_can_start():
    detector = PassageDetector(WINDOW)
    detector.add(observation("a", 0), received_at_monotonic=0)
    detector.advance_time(3)
    assert len(detector.states) == 1
    detector.advance_time(3.001)
    assert detector.states == {}
    assert detector.counters.candidates_expired == 1
    assert detector.add(observation("b", 5), received_at_monotonic=5) is None
    assert detector.counters.candidates_started == 2


def test_tags_and_portals_are_independent():
    detector = PassageDetector(WINDOW)
    for epc, portal in (("X", 1), ("Y", 1), ("X", 2)):
        detector.add(observation("a", 0, epc=epc, portal=portal), received_at_monotonic=0)
    passages = [
        detector.add(observation("b", 1, epc=epc, portal=portal), received_at_monotonic=1)
        for epc, portal in (("X", 1), ("Y", 1), ("X", 2))
    ]
    assert all(passages)
    assert {(item.epc, item.portal_id) for item in passages} == {
        ("X", 1), ("Y", 1), ("X", 2)
    }


def test_tied_timestamps_and_out_of_order_arrival_are_deterministic():
    a, b = observation("a", 0), observation("b", 0)
    forward = PassageDetector(WINDOW)
    reverse = PassageDetector(WINDOW)
    forward.add(a)
    reverse.add(b)
    assert forward.add(b) == reverse.add(a)
    late = PassageDetector(WINDOW)
    late.add(observation("b", 1))
    result = late.add(observation("a", 0))
    assert (result.first_side, result.second_side) == ("a", "b")


def test_activity_cluster_rearms_only_after_silence_in_event_time():
    detector = PassageDetector(WINDOW)
    detector.add(observation("a", 0), received_at_monotonic=0)
    first = detector.add(observation("b", 1), received_at_monotonic=1)
    detector.mark_persisted(first, duplicate=False)
    for side, second in (("b", 2), ("a", 3), ("b", 5)):
        assert detector.add(observation(side, second), received_at_monotonic=second) is None
    assert detector.counters.activity_suppressed == 3
    assert detector.add(observation("a", 8.001), received_at_monotonic=8.001) is None
    second = detector.add(observation("b", 9), received_at_monotonic=9)
    assert second is not None
    detector.mark_persisted(second, duplicate=True)
    assert detector.counters.passages_duplicates == 1
    assert detector.counters.passages_confirmed == 1


def test_failed_persistence_keeps_proposal_for_retry():
    detector = PassageDetector(WINDOW)
    detector.add(observation("a", 0), received_at_monotonic=0)
    proposal = detector.add(observation("b", 1), received_at_monotonic=1)
    detector.advance_time(100)
    assert detector.pending() == (proposal,)
    detector.mark_persisted(proposal, duplicate=False)
    assert detector.pending() == ()


def test_service_retries_failed_persistence_without_losing_raw_ack_boundary():
    class Repository:
        attempts = 0

        def resolve(self, item):
            return item

        def persist(self, passage):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("private database detail")
            return True

    repository = Repository()
    service = PassageInferenceService(
        PassageDetector(WINDOW), repository, monotonic_clock=lambda: 0
    )
    service.handle_observation(observation("a", 0))
    service.handle_observation(observation("b", 1))
    assert service.counters.persistence_failures == 1
    assert len(service.detector.pending()) == 1
    service.tick(0)
    assert repository.attempts == 2
    assert service.detector.pending() == ()
    assert service.detector.counters.passages_confirmed == 1


@pytest.mark.parametrize("interval", [timedelta(0), timedelta(seconds=-1)])
def test_invalid_window(interval):
    with pytest.raises(ValueError):
        PassageDetector(interval)
