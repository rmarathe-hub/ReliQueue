"""Extended metrics API edge and stress tests."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.enums import JobEventType, JobStatus
from app.models.job import Job
from app.models.job_event import JobEvent
from app.models.worker import Worker
from tests.conftest import TEST_DATABASE_SYNC_URL, TEST_DATABASE_URL

METRICS_KEYS = {
    "jobs_by_status",
    "dead_letter_count",
    "queue_depth",
    "jobs_created_last_hour",
    "failures_last_hour",
    "workers_by_status",
    "worker_count",
    "avg_runtime_seconds",
}


def _insert_job_sync(**fields: object) -> None:
    defaults = {
        "job_type": "sleep",
        "payload": "{}",
        "status": "PENDING",
        "queue_name": "default",
        "priority": 0,
        "max_attempts": 3,
        "attempts": 0,
        "run_at": datetime.now(UTC),
        "created_at": datetime.now(UTC),
        "started_at": None,
        "completed_at": None,
    }
    defaults.update(fields)
    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        conn.execute(
            """
            INSERT INTO jobs (
                id, job_type, payload, status, queue_name, priority,
                max_attempts, attempts, run_at, created_at, updated_at,
                started_at, completed_at
            )
            VALUES (
                gen_random_uuid(), %s, %s::jsonb, %s, %s, %s,
                %s, %s, %s, %s, NOW(),
                %s, %s
            )
            """,
            (
                defaults["job_type"],
                defaults["payload"],
                defaults["status"],
                defaults["queue_name"],
                defaults["priority"],
                defaults["max_attempts"],
                defaults["attempts"],
                defaults["run_at"],
                defaults["created_at"],
                defaults["started_at"],
                defaults["completed_at"],
            ),
        )
        conn.commit()


def test_metrics_response_contains_all_expected_keys(client):
    body = client.get("/api/metrics").json()
    assert set(body.keys()) == METRICS_KEYS


def test_metrics_response_is_json_serializable(client):
    body = client.get("/api/metrics").json()
    json.dumps(body)


def test_metrics_endpoint_is_read_only(client, job_payload):
    before = client.get("/api/metrics").json()
    client.post("/api/jobs", json=job_payload)
    after_first = client.get("/api/metrics").json()
    client.get("/api/metrics")
    after_second = client.get("/api/metrics").json()

    assert after_first["jobs_by_status"]["pending"] == before["jobs_by_status"]["pending"] + 1
    assert after_second == after_first


def test_metrics_queue_depth_excludes_future_run_at(client):
    future = datetime.now(UTC) + timedelta(hours=2)
    _insert_job_sync(status="PENDING", queue_name="future-q", run_at=future)
    _insert_job_sync(status="PENDING", queue_name="eligible-q", run_at=datetime.now(UTC))

    depth = client.get("/api/metrics").json()["queue_depth"]
    assert "eligible-q" in depth
    assert depth.get("future-q", 0) == 0


def test_metrics_queue_depth_excludes_non_pending_statuses(client):
    _insert_job_sync(status="RUNNING", queue_name="depth-q")
    _insert_job_sync(status="SUCCEEDED", queue_name="depth-q")
    _insert_job_sync(status="DEAD_LETTERED", queue_name="depth-q")
    _insert_job_sync(status="CANCELLED", queue_name="depth-q")

    depth = client.get("/api/metrics").json()["queue_depth"]
    assert depth.get("depth-q", 0) == 0


def test_metrics_multiple_queue_depths(client):
    _insert_job_sync(status="PENDING", queue_name="alpha", run_at=datetime.now(UTC))
    _insert_job_sync(status="PENDING", queue_name="alpha", run_at=datetime.now(UTC))
    _insert_job_sync(status="PENDING", queue_name="beta", run_at=datetime.now(UTC))

    depth = client.get("/api/metrics").json()["queue_depth"]
    assert depth["alpha"] == 2
    assert depth["beta"] == 1


def test_metrics_jobs_created_last_hour_excludes_old_jobs(client):
    old = datetime.now(UTC) - timedelta(hours=3)
    recent = datetime.now(UTC) - timedelta(minutes=10)
    _insert_job_sync(status="SUCCEEDED", created_at=old)
    _insert_job_sync(status="SUCCEEDED", created_at=recent)

    body = client.get("/api/metrics").json()
    assert body["jobs_created_last_hour"] == 1


def test_metrics_failures_last_hour_counts_failed_events(client):
    recent = datetime.now(UTC) - timedelta(minutes=5)
    old = datetime.now(UTC) - timedelta(hours=2)
    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        job_recent = conn.execute(
            """
            INSERT INTO jobs (
                id, job_type, payload, status, queue_name, priority,
                max_attempts, attempts, run_at, created_at, updated_at
            )
            VALUES (gen_random_uuid(), 'sleep', '{}', 'PENDING', 'default', 0, 3, 1, NOW(), NOW(), NOW())
            RETURNING id
            """
        ).fetchone()[0]
        job_old = conn.execute(
            """
            INSERT INTO jobs (
                id, job_type, payload, status, queue_name, priority,
                max_attempts, attempts, run_at, created_at, updated_at
            )
            VALUES (gen_random_uuid(), 'sleep', '{}', 'PENDING', 'default', 0, 3, 1, NOW(), NOW(), NOW())
            RETURNING id
            """
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO job_events (id, job_id, event_type, payload, created_at)
            VALUES (gen_random_uuid(), %s, 'job_failed', '{"error":"x"}', %s)
            """,
            (job_recent, recent),
        )
        conn.execute(
            """
            INSERT INTO job_events (id, job_id, event_type, payload, created_at)
            VALUES (gen_random_uuid(), %s, 'job_failed', '{"error":"x"}', %s)
            """,
            (job_old, old),
        )
        conn.commit()

    assert client.get("/api/metrics").json()["failures_last_hour"] == 1


