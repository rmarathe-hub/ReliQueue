from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import JobEventType, JobStatus
from app.models.job import Job
from app.models.job_event import JobEvent
from app.models.worker import Worker


async def recover_expired_leases(
    db: AsyncSession,
    *,
    queue_name: str | None = None,
) -> list[Job]:
    now = datetime.now(UTC)
    filters = [
        Job.status == JobStatus.RUNNING,
        Job.lease_expires_at.isnot(None),
        Job.lease_expires_at < now,
    ]
    if queue_name is not None:
        filters.append(Job.queue_name == queue_name)

    result = await db.execute(select(Job).where(*filters).with_for_update(skip_locked=True))
    jobs = list(result.scalars().all())
    if not jobs:
        return []

    recovered: list[Job] = []
    for job in jobs:
        previous_worker_id = job.locked_by
        previous_lease_expires_at = job.lease_expires_at

        job.status = JobStatus.PENDING
        job.run_at = now
        job.locked_by = None
        job.locked_at = None
        job.lease_expires_at = None

        if previous_worker_id is not None:
            worker = await db.get(Worker, previous_worker_id)
            if worker is not None and worker.current_job_id == job.id:
                worker.current_job_id = None

        db.add(
            JobEvent(
                job_id=job.id,
                event_type=JobEventType.JOB_LEASE_EXPIRED,
                payload={
                    "worker_id": previous_worker_id,
                    "attempts": job.attempts,
                    "lease_expires_at": (
                        previous_lease_expires_at.isoformat() if previous_lease_expires_at else None
                    ),
                },
            )
        )
        recovered.append(job)

    await db.commit()
    for job in recovered:
        await db.refresh(job)
    return recovered
