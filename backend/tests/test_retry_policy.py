from datetime import UTC, datetime

import pytest

from app.services.retry_policy import calculate_retry_delay_seconds, calculate_retry_run_at


def test_calculate_retry_delay_exponential_without_jitter():
    assert calculate_retry_delay_seconds(1, base_delay_seconds=2.0, jitter=False) == 2.0
    assert calculate_retry_delay_seconds(2, base_delay_seconds=2.0, jitter=False) == 4.0
    assert calculate_retry_delay_seconds(3, base_delay_seconds=2.0, jitter=False) == 8.0


def test_calculate_retry_delay_capped_at_max():
    delay = calculate_retry_delay_seconds(
        10,
        base_delay_seconds=2.0,
        max_delay_seconds=30.0,
        jitter=False,
    )

    assert delay == 30.0


def test_calculate_retry_delay_jitter_stays_within_bounds(monkeypatch):
    monkeypatch.setattr("app.services.retry_policy.random.random", lambda: 0.0)

    delay = calculate_retry_delay_seconds(1, base_delay_seconds=10.0, jitter=True)

    assert delay == 5.0


def test_calculate_retry_run_at_returns_future_timestamp():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    retry_at = calculate_retry_run_at(
        now,
        2,
        base_delay_seconds=3.0,
        max_delay_seconds=300.0,
        jitter=False,
    )

    assert retry_at == datetime(2026, 1, 1, 0, 0, 6, tzinfo=UTC)


@pytest.mark.parametrize(
    "attempt,expected",
    [
        (1, 1.0),
        (2, 2.0),
        (3, 4.0),
    ],
)
def test_calculate_retry_delay_by_attempt_without_jitter(attempt, expected):
    delay = calculate_retry_delay_seconds(
        attempt,
        base_delay_seconds=1.0,
        jitter=False,
    )
    assert delay == expected


def test_calculate_retry_delay_never_negative():
    for attempt in range(0, 5):
        delay = calculate_retry_delay_seconds(attempt, base_delay_seconds=1.0, jitter=True)
        assert delay >= 0


def test_calculate_retry_delay_jitter_upper_bound(monkeypatch):
    monkeypatch.setattr("app.services.retry_policy.random.random", lambda: 1.0)

    delay = calculate_retry_delay_seconds(1, base_delay_seconds=10.0, jitter=True)

    assert delay == 10.0


def test_calculate_retry_delay_respects_base_and_max_config():
    delay = calculate_retry_delay_seconds(
        20,
        base_delay_seconds=5.0,
        max_delay_seconds=60.0,
        jitter=False,
    )
    assert delay == 60.0


def test_calculate_retry_delay_jitter_disabled_is_deterministic():
    first = calculate_retry_delay_seconds(2, base_delay_seconds=2.0, jitter=False)
    second = calculate_retry_delay_seconds(2, base_delay_seconds=2.0, jitter=False)
    assert first == second == 4.0
