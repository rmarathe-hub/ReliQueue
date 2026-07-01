"""Concurrency and safe-claiming tests."""

import asyncio

import pytest
from sqlalchemy import func, select

from app.models.enums import JobEventType, JobStatus
from app.models.job import Job
from app.models.job_event import JobEvent
from app.services.job_claiming import claim_next_job
from app.services.workers import register_worker
from tests.helpers import create_pending_job


@pytest.mark.asyncio
async def test_sixty_claim_attempts_on_thirty_jobs_claims_exactly_thirty(db_session_factory):
    job_count = 30
    worker_count = 5

    async with db_session_factory() as db:
        for worker_index in range(worker_count):
            await register_worker(db, f"worker-{worker_index}", "default")
        for job_index in range(job_count):
            await create_pending_job(db, idempotency_key=f"attempts-{job_index}")

    async def claim_one(worker_id: str) -> Job | None:
        async with db_session_factory() as db:
            return await claim_next_job(db, worker_id=worker_id, queue_name="default")

    results = await asyncio.gather(
        *[claim_one(f"worker-{index % worker_count}") for index in range(job_count * 2)]
    )
    claimed = [job for job in results if job is not None]

    assert len(claimed) == job_count
    assert len({job.id for job in claimed}) == job_count


@pytest.mark.asyncio
@pytest.mark.slow
async def test_hundred_jobs_ten_workers_no_duplicate_claims(db_session_factory):
    job_count = 100
    worker_count = 10

    async with db_session_factory() as db:
        for worker_index in range(worker_count):
            await register_worker(db, f"worker-h-{worker_index}", "default")
        for job_index in range(job_count):
            await create_pending_job(db, idempotency_key=f"hundred-{job_index}")

    async def claim_one(worker_id: str) -> Job | None:
        async with db_session_factory() as db:
            return await claim_next_job(db, worker_id=worker_id, queue_name="default")

    results = await asyncio.gather(
        *[claim_one(f"worker-h-{index % worker_count}") for index in range(job_count)]
    )
    claimed = [job for job in results if job is not None]

    assert len(claimed) == job_count
    assert len({job.id for job in claimed}) == job_count

    async with db_session_factory() as db:
        running_count = await db.scalar(
            select(func.count()).select_from(Job).where(Job.status == JobStatus.RUNNING)
        )

    assert running_count == job_count


@pytest.mark.asyncio
async def test_concurrent_claiming_skips_future_and_cancelled_jobs(db_session_factory):
    from datetime import UTC, datetime, timedelta

    future = datetime.now(UTC) + timedelta(hours=1)

    async with db_session_factory() as db:
        for worker_index in range(3):
            await register_worker(db, f"worker-mix-{worker_index}", "default")
        eligible = await create_pending_job(db, idempotency_key="eligible-only")
        await create_pending_job(db, run_at=future, idempotency_key="future-skip")
        await create_pending_job(db, status=JobStatus.CANCELLED, idempotency_key="cancelled-skip")

    async def claim_one(worker_id: str) -> Job | None:
        async with db_session_factory() as db:
            return await claim_next_job(db, worker_id=worker_id, queue_name="default")

    results = await asyncio.gather(*[claim_one(f"worker-mix-{i}") for i in range(6)])
    claimed = [job for job in results if job is not None]

    assert len(claimed) == 1
    assert claimed[0].id == eligible.id


@pytest.mark.asyncio
async def test_concurrent_claiming_across_multiple_queues(db_session_factory):
    async with db_session_factory() as db:
        for queue in ("queue-a", "queue-b", "queue-c"):
            await register_worker(db, f"worker-{queue}", queue)
            await create_pending_job(db, queue_name=queue, idempotency_key=f"conc-{queue}")

    async def claim_for_queue(worker_id: str, queue_name: str) -> Job | None:
        async with db_session_factory() as db:
            return await claim_next_job(db, worker_id=worker_id, queue_name=queue_name)

    results = await asyncio.gather(
        claim_for_queue("worker-queue-a", "queue-a"),
        claim_for_queue("worker-queue-b", "queue-b"),
        claim_for_queue("worker-queue-c", "queue-c"),
        claim_for_queue("worker-queue-a", "queue-a"),
    )

    claimed = [job for job in results if job is not None]
    assert len(claimed) == 3
    assert len({job.queue_name for job in claimed}) == 3


@pytest.mark.asyncio
async def test_two_workers_cannot_claim_same_job(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-a", "default")
        await register_worker(db, "worker-b", "default")
        await create_pending_job(db, idempotency_key="single-job")

    async def claim(worker_id: str) -> Job | None:
        async with db_session_factory() as db:
            return await claim_next_job(db, worker_id=worker_id, queue_name="default")

    first, second = await asyncio.gather(claim("worker-a"), claim("worker-b"))
    claimed = [job for job in (first, second) if job is not None]

    assert len(claimed) == 1

    async with db_session_factory() as db:
        event_count = await db.scalar(
            select(func.count())
            .select_from(JobEvent)
            .where(JobEvent.event_type == JobEventType.JOB_CLAIMED)
        )

    assert event_count == 1
