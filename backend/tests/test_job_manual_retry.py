import psycopg
import pytest

from app.models.enums import JobStatus
from app.services.job_claiming import claim_next_job
from app.services.job_failure import complete_job_failure
from app.services.job_errors import ManualRetryNotAllowedError
from app.services.job_manual_retry import manual_retry_job
from app.services.workers import register_worker
from tests.conftest import TEST_DATABASE_SYNC_URL
from tests.test_worker_claiming import create_pending_job


@pytest.mark.asyncio
async def test_manual_retry_dead_lettered_job(db_session_factory):
    async with db_session_factory() as db:
        await register_worker(db, "worker-1", "default")
        job = await create_pending_job(db, max_attempts=1, idempotency_key="manual-retry-1")

    async with db_session_factory() as db:
        claimed = await claim_next_job(db, worker_id="worker-1", queue_name="default")

    async with db_session_factory() as db:
        failed = await complete_job_failure(db, claimed.id, "worker-1", "permanent failure")

    assert failed is not None
    assert failed.status == JobStatus.DEAD_LETTERED

    async with db_session_factory() as db:
        retried = await manual_retry_job(db, job.id)

    assert retried.status == JobStatus.PENDING
    assert retried.attempts == 0
    assert retried.last_error is None
    assert retried.locked_by is None
    assert retried.run_at is not None


@pytest.mark.asyncio
async def test_manual_retry_cancelled_job(db_session_factory):
    async with db_session_factory() as db:
        job = await create_pending_job(
            db,
            status=JobStatus.CANCELLED,
            idempotency_key="manual-retry-cancelled",
        )
        retried = await manual_retry_job(db, job.id)

    assert retried.status == JobStatus.PENDING
    assert retried.attempts == 0


@pytest.mark.asyncio
async def test_manual_retry_rejects_pending_job(db_session_factory):
    async with db_session_factory() as db:
        job = await create_pending_job(db, idempotency_key="manual-retry-pending")

        with pytest.raises(ManualRetryNotAllowedError):
            await manual_retry_job(db, job.id)


def test_retry_dead_lettered_job_via_api(client):
    created = client.post(
        "/api/jobs",
        json={
            "job_type": "sleep",
            "payload": {"seconds": 1},
            "max_attempts": 3,
            "idempotency_key": "retry-api-test",
        },
    )
    assert created.status_code == 201
    job_id = created.json()["id"]

    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status = 'DEAD_LETTERED', attempts = 3, last_error = 'permanent failure'
            WHERE id = %s
            """,
            (job_id,),
        )
        conn.commit()

    response = client.post(f"/api/jobs/{job_id}/retry")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(job_id)
    assert body["status"] == "pending"
    assert body["attempts"] == 0
    assert body["last_error"] is None

    events = client.get(f"/api/jobs/{job_id}/events")
    assert events.status_code == 200
    event_types = [event["event_type"] for event in events.json()]
    assert "job_manually_retried" in event_types


def test_retry_pending_job_returns_409(client, job_payload):
    created = client.post("/api/jobs", json=job_payload)
    job_id = created.json()["id"]

    response = client.post(f"/api/jobs/{job_id}/retry")

    assert response.status_code == 409
    assert response.json()["detail"]["status"] == "pending"


def test_retry_missing_job_returns_404(client):
    response = client.post("/api/jobs/00000000-0000-0000-0000-000000000000/retry")

    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found"
