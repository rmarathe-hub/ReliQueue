"""Load test script tests."""

import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from load_test import build_report, filter_jobs_by_prefix  # noqa: E402


def test_load_test_script_exists():
    assert (SCRIPTS_DIR / "load_test.py").is_file()


def test_load_test_help_lists_core_flags():
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "load_test.py"), "-h"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--jobs" in result.stdout
    assert "--workers" in result.stdout
    assert "--no-workers" in result.stdout


def test_filter_jobs_by_prefix():
    jobs = [
        {"id": "1", "idempotency_key": "load-abc-0", "status": "succeeded"},
        {"id": "2", "idempotency_key": "demo-0", "status": "succeeded"},
        {"id": "3", "idempotency_key": "load-abc-1", "status": "pending"},
    ]
    filtered = filter_jobs_by_prefix(jobs, "load-abc")
    assert len(filtered) == 2
    assert {job["id"] for job in filtered} == {"1", "3"}


def test_build_report_computes_throughput_and_counts():
    batch_jobs = [{"status": "succeeded"} for _ in range(50)]
    report = build_report(
        jobs=50,
        workers=5,
        queue_name="load-test",
        prefix="load-test-prefix",
        submit_seconds=1.0,
        processing_seconds=0.5,
        batch_jobs=batch_jobs,
        duplicate_claims=[],
    )
    assert report.throughput_jobs_per_sec == 100.0
    assert report.jobs_by_status == {"succeeded": 50}
    assert report.duplicate_claims == 0
    assert "throughput: 100.0 jobs/sec" in report.format_summary()


def test_readme_documents_load_test():
    readme = (SCRIPTS_DIR.parent / "README.md").read_text(encoding="utf-8")
    assert "scripts/load_test.py" in readme
    assert "--jobs 500" in readme
    assert "duplicate claims" in readme.lower() or "Duplicate claims" in readme
