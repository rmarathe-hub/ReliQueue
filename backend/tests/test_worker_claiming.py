from datetime import UTC, datetime, timedelta

import asyncio

import pytest
from sqlalchemy import func, select

from app.models.enums import JobEventType, JobStatus
from app.models.job import Job
from app.models.job_event import JobEvent
from app.services.job_claiming import claim_next_job
from app.services.workers import register_worker


async def create_pending_job(db, **overrides) -> Job:
    now = datetime.now(UTC)
    values = {
        "job_type": "sleep",
        "payload": {"seconds": 1},
        "status": JobStatus.PENDING,
        "queue_name": "default",
        "priority": 0,
        "max_attempts": 3,
        "attempts": 0,
        "run_at": now,
    }
    values.update(overrides)
    job = Job(**values)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


@pytest.mark.asyncio
async def test_claim_next_job_returns_none_when_queue_empty(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert claimed is None


@pytest.mark.asyncio
async def test_claim_next_job_marks_job_running(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db)

    async with db_session_factory() as db:
        claimed = await claim_next_job(
            db,
            worker_id="worker-1",
            queue_name="default",
            lease_seconds=30,
        )

    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.status == JobStatus.RUNNING
    assert claimed.locked_by == "worker-1"
    assert claimed.locked_at is not None
    assert claimed.lease_expires_at is not None
    assert claimed.attempts == 1
    assert claimed.started_at is not None


@pytest.mark.asyncio
async def test_claim_next_job_creates_job_claimed_event(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert claimed is not None

    async with db_session_factory() as db:
        result = await db.execute(
            select(JobEvent).where(JobEvent.job_id == job.id, JobEvent.event_type == JobEventType.JOB_CLAIMED)
        )
        events = list(result.scalars().all())

    assert len(events) == 1
    assert events[0].payload["worker_id"] == "worker-1"
    assert events[0].payload["attempts"] == 1


@pytest.mark.asyncio
async def test_concurrent_claiming_no_duplicates(db_session_factory):
    job_count = 30
    worker_count = 5
    claim_attempts = job_count * 2

    async with db_session_factory() as db:
        for worker_index in range(worker_count):
            await register_worker(db, f"worker-{worker_index}", "default")
        for job_index in range(job_count):
            await create_pending_job(db, idempotency_key=f"concurrent-{job_index}")

    async def claim_one(worker_id: str) -> Job | None:
        async with db_session_factory() as db:
            return await claim_next_job(db, worker_id=worker_id, queue_name="default")

    results = await asyncio.gather(
        *[claim_one(f"worker-{index % worker_count}") for index in range(claim_attempts)]
    )
    claimed_jobs = [job for job in results if job is not None]
    claimed_ids = [job.id for job in claimed_jobs]

    assert len(claimed_jobs) == job_count
    assert len(claimed_ids) == len(set(claimed_ids))

    async with db_session_factory() as db:
        running_count = await db.scalar(
            select(func.count()).select_from(Job).where(Job.status == JobStatus.RUNNING)
        )
        claim_counts = await db.execute(
            select(func.count())
            .select_from(JobEvent)
            .where(JobEvent.event_type == JobEventType.JOB_CLAIMED)
            .group_by(JobEvent.job_id)
        )

    assert running_count == job_count
    assert all(count == 1 for count in claim_counts.scalars().all())


@pytest.mark.asyncio
async def test_claim_next_job_skips_future_run_at(db_session_factory):
    future = datetime.now(UTC) + timedelta(hours=1)

    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db, run_at=future)
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert claimed is None


@pytest.mark.asyncio
async def test_claim_next_job_skips_cancelled_job(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db, status=JobStatus.CANCELLED)
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert claimed is None


@pytest.mark.asyncio
async def test_claim_next_job_skips_succeeded_job(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db, status=JobStatus.SUCCEEDED)
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert claimed is None


@pytest.mark.asyncio
async def test_claim_next_job_prefers_highest_priority(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db, priority=0, idempotency_key="low-priority")
        high_priority_job = await create_pending_job(db, priority=10, idempotency_key="high-priority")
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert claimed is not None
    assert claimed.id == high_priority_job.id


@pytest.mark.asyncio
async def test_claim_next_job_orders_by_run_at_when_priority_equal(db_session_factory):
    now = datetime.now(UTC)

    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db, run_at=now - timedelta(minutes=1), idempotency_key="later")
        earlier_job = await create_pending_job(db, run_at=now - timedelta(minutes=5), idempotency_key="earlier")
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert claimed is not None
    assert claimed.id == earlier_job.id


@pytest.mark.asyncio
async def test_claim_next_job_sets_lease_in_future(db_session_factory):
    before = datetime.now(UTC)

    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db)
        claimed = await claim_next_job(
            db,
            worker_id="worker-1",
            queue_name="default",
            lease_seconds=60,
        )

    after = datetime.now(UTC)
    assert claimed is not None
    assert claimed.lease_expires_at is not None
    assert claimed.lease_expires_at > before
    assert claimed.lease_expires_at > after
