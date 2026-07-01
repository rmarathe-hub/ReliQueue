"""CI-readiness checks for the ReliQueue pytest suite."""

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
PYTEST_INI = BACKEND_DIR / "pytest.ini"


def test_pytest_ini_declares_slow_and_reliability_markers():
    text = PYTEST_INI.read_text(encoding="utf-8")
    assert "reliability:" in text
    assert "slow:" in text


def test_pytest_collects_from_backend_directory():
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "error" not in result.stderr.lower()


def test_conftest_creates_test_database_name():
    from tests.conftest import TEST_DATABASE_SYNC_URL

    assert TEST_DATABASE_SYNC_URL.endswith("reliqueue_test")


def test_conftest_runs_migrations_in_session_fixture():
    conftest = (BACKEND_DIR / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "run_migrations" in conftest
    assert "prepare_test_database" in conftest


def test_conftest_truncates_tables_between_tests():
    conftest = (BACKEND_DIR / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "TRUNCATE job_events, workers, jobs" in conftest


def test_not_slow_marker_excludes_slow_tests():
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-m", "not slow", "--collect-only", "-q"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "test_hundred_jobs_ten_workers_no_duplicate_claims" not in result.stdout


def test_reliability_marker_collects_expected_suite():
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-m", "reliability", "--collect-only", "-q"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "test_reliability.py" in result.stdout


def test_test_files_do_not_hardcode_personal_home_paths():
    forbidden = "/Users/" + "rohitmarathe"
    for path in (BACKEND_DIR / "tests").glob("test_*.py"):
        text = path.read_text(encoding="utf-8")
        assert forbidden not in text


def test_helpers_module_available_for_shared_fixtures():
    from tests.helpers import create_pending_job, seed_metrics_dataset

    assert callable(create_pending_job)
    assert callable(seed_metrics_dataset)


def test_github_actions_ci_workflow_exists():
    workflow = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
    assert workflow.is_file()
    text = workflow.read_text(encoding="utf-8")
    assert "postgres:16" in text
    assert "TEST_DATABASE_URL" in text
    assert "alembic upgrade head" in text
    assert 'pytest -m "not slow"' in text
