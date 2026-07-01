from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import JobEventType, JobStatus
from app.models.job import Job
from app.models.job_event import JobEvent
from app.models.worker import Worker


async def complete_job_success(
    db: AsyncSession,
    job_id: UUID,
    worker_id: str,
) -> Job | None:
    job = await db.get(Job, job_id)
    if job is None or job.status != JobStatus.RUNNING:
        return None

    if job.locked_by is not None and job.locked_by != worker_id:
        return None

    now = datetime.now(UTC)
    job.status = JobStatus.SUCCEEDED
    job.completed_at = now
    job.locked_by = None
    job.locked_at = None
    job.lease_expires_at = None

    worker = await db.get(Worker, worker_id)
    if worker is not None:
        worker.current_job_id = None

    event = JobEvent(
        job_id=job.id,
        event_type=JobEventType.JOB_SUCCEEDED,
        payload={
            "worker_id": worker_id,
            "attempts": job.attempts,
        },
    )
    db.add(event)
    await db.commit()
    await db.refresh(job)
    return job
