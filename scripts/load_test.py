#!/usr/bin/env python3
"""Submit a batch workload, run workers, and report load-test metrics."""

from __future__ import annotations

import argparse
import atexit
import os
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx

_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_DIR.parent
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from demo_common import DEFAULT_API_BASE_URL, check_health  # noqa: E402
from verify_queue import TERMINAL_STATUSES, fetch_jobs, verify_claims  # noqa: E402

DEFAULT_DATABASE_URL = "postgresql+asyncpg://reliqueue:reliqueue@localhost:5432/reliqueue"


@dataclass(frozen=True)
class LoadTestReport:
    jobs: int
    workers: int
    queue_name: str
    prefix: str
    submit_seconds: float
    processing_seconds: float
    total_seconds: float
    jobs_by_status: dict[str, int]
    duplicate_claims: int
    throughput_jobs_per_sec: float

    def format_summary(self) -> str:
        lines = [
            "load test results:",
            f"  jobs: {self.jobs}",
            f"  workers: {self.workers}",
            f"  queue: {self.queue_name}",
            f"  prefix: {self.prefix}",
            f"  wall time: {self.total_seconds:.2f}s (submit {self.submit_seconds:.2f}s + process {self.processing_seconds:.2f}s)",
            f"  throughput: {self.throughput_jobs_per_sec:.1f} jobs/sec",
            "  status counts:",
        ]
        for status in sorted(self.jobs_by_status):
            lines.append(f"    {status}: {self.jobs_by_status[status]}")
        lines.append(f"  duplicate job_claimed events: {self.duplicate_claims}")
        return "\n".join(lines)


def resolve_python() -> Path:
    venv_python = _BACKEND_DIR / ".venv" / "bin" / "python"
    if venv_python.is_file():
        return venv_python
    return Path(sys.executable)


