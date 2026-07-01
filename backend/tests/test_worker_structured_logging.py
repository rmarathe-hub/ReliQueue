"""Structured worker logging tests."""

import json
from uuid import uuid4

from app.worker.structured_log import format_event


def test_format_event_job_succeeded_includes_core_fields() -> None:
    job_id = uuid4()
    line = format_event(
        "job_succeeded",
        worker_id="worker-1",
        job_id=job_id,
        job_type="sleep",
        duration_ms=12.5,
        status="succeeded",
        attempts=1,
    )

    payload = json.loads(line)
    assert payload["event"] == "job_succeeded"
    assert payload["worker_id"] == "worker-1"
    assert payload["job_id"] == str(job_id)
    assert payload["job_type"] == "sleep"
    assert payload["duration_ms"] == 12.5
    assert payload["status"] == "succeeded"
    assert payload["attempts"] == 1
    assert "timestamp" in payload


def test_format_event_omits_none_fields() -> None:
    payload = json.loads(
        format_event("worker_started", worker_id="worker-2", queue_name="default", job_id=None)
    )
    assert "job_id" not in payload
    assert payload["event"] == "worker_started"


def test_format_event_job_failed_includes_error() -> None:
    payload = json.loads(
        format_event(
            "job_failed",
            worker_id="worker-3",
            job_id=uuid4(),
            job_type="fail_always",
            duration_ms=3.2,
            status="pending",
            attempts=1,
            error="simulated permanent failure",
        )
    )
    assert payload["event"] == "job_failed"
    assert payload["status"] == "pending"
    assert payload["error"] == "simulated permanent failure"


def test_runner_module_exports_configure_logging() -> None:
    from app.worker import runner

    assert callable(runner.configure_logging)
