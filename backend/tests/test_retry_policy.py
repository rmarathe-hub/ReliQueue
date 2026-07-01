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
