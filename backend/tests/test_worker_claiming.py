from datetime import UTC, datetime

import pytest
from sqlalchemy import select

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
