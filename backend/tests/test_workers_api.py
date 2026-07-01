from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from app.models.enums import WorkerStatus
from app.services.workers import get_worker_by_id, list_workers, register_worker, touch_worker_heartbeat
from tests.conftest import TEST_DATABASE_SYNC_URL


@pytest.mark.asyncio
async def test_register_worker_sets_online_and_heartbeat(db_session_factory):
    async with db_session_factory() as db:
        worker = await register_worker(db, "worker-1", "default")

    assert worker.status == WorkerStatus.ONLINE
    assert worker.queue_name == "default"
    assert worker.last_heartbeat_at is not None


@pytest.mark.asyncio
async def test_touch_worker_heartbeat_updates_timestamp(db_session_factory):
    past = datetime.now(UTC) - timedelta(minutes=5)

    async with db_session_factory() as db:
        worker = await register_worker(db, "worker-1", "default")
        worker.last_heartbeat_at = past
        await db.commit()

    async with db_session_factory() as db:
        await touch_worker_heartbeat(db, "worker-1")

    async with db_session_factory() as db:
        worker = await get_worker_by_id(db, "worker-1")

    assert worker is not None
    assert worker.status == WorkerStatus.ONLINE
    assert worker.last_heartbeat_at is not None
    assert worker.last_heartbeat_at > past


@pytest.mark.asyncio
async def test_list_workers_returns_registered_workers(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        await register_worker(db, "worker-2", "priority")

    async with db_session_factory() as db:
        workers, total = await list_workers(db)

    assert total == 2
    assert {worker.id for worker in workers} == {"worker-1", "worker-2"}


@pytest.mark.asyncio
async def test_list_workers_filters_by_status_and_queue(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        worker = await register_worker(db, "worker-2", "priority")
        worker.status = WorkerStatus.OFFLINE
        await db.commit()

    async with db_session_factory() as db:
        online_default, total = await list_workers(
            db,
            status=WorkerStatus.ONLINE,
            queue_name="default",
        )

    assert total == 1
    assert online_default[0].id == "worker-1"


def test_list_workers_via_api(client):
    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        conn.execute(
            """
            INSERT INTO workers (id, status, queue_name, last_heartbeat_at, created_at, updated_at)
            VALUES ('worker-1', 'ONLINE', 'default', NOW(), NOW(), NOW())
            """
        )
        conn.commit()

    response = client.get("/api/workers")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == "worker-1"
    assert body["items"][0]["status"] == "online"
    assert body["items"][0]["queue_name"] == "default"
    assert body["items"][0]["last_heartbeat_at"] is not None


def test_get_worker_detail_via_api(client):
    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        conn.execute(
            """
            INSERT INTO workers (id, status, queue_name, last_heartbeat_at, created_at, updated_at)
            VALUES ('worker-1', 'ONLINE', 'default', NOW(), NOW(), NOW())
            """
        )
        conn.commit()

    response = client.get("/api/workers/worker-1")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "worker-1"
    assert body["status"] == "online"
    assert body["last_heartbeat_at"] is not None


def test_get_worker_not_found_returns_404(client):
    response = client.get("/api/workers/missing-worker")

    assert response.status_code == 404
    assert response.json()["detail"] == "Worker not found"
