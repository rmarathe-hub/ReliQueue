from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import JobEventType, JobStatus, WorkerStatus
from app.models.job import Job
from app.models.job_event import JobEvent
from app.models.worker import Worker
from app.schemas.metrics import MetricsResponse

ALL_JOB_STATUSES = [status.value for status in JobStatus]
ALL_WORKER_STATUSES = [status.value for status in WorkerStatus]


async def get_metrics(db: AsyncSession) -> MetricsResponse:
    now = datetime.now(UTC)
    one_hour_ago = now - timedelta(hours=1)

    status_counts = dict.fromkeys(ALL_JOB_STATUSES, 0)
    status_rows = await db.execute(
        select(Job.status, func.count()).select_from(Job).group_by(Job.status)
    )
    for status, count in status_rows.all():
        status_counts[status.value] = count

    dead_letter_count = status_counts[JobStatus.DEAD_LETTERED.value]

    queue_depth_rows = await db.execute(
        select(Job.queue_name, func.count())
        .select_from(Job)
        .where(
            Job.status == JobStatus.PENDING,
            Job.run_at <= now,
        )
        .group_by(Job.queue_name)
        .order_by(Job.queue_name.asc())
    )
    queue_depth = {queue_name: count for queue_name, count in queue_depth_rows.all()}

    jobs_created_last_hour = await db.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.created_at >= one_hour_ago)
    )

    failures_last_hour = await db.scalar(
        select(func.count())
        .select_from(JobEvent)
        .where(
            JobEvent.event_type == JobEventType.JOB_FAILED,
            JobEvent.created_at >= one_hour_ago,
        )
    )

    worker_status_counts = dict.fromkeys(ALL_WORKER_STATUSES, 0)
    worker_rows = await db.execute(
        select(Worker.status, func.count()).select_from(Worker).group_by(Worker.status)
    )
    for status, count in worker_rows.all():
        worker_status_counts[status.value] = count

    worker_count = sum(worker_status_counts.values())

    avg_runtime = await db.scalar(
        select(
            func.avg(
                func.extract("epoch", Job.completed_at - Job.started_at)
            )
        ).where(
            Job.status == JobStatus.SUCCEEDED,
            Job.started_at.isnot(None),
            Job.completed_at.isnot(None),
        )
    )

    avg_runtime_seconds = float(avg_runtime) if avg_runtime is not None else None

    return MetricsResponse(
        jobs_by_status=status_counts,
        dead_letter_count=dead_letter_count,
        queue_depth=queue_depth,
        jobs_created_last_hour=jobs_created_last_hour or 0,
        failures_last_hour=failures_last_hour or 0,
        workers_by_status=worker_status_counts,
        worker_count=worker_count,
        avg_runtime_seconds=avg_runtime_seconds,
    )
