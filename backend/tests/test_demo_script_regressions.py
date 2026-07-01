"""Demo script regression tests."""

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from demo_common import DEFAULT_API_BASE_URL, demo_job_specs, describe_demo_profile  # noqa: E402
from seed_jobs import build_payload, SUPPORTED_JOB_TYPES  # noqa: E402
from verify_queue import verify_claims  # noqa: E402


@pytest.mark.parametrize("profile", ["standard", "full"])
def test_each_demo_spec_has_valid_job_type_and_payload(profile):
    for spec in demo_job_specs(prefix="t", profile=profile):
        assert spec["job_type"] in SUPPORTED_JOB_TYPES or spec["job_type"] in {
            "sleep",
            "fail_once",
            "fail_always",
            "random_fail",
        }
        assert isinstance(spec["payload"], dict)


def test_seed_jobs_build_payload_shapes():
    assert build_payload("sleep", seconds=1.0, probability=0.5, duration=1.0) == {"seconds": 1.0}
    assert "probability" in build_payload("random_fail", seconds=1.0, probability=0.3, duration=1.0)


def test_verify_claims_passes_without_duplicates():
    class FakeClient:
        def get(self, path: str):
            class Response:
                def raise_for_status(self):
                    return None

                def json(self):
                    if path.endswith("/events"):
                        return [{"event_type": "job_claimed", "payload": {"worker_id": "w1"}}]
                    return {}

            return Response()

    duplicates, _ = verify_claims(FakeClient(), [{"id": "job-1"}])
    assert duplicates == []


def test_run_demo_uses_configurable_api_base_url_default():
    from demo_common import DEFAULT_API_BASE_URL as COMMON_DEFAULT

    text = (SCRIPTS_DIR / "run_demo.py").read_text(encoding="utf-8")
    assert "DEFAULT_API_BASE_URL" in text
    assert "--api-base-url" in text
    assert COMMON_DEFAULT == "http://localhost:8000"


def test_demo_run_sh_references_repo_relative_paths():
    text = (SCRIPTS_DIR / "demo_run.sh").read_text(encoding="utf-8")
    assert "run_demo.py" in text
    assert "docker compose" in text
    assert "alembic upgrade head" in text


def test_readme_documents_demo_commands():
    readme = (SCRIPTS_DIR.parent / "README.md").read_text(encoding="utf-8")
    assert "./scripts/demo_run.sh" in readme or "scripts/demo_run.sh" in readme
    assert "run_demo.py" in readme
    assert describe_demo_profile("full")[:15] in readme or "random_fail" in readme
