from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import JobEventType, JobStatus
from app.models.job import Job
from app.models.job_event import JobEvent
from app.schemas.job import JobCreate
from app.services.job_errors import IdempotencyConflictError, job_matches_create_request


async def get_job_by_idempotency_key(db: AsyncSession, idempotency_key: str) -> Job | None:
    result = await db.execute(select(Job).where(Job.idempotency_key == idempotency_key))
    return result.scalar_one_or_none()


async def create_job(db: AsyncSession, data: JobCreate) -> tuple[Job, bool]:
    if data.idempotency_key:
        existing_job = await get_job_by_idempotency_key(db, data.idempotency_key)
        if existing_job is not None:
            if not job_matches_create_request(existing_job, data):
                raise IdempotencyConflictError(data.idempotency_key)
            return existing_job, False

    job = Job(
        job_type=data.job_type,
        payload=data.payload,
        status=JobStatus.PENDING,
        queue_name=data.queue_name,
        priority=data.priority,
        max_attempts=data.max_attempts,
        idempotency_key=data.idempotency_key,
    )
    db.add(job)

    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        if not data.idempotency_key:
            raise

        existing_job = await get_job_by_idempotency_key(db, data.idempotency_key)
        if existing_job is None:
            raise

        if not job_matches_create_request(existing_job, data):
            raise IdempotencyConflictError(data.idempotency_key) from None

        return existing_job, False

    event = JobEvent(
        job_id=job.id,
        event_type=JobEventType.JOB_CREATED,
        payload={
            "job_type": data.job_type,
            "queue_name": data.queue_name,
            "priority": data.priority,
            "max_attempts": data.max_attempts,
        },
    )
    db.add(event)
    await db.commit()
    await db.refresh(job)
    return job, True


async def get_job_by_id(db: AsyncSession, job_id: UUID) -> Job | None:
    result = await db.execute(select(Job).where(Job.id == job_id))
    return result.scalar_one_or_none()


async def list_jobs(
    db: AsyncSession,
    *,
    status: JobStatus | None = None,
    queue_name: str | None = None,
    job_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Job], int]:
    filters = []
    if status is not None:
        filters.append(Job.status == status)
    if queue_name is not None:
        filters.append(Job.queue_name == queue_name)
    if job_type is not None:
        filters.append(Job.job_type == job_type)

    total_result = await db.execute(select(func.count()).select_from(Job).where(*filters))
    total = total_result.scalar_one()

    result = await db.execute(
        select(Job)
        .where(*filters)
        .order_by(Job.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total


async def get_job_events(db: AsyncSession, job_id: UUID) -> list[JobEvent] | None:
    job = await get_job_by_id(db, job_id)
    if job is None:
        return None

    result = await db.execute(
        select(JobEvent)
        .where(JobEvent.job_id == job_id)
        .order_by(JobEvent.created_at.asc())
    )
    return list(result.scalars().all())
