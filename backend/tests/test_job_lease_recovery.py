from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.enums import JobEventType, JobStatus
from app.models.job import Job
from app.models.job_event import JobEvent
from app.models.worker import Worker
from app.services.job_claiming import claim_next_job
from app.services.job_lease_recovery import recover_expired_leases
from app.services.workers import register_worker
from tests.test_worker_claiming import create_pending_job


@pytest.mark.asyncio
async def test_recover_expired_lease_moves_job_to_pending(db_session_factory):
    expired_at = datetime.now(UTC) - timedelta(minutes=1)

    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db, idempotency_key="lease-recover-1")

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    async with db_session_factory() as db:
        stored = await db.get(Job, claimed.id)
        stored.lease_expires_at = expired_at
        await db.commit()

    async with db_session_factory() as db:
        recovered = await recover_expired_leases(db, queue_name="default")

    assert len(recovered) == 1
    assert recovered[0].id == job.id
    assert recovered[0].status == JobStatus.PENDING
    assert recovered[0].locked_by is None
    assert recovered[0].locked_at is None
    assert recovered[0].lease_expires_at is None


@pytest.mark.asyncio
async def test_recover_expired_lease_creates_event(db_session_factory):
    expired_at = datetime.now(UTC) - timedelta(minutes=1)

    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db, idempotency_key="lease-recover-event-1")

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        stored = await db.get(Job, claimed.id)
        stored.lease_expires_at = expired_at
        await db.commit()

    async with db_session_factory() as db:
        await recover_expired_leases(db, queue_name="default")

    async with db_session_factory() as db:
        result = await db.execute(
            select(JobEvent).where(
                JobEvent.job_id == job.id,
                JobEvent.event_type == JobEventType.JOB_LEASE_EXPIRED,
            )
        )
        events = list(result.scalars().all())

    assert len(events) == 1
    assert events[0].payload["worker_id"] == "worker-1"
    assert events[0].payload["attempts"] == 1


@pytest.mark.asyncio
async def test_recover_expired_lease_clears_worker_current_job(db_session_factory):
    expired_at = datetime.now(UTC) - timedelta(minutes=1)

    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db, idempotency_key="lease-recover-worker-1")

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        stored = await db.get(Job, claimed.id)
        stored.lease_expires_at = expired_at
        await db.commit()

    async with db_session_factory() as db:
        await recover_expired_leases(db, queue_name="default")
        worker = await db.get(Worker, "worker-1")

    assert worker is not None
    assert worker.current_job_id is None


@pytest.mark.asyncio
async def test_recover_expired_lease_skips_active_lease(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db, idempotency_key="lease-recover-active-1")

    async with db_session_factory() as db:
        await claim_next_job(db, worker_id="worker-1", queue_name="default")

    async with db_session_factory() as db:
        recovered = await recover_expired_leases(db, queue_name="default")

    assert recovered == []


@pytest.mark.asyncio
async def test_recovered_job_can_be_claimed_again(db_session_factory):
    expired_at = datetime.now(UTC) - timedelta(minutes=1)

    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await register_worker(db, "worker-2", "default")
        job = await create_pending_job(db, idempotency_key="lease-recover-reclaim-1")

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        stored = await db.get(Job, claimed.id)
        stored.lease_expires_at = expired_at
        await db.commit()

    async with db_session_factory() as db:
        await recover_expired_leases(db, queue_name="default")

    async with db_session_factory() as db:
        reclaimed = await claim_next_job(db, worker_id="worker-2", queue_name="default")

    assert reclaimed is not None
    assert reclaimed.id == job.id
    assert reclaimed.status == JobStatus.RUNNING
    assert reclaimed.locked_by == "worker-2"
    assert reclaimed.attempts == 2
