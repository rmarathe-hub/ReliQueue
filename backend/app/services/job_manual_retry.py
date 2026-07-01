from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import JobEventType, JobStatus
from app.models.job import Job
from app.models.job_event import JobEvent
from app.services.job_errors import ManualRetryNotAllowedError
from app.services.jobs import get_job_by_id

MANUAL_RETRY_STATUSES = {JobStatus.DEAD_LETTERED, JobStatus.CANCELLED}


async def manual_retry_job(db: AsyncSession, job_id: UUID) -> Job:
    job = await get_job_by_id(db, job_id)
    if job is None:
        raise LookupError("Job not found")

    if job.status not in MANUAL_RETRY_STATUSES:
        raise ManualRetryNotAllowedError(str(job_id), job.status.value)

    previous_status = job.status.value
    previous_attempts = job.attempts
    now = datetime.now(UTC)

    job.status = JobStatus.PENDING
    job.attempts = 0
    job.run_at = now
    job.last_error = None
    job.locked_by = None
    job.locked_at = None
    job.lease_expires_at = None
    job.completed_at = None

    db.add(
        JobEvent(
            job_id=job.id,
            event_type=JobEventType.JOB_MANUALLY_RETRIED,
            payload={
                "previous_status": previous_status,
                "previous_attempts": previous_attempts,
                "run_at": now.isoformat(),
            },
        )
    )
    await db.commit()
    await db.refresh(job)
    return job
