from app.schemas.job import JobCreate
from app.models.job import Job


class IdempotencyConflictError(Exception):
    def __init__(self, idempotency_key: str) -> None:
        self.idempotency_key = idempotency_key
        super().__init__(f"Idempotency key '{idempotency_key}' is already used with different job data")


class ManualRetryNotAllowedError(Exception):
    def __init__(self, job_id: str, status: str) -> None:
        self.job_id = job_id
        self.status = status
        super().__init__(f"Job '{job_id}' with status '{status}' cannot be manually retried")


class JobCancellationNotAllowedError(Exception):
    def __init__(self, job_id: str, status: str) -> None:
        self.job_id = job_id
        self.status = status
        super().__init__(f"Job '{job_id}' with status '{status}' cannot be cancelled")


def job_matches_create_request(job: Job, data: JobCreate) -> bool:
    return (
        job.job_type == data.job_type
        and job.payload == data.payload
        and job.max_attempts == data.max_attempts
        and job.queue_name == data.queue_name
        and job.priority == data.priority
    )
