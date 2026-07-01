"""Metrics readiness fixture and seed tests."""

import pytest
from sqlalchemy import func, select

from app.models.enums import JobEventType, JobStatus, WorkerStatus
from app.models.job import Job
from app.models.job_event import JobEvent
from app.models.worker import Worker
from tests.helpers import seed_metrics_dataset


@pytest.mark.asyncio
async def test_seed_metrics_dataset_creates_all_job_statuses(db_session_factory):
    async with db_session_factory() as db:
        data = await seed_metrics_dataset(db)

    assert set(data["jobs"].keys()) >= {
        "pending",
        "running",
        "succeeded",
        "dead_lettered",
        "cancelled",
        "old_pending",
    }


@pytest.mark.asyncio
async def test_seed_metrics_dataset_creates_workers_in_multiple_statuses(db_session_factory):
    async with db_session_factory() as db:
        await seed_metrics_dataset(db)
        online = await db.scalar(
            select(func.count()).select_from(Worker).where(Worker.status == WorkerStatus.ONLINE)
        )
        offline = await db.scalar(
            select(func.count()).select_from(Worker).where(Worker.status == WorkerStatus.OFFLINE)
        )

    assert online == 2
    assert offline == 1


@pytest.mark.asyncio
async def test_seed_metrics_dataset_has_events(db_session_factory):
    async with db_session_factory() as db:
        await seed_metrics_dataset(db)
        event_count = await db.scalar(select(func.count()).select_from(JobEvent))

    assert event_count >= 5


@pytest.mark.asyncio
async def test_seed_metrics_dataset_succeeded_jobs_have_completed_at(db_session_factory):
    async with db_session_factory() as db:
        data = await seed_metrics_dataset(db)
        succeeded = data["jobs"]["succeeded"]

    assert succeeded.completed_at is not None
    assert succeeded.started_at is not None


@pytest.mark.asyncio
async def test_seed_metrics_dataset_multiple_queues(db_session_factory):
    async with db_session_factory() as db:
        await seed_metrics_dataset(db)
        queues = await db.execute(select(Job.queue_name).distinct())

    queue_names = {row[0] for row in queues.all()}
    assert "default" in queue_names
    assert "metrics-q" in queue_names


@pytest.mark.asyncio
async def test_pending_queue_depth_countable(db_session_factory):
    from app.services.workers import count_available_jobs

    async with db_session_factory() as db:
        await seed_metrics_dataset(db)
        depth = await count_available_jobs(db, "metrics-q")

    assert depth >= 1
