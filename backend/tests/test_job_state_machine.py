"""Job state machine transition tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.models.enums import JobStatus
from app.services.job_cancellation import cancel_job
from app.services.job_claiming import claim_next_job
from app.services.job_completion import complete_job_success
from app.services.job_errors import JobCancellationNotAllowedError, ManualRetryNotAllowedError
from app.services.job_failure import complete_job_failure
from app.services.job_lease_recovery import recover_expired_leases
from app.services.job_manual_retry import manual_retry_job
from app.services.workers import register_worker
from tests.helpers import create_pending_job


@pytest.mark.asyncio
async def test_pending_to_running_via_claim(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db)
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert claimed.id == job.id
    assert claimed.status == JobStatus.RUNNING


@pytest.mark.asyncio
async def test_running_to_succeeded(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        completed = await complete_job_success(db, claimed.id, "worker-1")

    assert completed.status == JobStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_running_to_pending_via_retryable_failure(db_session_factory, no_retry_delay):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db, max_attempts=3)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        failed = await complete_job_failure(db, claimed.id, "worker-1", "err")

    assert failed.status == JobStatus.PENDING


@pytest.mark.asyncio
async def test_running_to_dead_lettered_at_max_attempts(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db, max_attempts=1)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        failed = await complete_job_failure(db, claimed.id, "worker-1", "err")

    assert failed.status == JobStatus.DEAD_LETTERED


@pytest.mark.asyncio
async def test_pending_to_cancelled(db_session_factory):
    async with db_session_factory() as db:
        job = await create_pending_job(db)
        cancelled = await cancel_job(db, job.id)

    assert cancelled.status == JobStatus.CANCELLED


@pytest.mark.asyncio
async def test_dead_lettered_to_pending_via_manual_retry(db_session_factory):
    async with db_session_factory() as db:
        job = await create_pending_job(db, status=JobStatus.DEAD_LETTERED, attempts=3)
        retried = await manual_retry_job(db, job.id)

    assert retried.status == JobStatus.PENDING
    assert retried.attempts == 0


@pytest.mark.asyncio
async def test_cancelled_to_pending_via_manual_retry(db_session_factory):
    async with db_session_factory() as db:
        job = await create_pending_job(db, status=JobStatus.CANCELLED)
        retried = await manual_retry_job(db, job.id)

    assert retried.status == JobStatus.PENDING


@pytest.mark.asyncio
async def test_running_expired_lease_to_pending(db_session_factory):
    expired_at = datetime.now(UTC) - timedelta(minutes=1)

    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        claimed.lease_expires_at = expired_at
        await db.commit()

    async with db_session_factory() as db:
        recovered = await recover_expired_leases(db, queue_name="default")

    assert recovered[0].status == JobStatus.PENDING


@pytest.mark.asyncio
async def test_pending_cannot_complete_directly(db_session_factory):
    async with db_session_factory() as db:
        job = await create_pending_job(db)
        result = await complete_job_success(db, job.id, "worker-1")

    assert result is None


@pytest.mark.asyncio
async def test_pending_cannot_fail_directly(db_session_factory):
    async with db_session_factory() as db:
        job = await create_pending_job(db)
        result = await complete_job_failure(db, job.id, "worker-1", "err")

    assert result is None


@pytest.mark.asyncio
async def test_succeeded_cannot_transition_to_running_via_claim(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db, status=JobStatus.SUCCEEDED)
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert claimed is None


@pytest.mark.asyncio
async def test_succeeded_cannot_be_cancelled(db_session_factory):
    async with db_session_factory() as db:
        job = await create_pending_job(db, status=JobStatus.SUCCEEDED)
        with pytest.raises(JobCancellationNotAllowedError):
            await cancel_job(db, job.id)


@pytest.mark.asyncio
async def test_succeeded_cannot_be_manually_retried(db_session_factory):
    async with db_session_factory() as db:
        job = await create_pending_job(db, status=JobStatus.SUCCEEDED)
        with pytest.raises(ManualRetryNotAllowedError):
            await manual_retry_job(db, job.id)


@pytest.mark.asyncio
async def test_running_cannot_be_cancelled_via_endpoint(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db)
        await claim_next_job(db, worker_id="worker-1", queue_name="default")

    async with db_session_factory() as db:
        with pytest.raises(JobCancellationNotAllowedError):
            await cancel_job(db, job.id)


@pytest.mark.asyncio
async def test_dead_lettered_cannot_be_claimed_without_manual_retry(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db, status=JobStatus.DEAD_LETTERED)
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert claimed is None


@pytest.mark.asyncio
async def test_wrong_worker_cannot_complete_running_job(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await register_worker(db, "worker-2", "default")
        await create_pending_job(db)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        result = await complete_job_success(db, claimed.id, "worker-2")

    assert result is None


@pytest.mark.asyncio
async def test_wrong_worker_cannot_fail_running_job(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await register_worker(db, "worker-2", "default")
        await create_pending_job(db, max_attempts=3)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        result = await complete_job_failure(db, claimed.id, "worker-2", "err")

    assert result is None


@pytest.mark.asyncio
async def test_nonexistent_job_mutations_return_none_or_error(db_session_factory):
    missing_id = uuid4()

    async with db_session_factory() as db:
        assert await complete_job_success(db, missing_id, "worker-1") is None
        assert await complete_job_failure(db, missing_id, "worker-1", "err") is None

    async with db_session_factory() as db:
        with pytest.raises(LookupError):
            await manual_retry_job(db, missing_id)
        with pytest.raises(LookupError):
            await cancel_job(db, missing_id)


@pytest.mark.asyncio
async def test_cancelled_cannot_transition_to_running_without_manual_retry(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db, status=JobStatus.CANCELLED)
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert claimed is None


@pytest.mark.asyncio
async def test_running_without_lock_cannot_complete(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db, status=JobStatus.RUNNING, locked_by=None)
        result = await complete_job_success(db, job.id, "worker-1")

    assert result is None


@pytest.mark.asyncio
async def test_dead_lettered_cannot_fail_again(db_session_factory):
    async with db_session_factory() as db:
        job = await create_pending_job(db, status=JobStatus.DEAD_LETTERED, attempts=3)
        result = await complete_job_failure(db, job.id, "worker-1", "again")

    assert result is None
