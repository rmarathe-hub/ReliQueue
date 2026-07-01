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

logger = logging.getLogger(__name__)


async def run_worker(worker_id: str, queue_name: str, poll_interval: float) -> None:
    stop_event = asyncio.Event()

    def handle_shutdown(signum: int, _frame: object) -> None:
        logger.info("[%s] shutdown signal received (signal=%s)", worker_id, signum)
        stop_event.set()

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    async with async_session_factory() as db:
        await register_worker(db, worker_id, queue_name)

    logger.info(
        "[%s] worker started queue=%s poll_interval=%ss handlers=%s lease_seconds=%s",
        worker_id,
        queue_name,
        poll_interval,
        get_registered_job_types(),
        settings.worker_lease_seconds,
    )

    last_recovery_at = time.monotonic()

    while not stop_event.is_set():
        now_mono = time.monotonic()
        if now_mono - last_recovery_at >= settings.worker_recovery_interval_seconds:
            async with async_session_factory() as db:
                recovered_jobs = await recover_expired_leases(db, queue_name=queue_name)
            if recovered_jobs:
                logger.info(
                    "[%s] recovered %s expired job lease(s) on queue=%s",
                    worker_id,
                    len(recovered_jobs),
                    queue_name,
                )
            last_recovery_at = now_mono

        async with async_session_factory() as db:
            await touch_worker_heartbeat(db, worker_id)
            job = await claim_next_job(db, worker_id=worker_id, queue_name=queue_name)

        if job is None:
            logger.debug("[%s] no jobs available on queue=%s", worker_id, queue_name)
        else:
            handler = get_handler(job.job_type)
            logger.info(
                "[%s] job claimed job_id=%s job_type=%s attempts=%s handler=%s lease_expires_at=%s",
                worker_id,
                job.id,
                job.job_type,
                job.attempts,
                handler.__name__ if handler else None,
                job.lease_expires_at.isoformat() if job.lease_expires_at else None,
            )

            if handler is None:
                logger.warning(
                    "[%s] no handler registered for claimed job job_id=%s job_type=%s",
                    worker_id,
                    job.id,
                    job.job_type,
                )
                async with async_session_factory() as db:
                    failed = await complete_job_failure(
                        db,
                        job.id,
                        worker_id,
                        f"No handler registered for job_type '{job.job_type}'",
                    )
                if failed is not None:
                    logger.info(
                        "[%s] job failed job_id=%s job_type=%s attempts=%s status=%s",
                        worker_id,
                        failed.id,
                        failed.job_type,
                        failed.attempts,
                        failed.status.value,
                    )
            else:
                try:
                    await execute_job(job)
                except UnknownJobTypeError as exc:
                    logger.warning(
                        "[%s] unknown job type after claim job_id=%s job_type=%s",
                        worker_id,
                        job.id,
                        job.job_type,
                    )
                    async with async_session_factory() as db:
                        failed = await complete_job_failure(db, job.id, worker_id, str(exc))
                    if failed is not None:
                        logger.info(
                            "[%s] job failed job_id=%s job_type=%s attempts=%s status=%s",
                            worker_id,
                            failed.id,
                            failed.job_type,
                            failed.attempts,
                            failed.status.value,
                        )
                except Exception as exc:
                    logger.exception(
                        "[%s] job handler failed job_id=%s job_type=%s",
                        worker_id,
                        job.id,
                        job.job_type,
                    )
                    async with async_session_factory() as db:
                        failed = await complete_job_failure(db, job.id, worker_id, str(exc))
                    if failed is not None:
                        logger.info(
                            "[%s] job failed job_id=%s job_type=%s attempts=%s status=%s",
                            worker_id,
                            failed.id,
                            failed.job_type,
                            failed.attempts,
                            failed.status.value,
                        )
                else:
                    async with async_session_factory() as db:
                        completed = await complete_job_success(db, job.id, worker_id)
                    if completed is not None:
                        logger.info(
                            "[%s] job succeeded job_id=%s job_type=%s attempts=%s",
                            worker_id,
                            completed.id,
                            completed.job_type,
                            completed.attempts,
                        )

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
        except TimeoutError:
            continue

    await engine.dispose()
    logger.info("[%s] worker stopped", worker_id)


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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if not settings.debug:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


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