def test_metrics_avg_runtime_single_job(client):
    now = datetime.now(UTC)
    _insert_job_sync(
        status="SUCCEEDED",
        started_at=now - timedelta(seconds=10),
        completed_at=now,
    )

    avg = client.get("/api/metrics").json()["avg_runtime_seconds"]
    assert avg == pytest.approx(10.0, rel=0.01)


def test_metrics_avg_runtime_multiple_jobs(client):
    now = datetime.now(UTC)
    _insert_job_sync(
        status="SUCCEEDED",
        started_at=now - timedelta(seconds=4),
        completed_at=now,
    )
    _insert_job_sync(
        status="SUCCEEDED",
        started_at=now - timedelta(seconds=6),
        completed_at=now,
    )

    avg = client.get("/api/metrics").json()["avg_runtime_seconds"]
    assert avg == pytest.approx(5.0, rel=0.01)


def test_metrics_avg_runtime_ignores_non_succeeded_jobs(client):
    now = datetime.now(UTC)
    _insert_job_sync(status="RUNNING", started_at=now - timedelta(seconds=100))
    _insert_job_sync(
        status="SUCCEEDED",
        started_at=now - timedelta(seconds=2),
        completed_at=now,
    )

    avg = client.get("/api/metrics").json()["avg_runtime_seconds"]
    assert avg == pytest.approx(2.0, rel=0.01)


def test_metrics_avg_runtime_null_when_succeeded_missing_timestamps(client):
    _insert_job_sync(status="SUCCEEDED", started_at=None, completed_at=None)
    assert client.get("/api/metrics").json()["avg_runtime_seconds"] is None


@pytest.mark.parametrize("count", [10, 50])
def test_metrics_handles_many_pending_jobs(client, count):
    for index in range(count):
        _insert_job_sync(
            status="PENDING",
            queue_name="bulk",
            run_at=datetime.now(UTC),
        )

    body = client.get("/api/metrics").json()
    assert body["jobs_by_status"]["pending"] == count
    assert body["queue_depth"]["bulk"] == count


def test_metrics_after_cancellation_reflects_status(client, job_payload):
    created = client.post("/api/jobs", json=job_payload)
    job_id = created.json()["id"]
    client.post(f"/api/jobs/{job_id}/cancel")

    body = client.get("/api/metrics").json()
    assert body["jobs_by_status"]["cancelled"] == 1
    assert body["jobs_by_status"]["pending"] == 0


def test_metrics_after_manual_retry_reflects_pending(client):
    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        job_id = conn.execute(
            """
            INSERT INTO jobs (
                id, job_type, payload, status, queue_name, priority,
                max_attempts, attempts, run_at, created_at, updated_at
            )
            VALUES (gen_random_uuid(), 'sleep', '{}', 'DEAD_LETTERED', 'default', 0, 3, 3, NOW(), NOW(), NOW())
            RETURNING id
            """
        ).fetchone()[0]
        conn.commit()

    client.post(f"/api/jobs/{job_id}/retry")
    body = client.get("/api/metrics").json()
    assert body["jobs_by_status"]["pending"] == 1
    assert body["jobs_by_status"]["dead_lettered"] == 0


def test_metrics_workers_online_offline_counts(client):
    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        conn.execute(
            """
            INSERT INTO workers (id, status, queue_name, last_heartbeat_at, created_at, updated_at)
            VALUES
              ('online-1', 'ONLINE', 'default', NOW(), NOW(), NOW()),
              ('online-2', 'ONLINE', 'default', NOW(), NOW(), NOW()),
              ('offline-1', 'OFFLINE', 'default', NOW(), NOW(), NOW())
            """
        )
        conn.commit()

    body = client.get("/api/metrics").json()
    assert body["workers_by_status"]["online"] == 2
    assert body["workers_by_status"]["offline"] == 1
    assert body["worker_count"] == 3


async def _seed_bulk_succeeded(count: int) -> None:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    now = datetime.now(UTC)
    try:
        async with factory() as db:
            for _ in range(count):
                job = Job(
                    job_type="sleep",
                    payload={},
                    status=JobStatus.SUCCEEDED,
                    queue_name="bulk-succeeded",
                    started_at=now - timedelta(seconds=3),
                    completed_at=now,
                    run_at=now,
                )
                db.add(job)
            await db.commit()
    finally:
        await engine.dispose()


@pytest.mark.parametrize("count", [5, 20])
def test_metrics_avg_runtime_stable_with_many_succeeded_jobs(client, count):
    asyncio.run(_seed_bulk_succeeded(count))
    avg = client.get("/api/metrics").json()["avg_runtime_seconds"]
    assert avg == pytest.approx(3.0, rel=0.05)


def test_metrics_counts_multiple_failure_events_for_same_job(client):
    recent = datetime.now(UTC) - timedelta(minutes=10)
    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        job_id = conn.execute(
            """
            INSERT INTO jobs (
                id, job_type, payload, status, queue_name, priority,
                max_attempts, attempts, run_at, created_at, updated_at
            )
            VALUES (gen_random_uuid(), 'sleep', '{}', 'PENDING', 'default', 0, 3, 2, NOW(), NOW(), NOW())
            RETURNING id
            """
        ).fetchone()[0]
        for _ in range(2):
            conn.execute(
                """
                INSERT INTO job_events (id, job_id, event_type, payload, created_at)
                VALUES (gen_random_uuid(), %s, 'job_failed', '{"error":"x"}', %s)
                """,
                (job_id, recent),
            )
        conn.commit()

    assert client.get("/api/metrics").json()["failures_last_hour"] == 2
