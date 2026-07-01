from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import JobEventType, JobStatus
from app.models.job import Job
from app.models.job_event import JobEvent
from app.models.worker import Worker


async def complete_job_failure(
    db: AsyncSession,
    job_id: UUID,
    worker_id: str,
    error: str,
) -> Job | None:
    job = await db.get(Job, job_id)
    if job is None or job.status != JobStatus.RUNNING:
        return None

    if job.locked_by is not None and job.locked_by != worker_id:
        return None

    job.last_error = error
    job.locked_by = None
    job.locked_at = None
    job.lease_expires_at = None

    worker = await db.get(Worker, worker_id)
    if worker is not None:
        worker.current_job_id = None

    db.add(
        JobEvent(
            job_id=job.id,
            event_type=JobEventType.JOB_FAILED,
            payload={
                "worker_id": worker_id,
                "attempts": job.attempts,
                "error": error,
            },
        )
    )

    if job.attempts < job.max_attempts:
        job.status = JobStatus.PENDING
    else:
        job.status = JobStatus.DEAD_LETTERED

    await db.commit()
    await db.refresh(job)
    return job
