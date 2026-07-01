"""CI safety and determinism checks."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent


def test_tests_use_test_database_url():
    from tests.conftest import TEST_DATABASE_URL

    assert "reliqueue_test" in TEST_DATABASE_URL


def test_no_committed_dot_env():
    assert not (REPO_ROOT / ".env").exists()


def test_env_example_exists_without_secrets():
    example = REPO_ROOT / ".env.example"
    assert example.is_file()
    text = example.read_text(encoding="utf-8").lower()
    assert "password=" not in text or "reliqueue" in text


def test_readme_commands_reference_existing_files():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for path in (
        "scripts/run_demo.py",
        "scripts/demo_run.sh",
        "scripts/seed_jobs.py",
        "scripts/verify_queue.py",
        "scripts/load_test.py",
        "docs/tradeoffs.md",
        "docker-compose.yml",
    ):
        assert path in readme
        assert (REPO_ROOT / path).exists()


def test_pytest_strict_markers_can_be_enabled():
    ini = (BACKEND_DIR / "pytest.ini").read_text(encoding="utf-8")
    assert "reliability" in ini
    assert "slow" in ini


def test_no_personal_paths_in_scripts_or_docs():
    forbidden = "/Users/" + "rohitmarathe"
    for pattern in ("scripts/*.py", "scripts/*.sh", "docs/*.md", "README.md"):
        for path in REPO_ROOT.glob(pattern):
            assert forbidden not in path.read_text(encoding="utf-8")


def test_delete_jobs_list_returns_405(client):
    assert client.delete("/api/jobs").status_code == 405


def test_put_jobs_list_returns_405(client):
    assert client.put("/api/jobs").status_code == 405


def test_post_jobs_with_malformed_json_returns_422(client):
    response = client.post(
        "/api/jobs",
        content=b"not-json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
