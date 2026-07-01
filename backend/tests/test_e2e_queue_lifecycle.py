"""End-to-end queue lifecycle tests spanning API and services."""

import asyncio
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from sqlalchemy import select

from app.models.enums import JobEventType, JobStatus
from app.models.job import Job
from app.models.job_event import JobEvent
from app.services.job_claiming import claim_next_job
from app.services.job_completion import complete_job_success
from app.services.job_failure import complete_job_failure
from app.services.job_lease_recovery import recover_expired_leases
from app.services.job_manual_retry import manual_retry_job
from app.services.workers import register_worker
from tests.conftest import TEST_DATABASE_SYNC_URL, TEST_DATABASE_URL
from tests.test_worker_claiming import create_pending_job


def test_api_submit_claim_complete_success_lifecycle(client, job_payload):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    created = client.post("/api/jobs", json=job_payload)
    assert created.status_code == 201
    job_id = created.json()["id"]

    async def process():
        engine = create_async_engine(TEST_DATABASE_URL, echo=False)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with session_factory() as db:
                await register_worker(db, "worker-e2e", "default")
                claimed = await claim_next_job(db, worker_id="worker-e2e", queue_name="default")
                assert claimed is not None
                assert str(claimed.id) == job_id
                await complete_job_success(db, claimed.id, "worker-e2e")
        finally:
            await engine.dispose()

    asyncio.run(process())

    detail = client.get(f"/api/jobs/{job_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "succeeded"
    assert body["locked_by"] is None
    assert body["completed_at"] is not None

    events = client.get(f"/api/jobs/{job_id}/events")
    assert events.status_code == 200
    event_types = [event["event_type"] for event in events.json()]
    assert event_types == ["job_created", "job_claimed", "job_succeeded"]


def test_idempotency_duplicate_creates_single_job_created_event(client, job_payload):
    first = client.post("/api/jobs", json=job_payload)
    second = client.post("/api/jobs", json=job_payload)

    assert first.status_code == 201
    assert second.status_code == 200
    job_id = first.json()["id"]

    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM job_events WHERE job_id = %s AND event_type = 'job_created'",
            (job_id,),
        ).fetchone()[0]

    assert count == 1


@pytest.mark.asyncio
async def test_fail_always_dead_letters_with_event_timeline(db_session_factory, no_retry_delay):
    async with db_session_factory() as db:
        await register_worker(db, "worker-dl", "default")
        job = await create_pending_job(
            db,
            job_type="fail_always",
            max_attempts=2,
            idempotency_key="e2e-fail-always",
        )

    for _ in range(2):
        async with db_session_factory() as db:
            claimed = await claim_next_job(db, worker_id="worker-dl", queue_name="default")
            assert claimed is not None
            await complete_job_failure(db, claimed.id, "worker-dl", "always fails")

    async with db_session_factory() as db:
        stored = await db.get(Job, job.id)

    assert stored.status == JobStatus.DEAD_LETTERED

    async with db_session_factory() as db:
        result = await db.execute(
            select(JobEvent.event_type)
            .where(JobEvent.job_id == job.id)
            .order_by(JobEvent.created_at.asc())
        )
        event_types = [row[0] for row in result.all()]

    assert event_types == [
        JobEventType.JOB_CLAIMED,
        JobEventType.JOB_FAILED,
        JobEventType.JOB_RETRY_SCHEDULED,
        JobEventType.JOB_CLAIMED,
        JobEventType.JOB_FAILED,
    ]


@pytest.mark.asyncio
async def test_future_run_at_not_claimed_until_eligible(db_session_factory):
    future = datetime.now(UTC) + timedelta(hours=1)

    async with db_session_factory() as db:
        await register_worker(db, "worker-future", "default")
        job = await create_pending_job(db, run_at=future, idempotency_key="e2e-future")
        claimed = await claim_next_job(db, worker_id="worker-future", queue_name="default")

    assert claimed is None

    async with db_session_factory() as db:
        stored = await db.get(Job, job.id)
        stored.run_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-future", queue_name="default")

    assert claimed is not None
    assert claimed.id == job.id