def start_workers(
    *,
    worker_count: int,
    queue_name: str,
    poll_interval: float,
    database_url: str,
    python_executable: Path,
) -> list[subprocess.Popen[bytes]]:
    processes: list[subprocess.Popen[bytes]] = []
    log_paths: list[Path] = []
    env = {**os.environ, "DATABASE_URL": database_url}

    for index in range(1, worker_count + 1):
        log_path = Path(f"/tmp/reliqueue-load-worker-{index}.log")
        log_paths.append(log_path)
        log_file = log_path.open("w", encoding="utf-8")
        process = subprocess.Popen(
            [
                str(python_executable),
                "-m",
                "app.worker.runner",
                "--worker-id",
                f"load-worker-{index}",
                "--queue-name",
                queue_name,
                "--poll-interval",
                str(poll_interval),
            ],
            cwd=_BACKEND_DIR,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        log_file.close()
        processes.append(process)

    time.sleep(2.0)

    dead_workers: list[str] = []
    for index, process in enumerate(processes, start=1):
        if process.poll() is not None:
            log_text = log_paths[index - 1].read_text(encoding="utf-8")
            dead_workers.append(f"load-worker-{index} exited early:\n{log_text[-2000:]}")

    if dead_workers:
        stop_workers(processes)
        raise RuntimeError("\n\n".join(dead_workers))

    return processes


def stop_workers(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
    for process in processes:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def submit_load_jobs(
    client: httpx.Client,
    *,
    count: int,
    queue_name: str,
    prefix: str,
    sleep_seconds: float,
) -> float:
    started = time.perf_counter()
    for index in range(count):
        response = client.post(
            "/api/jobs",
            json={
                "job_type": "sleep",
                "payload": {"seconds": sleep_seconds},
                "queue_name": queue_name,
                "max_attempts": 1,
                "idempotency_key": f"{prefix}-{index}",
            },
        )
        response.raise_for_status()
    return time.perf_counter() - started


def filter_jobs_by_prefix(jobs: list[dict], prefix: str) -> list[dict]:
    return [job for job in jobs if job.get("idempotency_key", "").startswith(f"{prefix}-")]


def wait_for_batch(
    client: httpx.Client,
    *,
    prefix: str,
    expected_count: int,
    timeout_seconds: float,
    poll_interval: float,
) -> list[dict]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        jobs = filter_jobs_by_prefix(fetch_jobs(client, limit=100), prefix)
        if len(jobs) < expected_count:
            time.sleep(poll_interval)
            continue
        if all(job["status"] in TERMINAL_STATUSES for job in jobs):
            return jobs
        time.sleep(poll_interval)

    jobs = filter_jobs_by_prefix(fetch_jobs(client, limit=100), prefix)
    pending_or_running = [job for job in jobs if job["status"] not in TERMINAL_STATUSES]
    raise TimeoutError(
        f"timed out after {timeout_seconds:.0f}s with {len(pending_or_running)} jobs still active "
        f"({len(jobs)}/{expected_count} matched prefix)"
    )


def build_report(
    *,
    jobs: int,
    workers: int,
    queue_name: str,
    prefix: str,
    submit_seconds: float,
    processing_seconds: float,
    batch_jobs: list[dict],
    duplicate_claims: list[str],
) -> LoadTestReport:
    jobs_by_status: dict[str, int] = {}
    for job in batch_jobs:
        jobs_by_status[job["status"]] = jobs_by_status.get(job["status"], 0) + 1

    succeeded = jobs_by_status.get("succeeded", 0)
    throughput = succeeded / processing_seconds if processing_seconds > 0 else 0.0

    return LoadTestReport(
        jobs=jobs,
        workers=workers,
        queue_name=queue_name,
        prefix=prefix,
        submit_seconds=submit_seconds,
        processing_seconds=processing_seconds,
        total_seconds=submit_seconds + processing_seconds,
        jobs_by_status=jobs_by_status,
        duplicate_claims=len(duplicate_claims),
        throughput_jobs_per_sec=throughput,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a ReliQueue API load test")
    parser.add_argument("--jobs", type=int, default=500, help="Number of sleep jobs to submit")
    parser.add_argument("--workers", type=int, default=5, help="Worker processes to start")
    parser.add_argument(
        "--api-base-url",
        default=DEFAULT_API_BASE_URL,
        help="ReliQueue API base URL",
    )
    parser.add_argument("--queue-name", default="load-test", help="Target queue name")
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.0,
        help="Sleep duration for each load-test job",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.25,
        help="Worker poll interval in seconds",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Seconds to wait for the batch to finish",
    )
    parser.add_argument(
        "--wait-poll-interval",
        type=float,
        default=0.5,
        help="Polling interval while waiting for completion",
    )
    parser.add_argument(
        "--prefix",
        default=None,
        help="Idempotency key prefix (default: load-<random>)",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        help="Postgres URL for spawned workers",
    )
    parser.add_argument(
        "--no-workers",
        action="store_true",
        help="Do not spawn workers (assume they are already running)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.jobs < 1:
        print("jobs must be at least 1", file=sys.stderr)
        return 1
    if args.workers < 1 and not args.no_workers:
        print("workers must be at least 1 unless --no-workers is set", file=sys.stderr)
        return 1

    prefix = args.prefix or f"load-{uuid.uuid4().hex[:8]}"
    python_executable = resolve_python()
    worker_processes: list[subprocess.Popen[bytes]] = []

    if not args.no_workers:
        worker_processes = start_workers(
            worker_count=args.workers,
            queue_name=args.queue_name,
            poll_interval=args.poll_interval,
            database_url=args.database_url,
            python_executable=python_executable,
        )
        atexit.register(stop_workers, worker_processes)

    total_started = time.perf_counter()

    try:
        with httpx.Client(base_url=args.api_base_url.rstrip("/"), timeout=60.0) as client:
            health = check_health(client)
            print(f"api health: {health}")

            submit_seconds = submit_load_jobs(
                client,
                count=args.jobs,
                queue_name=args.queue_name,
                prefix=prefix,
                sleep_seconds=args.sleep_seconds,
            )
            print(f"submitted {args.jobs} sleep job(s) to queue '{args.queue_name}' in {submit_seconds:.2f}s")

            processing_started = time.perf_counter()
            batch_jobs = wait_for_batch(
                client,
                prefix=prefix,
                expected_count=args.jobs,
                timeout_seconds=args.timeout,
                poll_interval=args.wait_poll_interval,
            )
            processing_seconds = time.perf_counter() - processing_started

            duplicate_claims, _claims_by_worker = verify_claims(client, batch_jobs)
            report = build_report(
                jobs=args.jobs,
                workers=args.workers if not args.no_workers else 0,
                queue_name=args.queue_name,
                prefix=prefix,
                submit_seconds=submit_seconds,
                processing_seconds=processing_seconds,
                batch_jobs=batch_jobs,
                duplicate_claims=duplicate_claims,
            )
    except (httpx.HTTPError, TimeoutError, RuntimeError) as exc:
        print(f"load test failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if worker_processes:
            stop_workers(worker_processes)

    total_seconds = time.perf_counter() - total_started
    print(report.format_summary())
    print(f"  total elapsed: {total_seconds:.2f}s")

    if duplicate_claims:
        print("duplicate job_claimed events detected:", file=sys.stderr)
        for job_id in duplicate_claims:
            print(f"  {job_id}", file=sys.stderr)
        return 1

    if report.jobs_by_status.get("succeeded", 0) != args.jobs:
        print(
            f"expected {args.jobs} succeeded jobs, got {report.jobs_by_status.get('succeeded', 0)}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
