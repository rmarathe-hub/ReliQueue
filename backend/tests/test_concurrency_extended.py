"""Extended concurrency and race-prone path tests."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select

from app.models.enums import JobEventType, JobStatus
from app.models.job import Job
from app.models.job_event import JobEvent
from app.services.job_claiming import claim_next_job
from app.services.job_lease_recovery import recover_expired_leases
from app.services.workers import register_worker
from tests.helpers import create_pending_job


@pytest.mark.asyncio
@pytest.mark.slow
async def test_two_hundred_jobs_twenty_workers_no_duplicate_claims(db_session_factory):
    job_count = 200
    worker_count = 20

    async with db_session_factory() as db:
        for worker_index in range(worker_count):
            await register_worker(db, f"slow-worker-{worker_index}", "default")
        for job_index in range(job_count):
            await create_pending_job(db, idempotency_key=f"slow-200-{job_index}")

    async def claim_one(worker_id: str) -> Job | None:
        async with db_session_factory() as db:
            return await claim_next_job(db, worker_id=worker_id, queue_name="default")

    results = await asyncio.gather(
        *[claim_one(f"slow-worker-{index % worker_count}") for index in range(job_count)]
    )
    claimed = [job for job in results if job is not None]

    assert len(claimed) == job_count
    assert len({job.id for job in claimed}) == job_count


@pytest.mark.asyncio
@pytest.mark.slow
async def test_mixed_queues_concurrent_claiming_no_cross_queue_claims(db_session_factory):
    queues = ("queue-x", "queue-y", "queue-z")

    async with db_session_factory() as db:
        for queue in queues:
            await register_worker(db, f"worker-{queue}", queue)
            for index in range(5):
                await create_pending_job(db, queue_name=queue, idempotency_key=f"mix-{queue}-{index}")

    async def claim(worker_id: str, queue_name: str) -> Job | None:
        async with db_session_factory() as db:
            return await claim_next_job(db, worker_id=worker_id, queue_name=queue_name)

    tasks = []
    for queue in queues:
        for _ in range(5):
            tasks.append(claim(f"worker-{queue}", queue))

    results = await asyncio.gather(*tasks)
    claimed = [job for job in results if job is not None]

    assert len(claimed) == 15
    for job in claimed:
        assert job.queue_name in queues


@pytest.mark.asyncio
async def test_concurrent_lease_recovery_is_idempotent(db_session_factory):
    from datetime import UTC, datetime, timedelta

    expired = datetime.now(UTC) - timedelta(minutes=1)

    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await create_pending_job(db)
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")
        stored = await db.get(Job, claimed.id)
        stored.lease_expires_at = expired
        await db.commit()

    async def recover() -> list[Job]:
        async with db_session_factory() as db:
            return await recover_expired_leases(db, queue_name="default")

    first, second = await asyncio.gather(recover(), recover())
    total_recovered = len(first) + len(second)
    assert total_recovered == 1

    async with db_session_factory() as db:
        pending_count = await db.scalar(
            select(func.count()).select_from(Job).where(Job.status == JobStatus.PENDING)
        )
        lease_events = await db.scalar(
            select(func.count())
            .select_from(JobEvent)
            .where(JobEvent.event_type == JobEventType.JOB_LEASE_EXPIRED)
        )

    assert pending_count == 1
    assert lease_events == 1


def test_concurrent_idempotent_job_creation_via_api(client):
    payload = {
        "job_type": "sleep",
        "payload": {},
        "idempotency_key": "concurrent-idem",
    }

    def post():
        return client.post("/api/jobs", json=payload)

    with ThreadPoolExecutor(max_workers=5) as pool:
        responses = list(pool.map(lambda _: post(), range(5)))

    status_codes = {response.status_code for response in responses}
    job_ids = {response.json()["id"] for response in responses}

    assert status_codes <= {200, 201}
    assert len(job_ids) == 1

    events = client.get(f"/api/jobs/{job_ids.pop()}/events").json()
    assert sum(1 for event in events if event["event_type"] == "job_created") == 1
