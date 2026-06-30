import argparse
import asyncio
import logging
import signal

from app.core.config import settings
from app.db.session import async_session_factory, engine
from app.services.job_claiming import claim_next_job
from app.services.job_completion import complete_job_success
from app.services.workers import register_worker, touch_worker_heartbeat
from app.worker.handlers import UnknownJobTypeError, execute_job, get_handler, get_registered_job_types

logger = logging.getLogger(__name__)


async def run_worker(worker_id: str, queue_name: str, poll_interval: float) -> None:
    stop_event = asyncio.Event()

    def handle_shutdown(signum: int, _frame: object) -> None:
        logger.info("shutdown signal received", extra={"signal": signum, "worker_id": worker_id})
        stop_event.set()

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    async with async_session_factory() as db:
        await register_worker(db, worker_id, queue_name)

    logger.info(
        "worker started",
        extra={
            "worker_id": worker_id,
            "queue_name": queue_name,
            "poll_interval": poll_interval,
            "handlers": get_registered_job_types(),
            "lease_seconds": settings.worker_lease_seconds,
        },
    )

    while not stop_event.is_set():
        async with async_session_factory() as db:
            await touch_worker_heartbeat(db, worker_id)
            job = await claim_next_job(db, worker_id=worker_id, queue_name=queue_name)

        if job is None:
            logger.info("no jobs available", extra={"worker_id": worker_id, "queue_name": queue_name})
        else:
            handler = get_handler(job.job_type)
            logger.info(
                "job claimed",
                extra={
                    "worker_id": worker_id,
                    "queue_name": queue_name,
                    "job_id": str(job.id),
                    "job_type": job.job_type,
                    "attempts": job.attempts,
                    "handler": handler.__name__ if handler else None,
                    "lease_expires_at": job.lease_expires_at.isoformat() if job.lease_expires_at else None,
                },
            )

            if handler is None:
                logger.warning(
                    "no handler registered for claimed job",
                    extra={
                        "worker_id": worker_id,
                        "job_id": str(job.id),
                        "job_type": job.job_type,
                    },
                )
            else:
                try:
                    await execute_job(job)
                except UnknownJobTypeError:
                    logger.warning(
                        "unknown job type after claim",
                        extra={"worker_id": worker_id, "job_id": str(job.id), "job_type": job.job_type},
                    )
                except Exception as exc:
                    logger.exception(
                        "job handler failed",
                        extra={"worker_id": worker_id, "job_id": str(job.id), "job_type": job.job_type},
                    )
                    # Failure handling is added on Day 15.
                else:
                    async with async_session_factory() as db:
                        completed = await complete_job_success(db, job.id, worker_id)
                    if completed is not None:
                        logger.info(
                            "job succeeded",
                            extra={
                                "worker_id": worker_id,
                                "job_id": str(completed.id),
                                "job_type": completed.job_type,
                                "attempts": completed.attempts,
                            },
                        )

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
        except TimeoutError:
            continue

    await engine.dispose()
    logger.info("worker stopped", extra={"worker_id": worker_id})


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


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
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
