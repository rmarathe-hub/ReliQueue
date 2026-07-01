"""Metrics API tests tied to job lifecycle transitions."""

import psycopg
import pytest

from app.services.job_claiming import claim_next_job
from app.services.job_completion import complete_job_success
from app.services.job_failure import complete_job_failure
from app.services.workers import register_worker
from tests.conftest import TEST_DATABASE_SYNC_URL
from tests.helpers import create_pending_job, run_with_fresh_engine


def _metrics(client) -> dict:
    return client.get("/api/metrics").json()


def test_metrics_all_job_statuses_present_when_zero(client):
    body = _metrics(client)
    assert set(body["jobs_by_status"].keys()) == {
        "pending",
        "running",
        "succeeded",
        "dead_lettered",
        "cancelled",
    }


def test_metrics_all_worker_statuses_present_when_zero(client):
    body = _metrics(client)
    assert set(body["workers_by_status"].keys()) == {"online", "offline"}


def test_metrics_after_success_lifecycle(client, job_payload):
    created = client.post("/api/jobs", json=job_payload)
    job_id = created.json()["id"]

    def run():
        async def process(session_factory):
            async with session_factory() as db:
                await register_worker(db, "m-worker", "default")
                claimed = await claim_next_job(db, worker_id="m-worker", queue_name="default")
                if str(claimed.id) == job_id:
                    await complete_job_success(db, claimed.id, "m-worker")

        run_with_fresh_engine(process)

    run()
    body = _metrics(client)
    assert body["jobs_by_status"]["succeeded"] >= 1


def test_metrics_after_dead_letter_lifecycle(client):
    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        job_id = conn.execute(
            """
            INSERT INTO jobs (
                id, job_type, payload, status, queue_name, priority,
                max_attempts, attempts, run_at, created_at, updated_at, last_error
            )
            VALUES (gen_random_uuid(), 'sleep', '{}', 'DEAD_LETTERED', 'default', 0, 2, 2, NOW(), NOW(), NOW(), 'fail')
            RETURNING id
            """
        ).fetchone()[0]
        conn.commit()

    body = _metrics(client)
    assert body["jobs_by_status"]["dead_lettered"] == 1
    assert body["dead_letter_count"] == 1


def test_metrics_after_manual_retry_shows_pending(client):
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
    body = _metrics(client)
    assert body["jobs_by_status"]["pending"] == 1
    assert body["jobs_by_status"]["dead_lettered"] == 0


def test_metrics_queue_depth_excludes_future_retry_jobs(client, monkeypatch):
    from datetime import UTC, datetime, timedelta

    future = datetime.now(UTC) + timedelta(minutes=10)

    def future_retry(now, attempts, **kwargs):
        return future

    monkeypatch.setattr("app.services.job_failure.calculate_retry_run_at", future_retry)

    def seed():
        async def work(session_factory):
            async with session_factory() as db:
                await register_worker(db, "m-worker", "default")
                await create_pending_job(db, max_attempts=3)
                claimed = await claim_next_job(db, worker_id="m-worker", queue_name="default")
                await complete_job_failure(db, claimed.id, "m-worker", "retry")

        run_with_fresh_engine(work)

    seed()
    body = _metrics(client)
    assert body["queue_depth"].get("default", 0) == 0


def test_metrics_queue_depth_includes_manual_retried_pending(client):
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
    depth = _metrics(client)["queue_depth"]
    assert depth.get("default", 0) == 1


def test_metrics_read_only_snapshot_unchanged_by_second_get(client, job_payload):
    client.post("/api/jobs", json=job_payload)
    first = _metrics(client)
    second = _metrics(client)
    assert first == second
