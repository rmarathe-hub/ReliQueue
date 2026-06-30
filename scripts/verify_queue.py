#!/usr/bin/env python3
"""Summarize queue state and verify multi-worker job processing."""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter

import httpx

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


def verify_claims(client: httpx.Client, jobs: list[dict]) -> tuple[list[str], Counter[str]]:
    duplicate_claims: list[str] = []
    claims_by_worker: Counter[str] = Counter()

    for job in jobs:
        events = fetch_job_events(client, job["id"])
        claimed_events = [event for event in events if event["event_type"] == "job_claimed"]
        if len(claimed_events) > 1:
            duplicate_claims.append(job["id"])

        for event in claimed_events:
            worker_id = (event.get("payload") or {}).get("worker_id")
            if worker_id:
                claims_by_worker[worker_id] += 1

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

            jobs = fetch_jobs(client)
            duplicate_claims, claims_by_worker = verify_claims(client, jobs)
    except httpx.HTTPError as exc:
        print(f"failed to verify queue: {exc}", file=sys.stderr)
        return 1

    print("job status counts:")
    for status in sorted(counts):
        print(f"  {status}: {counts[status]}")

    if claims_by_worker:
        print("job_claimed events by worker:")
        for worker_id, claim_count in sorted(claims_by_worker.items()):
            print(f"  {worker_id}: {claim_count}")

    if duplicate_claims:
        print("duplicate job_claimed events detected:")
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

    print("no duplicate job_claimed events detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
