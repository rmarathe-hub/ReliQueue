"""Job creation and API validation tests."""

from datetime import UTC, datetime, timedelta

import pytest


@pytest.mark.parametrize(
    "payload_override,expected_status",
    [
        ({}, 201),
        ({"payload": {}}, 201),
        ({"payload": {"nested": {"a": 1}}}, 201),
    ],
)
def test_create_job_payload_variants(client, job_payload, payload_override, expected_status):
    body = {**job_payload, **payload_override}
    if "payload" in payload_override and payload_override["payload"] == {}:
        body.pop("payload", None)
        body["payload"] = {}
    response = client.post("/api/jobs", json=body)
    assert response.status_code == expected_status


def test_create_job_without_payload_defaults_to_empty_object(client):
    response = client.post(
        "/api/jobs",
        json={"job_type": "sleep", "idempotency_key": "no-payload-key"},
    )
    assert response.status_code == 201
    assert response.json()["payload"] == {}


@pytest.mark.parametrize(
    "invalid_body",
    [
        {"payload": {"seconds": 1}, "max_attempts": 3},
        {"job_type": "", "payload": {"seconds": 1}},
        {"job_type": "sleep", "payload": {"seconds": 1}, "max_attempts": 0},
        {"job_type": "sleep", "payload": {"seconds": 1}, "max_attempts": -1},
        {"job_type": "sleep", "payload": {"seconds": 1}, "max_attempts": 101},
        {"job_type": "sleep", "payload": {"seconds": 1}, "priority": -1},
        {"job_type": "sleep", "payload": {"seconds": 1}, "queue_name": ""},
        {"job_type": "sleep", "payload": {"seconds": 1}, "idempotency_key": ""},
        {"job_type": "sleep", "payload": "not-an-object"},
        {"job_type": "sleep", "payload": ["list"]},
    ],
)
def test_create_job_validation_errors(client, invalid_body):
    response = client.post("/api/jobs", json=invalid_body)
    assert response.status_code == 422


@pytest.mark.parametrize("job_type", ["", " ", "   "])
def test_create_job_rejects_empty_or_whitespace_job_type(client, job_type):
    response = client.post(
        "/api/jobs",
        json={"job_type": job_type, "payload": {}, "idempotency_key": "bad-type-key"},
    )
    assert response.status_code == 422


def test_create_job_strips_surrounding_whitespace_from_job_type(client):
    response = client.post(
        "/api/jobs",
        json={"job_type": " sleep ", "payload": {}, "idempotency_key": "strip-type"},
    )
    assert response.status_code == 201
    assert response.json()["job_type"] == "sleep"


def test_create_job_default_queue_name(client):
    response = client.post(
        "/api/jobs",
        json={"job_type": "sleep", "payload": {}, "idempotency_key": "default-queue"},
    )
    assert response.status_code == 201
    assert response.json()["queue_name"] == "default"


def test_create_job_custom_queue_name(client):
    response = client.post(
        "/api/jobs",
        json={
            "job_type": "sleep",
            "payload": {},
            "queue_name": "priority",
            "idempotency_key": "custom-queue",
        },
    )
    assert response.status_code == 201
    assert response.json()["queue_name"] == "priority"


def test_create_job_extra_run_at_field_is_ignored_by_api(client):
    future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    response = client.post(
        "/api/jobs",
        json={
            "job_type": "sleep",
            "payload": {},
            "run_at": future,
            "idempotency_key": "extra-run-at",
        },
    )
    assert response.status_code == 201
    assert "run_at" in response.json()


def test_create_job_priority_zero_and_positive(client):
    for priority in (0, 5, 100):
        response = client.post(
            "/api/jobs",
            json={
                "job_type": "sleep",
                "payload": {},
                "priority": priority,
                "idempotency_key": f"priority-{priority}",
            },
        )
        assert response.status_code == 201
        assert response.json()["priority"] == priority


@pytest.mark.parametrize(
    "path",
    [
        "/api/jobs/not-a-uuid",
        "/api/jobs/not-a-uuid/events",
    ],
)
def test_invalid_job_uuid_returns_422(client, path):
    assert client.get(path).status_code == 422


@pytest.mark.parametrize(
    "path",
    [
        "/api/jobs/not-a-uuid/retry",
        "/api/jobs/not-a-uuid/cancel",
    ],
)
def test_invalid_job_uuid_mutation_returns_422(client, path):
    assert client.post(path).status_code == 422


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
    ],
)
def test_list_jobs_invalid_pagination_returns_422(client, params):
    assert client.get("/api/jobs", params=params).status_code == 422


def test_list_jobs_limit_at_max_accepted(client, job_payload):
    client.post("/api/jobs", json=job_payload)
    response = client.get("/api/jobs", params={"limit": 100})
    assert response.status_code == 200
    assert response.json()["limit"] == 100


def test_list_workers_invalid_status_returns_422(client):
    assert client.get("/api/workers", params={"status": "invalid"}).status_code == 422


def test_list_workers_invalid_pagination_returns_422(client):
    assert client.get("/api/workers", params={"limit": 0}).status_code == 422
