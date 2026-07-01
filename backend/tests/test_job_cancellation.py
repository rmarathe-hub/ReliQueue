import psycopg
import pytest
from sqlalchemy import select

from app.models.enums import JobEventType, JobStatus
from app.models.job_event import JobEvent
from app.services.job_cancellation import cancel_job
from app.services.job_claiming import claim_next_job
from app.services.job_errors import JobCancellationNotAllowedError
from app.services.workers import register_worker
from tests.conftest import TEST_DATABASE_SYNC_URL
from tests.test_worker_claiming import create_pending_job


@pytest.mark.asyncio
async def test_cancel_pending_job(db_session_factory):
    async with db_session_factory() as db:
        job = await create_pending_job(db, idempotency_key="cancel-pending-1")
        cancelled = await cancel_job(db, job.id)

    assert cancelled.status == JobStatus.CANCELLED


@pytest.mark.asyncio
async def test_cancel_job_creates_job_cancelled_event(db_session_factory):
    async with db_session_factory() as db:
        job = await create_pending_job(db, idempotency_key="cancel-event-1")
        await cancel_job(db, job.id)

    async with db_session_factory() as db:
        result = await db.execute(
            select(JobEvent).where(
                JobEvent.job_id == job.id,
                JobEvent.event_type == JobEventType.JOB_CANCELLED,
            )
        )
        events = list(result.scalars().all())

    assert len(events) == 1
    assert events[0].payload["previous_status"] == JobStatus.PENDING.value


@pytest.mark.asyncio
async def test_cancel_job_rejects_running_job(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db, idempotency_key="cancel-running-1")

    async with db_session_factory() as db:
        await claim_next_job(db, worker_id="worker-1", queue_name="default")

    async with db_session_factory() as db:
        with pytest.raises(JobCancellationNotAllowedError):
            await cancel_job(db, job.id)


@pytest.mark.asyncio
async def test_cancelled_job_is_not_claimed(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db, idempotency_key="cancel-claim-1")
        await cancel_job(db, job.id)

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    assert claimed is None


def test_cancel_pending_job_via_api(client, job_payload):
    created = client.post("/api/jobs", json=job_payload)
    job_id = created.json()["id"]

    response = client.post(f"/api/jobs/{job_id}/cancel")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == job_id
    assert body["status"] == "cancelled"

    events = client.get(f"/api/jobs/{job_id}/events")
    event_types = [event["event_type"] for event in events.json()]
    assert "job_cancelled" in event_types


def test_cancel_running_job_returns_409(client, job_payload):
    created = client.post("/api/jobs", json=job_payload)
    job_id = created.json()["id"]

    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        conn.execute(
            "UPDATE jobs SET status = 'RUNNING', locked_by = 'worker-1' WHERE id = %s",
            (job_id,),
        )
        conn.commit()

    response = client.post(f"/api/jobs/{job_id}/cancel")

    assert response.status_code == 409
    assert response.json()["detail"]["status"] == "running"


def test_cancel_missing_job_returns_404(client):
    response = client.post("/api/jobs/00000000-0000-0000-0000-000000000000/cancel")

    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found"


@pytest.mark.asyncio
async def test_cancel_rejects_dead_lettered_job(db_session_factory):
    async with db_session_factory() as db:
        job = await create_pending_job(db, status=JobStatus.DEAD_LETTERED, idempotency_key="cancel-dead-letter")

        with pytest.raises(JobCancellationNotAllowedError):
            await cancel_job(db, job.id)


def test_cancel_succeeded_job_returns_409(client, job_payload):
    created = client.post("/api/jobs", json=job_payload)
    job_id = created.json()["id"]

    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        conn.execute("UPDATE jobs SET status = 'SUCCEEDED' WHERE id = %s", (job_id,))
        conn.commit()

    response = client.post(f"/api/jobs/{job_id}/cancel")

    assert response.status_code == 409
    assert response.json()["detail"]["status"] == "succeeded"


def test_cancel_dead_lettered_job_returns_409(client, job_payload):
    created = client.post("/api/jobs", json=job_payload)
    job_id = created.json()["id"]

    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        conn.execute("UPDATE jobs SET status = 'DEAD_LETTERED' WHERE id = %s", (job_id,))
        conn.commit()

    response = client.post(f"/api/jobs/{job_id}/cancel")

    assert response.status_code == 409


def test_cancel_invalid_uuid_returns_422(client):
    assert client.post("/api/jobs/not-a-uuid/cancel").status_code == 422


def test_cancelled_job_appears_in_cancelled_filter(client, job_payload):
    created = client.post("/api/jobs", json=job_payload)
    job_id = created.json()["id"]
    client.post(f"/api/jobs/{job_id}/cancel")

    response = client.get("/api/jobs", params={"status": "cancelled"})

    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert job_id in ids


@pytest.mark.asyncio
async def test_cancel_rejects_already_cancelled_job(db_session_factory):
    async with db_session_factory() as db:
        job = await create_pending_job(db, idempotency_key="cancel-twice")
        await cancel_job(db, job.id)

        with pytest.raises(JobCancellationNotAllowedError):
            await cancel_job(db, job.id)
