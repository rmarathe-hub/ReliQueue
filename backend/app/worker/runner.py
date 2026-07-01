import argparse
import asyncio
import logging
import signal
import time

from app.core.config import settings
from app.db.session import async_session_factory, engine
from app.services.job_claiming import claim_next_job
from app.services.job_completion import complete_job_success
from app.services.job_failure import complete_job_failure
from app.services.job_lease_recovery import recover_expired_leases
from app.services.workers import register_worker, touch_worker_heartbeat
from app.worker.handlers import UnknownJobTypeError, execute_job, get_handler, get_registered_job_types
from app.worker.structured_log import configure_worker_logging, emit

logger = logging.getLogger(__name__)


async def run_worker(worker_id: str, queue_name: str, poll_interval: float) -> None:
    stop_event = asyncio.Event()

    def handle_shutdown(signum: int, _frame: object) -> None:
        emit("shutdown_signal", worker_id=worker_id, signal=signum)
        stop_event.set()

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    async with async_session_factory() as db:
        await register_worker(db, worker_id, queue_name)

    emit(
        "worker_started",
        worker_id=worker_id,
        queue_name=queue_name,
        poll_interval=poll_interval,
        handlers=get_registered_job_types(),
        lease_seconds=settings.worker_lease_seconds,
    )

    last_recovery_at = time.monotonic()

    while not stop_event.is_set():
        now_mono = time.monotonic()
        if now_mono - last_recovery_at >= settings.worker_recovery_interval_seconds:
            async with async_session_factory() as db:
                recovered_jobs = await recover_expired_leases(db, queue_name=queue_name)
            if recovered_jobs:
                emit(
                    "lease_recovered",
                    worker_id=worker_id,
                    queue_name=queue_name,
                    recovered_count=len(recovered_jobs),
                )
            last_recovery_at = now_mono

        async with async_session_factory() as db:
            await touch_worker_heartbeat(db, worker_id)
            job = await claim_next_job(db, worker_id=worker_id, queue_name=queue_name)

        if job is None:
            logger.debug("no jobs available worker_id=%s queue_name=%s", worker_id, queue_name)
        else:
            handler = get_handler(job.job_type)
            emit(
                "job_claimed",
                worker_id=worker_id,
                job_id=job.id,
                job_type=job.job_type,
                attempts=job.attempts,
                queue_name=queue_name,
                status="running",
            )

            execution_started = time.perf_counter()

            if handler is None:
                emit(
                    "handler_missing",
                    worker_id=worker_id,
                    job_id=job.id,
                    job_type=job.job_type,
                    attempts=job.attempts,
                )
                async with async_session_factory() as db:
                    failed = await complete_job_failure(
                        db,
                        job.id,
                        worker_id,
                        f"No handler registered for job_type '{job.job_type}'",
                    )
                if failed is not None:
                    emit(
                        "job_failed",
                        worker_id=worker_id,
                        job_id=failed.id,
                        job_type=failed.job_type,
                        attempts=failed.attempts,
                        status=failed.status.value,
                        duration_ms=round((time.perf_counter() - execution_started) * 1000, 2),
                        error=f"No handler registered for job_type '{job.job_type}'",
                    )
            else:
                try:
                    await execute_job(job)
                except UnknownJobTypeError as exc:
                    async with async_session_factory() as db:
                        failed = await complete_job_failure(db, job.id, worker_id, str(exc))
                    if failed is not None:
                        emit(
                            "job_failed",
                            worker_id=worker_id,
                            job_id=failed.id,
                            job_type=failed.job_type,
                            attempts=failed.attempts,
                            status=failed.status.value,
                            duration_ms=round((time.perf_counter() - execution_started) * 1000, 2),
                            error=str(exc),
                        )
                except Exception as exc:
                    if settings.debug:
                        logger.exception(
                            "job handler failed worker_id=%s job_id=%s job_type=%s",
                            worker_id,
                            job.id,
                            job.job_type,
                        )
                    async with async_session_factory() as db:
                        failed = await complete_job_failure(db, job.id, worker_id, str(exc))
                    if failed is not None:
                        emit(
                            "job_failed",
                            worker_id=worker_id,
                            job_id=failed.id,
                            job_type=failed.job_type,
                            attempts=failed.attempts,
                            status=failed.status.value,
                            duration_ms=round((time.perf_counter() - execution_started) * 1000, 2),
                            error=str(exc),
                        )
                else:
                    async with async_session_factory() as db:
                        completed = await complete_job_success(db, job.id, worker_id)
                    if completed is not None:
                        emit(
                            "job_succeeded",
                            worker_id=worker_id,
                            job_id=completed.id,
                            job_type=completed.job_type,
                            attempts=completed.attempts,
                            status=completed.status.value,
                            duration_ms=round((time.perf_counter() - execution_started) * 1000, 2),
                        )

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
        except TimeoutError:
            continue

    await engine.dispose()
    emit("worker_stopped", worker_id=worker_id)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ReliQueue worker runner")
    parser.add_argument("--worker-id", required=True, help="Unique worker identifier")
    parser.add_argument("--queue-name", default="default", help="Queue to poll")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Seconds to wait between poll cycles",
    )
    return parser.parse_args()


def configure_logging() -> None:
    configure_worker_logging()


def main() -> None:
    configure_logging()
    args = parse_args()
    asyncio.run(
        run_worker(
            worker_id=args.worker_id,
            queue_name=args.queue_name,
            poll_interval=args.poll_interval,
        )
    )


if __name__ == "__main__":
    main()
