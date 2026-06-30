from app.schemas.job import JobCreate
from app.models.job import Job


class IdempotencyConflictError(Exception):
    def __init__(self, idempotency_key: str) -> None:
        self.idempotency_key = idempotency_key
        super().__init__(f"Idempotency key '{idempotency_key}' is already used with different job data")


def job_matches_create_request(job: Job, data: JobCreate) -> bool:
    return (
        job.job_type == data.job_type
        and job.payload == data.payload
        and job.max_attempts == data.max_attempts
        and job.queue_name == data.queue_name
        and job.priority == data.priority
    )
