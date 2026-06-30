from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import JobStatus, WorkerStatus
from app.models.job import Job
from app.models.worker import Worker


async def register_worker(db: AsyncSession, worker_id: str, queue_name: str) -> Worker:
    now = datetime.now(UTC)
    worker = await db.get(Worker, worker_id)

    if worker is None:
        worker = Worker(
            id=worker_id,
            status=WorkerStatus.ONLINE,
            queue_name=queue_name,
            last_heartbeat_at=now,
        )
        db.add(worker)
    else:
        worker.status = WorkerStatus.ONLINE
        worker.queue_name = queue_name
        worker.last_heartbeat_at = now

    await db.commit()
    await db.refresh(worker)
    return worker


async def touch_worker_heartbeat(db: AsyncSession, worker_id: str) -> None:
    worker = await db.get(Worker, worker_id)
    if worker is None:
        return

    worker.status = WorkerStatus.ONLINE
    worker.last_heartbeat_at = datetime.now(UTC)
    await db.commit()


async def count_available_jobs(db: AsyncSession, queue_name: str) -> int:
    now = datetime.now(UTC)
    result = await db.execute(
        select(func.count())
        .select_from(Job)
        .where(
            Job.status == JobStatus.PENDING,
            Job.queue_name == queue_name,
            Job.run_at <= now,
        )
    )
    return result.scalar_one()


async def peek_next_available_job(db: AsyncSession, queue_name: str) -> Job | None:
    now = datetime.now(UTC)
    result = await db.execute(
        select(Job)
        .where(
            Job.status == JobStatus.PENDING,
            Job.queue_name == queue_name,
            Job.run_at <= now,
        )
        .order_by(Job.priority.desc(), Job.run_at.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()
