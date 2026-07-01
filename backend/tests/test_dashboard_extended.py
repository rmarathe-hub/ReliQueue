"""Extended dashboard static content and route regression tests."""

from pathlib import Path

DASHBOARD_HTML = Path(__file__).resolve().parents[1] / "app" / "static" / "dashboard.html"


def _dashboard_text(client) -> str:
    return client.get("/dashboard").text


def test_dashboard_static_file_exists():
    assert DASHBOARD_HTML.is_file()


def test_dashboard_static_file_matches_route_content(client):
    route_body = _dashboard_text(client)
    file_body = DASHBOARD_HTML.read_text(encoding="utf-8")
    assert "ReliQueue" in route_body
    assert route_body == file_body


def test_dashboard_includes_metrics_cards_section(client):
    body = _dashboard_text(client)
    assert "metric-cards" in body
    assert "renderCards" in body


def test_dashboard_includes_jobs_table_section(client):
    body = _dashboard_text(client)
    assert "jobs-table-wrap" in body
    assert "Recent jobs" in body


def test_dashboard_includes_workers_table_section(client):
    body = _dashboard_text(client)
    assert "workers-table-wrap" in body
    assert "Workers" in body


def test_dashboard_includes_queue_depth_section(client):
    body = _dashboard_text(client)
    assert "queue-depth" in body
    assert "Queue depth" in body


def test_dashboard_includes_avg_runtime_display(client):
    body = _dashboard_text(client)
    assert "Avg runtime" in body
    assert "avg_runtime_seconds" in body


def test_dashboard_includes_dead_letter_display(client):
    body = _dashboard_text(client)
    assert "Dead letter" in body or "dead_letter" in body


def test_dashboard_has_refresh_interval(client):
    body = _dashboard_text(client)
    assert "REFRESH_MS" in body
    assert "5000" in body
    assert "Auto-refresh" in body


def test_dashboard_includes_error_banner(client):
    body = _dashboard_text(client)
    assert "error-banner" in body
    assert "Dashboard refresh failed" in body


def test_dashboard_does_not_contain_secrets(client):
    body = _dashboard_text(client).lower()
    for secret in ("password", "postgresql", "database_url", "api_key", "secret"):
        assert secret not in body


def test_dashboard_does_not_contain_local_absolute_paths(client):
    body = _dashboard_text(client)
    assert "/Users/" not in body
    assert "C:\\" not in body


def test_dashboard_route_works_after_metrics_seed(client, job_payload):
    client.post("/api/jobs", json=job_payload)
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
