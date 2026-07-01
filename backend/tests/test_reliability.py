from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.enums import JobEventType, JobStatus
from app.models.job import Job
from app.models.job_event import JobEvent
from app.services.job_cancellation import cancel_job
from app.services.job_claiming import claim_next_job
from app.services.job_completion import complete_job_success
from app.services.job_failure import complete_job_failure
from app.services.job_lease_recovery import recover_expired_leases
from app.services.job_manual_retry import manual_retry_job
from app.services.workers import register_worker
from app.worker.handlers import execute_job
from tests.test_worker_claiming import create_pending_job


pytestmark = pytest.mark.reliability


@pytest.mark.asyncio
async def test_failed_job_retries(db_session_factory, no_retry_delay):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db, job_type="fail_once", max_attempts=3, idempotency_key="reliability-retry-1")

    async with db_session_factory() as db:
        first_claim = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    with pytest.raises(RuntimeError, match="simulated one-time failure"):
        await execute_job(first_claim)

    async with db_session_factory() as db:
        failed = await complete_job_failure(db, first_claim.id, "worker-1", "simulated one-time failure")

    assert failed is not None
    assert failed.status == JobStatus.PENDING

    async with db_session_factory() as db:
        second_claim = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert second_claim is not None
    assert second_claim.attempts == 2
    await execute_job(second_claim)

    async with db_session_factory() as db:
        completed = await complete_job_success(db, second_claim.id, "worker-1")

    assert completed is not None
    assert completed.status == JobStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_max_attempts_leads_to_dead_letter(db_session_factory, no_retry_delay):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(
            db,
            job_type="fail_always",
            payload={"message": "simulated permanent failure"},
            max_attempts=2,
            idempotency_key="reliability-dead-letter-1",
        )

    for expected_status in (JobStatus.PENDING, JobStatus.DEAD_LETTERED):
        async with db_session_factory() as db:
            claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

        assert claimed is not None

        with pytest.raises(RuntimeError, match="simulated permanent failure"):
            await execute_job(claimed)

        async with db_session_factory() as db:
            failed = await complete_job_failure(
                db,
                claimed.id,
                "worker-1",
                "simulated permanent failure",
            )

        assert failed is not None
        assert failed.status == expected_status

    async with db_session_factory() as db:
        claimed_again = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert claimed_again is None


@pytest.mark.asyncio
async def test_retry_backoff_sets_future_run_at(db_session_factory, monkeypatch):
    future_retry = datetime.now(UTC) + timedelta(seconds=45)

    monkeypatch.setattr(
        "app.services.job_failure.calculate_retry_run_at",
        lambda now, attempts, **kwargs: future_retry,
    )

    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(
            db,
            job_type="fail_always",
            max_attempts=3,
            idempotency_key="reliability-backoff-1",
        )

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    with pytest.raises(RuntimeError):
        await execute_job(claimed)

    async with db_session_factory() as db:
        failed = await complete_job_failure(db, claimed.id, "worker-1", "simulated failure")

    assert failed is not None
    assert failed.status == JobStatus.PENDING
    assert failed.run_at == future_retry

    async with db_session_factory() as db:
        not_ready = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert not_ready is None


@pytest.mark.asyncio
async def test_manual_retry_works(db_session_factory, no_retry_delay, monkeypatch):
    async def fake_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr("app.worker.handlers.asyncio.sleep", fake_sleep)

    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(
            db,
            job_type="sleep",
            payload={"seconds": 0},
            max_attempts=1,
            idempotency_key="reliability-manual-retry-1",
        )
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        dead_lettered = await complete_job_failure(db, claimed.id, "worker-1", "permanent failure")

    assert dead_lettered is not None
    assert dead_lettered.status == JobStatus.DEAD_LETTERED

    async with db_session_factory() as db:
        retried = await manual_retry_job(db, job.id)

    assert retried.status == JobStatus.PENDING
    assert retried.attempts == 0

    async with db_session_factory() as db:
        reclaimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert reclaimed is not None
    await execute_job(reclaimed)

    async with db_session_factory() as db:
        completed = await complete_job_success(db, reclaimed.id, "worker-1")

    assert completed is not None
    assert completed.status == JobStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_cancelled_job_not_claimed(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db, idempotency_key="reliability-cancel-1")
        await cancel_job(db, job.id)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert claimed is None


@pytest.mark.asyncio
async def test_expired_lease_recovers_job(db_session_factory):
    expired_at = datetime.now(UTC) - timedelta(minutes=1)

    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await register_worker(db, "worker-2", "default")
        job = await create_pending_job(db, idempotency_key="reliability-lease-1")

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        stored = await db.get(Job, claimed.id)
        stored.lease_expires_at = expired_at
        await db.commit()

    async with db_session_factory() as db:
        recovered = await recover_expired_leases(db, queue_name="default")

    assert len(recovered) == 1
    assert recovered[0].status == JobStatus.PENDING

    async with db_session_factory() as db:
        reclaimed = await claim_next_job(db, worker_id="worker-2", queue_name="default")

    assert reclaimed is not None
    assert reclaimed.id == job.id
    assert reclaimed.locked_by == "worker-2"


@pytest.mark.asyncio
async def test_reliability_event_timeline_for_retry_and_dead_letter(db_session_factory, no_retry_delay):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(
            db,
            job_type="fail_always",
            max_attempts=1,
            idempotency_key="reliability-events-1",
        )

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    with pytest.raises(RuntimeError):
        await execute_job(claimed)

    async with db_session_factory() as db:
        await complete_job_failure(db, claimed.id, "worker-1", "permanent failure")

    async with db_session_factory() as db:
        result = await db.execute(
            select(JobEvent.event_type)
            .where(JobEvent.job_id == job.id)
            .order_by(JobEvent.created_at.asc())
        )

    assert [row[0] for row in result.all()] == [
        JobEventType.JOB_CLAIMED,
        JobEventType.JOB_FAILED,
    ]

    async with db_session_factory() as db:
        stored = await db.get(Job, job.id)

    assert stored is not None
    assert stored.status == JobStatus.DEAD_LETTERED
