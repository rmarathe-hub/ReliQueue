#!/usr/bin/env python3
"""Submit demo jobs to the ReliQueue API."""

from __future__ import annotations

import argparse
import sys
import uuid

import httpx

SUPPORTED_JOB_TYPES = (
    "sleep",
    "fail_once",
    "fail_always",
    "random_fail",
    "generate_report",
)


def build_payload(job_type: str, *, seconds: float, probability: float, duration: float) -> dict:
    if job_type == "sleep":
        return {"seconds": seconds}
    if job_type == "random_fail":
        return {"probability": probability}
    if job_type == "generate_report":
        return {"duration": duration}
    return {}


def seed_jobs(
    *,
    count: int,
    job_type: str,
    api_base_url: str,
    queue_name: str,
    seconds: float,
    probability: float,
    duration: float,
    prefix: str,
) -> int:
    created = 0
    with httpx.Client(base_url=api_base_url.rstrip("/"), timeout=30.0) as client:
        for index in range(count):
            response = client.post(
                "/api/jobs",
                json={
                    "job_type": job_type,
                    "payload": build_payload(
                        job_type,
                        seconds=seconds,
                        probability=probability,
                        duration=duration,
                    ),
                    "queue_name": queue_name,
                    "idempotency_key": f"{prefix}-{index}-{uuid.uuid4()}",
                },
            )
            response.raise_for_status()
            if response.status_code == 201:
                created += 1
    return created


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed ReliQueue with demo jobs")
    parser.add_argument("--count", type=int, default=20, help="Number of jobs to submit")
    parser.add_argument(
        "--job-type",
        choices=SUPPORTED_JOB_TYPES,
        default="sleep",
        help="Job handler type",
    )
    parser.add_argument(
        "--api-base-url",
        default="http://localhost:8000",
        help="ReliQueue API base URL",
    )
    parser.add_argument("--queue-name", default="default", help="Target queue name")
    parser.add_argument(
        "--seconds",
        type=float,
        default=0.1,
        help="Sleep duration for sleep jobs",
    )
    parser.add_argument(
        "--probability",
        type=float,
        default=0.5,
        help="Failure probability for random_fail jobs",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=1.0,
        help="Simulated duration for generate_report jobs",
    )
    parser.add_argument(
        "--prefix",
        default="seed",
        help="Idempotency key prefix for seeded jobs",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.count < 1:
        print("count must be at least 1", file=sys.stderr)
        return 1

    try:
        created = seed_jobs(
            count=args.count,
            job_type=args.job_type,
            api_base_url=args.api_base_url,
            queue_name=args.queue_name,
            seconds=args.seconds,
            probability=args.probability,
            duration=args.duration,
            prefix=args.prefix,
        )
    except httpx.HTTPError as exc:
        print(f"failed to seed jobs: {exc}", file=sys.stderr)
        return 1

    print(
        f"submitted {args.count} {args.job_type} job(s) to queue '{args.queue_name}' "
        f"({created} newly created)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
