"""Extended demo script and helper tests."""

import os
import stat
import sys
from pathlib import Path

import httpx
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from demo_common import (  # noqa: E402
    DEFAULT_API_BASE_URL,
    check_health,
    demo_job_specs,
    describe_demo_profile,
    format_metrics_summary,
    submit_job_batch,
)
from seed_jobs import SUPPORTED_JOB_TYPES, build_payload  # noqa: E402
from verify_queue import TERMINAL_STATUSES, verify_claims  # noqa: E402


def test_demo_run_shell_script_exists_and_is_executable():
    script = SCRIPTS_DIR / "demo_run.sh"
    assert script.is_file()
    assert os.access(script, os.X_OK)


def test_demo_run_shell_script_does_not_hardcode_user_home():
    text = (SCRIPTS_DIR / "demo_run.sh").read_text(encoding="utf-8")
    assert "/Users/" not in text


def test_run_demo_script_exists():
    assert (SCRIPTS_DIR / "run_demo.py").is_file()


def test_demo_common_default_api_base_url_is_localhost():
    assert DEFAULT_API_BASE_URL == "http://localhost:8000"


@pytest.mark.parametrize("profile,expected_count", [("standard", 15), ("full", 35)])
def test_demo_job_specs_counts(profile, expected_count):
    specs = demo_job_specs(prefix="count", profile=profile)
    assert len(specs) == expected_count


def test_demo_job_specs_use_configurable_prefix():
    specs = demo_job_specs(prefix="custom", profile="standard")
    assert all(spec["idempotency_key"].startswith("custom-") for spec in specs)


def test_demo_job_specs_include_required_submission_fields():
    for spec in demo_job_specs(prefix="fields", profile="full"):
        assert "job_type" in spec
        assert "payload" in spec
        assert "queue_name" in spec
        assert "max_attempts" in spec
        assert "idempotency_key" in spec


@pytest.mark.parametrize("job_type", SUPPORTED_JOB_TYPES)
def test_seed_jobs_build_payload_for_supported_types(job_type):
    payload = build_payload(
        job_type,
        seconds=0.1,
        probability=0.5,
        duration=1.0,
    )
    assert isinstance(payload, dict)


def test_verify_queue_terminal_statuses_include_expected_values():
    assert TERMINAL_STATUSES == {"succeeded", "dead_lettered", "cancelled"}


def test_verify_claims_detects_duplicate_job_claimed_events():
    class FakeClient:
        def get(self, path: str):
            class Response:
                def raise_for_status(self):
                    return None

                def json(self):
                    if path.endswith("/events"):
                        return [
                            {"event_type": "job_claimed", "payload": {"worker_id": "w1", "attempts": 1}},
                            {"event_type": "job_claimed", "payload": {"worker_id": "w2", "attempts": 1}},
                        ]
                    return {}

            return Response()

    duplicates, claims = verify_claims(FakeClient(), [{"id": "job-1"}])
    assert duplicates == ["job-1"]
    assert claims["w1"] == 1
    assert claims["w2"] == 1


def test_verify_claims_allows_retry_claims_on_different_attempts():
    class FakeClient:
        def get(self, path: str):
            class Response:
                def raise_for_status(self):
                    return None

                def json(self):
                    if path.endswith("/events"):
                        return [
                            {"event_type": "job_claimed", "payload": {"worker_id": "w1", "attempts": 1}},
                            {"event_type": "job_failed", "payload": {}},
                            {"event_type": "job_claimed", "payload": {"worker_id": "w1", "attempts": 2}},
                        ]
                    return {}

            return Response()

    duplicates, _ = verify_claims(FakeClient(), [{"id": "job-1"}])
    assert duplicates == []


def test_format_metrics_summary_handles_empty_queue_depth():
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
    assert "queue_depth: (empty)" in summary


def test_check_health_parses_ok_response():
    class FakeClient:
        def get(self, path: str):
            assert path == "/health"

            class Response:
                def raise_for_status(self):
                    return None

                def json(self):
                    return {"status": "ok", "database": "ok"}

            return Response()

    assert check_health(FakeClient())["status"] == "ok"


def test_submit_job_batch_counts_created_and_reused():
    seen: set[str] = set()

    class FakeClient:
        def post(self, path: str, json: dict):
            assert path == "/api/jobs"

            class Response:
                def raise_for_status(self):
                    return None

                status_code = 201 if json["idempotency_key"] not in seen else 200

            seen.add(json["idempotency_key"])
            return Response()

    specs = demo_job_specs(prefix="batch", profile="standard")[:2]
    specs.append({**specs[0]})
    counts = submit_job_batch(FakeClient(), specs)
    assert counts["submitted"] == 3
    assert counts["created"] == 2
    assert counts["reused"] == 1


def test_run_demo_module_exposes_dashboard_url_in_source():
    text = (SCRIPTS_DIR / "run_demo.py").read_text(encoding="utf-8")
    assert "/dashboard" in text
    assert "--profile" in text


def test_demo_common_profiles_documented_in_readme():
    readme = (Path(__file__).resolve().parents[2] / "README.md").read_text(encoding="utf-8")
    assert "demo_run.sh" in readme
    assert "run_demo.py" in readme
    assert describe_demo_profile("full")[:10] in readme or "random_fail" in readme
