"""Full event timeline ordering tests across lifecycles."""

import pytest
from sqlalchemy import select

from app.models.enums import JobEventType, JobStatus
from app.models.job_event import JobEvent
from app.services.job_cancellation import cancel_job
from app.services.job_claiming import claim_next_job
from app.services.job_completion import complete_job_success
from app.services.job_failure import complete_job_failure
from app.services.job_lease_recovery import recover_expired_leases
from app.services.job_manual_retry import manual_retry_job
from app.services.workers import register_worker
from app.worker.handlers import execute_job
from tests.helpers import create_pending_job


async def _event_types(db, job_id) -> list[str]:
    result = await db.execute(
        select(JobEvent.event_type)
        .where(JobEvent.job_id == job_id)
        .order_by(JobEvent.created_at.asc())
    )
    return [row[0] for row in result.all()]


@pytest.mark.asyncio
async def test_success_lifecycle_event_order(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db)
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        await complete_job_success(db, claimed.id, "worker-1")
        types = await _event_types(db, job.id)

    assert types == [JobEventType.JOB_CLAIMED, JobEventType.JOB_SUCCEEDED]


@pytest.mark.asyncio
async def test_retry_then_success_event_order(db_session_factory, no_retry_delay):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db, job_type="fail_once", max_attempts=3)
        first = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        await complete_job_failure(db, first.id, "worker-1", "once")
        second = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        await execute_job(second)
        await complete_job_success(db, second.id, "worker-1")
        types = await _event_types(db, job.id)

    assert types == [
        JobEventType.JOB_CLAIMED,
        JobEventType.JOB_FAILED,
        JobEventType.JOB_RETRY_SCHEDULED,
        JobEventType.JOB_CLAIMED,
        JobEventType.JOB_SUCCEEDED,
    ]


@pytest.mark.asyncio
async def test_dead_letter_max_attempts_one_event_order(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db, max_attempts=1)
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        await complete_job_failure(db, claimed.id, "worker-1", "fatal")
        types = await _event_types(db, job.id)

    assert types == [JobEventType.JOB_CLAIMED, JobEventType.JOB_FAILED]
    assert JobEventType.JOB_RETRY_SCHEDULED not in types


@pytest.mark.asyncio
async def test_dead_letter_max_attempts_two_event_order(db_session_factory, no_retry_delay):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db, max_attempts=2)
        first = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        await complete_job_failure(db, first.id, "worker-1", "fail")
        second = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        await complete_job_failure(db, second.id, "worker-1", "fail")
        types = await _event_types(db, job.id)

    assert types == [
        JobEventType.JOB_CLAIMED,
        JobEventType.JOB_FAILED,
        JobEventType.JOB_RETRY_SCHEDULED,
        JobEventType.JOB_CLAIMED,
        JobEventType.JOB_FAILED,
    ]


@pytest.mark.asyncio
async def test_cancel_lifecycle_event_order(db_session_factory):
    async with db_session_factory() as db:
        job = await create_pending_job(db)
        await cancel_job(db, job.id)
        types = await _event_types(db, job.id)

    assert types == [JobEventType.JOB_CANCELLED]


@pytest.mark.asyncio
async def test_cancel_manual_retry_success_event_order(db_session_factory, no_retry_delay):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db)
        await cancel_job(db, job.id)
        await manual_retry_job(db, job.id)
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        await complete_job_success(db, claimed.id, "worker-1")
        types = await _event_types(db, job.id)

    assert types == [
        JobEventType.JOB_CANCELLED,
        JobEventType.JOB_MANUALLY_RETRIED,
        JobEventType.JOB_CLAIMED,
        JobEventType.JOB_SUCCEEDED,
    ]


@pytest.mark.asyncio
async def test_lease_recovery_claim_success_event_order(db_session_factory):
    from datetime import UTC, datetime, timedelta

    expired = datetime.now(UTC) - timedelta(minutes=1)

    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await register_worker(db, "worker-2", "default")
        job = await create_pending_job(db)
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        stored = await db.get(type(claimed), claimed.id)
        stored.lease_expires_at = expired
        await db.commit()
        await recover_expired_leases(db, queue_name="default")
        reclaimed = await claim_next_job(db, worker_id="worker-2", queue_name="default")
        await complete_job_success(db, reclaimed.id, "worker-2")
        types = await _event_types(db, job.id)

    assert JobEventType.JOB_LEASE_EXPIRED in types
    assert types[-1] == JobEventType.JOB_SUCCEEDED


@pytest.mark.asyncio
async def test_failed_job_stores_last_error_and_job_failed_event(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db, max_attempts=1)
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        failed = await complete_job_failure(db, claimed.id, "worker-1", "boom")
        types = await _event_types(db, job.id)

    assert failed.last_error == "boom"
    assert JobEventType.JOB_FAILED in types


@pytest.mark.asyncio
async def test_events_remain_chronological_after_many_steps(db_session_factory, no_retry_delay):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db, job_type="fail_once", max_attempts=3)
        first = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        await complete_job_failure(db, first.id, "worker-1", "once")
        second = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        await execute_job(second)
        await complete_job_success(db, second.id, "worker-1")
        result = await db.execute(
            select(JobEvent.created_at).where(JobEvent.job_id == job.id).order_by(JobEvent.created_at.asc())
        )
        timestamps = [row[0] for row in result.all()]

    assert timestamps == sorted(timestamps)
