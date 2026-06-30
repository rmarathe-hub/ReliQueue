from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models.enums import JobEventType, JobStatus
from app.models.job import Job
from app.models.job_event import JobEvent
from app.services.job_claiming import claim_next_job
from app.services.job_completion import complete_job_success
from app.services.workers import register_worker
from app.worker.handlers import execute_job
from tests.test_worker_claiming import create_pending_job


@pytest.mark.asyncio
async def test_complete_job_success_updates_job(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert claimed is not None

    async with db_session_factory() as db:
        completed = await complete_job_success(db, claimed.id, "worker-1")

    assert completed is not None
    assert completed.status == JobStatus.SUCCEEDED
    assert completed.completed_at is not None
    assert completed.locked_by is None
    assert completed.locked_at is None
    assert completed.lease_expires_at is None


@pytest.mark.asyncio
async def test_complete_job_success_creates_event(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    async with db_session_factory() as db:
        await complete_job_success(db, claimed.id, "worker-1")

    async with db_session_factory() as db:
        result = await db.execute(
            select(JobEvent).where(
                JobEvent.job_id == job.id,
                JobEvent.event_type == JobEventType.JOB_SUCCEEDED,
            )
        )
        events = list(result.scalars().all())

    assert len(events) == 1
    assert events[0].payload["worker_id"] == "worker-1"


@pytest.mark.asyncio
async def test_sleep_job_runs_to_succeeded(db_session_factory, monkeypatch):
    async def fake_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr("app.worker.handlers.asyncio.sleep", fake_sleep)

    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db, payload={"seconds": 0})

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert claimed is not None
    await execute_job(claimed)

    async with db_session_factory() as db:
        completed = await complete_job_success(db, claimed.id, "worker-1")

    assert completed is not None
    assert completed.status == JobStatus.SUCCEEDED

    async with db_session_factory() as db:
        result = await db.execute(select(Job).where(Job.id == claimed.id))
        stored_job = result.scalar_one()
        event_types = await db.execute(
            select(JobEvent.event_type).where(JobEvent.job_id == claimed.id).order_by(JobEvent.created_at.asc())
        )

    assert stored_job.status == JobStatus.SUCCEEDED
    assert [row[0] for row in event_types.all()] == [
        JobEventType.JOB_CLAIMED,
        JobEventType.JOB_SUCCEEDED,
    ]
