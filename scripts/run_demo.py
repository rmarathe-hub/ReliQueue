#!/usr/bin/env python3
"""Run an end-to-end ReliQueue portfolio demo via the HTTP API."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from demo_common import (
    DEFAULT_API_BASE_URL,
    check_health,
    demo_job_specs,
    describe_demo_profile,
    fetch_metrics,
    format_metrics_summary,
    submit_job_batch,
)

SCRIPTS_DIR = _SCRIPTS_DIR
VERIFY_SCRIPT = SCRIPTS_DIR / "verify_queue.py"


def wait_for_queue_idle(
    client: httpx.Client,
    *,
    timeout_seconds: float,
    poll_interval: float,
) -> dict[str, int]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        metrics = fetch_metrics(client)
        by_status = metrics.get("jobs_by_status", {})
        if by_status.get("pending", 0) == 0 and by_status.get("running", 0) == 0:
            return by_status
        time.sleep(poll_interval)
    return fetch_metrics(client).get("jobs_by_status", {})


def run_verify(api_base_url: str) -> int:
    command = [
        sys.executable,
        str(VERIFY_SCRIPT),
        "--api-base-url",
        api_base_url,
        "--show-metrics",
    ]
    result = subprocess.run(command, check=False)
    return result.returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed, monitor, and verify a ReliQueue demo workload",
    )
    parser.add_argument(
        "--api-base-url",
        default=DEFAULT_API_BASE_URL,
        help="ReliQueue API base URL",
    )
    parser.add_argument(
        "--prefix",
        default=f"demo-{uuid.uuid4().hex[:8]}",
        help="Idempotency key prefix for seeded jobs",
    )
    parser.add_argument(
        "--profile",
        choices=("standard", "full"),
        default="standard",
        help="Demo workload shape (standard=15 jobs, full=35 jobs)",
    )
    parser.add_argument(
        "--skip-seed",
        action="store_true",
        help="Skip seeding jobs (useful if workers are already processing a batch)",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Do not wait for workers to finish",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Seconds to wait for demo jobs to finish (default: 120 standard, 180 full)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Polling interval while waiting",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip duplicate-claim verification",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    specs = demo_job_specs(prefix=args.prefix, profile=args.profile)
    wait_timeout = args.timeout if args.timeout is not None else (180.0 if args.profile == "full" else 120.0)

    try:
        with httpx.Client(base_url=args.api_base_url.rstrip("/"), timeout=30.0) as client:
            health = check_health(client)
            print(f"api health: {health}")

            if not args.skip_seed:
                counts = submit_job_batch(client, specs)
                print(
                    f"seeded demo batch ({args.profile}): {counts['submitted']} submitted "
                    f"({counts['created']} created, {counts['reused']} idempotent reuse)"
                )
                print(f"job mix: {describe_demo_profile(args.profile)}")
                print(f"idempotency prefix: {args.prefix}")
            else:
                print("skipped seeding")

            print(format_metrics_summary(fetch_metrics(client)))

            if not args.no_wait:
                print(
                    f"waiting up to {wait_timeout:.0f}s for queue to drain "
                    "(pending=0, running=0)..."
                )
                print("start workers if needed:")
                print("  cd backend && python -m app.worker.runner --worker-id worker-1")
                final_status = wait_for_queue_idle(
                    client,
                    timeout_seconds=wait_timeout,
                    poll_interval=args.poll_interval,
                )
                print("status after wait:")
                for status in sorted(final_status):
                    print(f"  {status}: {final_status[status]}")
                print(format_metrics_summary(fetch_metrics(client)))
            else:
                print("skipped wait (--no-wait)")

            print(f"dashboard: {args.api_base_url.rstrip('/')}/dashboard")
    except httpx.HTTPError as exc:
        print(f"demo failed: {exc}", file=sys.stderr)
        return 1

    if args.skip_verify or args.no_wait:
        return 0

    return run_verify(args.api_base_url)


if __name__ == "__main__":
    raise SystemExit(main())
