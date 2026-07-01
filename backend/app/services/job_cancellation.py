from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import JobEventType, JobStatus
from app.models.job import Job
from app.models.job_event import JobEvent
from app.services.job_errors import JobCancellationNotAllowedError
from app.services.jobs import get_job_by_id


async def cancel_job(db: AsyncSession, job_id: UUID) -> Job:
    job = await get_job_by_id(db, job_id)
    if job is None:
        raise LookupError("Job not found")

    if job.status != JobStatus.PENDING:
        raise JobCancellationNotAllowedError(str(job_id), job.status.value)

    job.status = JobStatus.CANCELLED

    db.add(
        JobEvent(
            job_id=job.id,
            event_type=JobEventType.JOB_CANCELLED,
            payload={
                "previous_status": JobStatus.PENDING.value,
            },
        )
    )
    await db.commit()
    await db.refresh(job)
    return job
