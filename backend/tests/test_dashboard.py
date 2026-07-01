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
