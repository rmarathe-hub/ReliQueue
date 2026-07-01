"""Deploy documentation and production config tests."""

from pathlib import Path

import pytest

from app.core.config import normalize_async_database_url

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_deploy_doc_exists():
    assert (REPO_ROOT / "docs" / "deploy.md").is_file()


def test_railway_toml_exists():
    text = (REPO_ROOT / "railway.toml").read_text(encoding="utf-8")
    assert "backend/Dockerfile" in text
    assert "/health" in text


def test_entrypoint_runs_migrations_and_uvicorn():
    text = (REPO_ROOT / "backend" / "entrypoint.sh").read_text(encoding="utf-8")
    assert "alembic upgrade head" in text
    assert "uvicorn" in text
    assert "PORT" in text


def test_fly_toml_exists():
    text = (REPO_ROOT / "backend" / "fly.toml").read_text(encoding="utf-8")
    assert "/health" in text


@pytest.mark.parametrize(
    ("raw", "expected_prefix"),
    [
        ("postgres://user:pass@host:5432/db", "postgresql+asyncpg://"),
        ("postgresql://user:pass@host:5432/db", "postgresql+asyncpg://"),
        ("postgresql+asyncpg://user:pass@host:5432/db", "postgresql+asyncpg://"),
    ],
)
def test_normalize_async_database_url(raw: str, expected_prefix: str):
    assert normalize_async_database_url(raw).startswith(expected_prefix)


def test_readme_links_deploy_doc():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/deploy.md" in readme
    assert "scripts/capstone.sh" in readme
    assert "scripts/final_audit.sh" in readme
