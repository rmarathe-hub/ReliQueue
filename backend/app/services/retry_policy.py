import random
from datetime import datetime, timedelta


def calculate_retry_delay_seconds(
    attempts: int,
    *,
    base_delay_seconds: float = 1.0,
    max_delay_seconds: float = 300.0,
    jitter: bool = True,
) -> float:
    exponent = max(attempts - 1, 0)
    delay = min(base_delay_seconds * (2**exponent), max_delay_seconds)

    if jitter:
        delay *= 0.5 + random.random() * 0.5

    return delay


def calculate_retry_run_at(
    now: datetime,
    attempts: int,
    *,
    base_delay_seconds: float = 1.0,
    max_delay_seconds: float = 300.0,
    jitter: bool = True,
) -> datetime:
    delay_seconds = calculate_retry_delay_seconds(
        attempts,
        base_delay_seconds=base_delay_seconds,
        max_delay_seconds=max_delay_seconds,
        jitter=jitter,
    )
    return now + timedelta(seconds=delay_seconds)
