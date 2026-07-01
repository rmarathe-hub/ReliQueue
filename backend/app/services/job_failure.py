from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.enums import JobEventType, JobStatus
from app.models.job import Job
from app.models.job_event import JobEvent
from app.models.worker import Worker
from app.services.retry_policy import calculate_retry_run_at


async def complete_job_failure(
    db: AsyncSession,
    job_id: UUID,
    worker_id: str,
    error: str,
) -> Job | None:
    job = await db.get(Job, job_id)
    if job is None or job.status != JobStatus.RUNNING:
        return None

    if job.locked_by != worker_id:
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
        now = datetime.now(UTC)
        retry_at = calculate_retry_run_at(
            now,
            job.attempts,
            base_delay_seconds=settings.retry_base_delay_seconds,
            max_delay_seconds=settings.retry_max_delay_seconds,
            jitter=settings.retry_jitter_enabled,
        )
        job.status = JobStatus.PENDING
        job.run_at = retry_at
        db.add(
            JobEvent(
                job_id=job.id,
                event_type=JobEventType.JOB_RETRY_SCHEDULED,
                payload={
                    "worker_id": worker_id,
                    "attempts": job.attempts,
                    "run_at": retry_at.isoformat(),
                    "delay_seconds": (retry_at - now).total_seconds(),
                },
            )
        )
    else:
        job.status = JobStatus.DEAD_LETTERED

    await db.commit()
    await db.refresh(job)
    return job
