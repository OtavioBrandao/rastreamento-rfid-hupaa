"""Semântica pura da ISS-014, sem MQTT ou PostgreSQL."""

from datetime import datetime, timedelta, timezone

import pytest

from rfid_inference.debounce import DebounceProcessor, DebounceReading

BASE = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)


def reading(
    milliseconds: int,
    *,
    reading_id: int | None = None,
    epc: str = "EPC-A",
    antenna_id: int = 1,
    rssi: float | None = None,
) -> DebounceReading:
    identifier = milliseconds if reading_id is None else reading_id
    return DebounceReading(
        event_id=f"event-{identifier}",
        reading_id=identifier,
        epc=epc,
        antenna_id=antenna_id,
        observed_at=BASE + timedelta(milliseconds=milliseconds),
        rssi=rssi,
    )


def processor(window_ms: int = 100, tolerance_ms: int = 500) -> DebounceProcessor:
    return DebounceProcessor.from_milliseconds(window_ms, tolerance_ms)


def test_simple_burst_becomes_one_observation() -> None:
    debounce = processor()
    results = [debounce.add(reading(value)) for value in (0, 30, 70, 120)]

    assert [result.incorporated for result in results] == [False, True, True, True]
    observation, = debounce.flush()
    assert observation.reading_count == 4
    assert observation.first_seen_at == BASE
    assert observation.last_seen_at == BASE + timedelta(milliseconds=120)
    assert debounce.counters.readings_received == 4
    assert debounce.counters.readings_incorporated == 3
    assert debounce.counters.observations_finalized == 1


def test_gap_greater_than_window_starts_another_observation() -> None:
    debounce = processor()
    debounce.add(reading(0))
    debounce.add(reading(101))

    assert [item.reading_count for item in debounce.flush()] == [1, 1]


def test_gap_exactly_equal_to_window_stays_in_same_observation() -> None:
    debounce = processor(window_ms=100)
    debounce.add(reading(0))
    debounce.add(reading(100))

    observation, = debounce.flush()
    assert observation.reading_count == 2


def test_different_antennas_never_merge() -> None:
    debounce = processor()
    debounce.add(reading(0, antenna_id=1))
    debounce.add(reading(10, antenna_id=2))

    observations = debounce.flush()
    assert len(observations) == 2
    assert {item.antenna_id for item in observations} == {1, 2}


def test_different_epcs_never_merge() -> None:
    debounce = processor()
    debounce.add(reading(0, epc="EPC-A"))
    debounce.add(reading(10, epc="EPC-B"))

    observations = debounce.flush()
    assert len(observations) == 2
    assert {item.epc for item in observations} == {"EPC-A", "EPC-B"}


def test_out_of_order_events_inside_tolerance_are_order_independent() -> None:
    def consolidate(order: tuple[int, ...]):
        debounce = processor(window_ms=60, tolerance_ms=200)
        for value in order:
            debounce.add(reading(value, reading_id=value + 1))
        return debounce.flush()

    ordered = consolidate((0, 50, 100, 180))
    reordered = consolidate((100, 0, 180, 50))

    assert reordered == ordered
    assert [item.reading_count for item in ordered] == [3, 1]


def test_event_older_than_watermark_is_reported_and_does_not_reopen_finalized() -> None:
    debounce = processor(window_ms=100, tolerance_ms=100)
    debounce.add(reading(0))
    result = debounce.add(reading(1000))

    first, = result.finalized
    assert first.reading_count == 1
    late = debounce.add(reading(50))
    assert late.late is True
    assert late.accepted is False
    second, = debounce.flush()
    assert second.first_seen_at == BASE + timedelta(milliseconds=1000)
    assert debounce.counters.late_events == 1


def test_rssi_statistics_ignore_null_and_all_null_stays_absent() -> None:
    debounce = processor()
    for item in (
        reading(0, rssi=-50),
        reading(10, rssi=None),
        reading(20, rssi=-40),
        reading(30, rssi=-30),
    ):
        debounce.add(item)

    observation, = debounce.flush()
    assert observation.rssi_min == -50
    assert observation.rssi_max == -30
    assert observation.rssi_mean == -40

    all_null = processor()
    all_null.add(reading(0))
    null_observation, = all_null.flush()
    assert null_observation.rssi_min is None
    assert null_observation.rssi_max is None
    assert null_observation.rssi_mean is None


