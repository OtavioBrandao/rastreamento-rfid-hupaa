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
    detector = PassageDetector(WINDOW, refractory=timedelta(seconds=1))
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


def test_slow_single_reading_observations_can_still_confirm_passage():
    detector = PassageDetector(WINDOW, silence_grace=timedelta(milliseconds=1250))
    for indice in range(70):
        instante = indice * 1.7
        detector.advance_time(instante)
        assert detector.add(observation("a", instante),
                            received_at_monotonic=instante) is None
    instante = 70 * 1.7
    detector.advance_time(instante)
    passagem = detector.add(observation("b", instante),
                            received_at_monotonic=instante)
    assert passagem is not None
    assert (passagem.first_side, passagem.second_side) == ("a", "b")


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


def _walk(detector, steps):
    sides = []
    for side, second in steps:
        passage = detector.add(observation(side, second), received_at_monotonic=second)
        if passage is not None:
            detector.mark_persisted(passage, duplicate=False)
            sides.append(f"{passage.first_side}->{passage.second_side}")
    return sides


def test_continuous_back_and_forth_confirms_every_crossing_without_silence():
    # Ensaio físico 05/10/2026: a tag era lida quase todo segundo; a regra antiga
    # exigia 3 s de silêncio e descartava 25 de 26 travessias.
    detector = PassageDetector(WINDOW, refractory=timedelta(seconds=1))
    steps = [("a", 0), ("b", 1.5), ("b", 2.5), ("a", 4), ("a", 5), ("b", 6.5), ("a", 8)]
    assert _walk(detector, steps) == ["a->b", "b->a", "a->b", "b->a"]
    assert detector.counters.activity_suppressed == 2


def test_refractory_and_overlap_suppress_bounce_after_crossing():
    detector = PassageDetector(WINDOW, refractory=timedelta(seconds=1))
    assert _walk(detector, [("a", 0), ("b", 1), ("a", 1.5)]) == ["a->b"]
    # Lado oposto que começou antes da âncora (sobreposição das antenas).
    assert _walk(detector, [("a", 0.9)]) == []
    assert _walk(detector, [("a", 2.5)]) == ["b->a"]
    assert detector.counters.activity_suppressed == 2


def test_origin_still_reading_tag_is_reflection_not_passage():
    # Tag parada na antena A, lida esporadicamente por B (reflexão).
    calls = []

    def origin_active(origin, destination):
        calls.append((origin.side, destination.side))
        return True

    detector = PassageDetector(WINDOW, origin_active=origin_active)
    assert _walk(detector, [("a", 0), ("b", 1), ("a", 2), ("b", 3)]) == []
    assert calls == [("a", "b"), ("a", "b")]
    assert detector.counters.origin_still_active == 2

    moved = PassageDetector(WINDOW, origin_active=lambda origin, destination: False)
    assert _walk(moved, [("a", 0), ("b", 1)]) == ["a->b"]


def test_reflection_after_confirmed_passage_keeps_destination_anchor():
    active = {"value": False}
    detector = PassageDetector(WINDOW, origin_active=lambda o, d: active["value"])
    assert _walk(detector, [("a", 0), ("b", 1)]) == ["a->b"]
    active["value"] = True
    assert _walk(detector, [("a", 2)]) == []
    active["value"] = False
    assert _walk(detector, [("b", 2.5), ("a", 4)]) == ["b->a"]


def test_return_after_long_absence_starts_new_candidate():
    detector = PassageDetector(WINDOW)
    assert _walk(detector, [("a", 0), ("b", 1), ("a", 10)]) == ["a->b"]
    assert detector.counters.candidates_expired == 1
    assert _walk(detector, [("b", 11)]) == ["a->b"]


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


@pytest.mark.parametrize("dwell_seconds", [3, 10, 30])
def test_tag_staying_at_destination_confirms_passage_without_leaving(dwell_seconds):
    from rfid_inference.debounce import DebounceProcessor, DebounceReading

    debounce = DebounceProcessor.from_milliseconds(250, 1000, 500)
    detector = PassageDetector(WINDOW, silence_grace=timedelta(milliseconds=1750),
                               refractory=timedelta(seconds=1))
    readings = [(seconds / 10, 1) for seconds in range(0, 20, 2)]
    readings += [(2.6 + seconds / 10, 2) for seconds in range(0, dwell_seconds * 10, 2)]
    passages = []

    def deliver(observations, now):
        for item in observations:
            side = "a" if item.antenna_id == 1 else "b"
            proposal = detector.add(PortalObservation(
                item.epc, 1, item.antenna_id, side, 1 if side == "a" else 2, item.antenna_id,
                item.first_seen_at, item.last_seen_at, item.first_reading_id,
                item.last_reading_id, item.first_event_id, item.last_event_id,
            ), received_at_monotonic=now)
            if proposal is not None:
                detector.mark_persisted(proposal, duplicate=False)
                passages.append((now, proposal.first_side, proposal.second_side))

    index = 0
    for tick in range(int((2.6 + dwell_seconds) * 20)):
        now = tick / 20
        while index < len(readings) and readings[index][0] <= now:
            instant, antenna = readings[index]
            index += 1
            result = debounce.add(DebounceReading(
                f"e{index}", index, "X", antenna, T0 + timedelta(seconds=instant)),
                received_at_monotonic=now)
            deliver(result.finalized, now)
        deliver(debounce.advance_time(now), now)
        detector.advance_time(now)

    # A tag continua em B: a passagem sai em ~2 s, sem esperar a saída do alcance.
    assert len(passages) == 1
    detected_at, origin, destination = passages[0]
    assert (origin, destination) == ("a", "b")
    assert detected_at - 2.6 < 2.5
