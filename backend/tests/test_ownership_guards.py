"""Worker ownership guard tests for completion and failure paths."""

import pytest

from app.models.enums import JobStatus
from app.services.job_claiming import claim_next_job
from app.services.job_completion import complete_job_success
from app.services.job_failure import complete_job_failure
from app.services.job_lease_recovery import recover_expired_leases
from app.services.workers import register_worker
from tests.helpers import create_pending_job


@pytest.mark.asyncio
async def test_running_job_with_null_lock_cannot_complete(db_session_factory):
    async with db_session_factory() as db:
        job = await create_pending_job(db, status=JobStatus.RUNNING, locked_by=None)
        result = await complete_job_success(db, job.id, "worker-1")

    assert result is None


@pytest.mark.asyncio
async def test_running_job_with_null_lock_cannot_fail(db_session_factory):
    async with db_session_factory() as db:
        job = await create_pending_job(db, status=JobStatus.RUNNING, locked_by=None, max_attempts=3)
        result = await complete_job_failure(db, job.id, "worker-1", "err")

    assert result is None


@pytest.mark.asyncio
async def test_wrong_worker_cannot_complete_claimed_job(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-a", "default")
        await register_worker(db, "worker-b", "default")
        await create_pending_job(db)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-a", queue_name="default")
        result = await complete_job_success(db, claimed.id, "worker-b")

    assert result is None


@pytest.mark.asyncio
async def test_wrong_worker_cannot_fail_claimed_job(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-a", "default")
        await register_worker(db, "worker-b", "default")
        await create_pending_job(db, max_attempts=3)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-a", queue_name="default")
        result = await complete_job_failure(db, claimed.id, "worker-b", "err")

    assert result is None


@pytest.mark.asyncio
async def test_owning_worker_can_complete_claimed_job(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-a", "default")
        await create_pending_job(db)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-a", queue_name="default")
        completed = await complete_job_success(db, claimed.id, "worker-a")

    assert completed.status == JobStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_owning_worker_can_fail_claimed_job(db_session_factory, no_retry_delay):
    async with db_session_factory() as db:
        await register_worker(db, "worker-a", "default")
        await create_pending_job(db, max_attempts=3)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-a", queue_name="default")
        failed = await complete_job_failure(db, claimed.id, "worker-a", "err")

    assert failed.status == JobStatus.PENDING


@pytest.mark.asyncio
async def test_worker_current_job_id_set_after_claim(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db)

    async with db_session_factory() as db:
        await claim_next_job(db, worker_id="worker-1", queue_name="default")
        from app.services.workers import get_worker_by_id

        worker = await get_worker_by_id(db, "worker-1")

    assert worker.current_job_id == job.id


@pytest.mark.asyncio
async def test_worker_current_job_id_cleared_after_success(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        await complete_job_success(db, claimed.id, "worker-1")
        from app.services.workers import get_worker_by_id

        worker = await get_worker_by_id(db, "worker-1")

    assert worker.current_job_id is None


@pytest.mark.asyncio
async def test_worker_current_job_id_cleared_after_retryable_failure(db_session_factory, no_retry_delay):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db, max_attempts=3)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        await complete_job_failure(db, claimed.id, "worker-1", "retry")
        from app.services.workers import get_worker_by_id

        worker = await get_worker_by_id(db, "worker-1")

    assert worker.current_job_id is None


@pytest.mark.asyncio
async def test_worker_current_job_id_cleared_after_dead_letter_failure(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db, max_attempts=1)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        await complete_job_failure(db, claimed.id, "worker-1", "dead")
        from app.services.workers import get_worker_by_id

        worker = await get_worker_by_id(db, "worker-1")

    assert worker.current_job_id is None


@pytest.mark.asyncio
async def test_worker_current_job_id_cleared_after_lease_recovery(db_session_factory):
    from datetime import UTC, datetime, timedelta

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
        await recover_expired_leases(db, queue_name="default")
        from app.services.workers import get_worker_by_id

        worker = await get_worker_by_id(db, "worker-1")

    assert worker.current_job_id is None


@pytest.mark.asyncio
async def test_recovered_job_must_be_reclaimed_before_completion(db_session_factory):
    from datetime import UTC, datetime, timedelta

    expired = datetime.now(UTC) - timedelta(minutes=1)

    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await register_worker(db, "worker-2", "default")
        job = await create_pending_job(db)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        stored = await db.get(type(claimed), claimed.id)
        stored.lease_expires_at = expired
        await db.commit()

    async with db_session_factory() as db:
        await recover_expired_leases(db, queue_name="default")
        assert await complete_job_success(db, job.id, "worker-2") is None
        reclaimed = await claim_next_job(db, worker_id="worker-2", queue_name="default")
        completed = await complete_job_success(db, reclaimed.id, "worker-2")

    assert completed.status == JobStatus.SUCCEEDED
