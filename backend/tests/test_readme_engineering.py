"""README engineering and documentation link tests."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"


def test_readme_links_to_tradeoffs_and_test_matrix():
    text = README.read_text(encoding="utf-8")
    assert "docs/tradeoffs.md" in text
    assert "docs/test_matrix.md" in text
    assert (REPO_ROOT / "docs/tradeoffs.md").is_file()
    assert (REPO_ROOT / "docs/test_matrix.md").is_file()


def test_readme_documents_run_ci_locally():
    text = README.read_text(encoding="utf-8")
    assert "Run CI locally" in text
    assert 'pytest -m "not slow"' in text
    assert "pytest -m reliability" in text
    assert "alembic upgrade head" in text


def test_readme_api_table_lists_core_endpoints():
    text = README.read_text(encoding="utf-8")
    endpoints = (
        "/health",
        "POST",
        "/api/jobs",
        "/api/jobs/{job_id}/events",
        "/api/jobs/{job_id}/retry",
        "/api/jobs/{job_id}/cancel",
        "/api/workers",
        "/api/metrics",
        "/dashboard",
    )
    for endpoint in endpoints:
        assert endpoint in text


def test_readme_references_load_test_and_ci_workflows():
    text = README.read_text(encoding="utf-8")
    assert "scripts/load_test.py" in text
    assert ".github/workflows/ci.yml" in text
    assert (REPO_ROOT / "scripts/load_test.py").is_file()
    assert (REPO_ROOT / ".github/workflows/ci.yml").is_file()


def test_readme_architecture_mentions_skip_locked_and_scripts():
    text = README.read_text(encoding="utf-8")
    assert "SKIP LOCKED" in text
    assert "load_test" in text
