import asyncio
import logging
import random
from collections.abc import Awaitable, Callable

from app.models.job import Job

logger = logging.getLogger(__name__)

JobHandler = Callable[[Job], Awaitable[None]]


class UnknownJobTypeError(Exception):
    def __init__(self, job_type: str) -> None:
        self.job_type = job_type
        super().__init__(f"No handler registered for job_type '{job_type}'")


async def handle_sleep(job: Job) -> None:
    seconds = float(job.payload.get("seconds", 1))
    await asyncio.sleep(seconds)


async def handle_fail_once(job: Job) -> None:
    if job.attempts == 1:
        raise RuntimeError("simulated one-time failure")


async def handle_fail_always(job: Job) -> None:
    message = job.payload.get("message", "simulated permanent failure")
    raise RuntimeError(message)


async def handle_random_fail(job: Job) -> None:
    probability = float(job.payload.get("probability", 0.5))
    if random.random() < probability:
        raise RuntimeError("simulated random failure")


async def handle_generate_report(job: Job) -> None:
    duration = float(job.payload.get("duration", 2))
    report_name = job.payload.get("report_name", "monthly-summary")
    logger.info("generating report %s", report_name, extra={"job_id": str(job.id)})
    await asyncio.sleep(duration)


HANDLERS: dict[str, JobHandler] = {
    "sleep": handle_sleep,
    "fail_once": handle_fail_once,
    "fail_always": handle_fail_always,
    "random_fail": handle_random_fail,
    "generate_report": handle_generate_report,
}


def get_handler(job_type: str) -> JobHandler | None:
    return HANDLERS.get(job_type)


def get_registered_job_types() -> list[str]:
    return sorted(HANDLERS)


async def execute_job(job: Job) -> None:
    handler = get_handler(job.job_type)
    if handler is None:
        raise UnknownJobTypeError(job.job_type)
    await handler(job)
