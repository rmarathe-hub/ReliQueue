"""Dashboard security and regression checks."""

from pathlib import Path

DASHBOARD_HTML = Path(__file__).resolve().parents[1] / "app" / "static" / "dashboard.html"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _body(client) -> str:
    return client.get("/dashboard").text


def test_dashboard_includes_all_dependent_api_endpoints(client):
    body = _body(client)
    for endpoint in ("/health", "/api/metrics", "/api/jobs", "/api/workers"):
        assert endpoint in body


def test_dashboard_includes_dead_letter_card(client):
    assert "Dead letter" in _body(client)


def test_dashboard_includes_queue_depth_section(client):
    body = _body(client)
    assert "queue-depth" in body
    assert "Queue depth" in body


def test_dashboard_includes_avg_runtime_section(client):
    body = _body(client)
    assert "Avg runtime" in body
    assert "avg_runtime_seconds" in body


def test_dashboard_includes_recent_jobs_section(client):
    body = _body(client)
    assert "Recent jobs" in body
    assert "jobs-table-wrap" in body


def test_dashboard_includes_worker_health_section(client):
    body = _body(client)
    assert "Worker health" in body
    assert "workers-table-wrap" in body


def test_dashboard_includes_event_timeline_rendering(client):
    body = _body(client)
    assert "Event timeline" in body
    assert "timeline-table" in body


def test_dashboard_includes_error_handling_ui(client):
    body = _body(client)
    assert "error-banner" in body
    assert "Dashboard refresh failed" in body


def test_dashboard_contains_no_env_or_secrets(client):
    body = _body(client).lower()
    for token in (".env", "password", "token", "secret", "postgresql", "database_url"):
        assert token not in body


def test_dashboard_static_file_contains_no_personal_absolute_path():
    text = DASHBOARD_HTML.read_text(encoding="utf-8")
    forbidden = "/Users/" + "rohitmarathe"
    assert forbidden not in text
    assert "C:\\Users\\" not in text


def test_readme_contains_no_committed_env_file():
    assert not (REPO_ROOT / ".env").exists()
