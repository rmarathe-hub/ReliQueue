"""Extended job claiming service edge tests."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.enums import JobStatus
from app.services.job_claiming import claim_next_job
from app.services.workers import register_worker
from tests.helpers import create_pending_job


@pytest.mark.asyncio
async def test_claim_returns_none_when_queue_empty(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert claimed is None


@pytest.mark.asyncio
async def test_claim_started_at_not_overwritten_on_retry_claim(db_session_factory):
    first_started = datetime.now(UTC) - timedelta(hours=1)

    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db, started_at=first_started, attempts=1)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert claimed.id == job.id
    assert claimed.started_at == first_started


@pytest.mark.asyncio
async def test_claim_does_not_mutate_unrelated_jobs(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        target = await create_pending_job(db, queue_name="default", priority=10)
        other = await create_pending_job(db, queue_name="default", priority=0)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert claimed.id == target.id

    async with db_session_factory() as db:
        stored_other = await db.get(type(target), other.id)

    assert stored_other.status == JobStatus.PENDING
    assert stored_other.attempts == 0


@pytest.mark.asyncio
async def test_claim_wrong_queue_worker_does_not_claim_job(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-a", "queue-a")
        await create_pending_job(db, queue_name="queue-b")

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-a", queue_name="queue-a")

    assert claimed is None


@pytest.mark.asyncio
async def test_claim_lease_expires_at_is_in_future(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default", lease_seconds=30)

    assert claimed.lease_expires_at > datetime.now(UTC)


@pytest.mark.asyncio
async def test_claim_sets_worker_current_job_id(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db)

    async with db_session_factory() as db:
        await claim_next_job(db, worker_id="worker-1", queue_name="default")
        from app.services.workers import get_worker_by_id

        worker = await get_worker_by_id(db, "worker-1")

    assert worker.current_job_id == job.id
