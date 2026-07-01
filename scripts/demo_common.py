"""Shared helpers for ReliQueue demo scripts."""

from __future__ import annotations

from typing import Any

import httpx

DEFAULT_API_BASE_URL = "http://localhost:8000"

DEMO_PROFILES = ("standard", "full")


def describe_demo_profile(profile: str) -> str:
    if profile == "full":
        return "20 sleep, 10 random_fail, 5 fail_always (expect mixed outcomes + dead-letter)"
    if profile == "standard":
        return "10 sleep, 3 fail_once, 2 fail_always (expect retries + dead-letter)"
    raise ValueError(f"unknown demo profile: {profile}")


def demo_job_specs(*, prefix: str = "demo", profile: str = "standard") -> list[dict[str, Any]]:
    """Return job specs for a demo profile."""
    if profile not in DEMO_PROFILES:
        raise ValueError(f"unknown demo profile: {profile}")
    if profile == "full":
        return _full_demo_job_specs(prefix=prefix)
    return _standard_demo_job_specs(prefix=prefix)


def _standard_demo_job_specs(*, prefix: str) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []

    for index in range(10):
        specs.append(
            {
                "job_type": "sleep",
                "payload": {"seconds": 0.1},
                "queue_name": "default",
                "max_attempts": 3,
                "idempotency_key": f"{prefix}-sleep-{index}",
            }
        )

    for index in range(3):
        specs.append(
            {
                "job_type": "fail_once",
                "payload": {},
                "queue_name": "default",
                "max_attempts": 3,
                "idempotency_key": f"{prefix}-fail-once-{index}",
            }
        )

    for index in range(2):
        specs.append(
            {
                "job_type": "fail_always",
                "payload": {"message": "demo permanent failure"},
                "queue_name": "default",
                "max_attempts": 2,
                "idempotency_key": f"{prefix}-fail-always-{index}",
            }
        )

    return specs


def _full_demo_job_specs(*, prefix: str) -> list[dict[str, Any]]:
    """Original Day 27 portfolio batch: sleep, probabilistic failures, and dead-letter."""
    specs: list[dict[str, Any]] = []

    for index in range(20):
        specs.append(
            {
                "job_type": "sleep",
                "payload": {"seconds": 0.1},
                "queue_name": "default",
                "max_attempts": 3,
                "idempotency_key": f"{prefix}-sleep-{index}",
            }
        )

    for index in range(10):
        specs.append(
            {
                "job_type": "random_fail",
                "payload": {"probability": 0.5},
                "queue_name": "default",
                "max_attempts": 3,
                "idempotency_key": f"{prefix}-random-fail-{index}",
            }
        )

    for index in range(5):
        specs.append(
            {
                "job_type": "fail_always",
                "payload": {"message": "demo permanent failure"},
                "queue_name": "default",
                "max_attempts": 2,
                "idempotency_key": f"{prefix}-fail-always-{index}",
            }
        )

    return specs


def check_health(client: httpx.Client) -> dict[str, Any]:
    response = client.get("/health")
    response.raise_for_status()
    return response.json()


def fetch_metrics(client: httpx.Client) -> dict[str, Any]:
    response = client.get("/api/metrics")
    response.raise_for_status()
    return response.json()


def submit_job(client: httpx.Client, spec: dict[str, Any]) -> int:
    response = client.post("/api/jobs", json=spec)
    response.raise_for_status()
    return response.status_code


def submit_job_batch(client: httpx.Client, specs: list[dict[str, Any]]) -> dict[str, int]:
    created = 0
    reused = 0
    for spec in specs:
        status = submit_job(client, spec)
        if status == 201:
            created += 1
        else:
            reused += 1
    return {"submitted": len(specs), "created": created, "reused": reused}


def format_metrics_summary(metrics: dict[str, Any]) -> str:
    by_status = metrics.get("jobs_by_status", {})
    lines = [
        "metrics snapshot:",
        f"  pending: {by_status.get('pending', 0)}",
        f"  running: {by_status.get('running', 0)}",
        f"  succeeded: {by_status.get('succeeded', 0)}",
        f"  dead_lettered: {metrics.get('dead_letter_count', 0)}",
        f"  cancelled: {by_status.get('cancelled', 0)}",
        f"  workers: {metrics.get('worker_count', 0)}",
        f"  jobs_created_last_hour: {metrics.get('jobs_created_last_hour', 0)}",
        f"  failures_last_hour: {metrics.get('failures_last_hour', 0)}",
    ]
    avg = metrics.get("avg_runtime_seconds")
    lines.append(f"  avg_runtime_seconds: {avg if avg is not None else '—'}")

    depth = metrics.get("queue_depth") or {}
    if depth:
        depth_text = ", ".join(f"{queue}={count}" for queue, count in sorted(depth.items()))
        lines.append(f"  queue_depth: {depth_text}")
    else:
        lines.append("  queue_depth: (empty)")

    return "\n".join(lines)
