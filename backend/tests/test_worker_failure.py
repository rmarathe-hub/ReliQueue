import pytest
from datetime import UTC, datetime, timedelta
from sqlalchemy import select

from app.models.enums import JobEventType, JobStatus
from app.models.job_event import JobEvent
from app.services.job_claiming import claim_next_job
from app.services.job_completion import complete_job_success
from app.services.job_failure import complete_job_failure
from app.services.workers import register_worker
from app.worker.handlers import execute_job
from tests.test_worker_claiming import create_pending_job


@pytest.mark.asyncio
async def test_complete_job_failure_schedules_retry_when_attempts_remain(db_session_factory, monkeypatch):
    fixed_now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    fixed_retry = datetime(2026, 1, 1, 12, 0, 5, tzinfo=UTC)

    class FixedDateTime:
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr("app.services.job_failure.datetime", FixedDateTime)
    monkeypatch.setattr(
        "app.services.job_failure.calculate_retry_run_at",
        lambda now, attempts, **kwargs: fixed_retry,
    )

    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db, max_attempts=3)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert claimed is not None

    async with db_session_factory() as db:
        failed = await complete_job_failure(db, claimed.id, "worker-1", "simulated failure")

    assert failed is not None
    assert failed.status == JobStatus.PENDING
    assert failed.last_error == "simulated failure"
    assert failed.locked_by is None
    assert failed.locked_at is None
    assert failed.lease_expires_at is None
    assert failed.attempts == 1
    assert failed.run_at == fixed_retry
    assert failed.run_at > fixed_now

    async with db_session_factory() as db:
        result = await db.execute(
            select(JobEvent).where(
                JobEvent.job_id == job.id,
                JobEvent.event_type == JobEventType.JOB_RETRY_SCHEDULED,
            )
        )
        events = list(result.scalars().all())

    assert len(events) == 1
    assert events[0].payload["run_at"] == fixed_retry.isoformat()
    assert events[0].payload["delay_seconds"] == 5.0


@pytest.mark.asyncio
async def test_complete_job_failure_dead_letters_when_max_attempts_reached(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db, max_attempts=1)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert claimed is not None

    async with db_session_factory() as db:
        failed = await complete_job_failure(db, claimed.id, "worker-1", "simulated permanent failure")

    assert failed is not None
    assert failed.status == JobStatus.DEAD_LETTERED
    assert failed.last_error == "simulated permanent failure"
    assert failed.attempts == 1


@pytest.mark.asyncio
async def test_complete_job_failure_creates_job_failed_event(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db, max_attempts=1)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    async with db_session_factory() as db:
        await complete_job_failure(db, claimed.id, "worker-1", "boom")

    async with db_session_factory() as db:
        result = await db.execute(
            select(JobEvent).where(
                JobEvent.job_id == job.id,
                JobEvent.event_type == JobEventType.JOB_FAILED,
            )
        )
        events = list(result.scalars().all())

    assert len(events) == 1
    assert events[0].payload["worker_id"] == "worker-1"
    assert events[0].payload["attempts"] == 1
    assert events[0].payload["error"] == "boom"


@pytest.mark.asyncio
async def test_complete_job_failure_ignores_wrong_worker(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await register_worker(db, "worker-2", "default")
        job = await create_pending_job(db, max_attempts=1)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    async with db_session_factory() as db:
        result = await complete_job_failure(db, claimed.id, "worker-2", "wrong worker")

    assert result is None


@pytest.mark.asyncio
async def test_failed_job_not_claimed_before_retry_time(db_session_factory, monkeypatch):
    future_retry = datetime.now(UTC) + timedelta(seconds=60)

    monkeypatch.setattr(
        "app.services.job_failure.calculate_retry_run_at",
        lambda now, attempts, **kwargs: future_retry,
    )

    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db, max_attempts=3)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    async with db_session_factory() as db:
        await complete_job_failure(db, claimed.id, "worker-1", "simulated failure")

    async with db_session_factory() as db:
        not_ready = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert not_ready is None


@pytest.mark.asyncio
async def test_fail_always_dead_letters_after_max_attempts(db_session_factory, no_retry_delay):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(
            db,
            job_type="fail_always",
            payload={"message": "simulated permanent failure"},
            max_attempts=3,
        )

    for expected_status in (JobStatus.PENDING, JobStatus.PENDING, JobStatus.DEAD_LETTERED):
        async with db_session_factory() as db:
            claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

        assert claimed is not None

        with pytest.raises(RuntimeError, match="simulated permanent failure"):
            await execute_job(claimed)

        async with db_session_factory() as db:
            failed = await complete_job_failure(
                db,
                claimed.id,
                "worker-1",
                "simulated permanent failure",
            )

        assert failed is not None
        assert failed.status == expected_status

    async with db_session_factory() as db:
        claimed_again = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert claimed_again is None


@pytest.mark.asyncio
async def test_fail_once_retries_then_succeeds(db_session_factory, no_retry_delay):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db, job_type="fail_once", max_attempts=3)

    async with db_session_factory() as db:
        first_claim = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert first_claim is not None

    with pytest.raises(RuntimeError, match="simulated one-time failure"):
        await execute_job(first_claim)

    async with db_session_factory() as db:
        failed = await complete_job_failure(db, first_claim.id, "worker-1", "simulated one-time failure")

    assert failed is not None
    assert failed.status == JobStatus.PENDING

    async with db_session_factory() as db:
        second_claim = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert second_claim is not None
    assert second_claim.attempts == 2
    await execute_job(second_claim)

    async with db_session_factory() as db:
        completed = await complete_job_success(db, second_claim.id, "worker-1")

    assert completed is not None
    assert completed.status == JobStatus.SUCCEEDED
