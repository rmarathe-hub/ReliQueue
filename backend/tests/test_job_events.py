"""Job event timeline and metadata tests."""

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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
from tests.conftest import TEST_DATABASE_URL
from tests.helpers import create_pending_job


def test_job_events_are_chronological_via_api(client, job_payload):
    created = client.post("/api/jobs", json=job_payload)
    job_id = created.json()["id"]

    async def run():
        engine = create_async_engine(TEST_DATABASE_URL, echo=False)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with factory() as db:
                await register_worker(db, "worker-events", "default")
                claimed = await claim_next_job(db, worker_id="worker-events", queue_name="default")
                await complete_job_success(db, claimed.id, "worker-events")
        finally:
            await engine.dispose()

    asyncio.run(run())

    events = client.get(f"/api/jobs/{job_id}/events").json()
    timestamps = [event["created_at"] for event in events]
    assert timestamps == sorted(timestamps)
    assert [e["event_type"] for e in events] == ["job_created", "job_claimed", "job_succeeded"]


def test_job_created_event_metadata(client):
    response = client.post(
        "/api/jobs",
        json={"job_type": "sleep", "payload": {"x": 1}, "idempotency_key": "event-created-meta"},
    )
    job_id = response.json()["id"]
    events = client.get(f"/api/jobs/{job_id}/events").json()

    assert events[0]["event_type"] == "job_created"
    assert isinstance(events[0]["payload"], dict)
    assert events[0]["payload"]["job_type"] == "sleep"


@pytest.mark.asyncio
async def test_job_claimed_event_includes_worker_id(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db)
        await claim_next_job(db, worker_id="worker-1", queue_name="default")
        result = await db.execute(
            select(JobEvent).where(
                JobEvent.job_id == job.id,
                JobEvent.event_type == JobEventType.JOB_CLAIMED,
            )
        )
        event = result.scalar_one()

    assert event.payload["worker_id"] == "worker-1"


@pytest.mark.asyncio
async def test_job_failed_event_includes_error_metadata(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db, max_attempts=1)
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        await complete_job_failure(db, claimed.id, "worker-1", "boom")
        result = await db.execute(
            select(JobEvent).where(
                JobEvent.job_id == job.id,
                JobEvent.event_type == JobEventType.JOB_FAILED,
            )
        )
        event = result.scalar_one()

    assert event.payload["error"] == "boom"
    assert event.payload["worker_id"] == "worker-1"


@pytest.mark.asyncio
async def test_job_retry_scheduled_event_includes_delay_metadata(db_session_factory, no_retry_delay):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db, max_attempts=3)
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        await complete_job_failure(db, claimed.id, "worker-1", "retry me")
        result = await db.execute(
            select(JobEvent).where(
                JobEvent.job_id == job.id,
                JobEvent.event_type == JobEventType.JOB_RETRY_SCHEDULED,
            )
        )
        event = result.scalar_one()

    assert "run_at" in event.payload
    assert "delay_seconds" in event.payload


@pytest.mark.asyncio
async def test_job_cancelled_event_exists(db_session_factory):
    async with db_session_factory() as db:
        job = await create_pending_job(db, idempotency_key="event-cancel")
        await cancel_job(db, job.id)
        result = await db.execute(
            select(JobEvent).where(
                JobEvent.job_id == job.id,
                JobEvent.event_type == JobEventType.JOB_CANCELLED,
            )
        )
        events = list(result.scalars().all())

    assert len(events) == 1
    assert events[0].payload["previous_status"] == JobStatus.PENDING.value


@pytest.mark.asyncio
async def test_job_manually_retried_event_exists(db_session_factory):
    async with db_session_factory() as db:
        job = await create_pending_job(
            db,
            status=JobStatus.DEAD_LETTERED,
            attempts=2,
            idempotency_key="event-manual-retry",
        )
        await manual_retry_job(db, job.id)
        result = await db.execute(
            select(JobEvent).where(
                JobEvent.job_id == job.id,
                JobEvent.event_type == JobEventType.JOB_MANUALLY_RETRIED,
            )
        )
        event = result.scalar_one()

    assert event.payload["previous_status"] == JobStatus.DEAD_LETTERED.value
    assert event.payload["previous_attempts"] == 2


@pytest.mark.asyncio
async def test_job_lease_expired_event_exists(db_session_factory):
    from datetime import UTC, datetime, timedelta

    expired_at = datetime.now(UTC) - timedelta(minutes=1)

    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db, idempotency_key="event-lease")
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        stored = await db.get(Job, job.id)
        stored.lease_expires_at = expired_at
        await db.commit()
        await recover_expired_leases(db, queue_name="default")
        result = await db.execute(
            select(JobEvent).where(
                JobEvent.job_id == job.id,
                JobEvent.event_type == JobEventType.JOB_LEASE_EXPIRED,
            )
        )
        event = result.scalar_one()

    assert event.payload["worker_id"] == "worker-1"
