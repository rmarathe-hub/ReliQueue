"""Extended lease recovery edge tests."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.enums import JobEventType, JobStatus
from app.models.job_event import JobEvent
from app.services.job_claiming import claim_next_job
from app.services.job_lease_recovery import recover_expired_leases
from app.services.workers import register_worker
from sqlalchemy import select

from tests.helpers import create_pending_job


@pytest.mark.asyncio
async def test_recovery_skips_cancelled_and_dead_lettered(db_session_factory):
    expired = datetime.now(UTC) - timedelta(minutes=1)
    async with db_session_factory() as db:
        for status in (JobStatus.CANCELLED, JobStatus.DEAD_LETTERED):
            job = await create_pending_job(db, status=status)
            job.lease_expires_at = expired
            job.locked_by = "ghost"
        await db.commit()
        recovered = await recover_expired_leases(db)

    assert recovered == []


@pytest.mark.asyncio
async def test_recovery_is_idempotent_when_called_twice(db_session_factory):
    expired = datetime.now(UTC) - timedelta(minutes=1)
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        stored = await db.get(type(claimed), claimed.id)
        stored.lease_expires_at = expired
        await db.commit()

    async with db_session_factory() as db:
        first = await recover_expired_leases(db, queue_name="default")
        second = await recover_expired_leases(db, queue_name="default")

    assert len(first) == 1
    assert second == []


@pytest.mark.asyncio
async def test_recovery_recovers_multiple_expired_jobs(db_session_factory):
    expired = datetime.now(UTC) - timedelta(minutes=1)
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        for _ in range(3):
            job = await create_pending_job(db)
            claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
            stored = await db.get(type(claimed), claimed.id)
            stored.lease_expires_at = expired
            await db.commit()

    async with db_session_factory() as db:
        recovered = await recover_expired_leases(db, queue_name="default")

    assert len(recovered) == 3
    assert all(job.status == JobStatus.PENDING for job in recovered)


@pytest.mark.asyncio
async def test_recovery_preserves_attempts(db_session_factory):
    expired = datetime.now(UTC) - timedelta(minutes=1)
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db, max_attempts=5)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        stored = await db.get(type(claimed), claimed.id)
        stored.lease_expires_at = expired
        attempts_before = stored.attempts
        await db.commit()

    async with db_session_factory() as db:
        recovered = await recover_expired_leases(db, queue_name="default")

    assert recovered[0].attempts == attempts_before


@pytest.mark.asyncio
async def test_recovery_safe_when_no_workers_exist(db_session_factory):
    expired = datetime.now(UTC) - timedelta(minutes=1)
    async with db_session_factory() as db:
        job = await create_pending_job(db, status=JobStatus.RUNNING, attempts=1)
        job.locked_by = "ghost-worker"
        job.lease_expires_at = expired
        await db.commit()
        recovered = await recover_expired_leases(db)

    assert len(recovered) == 1
    assert recovered[0].locked_by is None

    async with db_session_factory() as db:
        result = await db.execute(
            select(JobEvent).where(
                JobEvent.job_id == job.id,
                JobEvent.event_type == JobEventType.JOB_LEASE_EXPIRED,
            )
        )
        assert result.scalar_one_or_none() is not None