@pytest.mark.asyncio
async def test_dead_lettered_manual_retry_then_claim(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-retry", "default")
        job = await create_pending_job(
            db,
            status=JobStatus.DEAD_LETTERED,
            attempts=3,
            last_error="permanent",
            idempotency_key="e2e-manual-retry",
        )
        await manual_retry_job(db, job.id)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-retry", queue_name="default")

    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.status == JobStatus.RUNNING
    assert claimed.attempts == 1


@pytest.mark.asyncio
async def test_expired_lease_recovered_then_claimed_by_another_worker(db_session_factory):
    expired_at = datetime.now(UTC) - timedelta(minutes=1)

    async with db_session_factory() as db:
        await register_worker(db, "worker-a", "default")
        await register_worker(db, "worker-b", "default")
        job = await create_pending_job(db, idempotency_key="e2e-lease")

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-a", queue_name="default")
        stored = await db.get(Job, claimed.id)
        stored.lease_expires_at = expired_at
        await db.commit()

    async with db_session_factory() as db:
        recovered = await recover_expired_leases(db, queue_name="default")

    assert len(recovered) == 1

    async with db_session_factory() as db:
        reclaimed = await claim_next_job(db, worker_id="worker-b", queue_name="default")

    assert reclaimed is not None
    assert reclaimed.id == job.id
    assert reclaimed.locked_by == "worker-b"


@pytest.mark.asyncio
async def test_multiple_queues_do_not_interfere(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-q1", "queue-a")
        await register_worker(db, "worker-q2", "queue-b")
        job_a = await create_pending_job(db, queue_name="queue-a", idempotency_key="e2e-qa")
        job_b = await create_pending_job(db, queue_name="queue-b", idempotency_key="e2e-qb")

    async with db_session_factory() as db:
        claimed_a = await claim_next_job(db, worker_id="worker-q1", queue_name="queue-a")
        claimed_b = await claim_next_job(db, worker_id="worker-q2", queue_name="queue-b")

    assert claimed_a.id == job_a.id
    assert claimed_b.id == job_b.id


def test_api_submit_claim_failure_schedules_retry(client, no_retry_delay):
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from tests.conftest import TEST_DATABASE_URL

    created = client.post(
        "/api/jobs",
        json={
            "job_type": "sleep",
            "payload": {},
            "max_attempts": 3,
            "idempotency_key": "e2e-failure-retry",
        },
    )
    job_id = created.json()["id"]

    async def run():
        engine = create_async_engine(TEST_DATABASE_URL, echo=False)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with factory() as db:
                await register_worker(db, "worker-fail", "default")
                claimed = await claim_next_job(db, worker_id="worker-fail", queue_name="default")
                await complete_job_failure(db, claimed.id, "worker-fail", "transient")
        finally:
            await engine.dispose()

    asyncio.run(run())

    detail = client.get(f"/api/jobs/{job_id}").json()
    assert detail["status"] == "pending"
    assert detail["last_error"] == "transient"

    events = client.get(f"/api/jobs/{job_id}/events").json()
    event_types = [e["event_type"] for e in events]
    assert "job_failed" in event_types
    assert "job_retry_scheduled" in event_types


def test_api_pending_cancel_not_claimed(client, job_payload):
    created = client.post("/api/jobs", json=job_payload)
    job_id = created.json()["id"]
    client.post(f"/api/jobs/{job_id}/cancel")

    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from tests.conftest import TEST_DATABASE_URL

    async def run():
        engine = create_async_engine(TEST_DATABASE_URL, echo=False)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with factory() as db:
                await register_worker(db, "worker-cancel", "default")
                return await claim_next_job(db, worker_id="worker-cancel", queue_name="default")
        finally:
            await engine.dispose()

    claimed = asyncio.run(run())
    assert claimed is None

    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_retry_then_success_event_order(db_session_factory, no_retry_delay):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db, job_type="fail_once", max_attempts=3, idempotency_key="e2e-retry-success")

    async with db_session_factory() as db:
        first = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        await complete_job_failure(db, first.id, "worker-1", "once")

    async with db_session_factory() as db:
        second = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        from app.worker.handlers import execute_job

        await execute_job(second)
        await complete_job_success(db, second.id, "worker-1")

    async with db_session_factory() as db:
        result = await db.execute(
            select(JobEvent.event_type)
            .where(JobEvent.job_id == job.id)
            .order_by(JobEvent.created_at.asc())
        )
        event_types = [row[0] for row in result.all()]

    assert event_types == [
        JobEventType.JOB_CLAIMED,
        JobEventType.JOB_FAILED,
        JobEventType.JOB_RETRY_SCHEDULED,
        JobEventType.JOB_CLAIMED,
        JobEventType.JOB_SUCCEEDED,
    ]
