def test_create_job(client, job_payload):
    response = client.post("/api/jobs", json=job_payload)

    assert response.status_code == 201
    body = response.json()
    assert body["job_type"] == "sleep"
    assert body["payload"] == {"seconds": 3}
    assert body["status"] == "pending"
    assert body["max_attempts"] == 3
    assert body["attempts"] == 0
    assert body["idempotency_key"] == "test-job-1"
    assert "id" in body


def test_duplicate_idempotency_key_returns_same_job(client, job_payload):
    first = client.post("/api/jobs", json=job_payload)
    second = client.post("/api/jobs", json=job_payload)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_idempotency_conflict_returns_409(client, job_payload):
    created = client.post("/api/jobs", json=job_payload)
    assert created.status_code == 201

    conflict_payload = {
        **job_payload,
        "payload": {"seconds": 99},
    }
    response = client.post("/api/jobs", json=conflict_payload)

    assert response.status_code == 409
    assert response.json()["detail"]["idempotency_key"] == "test-job-1"


def test_list_jobs(client, job_payload):
    created = client.post("/api/jobs", json=job_payload)
    assert created.status_code == 201

    response = client.get("/api/jobs", params={"status": "pending", "job_type": "sleep"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == created.json()["id"]


def test_get_job_detail(client, job_payload):
    created = client.post("/api/jobs", json=job_payload)
    job_id = created.json()["id"]

    response = client.get(f"/api/jobs/{job_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == job_id
    assert body["job_type"] == "sleep"
    assert body["last_error"] is None
    assert "updated_at" in body


def test_get_job_not_found_returns_404(client):
    response = client.get("/api/jobs/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found"


def test_get_job_events_not_found_returns_404(client):
    response = client.get("/api/jobs/00000000-0000-0000-0000-000000000000/events")

    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found"


def test_create_job_validation_error(client, job_payload):
    invalid_payload = {**job_payload, "max_attempts": 0}
    response = client.post("/api/jobs", json=invalid_payload)

    assert response.status_code == 422


def test_job_events_created_on_create(client, job_payload):
    created = client.post("/api/jobs", json=job_payload)
    job_id = created.json()["id"]

    response = client.get(f"/api/jobs/{job_id}/events")

    assert response.status_code == 200
    events = response.json()
    assert len(events) == 1
    assert events[0]["event_type"] == "job_created"
    assert events[0]["job_id"] == job_id
    assert events[0]["payload"]["job_type"] == "sleep"
