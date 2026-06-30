from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.enums import JobStatus
from app.models.job import Job
from app.schemas.job import (
    JobCreate,
    JobDetail,
    JobEventResponse,
    JobListResponse,
    JobResponse,
)
from app.services.job_errors import IdempotencyConflictError
from app.services.jobs import create_job, get_job_by_id, get_job_events, list_jobs

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("", response_model=JobResponse)
async def submit_job(
    data: JobCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> Job:
    try:
        job, created = await create_job(db, data)
    except IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(exc),
                "idempotency_key": exc.idempotency_key,
            },
        ) from exc

    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return job


@router.get("", response_model=JobListResponse)
async def list_jobs_endpoint(
    status_filter: JobStatus | None = Query(default=None, alias="status"),
    queue_name: str | None = None,
    job_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> JobListResponse:
    jobs, total = await list_jobs(
        db,
        status=status_filter,
        queue_name=queue_name,
        job_type=job_type,
        limit=limit,
        offset=offset,
    )
    return JobListResponse(
        items=jobs,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{job_id}", response_model=JobDetail)
async def get_job_endpoint(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> Job:
    job = await get_job_by_id(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.get("/{job_id}/events", response_model=list[JobEventResponse])
async def get_job_events_endpoint(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> list[JobEventResponse]:
    events = await get_job_events(db, job_id)
    if events is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return events
