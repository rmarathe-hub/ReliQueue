"""Tradeoffs documentation tests."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TRADEOFFS = REPO_ROOT / "docs" / "tradeoffs.md"


def test_tradeoffs_doc_exists():
    assert TRADEOFFS.is_file()


def test_tradeoffs_doc_covers_required_sections():
    text = TRADEOFFS.read_text(encoding="utf-8").lower()
    required = (
        "postgres queue vs redis vs rabbitmq",
        "at-least-once",
        "polling vs push",
        "worker leases",
        "idempotency",
        "reliqueue vs celery vs bullmq",
        "add next to reach parity",
        "choose reliqueue vs celery",
    )
    for heading in required:
        assert heading in text, f"missing section: {heading}"


def test_tradeoffs_comparison_table_includes_core_features():
    text = TRADEOFFS.read_text(encoding="utf-8")
    for feature in (
        "SKIP LOCKED",
        "Dead-letter",
        "Result backend",
        "Task chains",
        "Priority queues",
    ):
        assert feature in text


def test_tradeoffs_roadmap_items_include_effort():
    text = TRADEOFFS.read_text(encoding="utf-8")
    for item in ("Prometheus", "run_at", "Rate limiting"):
        assert item in text
    assert "**S**" in text or "**M**" in text or "**L**" in text
