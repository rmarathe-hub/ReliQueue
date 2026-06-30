import enum


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    DEAD_LETTERED = "dead_lettered"
    CANCELLED = "cancelled"


class WorkerStatus(str, enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"


class JobEventType:
    JOB_CREATED = "job_created"
    JOB_CLAIMED = "job_claimed"
    JOB_SUCCEEDED = "job_succeeded"
    JOB_FAILED = "job_failed"
    JOB_RETRY_SCHEDULED = "job_retry_scheduled"
    JOB_MANUALLY_RETRIED = "job_manually_retried"
    JOB_CANCELLED = "job_cancelled"
    JOB_LEASE_EXPIRED = "job_lease_expired"
