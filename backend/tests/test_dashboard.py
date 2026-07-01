"""Tests for the ReliQueue HTML dashboard."""


def test_dashboard_returns_html(client):
    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "ReliQueue" in body
    assert "Dashboard" in body


def test_dashboard_polls_api_endpoints(client):
    response = client.get("/dashboard")

    body = response.text
    assert "/api/metrics" in body
    assert "/api/jobs" in body
    assert "/api/workers" in body
    assert "/health" in body


def test_dashboard_includes_job_status_badges(client):
    response = client.get("/dashboard")

    body = response.text
    for status in ("pending", "running", "succeeded", "dead_lettered", "cancelled"):
        assert status in body


def test_dashboard_includes_job_detail_view(client):
    response = client.get("/dashboard")

    body = response.text
    assert "/api/jobs/${jobId}" in body or "/api/jobs/" in body
    assert "/events" in body
    assert "Event timeline" in body
    assert "Payload" in body
    assert "Last error" in body or "last_error" in body.lower() or "Last error:" in body


def test_dashboard_includes_worker_health_view(client):
    response = client.get("/dashboard")

    body = response.text
    assert "/api/workers/" in body
    assert "Worker health" in body
    assert "heartbeat" in body.lower()
    assert "HEARTBEAT_STALE_SECONDS" in body or "stale" in body.lower()
