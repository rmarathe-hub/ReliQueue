"""Shared test helpers for ReliQueue backend tests."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar
from uuid import UUID

import psycopg
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.enums import JobEventType, JobStatus, WorkerStatus
from app.models.job import Job
from app.models.job_event import JobEvent
from app.models.worker import Worker
from tests.conftest import TEST_DATABASE_SYNC_URL, TEST_DATABASE_URL

T = TypeVar("T")


async def create_pending_job(db: AsyncSession, **overrides: Any) -> Job:
    now = datetime.now(UTC)
    values = {
        "job_type": "sleep",
        "payload": {"seconds": 1},
        "status": JobStatus.PENDING,
        "queue_name": "default",
        "priority": 0,
        "max_attempts": 3,
        "attempts": 0,
        "run_at": now,
    }
    values.update(overrides)
    job = Job(**values)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def create_job_with_event(
    db: AsyncSession,
    *,
    event_type: JobEventType = JobEventType.JOB_CREATED,
    event_payload: dict[str, Any] | None = None,
    **job_overrides: Any,
) -> Job:
    job = await create_pending_job(db, **job_overrides)
    if event_type != JobEventType.JOB_CREATED or event_payload is not None:
        db.add(
            JobEvent(
                job_id=job.id,
                event_type=event_type,
                payload=event_payload or {},
            )
        )
        await db.commit()
    return job


def set_job_status_sync(job_id: UUID | str, status: JobStatus, **fields: Any) -> None:
    assignments = ["status = %s"]
    values: list[Any] = [status.name]
    for key, value in fields.items():
        assignments.append(f"{key} = %s")
        values.append(value)
    values.append(str(job_id))
    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        conn.execute(
            f"UPDATE jobs SET {', '.join(assignments)} WHERE id = %s",
            values,
        )
        conn.commit()


def insert_worker_sync(
    worker_id: str,
    *,
    queue_name: str = "default",
    status: WorkerStatus = WorkerStatus.ONLINE,
    current_job_id: UUID | str | None = None,
) -> None:
    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        conn.execute(
            """
            INSERT INTO workers (id, status, queue_name, current_job_id, last_heartbeat_at, created_at, updated_at)
            VALUES (%s, %s, %s, %s, NOW(), NOW(), NOW())
            """,
            (worker_id, status.name, queue_name, str(current_job_id) if current_job_id else None),
        )
        conn.commit()


def count_rows_sync(table: str, where: str = "", params: tuple[Any, ...] = ()) -> int:
    query = f"SELECT COUNT(*) FROM {table}"
    if where:
        query += f" WHERE {where}"
    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        row = conn.execute(query, params).fetchone()
    return row[0]


def run_with_fresh_engine(coro_factory: Callable[[async_sessionmaker], Awaitable[T]]) -> T:
    async def _run() -> T:
        engine = create_async_engine(TEST_DATABASE_URL, echo=False)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            return await coro_factory(session_factory)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


async def seed_metrics_dataset(db: AsyncSession) -> dict[str, Any]:
    """Seed jobs, events, and workers useful for future metrics endpoint tests."""
    now = datetime.now(UTC)
    recent = now - timedelta(minutes=30)
    old = now - timedelta(hours=2)

    jobs: dict[str, Job] = {}
    status_specs = [
        ("pending", JobStatus.PENDING, {}),
        ("running", JobStatus.RUNNING, {"locked_by": "metrics-worker-1", "attempts": 1}),
        ("succeeded", JobStatus.SUCCEEDED, {"completed_at": recent, "started_at": recent - timedelta(seconds=5)}),
        ("dead_lettered", JobStatus.DEAD_LETTERED, {"last_error": "failed", "attempts": 3}),
        ("cancelled", JobStatus.CANCELLED, {}),
    ]
    for name, status, extras in status_specs:
        job = Job(
            job_type="sleep",
            payload={"seconds": 1},
            status=status,
            queue_name="metrics-q" if name == "pending" else "default",
            priority=0,
            max_attempts=3,
            attempts=extras.get("attempts", 0),
            run_at=recent,
            locked_by=extras.get("locked_by"),
            last_error=extras.get("last_error"),
            started_at=extras.get("started_at"),
            completed_at=extras.get("completed_at"),
            created_at=recent if name != "old_pending" else old,
        )
        db.add(job)
        await db.flush()
        jobs[name] = job
        db.add(
            JobEvent(
                job_id=job.id,
                event_type=JobEventType.JOB_CREATED,
                payload={"job_type": "sleep"},
                created_at=job.created_at,
            )
        )
        if status == JobStatus.SUCCEEDED:
            db.add(
                JobEvent(
                    job_id=job.id,
                    event_type=JobEventType.JOB_FAILED,
                    payload={"error": "transient"},
                    created_at=recent,
                )
            )

    old_job = Job(
        job_type="sleep",
        payload={},
        status=JobStatus.PENDING,
        queue_name="default",
        priority=0,
        max_attempts=3,
        attempts=0,
        run_at=old,
        created_at=old,
    )
    db.add(old_job)
    await db.flush()
    jobs["old_pending"] = old_job
    db.add(
        JobEvent(
            job_id=old_job.id,
            event_type=JobEventType.JOB_CREATED,
            payload={},
            created_at=old,
        )
    )

    for worker_id, queue_name, worker_status in [
        ("metrics-worker-1", "default", WorkerStatus.ONLINE),
        ("metrics-worker-2", "metrics-q", WorkerStatus.ONLINE),
        ("metrics-worker-offline", "default", WorkerStatus.OFFLINE),
    ]:
        db.add(
            Worker(
                id=worker_id,
                status=worker_status,
                queue_name=queue_name,
                last_heartbeat_at=recent,
            )
        )

    await db.commit()
    return {"jobs": jobs, "recent": recent, "old": old}
