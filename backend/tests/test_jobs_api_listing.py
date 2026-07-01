"""Job listing, filtering, and pagination tests."""

import psycopg
import pytest

from tests.conftest import TEST_DATABASE_SYNC_URL


def _insert_job(
    *,
    job_type: str = "sleep",
    status: str = "PENDING",
    queue_name: str = "default",
    idempotency_key: str,
) -> str:
    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        row = conn.execute(
            """
            INSERT INTO jobs (
                id, job_type, payload, status, queue_name, priority,
                max_attempts, attempts, idempotency_key, run_at, created_at, updated_at
            )
            VALUES (
                gen_random_uuid(), %s, '{"seconds": 1}', %s, %s, 0,
                3, 0, %s, NOW(), NOW(), NOW()
            )
            RETURNING id
            """,
            (job_type, status, queue_name, idempotency_key),
        ).fetchone()
        conn.commit()
    return str(row[0])


@pytest.mark.parametrize(
    "db_status,api_status",
    [
        ("PENDING", "pending"),
        ("RUNNING", "running"),
        ("SUCCEEDED", "succeeded"),
        ("DEAD_LETTERED", "dead_lettered"),
        ("CANCELLED", "cancelled"),
    ],
)
def test_list_jobs_filters_by_status(client, db_status, api_status):
    job_id = _insert_job(status=db_status, idempotency_key=f"status-{api_status}")
    other_id = _insert_job(status="PENDING", idempotency_key=f"other-{api_status}")

    response = client.get("/api/jobs", params={"status": api_status})

    assert response.status_code == 200
    body = response.json()
    ids = {item["id"] for item in body["items"]}
    assert job_id in ids
    if db_status != "PENDING":
        assert other_id not in ids


def test_list_jobs_filters_by_queue_name(client):
    default_id = _insert_job(queue_name="default", idempotency_key="list-q-default")
    priority_id = _insert_job(queue_name="priority", idempotency_key="list-q-priority")

    response = client.get("/api/jobs", params={"queue_name": "priority"})

    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert priority_id in ids
    assert default_id not in ids


def test_list_jobs_filters_by_job_type(client):
    sleep_id = _insert_job(job_type="sleep", idempotency_key="list-type-sleep")
    fail_id = _insert_job(job_type="fail_once", idempotency_key="list-type-fail")

    response = client.get("/api/jobs", params={"job_type": "fail_once"})

    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert fail_id in ids
    assert sleep_id not in ids


def test_list_jobs_combined_filters(client):
    match_id = _insert_job(
        job_type="sleep",
        status="PENDING",
        queue_name="priority",
        idempotency_key="combined-match",
    )
    _insert_job(job_type="sleep", status="RUNNING", queue_name="priority", idempotency_key="combined-running")
    _insert_job(job_type="fail_once", status="PENDING", queue_name="priority", idempotency_key="combined-type")

    response = client.get(
        "/api/jobs",
        params={"status": "pending", "queue_name": "priority", "job_type": "sleep"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == match_id


def test_list_jobs_limit_and_offset(client):
    ids = [_insert_job(idempotency_key=f"page-{index}") for index in range(5)]

    page1 = client.get("/api/jobs", params={"limit": 2, "offset": 0})
    page2 = client.get("/api/jobs", params={"limit": 2, "offset": 2})

    assert page1.status_code == 200
    assert page2.status_code == 200
    assert page1.json()["total"] == 5
    assert len(page1.json()["items"]) == 2
    assert len(page2.json()["items"]) == 2

    page1_ids = {item["id"] for item in page1.json()["items"]}
    page2_ids = {item["id"] for item in page2.json()["items"]}
    assert page1_ids.isdisjoint(page2_ids)
    assert page1_ids.union(page2_ids).issubset(set(ids))


def test_list_jobs_empty_result(client):
    response = client.get("/api/jobs", params={"status": "succeeded"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_list_jobs_default_order_newest_first(client):
    first_id = _insert_job(idempotency_key="order-first")
    second_id = _insert_job(idempotency_key="order-second")

    response = client.get("/api/jobs", params={"limit": 10})

    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    assert ids.index(second_id) < ids.index(first_id)
