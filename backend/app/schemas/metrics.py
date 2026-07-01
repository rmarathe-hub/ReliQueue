from pydantic import BaseModel


class MetricsResponse(BaseModel):
    jobs_by_status: dict[str, int]
    dead_letter_count: int
    queue_depth: dict[str, int]
    jobs_created_last_hour: int
    failures_last_hour: int
    workers_by_status: dict[str, int]
    worker_count: int
    avg_runtime_seconds: float | None
