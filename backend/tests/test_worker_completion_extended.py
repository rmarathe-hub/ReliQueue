"""Extended success completion tests."""

import pytest
from sqlalchemy import select

from app.models.enums import JobStatus
from app.models.job import Job
from app.models.worker import Worker
from app.services.job_claiming import claim_next_job
from app.services.job_completion import complete_job_success
from app.services.workers import register_worker
from tests.helpers import create_pending_job


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [JobStatus.CANCELLED, JobStatus.DEAD_LETTERED, JobStatus.SUCCEEDED],
)
async def test_complete_job_success_rejects_non_running_status(db_session_factory, status):
    async with db_session_factory() as db:
        job = await create_pending_job(db, status=status)
        result = await complete_job_success(db, job.id, "worker-1")

    assert result is None


@pytest.mark.asyncio
async def test_complete_job_success_clears_worker_current_job_id(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        await complete_job_success(db, claimed.id, "worker-1")
        worker = await db.get(Worker, "worker-1")

    assert worker.current_job_id is None


@pytest.mark.asyncio
async def test_complete_job_success_does_not_mutate_unrelated_jobs(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        target = await create_pending_job(db, idempotency_key="complete-target")
        other = await create_pending_job(db, idempotency_key="complete-other")

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        await complete_job_success(db, claimed.id, "worker-1")

    async with db_session_factory() as db:
        result = await db.execute(select(Job).where(Job.id == other.id))
        untouched = result.scalar_one()

    assert untouched.status == JobStatus.PENDING
    assert untouched.attempts == 0


@pytest.mark.asyncio
async def test_complete_job_success_does_not_clear_unrelated_worker(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await register_worker(db, "worker-2", "default")
        job = await create_pending_job(db)
        worker2 = await db.get(Worker, "worker-2")
        worker2.current_job_id = job.id
        await db.commit()

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        await complete_job_success(db, claimed.id, "worker-1")
        worker2 = await db.get(Worker, "worker-2")

    assert worker2.current_job_id == job.id