def test_reading_references_follow_event_time_not_arrival_time() -> None:
    debounce = processor()
    debounce.add(reading(80, reading_id=8))
    debounce.add(reading(0, reading_id=1))
    debounce.add(reading(40, reading_id=4))

    observation, = debounce.flush()
    assert observation.first_reading_id == 1
    assert observation.last_reading_id == 8
    assert observation.first_event_id == "event-1"
    assert observation.last_event_id == "event-8"
    assert observation.first_seen_at == BASE
    assert observation.last_seen_at == BASE + timedelta(milliseconds=80)


def test_flush_is_deterministic_and_does_not_emit_twice() -> None:
    debounce = processor()
    debounce.add(reading(0))

    assert len(debounce.flush()) == 1
    assert debounce.flush() == ()


def test_silent_antenna_finalizes_without_another_reading_on_that_key() -> None:
    debounce = processor(window_ms=250, tolerance_ms=1000)
    for event_ms, received_at in ((0, 0.0), (50, 0.05), (100, 0.1)):
        debounce.add(
            reading(event_ms, antenna_id=1),
            received_at_monotonic=received_at,
        )

    assert debounce.advance_time(1.349) == ()
    first, = debounce.advance_time(1.351)
    assert (first.antenna_id, first.reading_count) == (1, 3)
    assert debounce.advance_time(1.352) == ()

    debounce.add(reading(1360, antenna_id=2), received_at_monotonic=1.36)
    debounce.add(reading(1410, antenna_id=2), received_at_monotonic=1.41)
    second, = debounce.advance_time(2.661)
    assert (second.antenna_id, second.reading_count) == (2, 2)
    assert debounce.flush() == ()
    assert debounce.counters.readings_received == 5
    assert debounce.counters.readings_incorporated == 3
    assert debounce.counters.observations_finalized == 2


def test_event_after_automatic_finalization_is_late_and_cannot_reopen() -> None:
    debounce = processor(window_ms=250, tolerance_ms=1000)
    debounce.add(reading(0), received_at_monotonic=0.0)
    debounce.add(reading(100), received_at_monotonic=0.1)
    finalized, = debounce.advance_time(1.351)

    late = debounce.add(reading(50), received_at_monotonic=1.4)
    assert late.late is True
    assert late.finalized == ()
    assert debounce.advance_time(3.0) == ()
    assert debounce.flush() == ()
    assert finalized.reading_count == 2
    assert debounce.counters.readings_received == 3
    assert debounce.counters.readings_incorporated == 1
    assert debounce.counters.observations_finalized == 1
    assert debounce.counters.late_events == 1


def test_silence_deadline_is_strictly_exceeded() -> None:
    debounce = processor(window_ms=1000, tolerance_ms=1000)
    debounce.add(reading(0), received_at_monotonic=10.0)

    assert debounce.advance_time(12.0) == ()
    observation, = debounce.advance_time(12.001)
    assert observation.reading_count == 1


def test_reordered_readings_still_match_when_finalized_by_silence() -> None:
    def consolidate(order: tuple[int, ...]):
        debounce = processor(window_ms=100, tolerance_ms=500)
        for arrival, event_ms in enumerate(order):
            debounce.add(
                reading(event_ms, reading_id=event_ms + 1),
                received_at_monotonic=arrival * 0.01,
            )
        return debounce.advance_time(0.7)

    assert consolidate((0, 50, 100)) == consolidate((100, 0, 50))


@pytest.mark.parametrize(
    "window,tolerance",
    [(timedelta(0), timedelta(0)), (timedelta(milliseconds=-1), timedelta(0)),
     (timedelta(milliseconds=1), timedelta(milliseconds=-1))],
)
def test_invalid_constructor_values_are_rejected(window, tolerance) -> None:
    with pytest.raises(ValueError):
        DebounceProcessor(window, tolerance)


def test_reading_timestamp_requires_timezone() -> None:
    with pytest.raises(ValueError, match="fuso"):
        DebounceReading("event", 1, "EPC", 1, datetime(2026, 1, 1))
