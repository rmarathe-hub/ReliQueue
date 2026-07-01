"""Extended worker API and service tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from app.models.enums import WorkerStatus
from app.services.workers import get_worker_by_id, register_worker, touch_worker_heartbeat
from tests.helpers import create_pending_job
from tests.conftest import TEST_DATABASE_SYNC_URL


def test_list_workers_empty_database(client):
    response = client.get("/api/workers")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []
    assert body["limit"] == 50
    assert body["offset"] == 0


def test_list_workers_response_shape(client):
    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        conn.execute(
            """
            INSERT INTO workers (id, status, queue_name, last_heartbeat_at, created_at, updated_at)
            VALUES ('shape-worker', 'ONLINE', 'default', NOW(), NOW(), NOW())
            """
        )
        conn.commit()

    body = client.get("/api/workers").json()
    item = body["items"][0]
    assert set(item.keys()) == {
        "id",
        "status",
        "queue_name",
        "current_job_id",
        "last_heartbeat_at",
        "created_at",
        "updated_at",
    }


def test_list_workers_pagination(client):
    for index in range(3):
        with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
            conn.execute(
                """
                INSERT INTO workers (id, status, queue_name, last_heartbeat_at, created_at, updated_at)
                VALUES (%s, 'ONLINE', 'default', NOW(), NOW(), NOW())
                """,
                (f"page-worker-{index}",),
            )
            conn.commit()

    page1 = client.get("/api/workers", params={"limit": 2, "offset": 0}).json()
    page2 = client.get("/api/workers", params={"limit": 2, "offset": 2}).json()

    assert page1["total"] == 3
    assert len(page1["items"]) == 2
    assert len(page2["items"]) == 1


def test_list_workers_filters_by_queue_name(client):
    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        conn.execute(
            """
            INSERT INTO workers (id, status, queue_name, last_heartbeat_at, created_at, updated_at)
            VALUES
              ('worker-default', 'ONLINE', 'default', NOW(), NOW(), NOW()),
              ('worker-reports', 'ONLINE', 'reports', NOW(), NOW(), NOW())
            """
        )
        conn.commit()

    body = client.get("/api/workers", params={"queue_name": "reports"}).json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == "worker-reports"


def test_get_worker_with_current_job_id(client):
    job_id = uuid4()
    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        conn.execute(
            """
            INSERT INTO jobs (
                id, job_type, payload, status, queue_name, priority,
                max_attempts, attempts, run_at, created_at, updated_at
            )
            VALUES (%s, 'sleep', '{}', 'RUNNING', 'default', 0, 3, 1, NOW(), NOW(), NOW())
            """,
            (str(job_id),),
        )
        conn.execute(
            """
            INSERT INTO workers (id, status, queue_name, current_job_id, last_heartbeat_at, created_at, updated_at)
            VALUES ('busy-worker', 'ONLINE', 'default', %s, NOW(), NOW(), NOW())
            """,
            (str(job_id),),
        )
        conn.commit()

    body = client.get("/api/workers/busy-worker").json()
    assert body["current_job_id"] == str(job_id)


@pytest.mark.asyncio
async def test_register_worker_is_idempotent(db_session_factory):
    async with db_session_factory() as db:
        first = await register_worker(db, "dup-worker", "default")
        second = await register_worker(db, "dup-worker", "default")

    assert first.id == second.id
    assert second.status == WorkerStatus.ONLINE


@pytest.mark.asyncio
async def test_get_worker_by_id_missing_returns_none(db_session_factory):
    async with db_session_factory() as db:
        worker = await get_worker_by_id(db, "missing-worker")

    assert worker is None


@pytest.mark.asyncio
async def test_touch_worker_heartbeat_preserves_current_job_id(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-hb", "default")
        job = await create_pending_job(db)
        worker = await get_worker_by_id(db, "worker-hb")
        worker.current_job_id = job.id
        await db.commit()

    async with db_session_factory() as db:
        await touch_worker_heartbeat(db, "worker-hb")

    async with db_session_factory() as db:
        worker = await get_worker_by_id(db, "worker-hb")

    assert worker.current_job_id == job.id
    assert worker.last_heartbeat_at > datetime.now(UTC) - timedelta(minutes=1)
