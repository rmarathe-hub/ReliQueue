"""Job detail API tests across statuses and field coverage."""

from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from tests.conftest import TEST_DATABASE_SYNC_URL

DETAIL_FIELDS = {
    "id",
    "job_type",
    "payload",
    "status",
    "queue_name",
    "priority",
    "max_attempts",
    "attempts",
    "idempotency_key",
    "run_at",
    "created_at",
    "locked_by",
    "locked_at",
    "lease_expires_at",
    "last_error",
    "started_at",
    "completed_at",
    "updated_at",
}


def _insert_job(**fields: object) -> str:
    defaults = {
        "job_type": "sleep",
        "payload": '{"seconds": 1}',
        "status": "PENDING",
        "queue_name": "default",
        "priority": 0,
        "max_attempts": 3,
        "attempts": 0,
        "idempotency_key": "detail-key",
        "run_at": datetime.now(UTC),
        "locked_by": None,
        "locked_at": None,
        "lease_expires_at": None,
        "last_error": None,
        "started_at": None,
        "completed_at": None,
    }
    defaults.update(fields)
    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        row = conn.execute(
            """
            INSERT INTO jobs (
                id, job_type, payload, status, queue_name, priority,
                max_attempts, attempts, idempotency_key, run_at,
                locked_by, locked_at, lease_expires_at, last_error,
                started_at, completed_at, created_at, updated_at
            )
            VALUES (
                gen_random_uuid(), %s, %s::jsonb, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, NOW(), NOW()
            )
            RETURNING id
            """,
            (
                defaults["job_type"],
                defaults["payload"],
                defaults["status"],
                defaults["queue_name"],
                defaults["priority"],
                defaults["max_attempts"],
                defaults["attempts"],
                defaults["idempotency_key"],
                defaults["run_at"],
                defaults["locked_by"],
                defaults["locked_at"],
                defaults["lease_expires_at"],
                defaults["last_error"],
                defaults["started_at"],
                defaults["completed_at"],
            ),
        ).fetchone()
        conn.commit()
    return str(row[0])


@pytest.mark.parametrize(
    "status",
    ["PENDING", "RUNNING", "SUCCEEDED", "DEAD_LETTERED", "CANCELLED"],
)
def test_get_job_detail_for_each_status(client, status):
    job_id = _insert_job(status=status, idempotency_key=f"detail-{status.lower()}")
    response = client.get(f"/api/jobs/{job_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == status.lower()
    assert set(body.keys()) == DETAIL_FIELDS


def test_get_job_detail_running_includes_lock_fields(client):
    now = datetime.now(UTC)
    job_id = _insert_job(
        status="RUNNING",
        attempts=1,
        locked_by="worker-1",
        locked_at=now,
        lease_expires_at=now + timedelta(seconds=60),
        started_at=now,
        idempotency_key="detail-running",
    )
    body = client.get(f"/api/jobs/{job_id}").json()

    assert body["locked_by"] == "worker-1"
    assert body["locked_at"] is not None
    assert body["lease_expires_at"] is not None
    assert body["started_at"] is not None


def test_get_job_detail_dead_lettered_includes_last_error(client):
    job_id = _insert_job(
        status="DEAD_LETTERED",
        attempts=3,
        last_error="permanent failure",
        idempotency_key="detail-dl",
    )
    body = client.get(f"/api/jobs/{job_id}").json()

    assert body["last_error"] == "permanent failure"


def test_get_job_detail_succeeded_includes_completed_at(client):
    now = datetime.now(UTC)
    job_id = _insert_job(
        status="SUCCEEDED",
        attempts=1,
        started_at=now - timedelta(seconds=5),
        completed_at=now,
        idempotency_key="detail-succeeded",
    )
    body = client.get(f"/api/jobs/{job_id}").json()

    assert body["completed_at"] is not None
    assert body["last_error"] is None


def test_created_job_appears_in_list_immediately(client, job_payload):
    created = client.post("/api/jobs", json=job_payload)
    job_id = created.json()["id"]

    listed = client.get("/api/jobs", params={"status": "pending"}).json()
    assert any(item["id"] == job_id for item in listed["items"])


def test_create_job_response_includes_expected_fields(client, job_payload):
    body = client.post("/api/jobs", json=job_payload).json()

    assert set(body.keys()) >= {
        "id",
        "job_type",
        "payload",
        "status",
        "queue_name",
        "priority",
        "max_attempts",
        "attempts",
        "idempotency_key",
        "run_at",
        "created_at",
    }


def test_create_job_max_attempts_one_allowed(client):
    response = client.post(
        "/api/jobs",
        json={
            "job_type": "sleep",
            "payload": {},
            "max_attempts": 1,
            "idempotency_key": "max-attempts-one",
        },
    )
    assert response.status_code == 201
    assert response.json()["max_attempts"] == 1
