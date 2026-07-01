"""Extended failure handling tests."""

import pytest
from sqlalchemy import select

from app.models.enums import JobEventType, JobStatus
from app.models.job import Job
from app.models.job_event import JobEvent
from app.models.worker import Worker
from app.services.job_claiming import claim_next_job
from app.services.job_failure import complete_job_failure
from app.services.workers import register_worker
from tests.helpers import create_pending_job


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [JobStatus.PENDING, JobStatus.SUCCEEDED, JobStatus.CANCELLED, JobStatus.DEAD_LETTERED],
)
async def test_complete_job_failure_rejects_non_running_status(db_session_factory, status):
    async with db_session_factory() as db:
        job = await create_pending_job(db, status=status)
        result = await complete_job_failure(db, job.id, "worker-1", "err")

    assert result is None


@pytest.mark.asyncio
async def test_retryable_failure_clears_worker_current_job_id(db_session_factory, no_retry_delay):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db, max_attempts=3)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        await complete_job_failure(db, claimed.id, "worker-1", "err")
        worker = await db.get(Worker, "worker-1")

    assert worker.current_job_id is None


@pytest.mark.asyncio
async def test_dead_lettered_failure_keeps_last_error(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db, max_attempts=1)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        failed = await complete_job_failure(db, claimed.id, "worker-1", "permanent")

    assert failed.status == JobStatus.DEAD_LETTERED
    assert failed.last_error == "permanent"


@pytest.mark.asyncio
async def test_retryable_failure_clears_lock_fields(db_session_factory, no_retry_delay):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db, max_attempts=3)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        failed = await complete_job_failure(db, claimed.id, "worker-1", "err")

    assert failed.locked_by is None
    assert failed.locked_at is None
    assert failed.lease_expires_at is None


@pytest.mark.asyncio
async def test_dead_lettered_failure_clears_lock_fields(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db, max_attempts=1)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        failed = await complete_job_failure(db, claimed.id, "worker-1", "err")

    assert failed.locked_by is None
    assert failed.locked_at is None
    assert failed.lease_expires_at is None


@pytest.mark.asyncio
async def test_failure_does_not_mutate_unrelated_jobs(db_session_factory, no_retry_delay):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db, idempotency_key="fail-target", max_attempts=3)
        other = await create_pending_job(db, idempotency_key="fail-other")

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        await complete_job_failure(db, claimed.id, "worker-1", "err")

    async with db_session_factory() as db:
        result = await db.execute(select(Job).where(Job.id == other.id))
        untouched = result.scalar_one()

    assert untouched.status == JobStatus.PENDING
    assert untouched.last_error is None


@pytest.mark.asyncio
async def test_retryable_failure_writes_job_retry_scheduled_event(db_session_factory, no_retry_delay):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db, max_attempts=3)
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        await complete_job_failure(db, claimed.id, "worker-1", "err")
        result = await db.execute(
            select(JobEvent).where(
                JobEvent.job_id == job.id,
                JobEvent.event_type == JobEventType.JOB_RETRY_SCHEDULED,
            )
        )

    assert len(list(result.scalars().all())) == 1
