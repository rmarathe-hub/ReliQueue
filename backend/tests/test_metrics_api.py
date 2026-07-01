"""Tests for GET /api/metrics."""

import asyncio

import pytest

from app.models.enums import WorkerStatus
from tests.helpers import seed_metrics_dataset


def _seed_metrics() -> None:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from tests.conftest import TEST_DATABASE_URL

    async def run():
        engine = create_async_engine(TEST_DATABASE_URL, echo=False)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with factory() as db:
                await seed_metrics_dataset(db)
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_metrics_empty_database(client):
    response = client.get("/api/metrics")

    assert response.status_code == 200
    body = response.json()

    assert body["jobs_by_status"] == {
        "pending": 0,
        "running": 0,
        "succeeded": 0,
        "dead_lettered": 0,
        "cancelled": 0,
    }
    assert body["dead_letter_count"] == 0
    assert body["queue_depth"] == {}
    assert body["jobs_created_last_hour"] == 0
    assert body["failures_last_hour"] == 0
    assert body["workers_by_status"] == {"online": 0, "offline": 0}
    assert body["worker_count"] == 0
    assert body["avg_runtime_seconds"] is None


def test_metrics_with_seeded_dataset(client):
    _seed_metrics()

    response = client.get("/api/metrics")

    assert response.status_code == 200
    body = response.json()

    assert body["jobs_by_status"]["pending"] == 2
    assert body["jobs_by_status"]["running"] == 1
    assert body["jobs_by_status"]["succeeded"] == 1
    assert body["jobs_by_status"]["dead_lettered"] == 1
    assert body["jobs_by_status"]["cancelled"] == 1
    assert sum(body["jobs_by_status"].values()) == 6


def test_metrics_dead_letter_count(client):
    _seed_metrics()

    body = client.get("/api/metrics").json()

    assert body["dead_letter_count"] == 1
    assert body["dead_letter_count"] == body["jobs_by_status"]["dead_lettered"]


def test_metrics_queue_depth(client):
    _seed_metrics()

    body = client.get("/api/metrics").json()

    assert body["queue_depth"]["metrics-q"] == 1
    assert body["queue_depth"]["default"] == 1


def test_metrics_workers_and_recent_activity(client):
    _seed_metrics()

    body = client.get("/api/metrics").json()

    assert body["workers_by_status"][WorkerStatus.ONLINE.value] == 2
    assert body["workers_by_status"][WorkerStatus.OFFLINE.value] == 1
    assert body["worker_count"] == 3
    assert body["jobs_created_last_hour"] == 5
    assert body["failures_last_hour"] == 1


def test_metrics_avg_runtime_seconds(client):
    _seed_metrics()

    body = client.get("/api/metrics").json()

    assert body["avg_runtime_seconds"] == pytest.approx(5.0, rel=0.01)
