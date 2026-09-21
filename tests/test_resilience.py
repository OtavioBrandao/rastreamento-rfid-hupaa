from __future__ import annotations

from threading import Event

import pytest

from rfid_ingestion.resilience import Backoff, BackoffPolicy


def test_first_delay_exponential_growth_and_maximum() -> None:
    backoff = Backoff(
        BackoffPolicy(1, 5, 2, 0),
        random_source=lambda: 0.5,
    )

    assert [backoff.next_delay() for _ in range(5)] == [1, 2, 4, 5, 5]


def test_jitter_stays_inside_bounds_and_maximum() -> None:
    policy = BackoffPolicy(10, 20, 2, 0.25)

    assert Backoff(policy, random_source=lambda: 0).next_delay() == 7.5
    assert Backoff(policy, random_source=lambda: 1).next_delay() == 12.5
    capped = Backoff(policy, random_source=lambda: 1)
    capped.next_delay()
    assert capped.next_delay() == 20


def test_reset_starts_again_from_first_delay() -> None:
    backoff = Backoff(BackoffPolicy(1, 30, 2, 0))

    assert [backoff.next_delay(), backoff.next_delay()] == [1, 2]
    backoff.reset()
    assert backoff.next_delay() == 1


def test_wait_is_cancelled_without_sleeping_full_delay() -> None:
    stop = Event()
    stop.set()
    backoff = Backoff(BackoffPolicy(60, 60, 1, 0))

    should_continue, delay = backoff.wait(stop)

    assert not should_continue
    assert delay == 60


@pytest.mark.parametrize(
    "policy",
    [
        BackoffPolicy(1, 1, 1, 0),
    ],
)
def test_policy_accepts_boundary_values(policy) -> None:
    assert policy.jitter == 0


@pytest.mark.parametrize(
    "values",
    [
        (0, 1, 2, 0),
        (2, 1, 2, 0),
        (1, 2, 0.5, 0),
        (1, 2, 2, -0.1),
        (1, 2, 2, 1.1),
        (1, float("inf"), 2, 0),
    ],
)
def test_invalid_policy_is_rejected(values) -> None:
    with pytest.raises(ValueError):
        BackoffPolicy(*values)
