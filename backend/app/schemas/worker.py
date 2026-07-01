from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import WorkerStatus


class WorkerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: WorkerStatus
    queue_name: str
    current_job_id: UUID | None
    last_heartbeat_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WorkerListResponse(BaseModel):
    items: list[WorkerResponse]
    total: int
    limit: int
    offset: int
