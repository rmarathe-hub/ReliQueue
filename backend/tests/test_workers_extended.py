"""Extended worker service and API tests."""

from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from app.models.enums import WorkerStatus
from app.models.worker import Worker
from app.services.job_claiming import claim_next_job
from app.services.workers import get_worker_by_id, list_workers, register_worker, touch_worker_heartbeat
from tests.conftest import TEST_DATABASE_SYNC_URL
from tests.helpers import create_pending_job, insert_worker_sync


@pytest.mark.asyncio
async def test_register_same_worker_twice_is_safe(db_session_factory):
    async with db_session_factory() as db:
        first = await register_worker(db, "worker-dup", "default")
        second = await register_worker(db, "worker-dup", "priority")

    assert first.id == second.id
    assert second.queue_name == "priority"
    assert second.status == WorkerStatus.ONLINE


@pytest.mark.asyncio
async def test_claim_sets_current_job_id_visible_on_worker_detail(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db)
        await claim_next_job(db, worker_id="worker-1", queue_name="default")
        worker = await db.get(Worker, "worker-1")

    assert worker.current_job_id == job.id


def test_worker_list_pagination_via_api(client):
    for index in range(3):
        insert_worker_sync(f"page-worker-{index}", queue_name="default")

    page = client.get("/api/workers", params={"limit": 2, "offset": 1})

    assert page.status_code == 200
    body = page.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2


def test_worker_list_filter_by_status_via_api(client):
    insert_worker_sync("online-worker", status=WorkerStatus.ONLINE)
    insert_worker_sync("offline-worker", status=WorkerStatus.OFFLINE)

    response = client.get("/api/workers", params={"status": "offline"})

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == "offline-worker"


def test_worker_list_filter_by_queue_via_api(client):
    insert_worker_sync("default-worker", queue_name="default")
    insert_worker_sync("priority-worker", queue_name="priority")

    response = client.get("/api/workers", params={"queue_name": "priority"})

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["queue_name"] == "priority"


def test_worker_detail_shows_current_job_id(client):
    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        job_id = conn.execute(
            """
            INSERT INTO jobs (
                id, job_type, payload, status, queue_name, priority,
                max_attempts, attempts, run_at, created_at, updated_at
            )
            VALUES (
                gen_random_uuid(), 'sleep', '{}', 'RUNNING', 'default', 0,
                3, 1, NOW(), NOW(), NOW()
            )
            RETURNING id
            """
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO workers (id, status, queue_name, current_job_id, last_heartbeat_at, created_at, updated_at)
            VALUES ('busy-worker', 'ONLINE', 'default', %s, NOW(), NOW(), NOW())
            """,
            (job_id,),
        )
        conn.commit()

    response = client.get("/api/workers/busy-worker")

    assert response.status_code == 200
    assert response.json()["current_job_id"] == str(job_id)


@pytest.mark.asyncio
async def test_touch_worker_heartbeat_on_missing_worker_is_noop(db_session_factory):
    async with db_session_factory() as db:
        await touch_worker_heartbeat(db, "missing-worker")

    async with db_session_factory() as db:
        worker = await get_worker_by_id(db, "missing-worker")

    assert worker is None


@pytest.mark.asyncio
async def test_list_workers_empty_offset_beyond_total(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        workers, total = await list_workers(db, offset=10)

    assert total == 1
    assert workers == []
