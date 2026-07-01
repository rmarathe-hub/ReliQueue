"""Extended health endpoint tests."""

import json


def test_health_returns_ok_status_and_database(client):
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


def test_health_response_has_only_expected_top_level_keys(client):
    body = client.get("/health").json()

    assert set(body.keys()) == {"status", "database"}


def test_health_response_is_json_serializable(client):
    body = client.get("/health").json()
    serialized = json.dumps(body)
    assert '"status"' in serialized
    assert '"database"' in serialized


def test_health_does_not_expose_database_url(client):
    response = client.get("/health")
    text = response.text.lower()
    assert "postgresql" not in text
    assert "password" not in text
    assert "database_url" not in text
