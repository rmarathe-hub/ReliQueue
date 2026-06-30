from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import JobStatus


class JobCreate(BaseModel):
    job_type: str = Field(..., min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = Field(default=3, ge=1, le=100)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)
    queue_name: str = Field(default="default", min_length=1, max_length=128)
    priority: int = Field(default=0, ge=0)


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_type: str
    payload: dict[str, Any]
    status: JobStatus
    queue_name: str
    priority: int
    max_attempts: int
    attempts: int
    idempotency_key: str | None
    run_at: datetime
    created_at: datetime


class JobDetail(JobResponse):
    locked_by: str | None
    locked_at: datetime | None
    lease_expires_at: datetime | None
    last_error: str | None
    started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime


class JobEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    event_type: str
    payload: dict[str, Any] | None
    created_at: datetime


class JobListResponse(BaseModel):
    items: list[JobResponse]
    total: int
    limit: int
    offset: int
