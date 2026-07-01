"""Tests for ReliQueue demo script helpers."""

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from demo_common import (  # noqa: E402
    demo_job_specs,
    describe_demo_profile,
    format_metrics_summary,
)


def test_demo_job_specs_returns_mixed_batch():
    specs = demo_job_specs(prefix="test", profile="standard")

    assert len(specs) == 15
    assert sum(1 for spec in specs if spec["job_type"] == "sleep") == 10
    assert sum(1 for spec in specs if spec["job_type"] == "fail_once") == 3
    assert sum(1 for spec in specs if spec["job_type"] == "fail_always") == 2
    assert all(spec["idempotency_key"].startswith("test-") for spec in specs)


def test_full_demo_job_specs_matches_day_27_batch():
    specs = demo_job_specs(prefix="full", profile="full")

    assert len(specs) == 35
    assert sum(1 for spec in specs if spec["job_type"] == "sleep") == 20
    assert sum(1 for spec in specs if spec["job_type"] == "random_fail") == 10
    assert sum(1 for spec in specs if spec["job_type"] == "fail_always") == 5
    assert all(spec["queue_name"] == "default" for spec in specs)


def test_describe_demo_profile_documents_mix():
    assert "random_fail" in describe_demo_profile("full")
    assert "fail_once" in describe_demo_profile("standard")


def test_unknown_demo_profile_raises():
    with pytest.raises(ValueError, match="unknown demo profile"):
        demo_job_specs(prefix="x", profile="missing")


def test_format_metrics_summary_includes_core_fields():
    summary = format_metrics_summary(
        {
            "jobs_by_status": {
                "pending": 2,
                "running": 1,
                "succeeded": 10,
                "dead_lettered": 1,
                "cancelled": 0,
            },
            "dead_letter_count": 1,
            "queue_depth": {"default": 2},
            "jobs_created_last_hour": 5,
            "failures_last_hour": 2,
            "worker_count": 3,
            "avg_runtime_seconds": 1.25,
        }
    )

    assert "pending: 2" in summary
    assert "succeeded: 10" in summary
    assert "dead_lettered: 1" in summary
    assert "queue_depth: default=2" in summary
    assert "avg_runtime_seconds: 1.25" in summary


def test_format_metrics_summary_handles_missing_avg_runtime():
    summary = format_metrics_summary(
        {
            "jobs_by_status": {},
            "dead_letter_count": 0,
            "queue_depth": {},
            "jobs_created_last_hour": 0,
            "failures_last_hour": 0,
            "worker_count": 0,
            "avg_runtime_seconds": None,
        }
    )

    assert "avg_runtime_seconds: —" in summary
