"""Idempotency behavior tests."""

import psycopg
import pytest

from tests.conftest import TEST_DATABASE_SYNC_URL


def test_no_idempotency_key_creates_separate_jobs(client):
    base = {"job_type": "sleep", "payload": {"seconds": 1}}
    first = client.post("/api/jobs", json=base)
    second = client.post("/api/jobs", json=base)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("payload", {"seconds": 99}),
        ("job_type", "fail_once"),
        ("queue_name", "other-queue"),
        ("max_attempts", 5),
        ("priority", 10),
    ],
)
def test_idempotency_conflict_on_field_mismatch(client, job_payload, field, value):
    created = client.post("/api/jobs", json=job_payload)
    assert created.status_code == 201

    conflict = {**job_payload, field: value}
    response = client.post("/api/jobs", json=conflict)

    assert response.status_code == 409
    assert response.json()["detail"]["idempotency_key"] == job_payload["idempotency_key"]


def test_idempotency_same_request_returns_same_id_and_200(client, job_payload):
    first = client.post("/api/jobs", json=job_payload)
    second = client.post("/api/jobs", json=job_payload)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_idempotency_duplicate_does_not_create_second_job_row(client, job_payload):
    client.post("/api/jobs", json=job_payload)
    client.post("/api/jobs", json=job_payload)

    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE idempotency_key = %s",
            (job_payload["idempotency_key"],),
        ).fetchone()[0]

    assert count == 1


def test_idempotency_duplicate_does_not_create_second_job_created_event(client, job_payload):
    first = client.post("/api/jobs", json=job_payload)
    client.post("/api/jobs", json=job_payload)
    job_id = first.json()["id"]

    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM job_events WHERE job_id = %s AND event_type = 'job_created'",
            (job_id,),
        ).fetchone()[0]

    assert count == 1


def test_idempotency_key_unique_at_db_level(client):
    client.post(
        "/api/jobs",
        json={
            "job_type": "sleep",
            "payload": {},
            "idempotency_key": "db-unique-key",
        },
    )

    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(
                """
                INSERT INTO jobs (
                    id, job_type, payload, status, queue_name, priority,
                    max_attempts, attempts, idempotency_key, run_at, created_at, updated_at
                )
                VALUES (
                    gen_random_uuid(), 'sleep', '{}', 'PENDING', 'default', 0,
                    3, 0, 'db-unique-key', NOW(), NOW(), NOW()
                )
                """
            )
            conn.commit()
