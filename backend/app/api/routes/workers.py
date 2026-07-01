from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.enums import WorkerStatus
from app.models.worker import Worker
from app.schemas.worker import WorkerListResponse, WorkerResponse
from app.services.workers import get_worker_by_id, list_workers

router = APIRouter(prefix="/api/workers", tags=["workers"])


@router.get("", response_model=WorkerListResponse)
async def list_workers_endpoint(
    status_filter: WorkerStatus | None = Query(default=None, alias="status"),
    queue_name: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> WorkerListResponse:
    workers, total = await list_workers(
        db,
        status=status_filter,
        queue_name=queue_name,
        limit=limit,
        offset=offset,
    )
    return WorkerListResponse(
        items=workers,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{worker_id}", response_model=WorkerResponse)
async def get_worker_endpoint(
    worker_id: str,
    db: AsyncSession = Depends(get_db),
) -> Worker:
    worker = await get_worker_by_id(db, worker_id)
    if worker is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found")
    return worker
