"""Extended forbidden state machine transition tests."""

import pytest

from app.models.enums import JobStatus
from app.services.job_cancellation import cancel_job
from app.services.job_claiming import claim_next_job
from app.services.job_completion import complete_job_success
from app.services.job_errors import JobCancellationNotAllowedError, ManualRetryNotAllowedError
from app.services.job_failure import complete_job_failure
from app.services.job_manual_retry import manual_retry_job
from app.services.workers import register_worker
from tests.helpers import create_pending_job


@pytest.mark.asyncio
async def test_pending_cannot_complete(db_session_factory):
    async with db_session_factory() as db:
        job = await create_pending_job(db)
        assert await complete_job_success(db, job.id, "worker-1") is None


@pytest.mark.asyncio
async def test_pending_cannot_fail(db_session_factory):
    async with db_session_factory() as db:
        job = await create_pending_job(db)
        assert await complete_job_failure(db, job.id, "worker-1", "err") is None


@pytest.mark.asyncio
async def test_cancelled_cannot_be_claimed(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db, status=JobStatus.CANCELLED)
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert claimed is None


@pytest.mark.asyncio
async def test_cancelled_cannot_complete(db_session_factory):
    async with db_session_factory() as db:
        job = await create_pending_job(db, status=JobStatus.CANCELLED, locked_by="worker-1")
        assert await complete_job_success(db, job.id, "worker-1") is None


@pytest.mark.asyncio
async def test_dead_lettered_cannot_complete(db_session_factory):
    async with db_session_factory() as db:
        job = await create_pending_job(db, status=JobStatus.DEAD_LETTERED, locked_by="worker-1")
        assert await complete_job_success(db, job.id, "worker-1") is None


@pytest.mark.asyncio
async def test_succeeded_cannot_manual_retry(db_session_factory):
    async with db_session_factory() as db:
        job = await create_pending_job(db, status=JobStatus.SUCCEEDED)
        with pytest.raises(ManualRetryNotAllowedError):
            await manual_retry_job(db, job.id)


@pytest.mark.asyncio
async def test_succeeded_cannot_cancel(db_session_factory):
    async with db_session_factory() as db:
        job = await create_pending_job(db, status=JobStatus.SUCCEEDED)
        with pytest.raises(JobCancellationNotAllowedError):
            await cancel_job(db, job.id)


@pytest.mark.asyncio
async def test_dead_lettered_only_returns_to_pending_via_manual_retry(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db, status=JobStatus.DEAD_LETTERED, attempts=3)
        assert await claim_next_job(db, worker_id="worker-1", queue_name="default") is None
        retried = await manual_retry_job(db, job.id)

    assert retried.status == JobStatus.PENDING


@pytest.mark.asyncio
async def test_cancelled_returns_to_pending_via_manual_retry(db_session_factory):
    async with db_session_factory() as db:
        job = await create_pending_job(db, status=JobStatus.CANCELLED)
        retried = await manual_retry_job(db, job.id)

    assert retried.status == JobStatus.PENDING


@pytest.mark.asyncio
async def test_claim_orders_by_created_at_when_priority_and_run_at_equal(db_session_factory):
    from datetime import UTC, datetime, timedelta

    older = datetime.now(UTC) - timedelta(minutes=5)
    newer = datetime.now(UTC) - timedelta(minutes=1)
    same_run_at = datetime.now(UTC) - timedelta(hours=1)

    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        first = await create_pending_job(
            db,
            priority=0,
            run_at=same_run_at,
            created_at=older,
            idempotency_key="tie-older",
        )
        await create_pending_job(
            db,
            priority=0,
            run_at=same_run_at,
            created_at=newer,
            idempotency_key="tie-newer",
        )

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert claimed.id == first.id
