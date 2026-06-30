import uuid
from datetime import UTC, datetime

import pytest

from app.models.enums import JobStatus
from app.models.job import Job
from app.worker.handlers import (
    UnknownJobTypeError,
    execute_job,
    get_handler,
    get_registered_job_types,
)


def make_job(
    *,
    job_type: str,
    payload: dict | None = None,
    attempts: int = 0,
) -> Job:
    now = datetime.now(UTC)
    return Job(
        id=uuid.uuid4(),
        job_type=job_type,
        payload=payload or {},
        status=JobStatus.PENDING,
        queue_name="default",
        priority=0,
        max_attempts=3,
        attempts=attempts,
        run_at=now,
        created_at=now,
        updated_at=now,
    )


def test_registered_job_types():
    assert get_registered_job_types() == [
        "fail_always",
        "fail_once",
        "generate_report",
        "random_fail",
        "sleep",
    ]


def test_get_handler_returns_callable_for_known_job_type():
    handler = get_handler("sleep")
    assert handler is not None
    assert handler.__name__ == "handle_sleep"


@pytest.mark.asyncio
async def test_sleep_handler_waits(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("app.worker.handlers.asyncio.sleep", fake_sleep)

    job = make_job(job_type="sleep", payload={"seconds": 3})
    await execute_job(job)

    assert slept == [3.0]


@pytest.mark.asyncio
async def test_fail_once_raises_on_first_attempt():
    job = make_job(job_type="fail_once", attempts=1)

    with pytest.raises(RuntimeError, match="one-time failure"):
        await execute_job(job)


@pytest.mark.asyncio
async def test_fail_once_succeeds_on_retry():
    job = make_job(job_type="fail_once", attempts=2)
    await execute_job(job)


@pytest.mark.asyncio
async def test_fail_always_raises():
    job = make_job(job_type="fail_always", payload={"message": "boom"})

    with pytest.raises(RuntimeError, match="boom"):
        await execute_job(job)


@pytest.mark.asyncio
async def test_random_fail_respects_probability(monkeypatch):
    monkeypatch.setattr("app.worker.handlers.random.random", lambda: 0.1)
    job = make_job(job_type="random_fail", payload={"probability": 0.5})

    with pytest.raises(RuntimeError, match="random failure"):
        await execute_job(job)


@pytest.mark.asyncio
async def test_random_fail_can_succeed(monkeypatch):
    monkeypatch.setattr("app.worker.handlers.random.random", lambda: 0.9)
    job = make_job(job_type="random_fail", payload={"probability": 0.5})
    await execute_job(job)


@pytest.mark.asyncio
async def test_generate_report_simulates_work(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("app.worker.handlers.asyncio.sleep", fake_sleep)

    job = make_job(
        job_type="generate_report",
        payload={"duration": 4, "report_name": "weekly-summary"},
    )
    await execute_job(job)

    assert slept == [4.0]


@pytest.mark.asyncio
async def test_unknown_job_type_raises():
    job = make_job(job_type="does_not_exist")

    with pytest.raises(UnknownJobTypeError):
        await execute_job(job)
