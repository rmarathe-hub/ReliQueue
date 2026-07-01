from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.enums import JobEventType, JobStatus
from app.models.job import Job
from app.models.job_event import JobEvent
from app.models.worker import Worker


async def claim_next_job(
    db: AsyncSession,
    *,
    worker_id: str,
    queue_name: str,
    lease_seconds: int | None = None,
) -> Job | None:
    now = datetime.now(UTC)
    lease_duration = lease_seconds if lease_seconds is not None else settings.worker_lease_seconds

    result = await db.execute(
        select(Job)
        .where(
            Job.status == JobStatus.PENDING,
            Job.queue_name == queue_name,
            Job.run_at <= now,
        )
        .order_by(Job.priority.desc(), Job.run_at.asc(), Job.created_at.asc(), Job.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = result.scalar_one_or_none()
    if job is None:
        return None

    job.status = JobStatus.RUNNING
    job.locked_by = worker_id
    job.locked_at = now
    job.lease_expires_at = now + timedelta(seconds=lease_duration)
    job.attempts += 1
    if job.started_at is None:
        job.started_at = now

    worker = await db.get(Worker, worker_id)
    if worker is not None:
        worker.current_job_id = job.id

    event = JobEvent(
        job_id=job.id,
        event_type=JobEventType.JOB_CLAIMED,
        payload={
            "worker_id": worker_id,
            "attempts": job.attempts,
            "lease_expires_at": job.lease_expires_at.isoformat(),
        },
    )
    db.add(event)
    await db.commit()
    await db.refresh(job)
    return job
