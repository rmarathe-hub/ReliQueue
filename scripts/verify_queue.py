#!/usr/bin/env python3
"""Summarize queue state and verify multi-worker job processing."""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from demo_common import fetch_metrics, format_metrics_summary

TERMINAL_STATUSES = {"succeeded", "dead_lettered", "cancelled"}


def fetch_jobs(client: httpx.Client, *, status: str | None = None, limit: int = 100) -> list[dict]:
    params: dict[str, str | int] = {"limit": limit, "offset": 0}
    if status is not None:
        params["status"] = status

    items: list[dict] = []
    while True:
        response = client.get("/api/jobs", params=params)
        response.raise_for_status()
        payload = response.json()
        items.extend(payload["items"])
        if len(items) >= payload["total"]:
            break
        params["offset"] = len(items)
    return items


def fetch_job_events(client: httpx.Client, job_id: str) -> list[dict]:
    response = client.get(f"/api/jobs/{job_id}/events")
    response.raise_for_status()
    return response.json()


def summarize_queue(client: httpx.Client) -> dict[str, int]:
    jobs = fetch_jobs(client)
    counts = Counter(job["status"] for job in jobs)
    return dict(counts)


def filter_jobs_by_prefix(jobs: list[dict], prefix: str | None) -> list[dict]:
    if prefix is None:
        return jobs
    needle = f"{prefix}-"
    return [job for job in jobs if job.get("idempotency_key", "").startswith(needle)]


def verify_claims(client: httpx.Client, jobs: list[dict]) -> tuple[list[str], Counter[str]]:
    """Flag jobs with more than one job_claimed event for the same attempt number."""
    duplicate_claims: list[str] = []
    claims_by_worker: Counter[str] = Counter()

    for job in jobs:
        events = fetch_job_events(client, job["id"])
        claimed_events = [event for event in events if event["event_type"] == "job_claimed"]
        attempts_seen: set[int] = set()
        has_duplicate_attempt = False

        for event in claimed_events:
            payload = event.get("payload") or {}
            worker_id = payload.get("worker_id")
            if worker_id:
                claims_by_worker[worker_id] += 1

            attempt = payload.get("attempts")
            if attempt is None:
                continue
            if attempt in attempts_seen:
                has_duplicate_attempt = True
                break
            attempts_seen.add(attempt)

        if has_duplicate_attempt:
            duplicate_claims.append(job["id"])

    return duplicate_claims, claims_by_worker


def wait_for_jobs(
    client: httpx.Client,
    *,
    expected_succeeded: int,
    timeout_seconds: float,
    poll_interval: float,
) -> dict[str, int]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        counts = summarize_queue(client)
        if counts.get("succeeded", 0) >= expected_succeeded:
            return counts
        time.sleep(poll_interval)
    return summarize_queue(client)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify ReliQueue queue state")
    parser.add_argument(
        "--api-base-url",
        default="http://localhost:8000",
        help="ReliQueue API base URL",
    )
    parser.add_argument(
        "--expected-succeeded",
        type=int,
        default=None,
        help="Wait until at least this many jobs have succeeded",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Seconds to wait when --expected-succeeded is set",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Polling interval while waiting",
    )
    parser.add_argument(
        "--show-metrics",
        action="store_true",
        help="Print /api/metrics snapshot after verification",
    )
    parser.add_argument(
        "--prefix",
        default=None,
        help="Only verify jobs whose idempotency_key starts with PREFIX-",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        with httpx.Client(base_url=args.api_base_url.rstrip("/"), timeout=30.0) as client:
            if args.expected_succeeded is not None:
                counts = wait_for_jobs(
                    client,
                    expected_succeeded=args.expected_succeeded,
                    timeout_seconds=args.timeout,
                    poll_interval=args.poll_interval,
                )
            else:
                counts = summarize_queue(client)

            jobs = filter_jobs_by_prefix(fetch_jobs(client), args.prefix)
            if args.prefix is not None:
                counts = dict(Counter(job["status"] for job in jobs))

            duplicate_claims, claims_by_worker = verify_claims(client, jobs)

            print("job status counts:")
            for status in sorted(counts):
                print(f"  {status}: {counts[status]}")

            if claims_by_worker:
                print("job_claimed events by worker:")
                for worker_id, claim_count in sorted(claims_by_worker.items()):
                    print(f"  {worker_id}: {claim_count}")

            if duplicate_claims:
                print("duplicate job_claimed events for the same attempt detected:")
                for job_id in duplicate_claims:
                    print(f"  {job_id}")
                return 1

            if args.expected_succeeded is not None and counts.get("succeeded", 0) < args.expected_succeeded:
                print(
                    f"timed out waiting for {args.expected_succeeded} succeeded jobs "
                    f"(got {counts.get('succeeded', 0)})",
                    file=sys.stderr,
                )
                return 1

            if args.show_metrics:
                print(format_metrics_summary(fetch_metrics(client)))

            print("no duplicate job_claimed events for the same attempt detected")
            return 0
    except httpx.HTTPError as exc:
        print(f"failed to verify queue: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
