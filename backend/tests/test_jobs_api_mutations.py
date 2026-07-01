"""Retry and cancel API regression tests."""

import psycopg
import pytest

from tests.conftest import TEST_DATABASE_SYNC_URL


def _set_job_status(job_id: str, status: str, **extra: object) -> None:
    assignments = ["status = %s"]
    values: list[object] = [status]
    for key, value in extra.items():
        assignments.append(f"{key} = %s")
        values.append(value)
    values.append(job_id)
    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(assignments)} WHERE id = %s", values)
        conn.commit()


def _create_job(idempotency_key: str) -> str:
    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        row = conn.execute(
            """
            INSERT INTO jobs (
                id, job_type, payload, status, queue_name, priority,
                max_attempts, attempts, idempotency_key, run_at, created_at, updated_at
            )
            VALUES (
                gen_random_uuid(), 'sleep', '{}', 'PENDING', 'default', 0,
                3, 0, %s, NOW(), NOW(), NOW()
            )
            RETURNING id
            """,
            (idempotency_key,),
        ).fetchone()
        conn.commit()
    return str(row[0])


@pytest.mark.parametrize(
    "status",
    ["pending", "running", "succeeded"],
)
def test_retry_rejects_non_retryable_statuses(client, status):
    job_id = _create_job(f"retry-reject-{status}")
    if status != "pending":
        _set_job_status(job_id, status.upper())

    response = client.post(f"/api/jobs/{job_id}/retry")
    assert response.status_code == 409


def test_retry_dead_lettered_via_api(client):
    job_id = _create_job("retry-dl")
    _set_job_status(job_id, "DEAD_LETTERED", attempts=3, last_error="boom")

    response = client.post(f"/api/jobs/{job_id}/retry")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["attempts"] == 0
    assert body["last_error"] is None
    assert body["locked_by"] is None


def test_retry_cancelled_via_api(client):
    job_id = _create_job("retry-cancelled")
    _set_job_status(job_id, "CANCELLED")

    response = client.post(f"/api/jobs/{job_id}/retry")
    assert response.status_code == 200
    assert response.json()["status"] == "pending"


def test_retry_writes_manually_retried_event(client):
    job_id = _create_job("retry-event")
    _set_job_status(job_id, "DEAD_LETTERED", attempts=2, last_error="x")

    client.post(f"/api/jobs/{job_id}/retry")
    events = client.get(f"/api/jobs/{job_id}/events").json()
    assert any(event["event_type"] == "job_manually_retried" for event in events)


def test_retry_nonexistent_job_returns_404(client):
    response = client.post("/api/jobs/00000000-0000-0000-0000-000000000000/retry")
    assert response.status_code == 404


@pytest.mark.parametrize(
    "status",
    ["running", "succeeded", "dead_lettered"],
)
def test_cancel_rejects_non_pending_statuses(client, status):
    job_id = _create_job(f"cancel-reject-{status}")
    _set_job_status(job_id, status.upper())

    response = client.post(f"/api/jobs/{job_id}/cancel")
    assert response.status_code == 409


def test_cancel_pending_via_api(client):
    job_id = _create_job("cancel-pending")

    response = client.post(f"/api/jobs/{job_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_cancel_already_cancelled_returns_409(client):
    job_id = _create_job("cancel-twice")
    _set_job_status(job_id, "CANCELLED")

    response = client.post(f"/api/jobs/{job_id}/cancel")
    assert response.status_code == 409


def test_cancel_writes_cancelled_event(client):
    job_id = _create_job("cancel-event")

    client.post(f"/api/jobs/{job_id}/cancel")
    events = client.get(f"/api/jobs/{job_id}/events").json()
    assert any(event["event_type"] == "job_cancelled" for event in events)


def test_cancel_nonexistent_job_returns_404(client):
    response = client.post("/api/jobs/00000000-0000-0000-0000-000000000000/cancel")
    assert response.status_code == 404


def test_cancelled_job_can_be_manually_retried(client):
    job_id = _create_job("cancel-then-retry")
    client.post(f"/api/jobs/{job_id}/cancel")
    response = client.post(f"/api/jobs/{job_id}/retry")

    assert response.status_code == 200
    assert response.json()["status"] == "pending"
