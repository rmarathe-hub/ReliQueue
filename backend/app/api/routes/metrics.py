from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.metrics import MetricsResponse
from app.services.metrics import get_metrics

router = APIRouter(prefix="/api", tags=["metrics"])


@router.get("/metrics", response_model=MetricsResponse)
async def metrics_endpoint(db: AsyncSession = Depends(get_db)) -> MetricsResponse:
    return await get_metrics(db)
