# ReliQueue

[![CI](https://github.com/rmarathe-hub/ReliQueue/actions/workflows/ci.yml/badge.svg)](https://github.com/rmarathe-hub/ReliQueue/actions/workflows/ci.yml)

A durable distributed job queue and task scheduler built with **FastAPI**, **Postgres**, and **Python workers**.

ReliQueue stores jobs in Postgres, exposes a REST API for submission and inspection, and runs Python workers that claim and execute jobs safely under concurrency. Failed jobs retry with exponential backoff, permanently failed jobs dead-letter, and a live dashboard surfaces queue health for demos and debugging.

**Documentation:** [Design tradeoffs](docs/tradeoffs.md) (vs Celery/BullMQ) · [Test coverage matrix](docs/test_matrix.md) · [OpenAPI docs](http://localhost:8000/docs) (when API is running)

## What works today

**Week 1 — API foundation**

- FastAPI service with health checks
- Docker Compose environment (API + Postgres)
- Durable job schema (`jobs`, `job_events`, `workers`)
- Job submission with idempotency keys
- Job list, detail, and event timeline APIs
- 458-test Postgres-backed pytest suite with documented markers (`reliability`, `slow`)

**Week 2 — Worker engine**

- Worker runner with registration, heartbeats, and polling
- Safe concurrent job claiming via Postgres `FOR UPDATE SKIP LOCKED`
- Job handlers (`sleep`, `fail_once`, `fail_always`, `random_fail`, `generate_report`)
- Successful job completion and `job_succeeded` events
- Multi-worker demo scripts and concurrency tests

**Week 3 — Reliability**

- Failure handling with exponential backoff and jitter
- Manual retry and job cancellation APIs
- Dead-letter queue after max attempts
- Worker lease recovery for crashed workers
- Worker list/detail APIs and reliability test suite

**Week 4 — Observability and demo**

- `GET /api/metrics` — queue depth, status counts, worker counts, recent activity
- Live HTML dashboard at `/dashboard` with metrics, job drill-down, and worker health
- One-command demo script (`scripts/run_demo.py`) for portfolio walkthroughs
- Hands-off demo launcher (`scripts/demo_run.sh`) — Docker, migrations, workers, and full 35-job batch

**Week 5 — CI and engineering credibility**

- GitHub Actions CI on Postgres ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) — 450 fast tests + reliability slice on every push
- [`scripts/load_test.py`](scripts/load_test.py) — 500 jobs / 5 workers, 0 duplicate claims (~9 jobs/sec locally)
- Structured JSON worker logs (`event`, `worker_id`, `job_id`, `duration_ms`, `status`)
- [`docs/tradeoffs.md`](docs/tradeoffs.md) — Postgres vs Redis/RabbitMQ, at-least-once guarantees, Celery/BullMQ comparison table

## Architecture

```mermaid
flowchart TB
    subgraph Clients
        HTTP[HTTP clients / curl]
        Scripts[scripts: demo, load_test, seed]
        Dash[Dashboard /dashboard]
    end

    HTTP --> API[FastAPI API]
    Scripts --> API
    Dash --> API

    API --> DB[(Postgres)]

    subgraph Worker processes
        W1[Worker 1]
        W2[Worker 2]
        WN[Worker N]
    end

    W1 --> DB
    W2 --> DB
    WN --> DB

    subgraph Postgres tables
        Jobs[jobs]
        Events[job_events]
        WorkersTbl[workers]
    end

    DB --- Jobs
    DB --- Events
    DB --- WorkersTbl
```

**Claiming model:** workers poll Postgres and claim with `SELECT … FOR UPDATE SKIP LOCKED` inside a transaction — no Redis or RabbitMQ broker. See [How workers claim jobs](#how-workers-claim-jobs) and [tradeoffs.md](docs/tradeoffs.md).

### Worker execution loop

```mermaid
sequenceDiagram
    participant W as Worker
    participant DB as Postgres

    W->>DB: register + heartbeat
    loop Poll cycle
        W->>DB: recover expired leases (optional)
        W->>DB: claim next pending job (SKIP LOCKED)
        alt job available
            W->>W: run handler
            alt success
                W->>DB: mark succeeded + job_succeeded event
            else failure
                W->>DB: mark failed/retry/dead-letter + job_failed event
            end
        else no job
            W->>W: sleep poll interval
        end
        W->>DB: heartbeat
    end
```

### Job lifecycle

```mermaid
stateDiagram-v2
    [*] --> pending: POST /api/jobs
    pending --> running: worker claims job
    running --> succeeded: handler completes
    running --> pending: failure with retries left (backoff via run_at)
    running --> dead_lettered: max attempts exceeded
    pending --> cancelled: POST /api/jobs/{id}/cancel
    running --> pending: lease expires (recovery)
    dead_lettered --> pending: POST /api/jobs/{id}/retry
    succeeded --> [*]
    dead_lettered --> [*]
    cancelled --> [*]
```

**Submit path**

1. Client submits a job via `POST /api/jobs`.
2. API writes a `pending` row to `jobs` and a `job_created` event to `job_events`.
3. Client polls list/detail/events endpoints (or the dashboard) to inspect job state.

**Worker path**

1. Each worker registers in `workers` and polls its queue on an interval.
2. A worker claims the next eligible `pending` job inside a Postgres transaction using `FOR UPDATE SKIP LOCKED`.
3. The worker runs the handler, then marks the job `succeeded` or records a failure with retry/dead-letter logic.
4. Multiple workers can poll the same queue without claiming the same job twice.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- Python 3.12+ (for local development and tests; matches `backend/Dockerfile`)

## Quick start

### 1. Clone and start services

```bash
git clone https://github.com/rmarathe-hub/ReliQueue.git
cd ReliQueue
docker compose up --build -d
```

### 2. Run database migrations

```bash
docker compose exec api alembic upgrade head
```

### 3. Verify the API

```bash
curl http://localhost:8000/health
```

Expected:

```json
{"status": "ok", "database": "ok"}
```

Open interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs)

Open the live dashboard: [http://localhost:8000/dashboard](http://localhost:8000/dashboard)

### 4. Create a job

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "job_type": "sleep",
    "payload": {"seconds": 3},
    "max_attempts": 3,
    "idempotency_key": "demo-1"
  }'
```

Save the `id` from the response, then:

```bash
# List jobs
curl 'http://localhost:8000/api/jobs?status=pending&limit=50'

# Job detail (replace JOB_ID)
curl http://localhost:8000/api/jobs/JOB_ID

# Event timeline
curl http://localhost:8000/api/jobs/JOB_ID/events

# Queue metrics snapshot
curl http://localhost:8000/api/metrics

# List workers
curl http://localhost:8000/api/workers
```

Example metrics response:

```json
{
  "jobs_by_status": {
    "pending": 2,
    "running": 1,
    "succeeded": 10,
    "dead_lettered": 0,
    "cancelled": 0
  },
  "dead_letter_count": 0,
  "queue_depth": {"default": 1},
  "jobs_created_last_hour": 3,
  "failures_last_hour": 1,
  "workers_by_status": {"online": 2, "offline": 0},
  "worker_count": 2,
  "avg_runtime_seconds": 1.05
}
```

### Stop services

```bash
docker compose down
```

## Dashboard

The dashboard at [http://localhost:8000/dashboard](http://localhost:8000/dashboard) auto-refreshes every 5 seconds and polls existing API endpoints — no separate frontend build step.

| View | What it shows |
|------|----------------|
| **Metrics cards** | Pending, running, succeeded, dead-letter, cancelled, workers, hourly activity, avg runtime |
| **Queue depth** | Eligible pending jobs per queue |
| **Recent jobs** | Click any row for payload, attempts, last error, and full event timeline |
| **Workers** | Status, heartbeat age, health estimate (healthy / stale / offline), current job |
| **Worker detail** | Heartbeat timestamps, queue assignment, link to current job |

Capture a screenshot after running `python scripts/run_demo.py` with workers active for portfolio READMEs or LinkedIn posts.

## Local development (without Docker API)

Useful if you want hot reload outside the container.

```bash
# Terminal 1 — Postgres only
docker compose up db

# Terminal 2 — API
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example ../.env
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## API reference

Full interactive reference: [http://localhost:8000/docs](http://localhost:8000/docs) (Swagger UI) and [http://localhost:8000/redoc](http://localhost:8000/redoc).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | API and database health |
| `POST` | `/api/jobs` | Submit a job (`201` new, `200` idempotent replay) |
| `GET` | `/api/jobs` | List jobs — query: `status`, `queue_name`, `job_type`, `limit` (1–100), `offset` |
| `GET` | `/api/jobs/{job_id}` | Job detail (lock fields, `last_error`, timestamps) |
| `GET` | `/api/jobs/{job_id}/events` | Append-only event timeline |
| `POST` | `/api/jobs/{job_id}/retry` | Manual retry — `dead_lettered` or `cancelled` → `pending` (`409` if not allowed) |
| `POST` | `/api/jobs/{job_id}/cancel` | Cancel — `pending` only (`409` if running or terminal) |
| `GET` | `/api/workers` | List workers — query: `status`, `queue_name`, `limit`, `offset` |
| `GET` | `/api/workers/{worker_id}` | Worker detail (`current_job_id`, heartbeat) |
| `GET` | `/api/metrics` | Queue depth, status counts, worker counts, hourly activity, avg runtime |
| `GET` | `/dashboard` | Live HTML dashboard (auto-refreshes every 5s) |

**Not exposed on create API:** `run_at` is set internally for retry backoff (see [tradeoffs.md](docs/tradeoffs.md#6-feature-comparison--reliqueue-vs-celery-vs-bullmq)).

### Job submission body

```json
{
  "job_type": "sleep",
  "payload": {"seconds": 3},
  "max_attempts": 3,
  "idempotency_key": "demo-1",
  "queue_name": "default",
  "priority": 0
}
```

### Idempotency rules

| Case | Response |
|------|----------|
| New job | `201 Created` |
| Same `idempotency_key` + same payload | `200 OK` (returns existing job) |
| Same `idempotency_key` + different payload | `409 Conflict` |

### Job statuses

`pending` · `running` · `succeeded` · `dead_lettered` · `cancelled`

## Tests

**458 Postgres-backed integration tests** across API validation, job state machine, worker claiming, retries/DLQ, lease recovery, metrics, dashboard, concurrency, and demo scripts. Full suite runs in ~30 seconds on a laptop.

Requires Postgres (for example `docker compose up db`). Tests use a separate `reliqueue_test` database — created automatically if missing — run Alembic migrations once per session, and truncate tables between tests.

### Setup

```bash
cd backend
source .venv/bin/activate
pip install -r requirements.txt
export TEST_DATABASE_URL=postgresql+asyncpg://reliqueue:reliqueue@localhost:5432/reliqueue_test
```

### Commands

| Command | Tests | Use when |
|---------|-------|----------|
| `pytest -v` | 458 (full suite) | Local validation before a commit or PR |
| `pytest -m "not slow" -v` | 455 | **CI and fast feedback** — skips 3 stress/concurrency tests |
| `pytest -m reliability -v` | 7 | Core retry, DLQ, lease, cancel, and event-timeline scenarios |
| `pytest -m slow -v` | 3 | High-volume concurrency only (200-job / multi-queue stress) |

```bash
cd backend
pytest -v                      # full suite
pytest -m "not slow" -v        # recommended for CI
pytest -m reliability -v       # reliability slice
pytest -m slow -v              # stress tests only
```

### Pytest markers

Defined in `backend/pytest.ini`:

| Marker | Meaning |
|--------|---------|
| `reliability` | Week 3 reliability scenarios in `test_reliability.py` — retries, backoff, manual retry, cancellation, lease recovery, event timelines |
| `slow` | Heavier concurrency tests (large job batches, parallel workers) — excluded from the default CI command |

List registered markers: `pytest --markers`

### Coverage map

See [`docs/test_matrix.md`](docs/test_matrix.md) for behavior-area → test-file mapping (458 tests), intentional overlap notes, and remaining risk.

### CI

[![CI](https://github.com/rmarathe-hub/ReliQueue/actions/workflows/ci.yml/badge.svg)](https://github.com/rmarathe-hub/ReliQueue/actions/workflows/ci.yml)

On every push/PR to `main` ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)):

1. Postgres 16 service
2. `alembic upgrade head`
3. `pytest -m "not slow"` — 455 integration tests
4. `pytest -m reliability` — 7 core retry/DLQ/lease scenarios

**Slow tests** (3 concurrency stress tests) run on demand or weekly via [`.github/workflows/slow-tests.yml`](.github/workflows/slow-tests.yml) (`workflow_dispatch` or Mondays 06:00 UTC).

#### Run CI locally

Mirror the GitHub Actions job before pushing:

```bash
# 1. Postgres
docker compose up -d db

# 2. Backend venv + env
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export TEST_DATABASE_URL=postgresql+asyncpg://reliqueue:reliqueue@localhost:5432/reliqueue_test
export DATABASE_URL="$TEST_DATABASE_URL"

# 3. Migrations + same pytest commands as CI
alembic upgrade head
pytest -m "not slow" -v
pytest -m reliability -v
```

Optional: `pytest -m slow -v` for the 3 stress tests (also run weekly in Actions).

### Load test

`scripts/load_test.py` submits a batch of `sleep` jobs via the API, starts worker processes, waits for completion, and verifies there are no duplicate `job_claimed` events.

```bash
docker compose up -d
cd backend && source .venv/bin/activate
python ../scripts/load_test.py --jobs 500 --workers 5
```

Use `--no-workers` if workers are already running on the target queue. Jobs use a dedicated queue (`load-test` by default) and a unique idempotency prefix so results stay isolated from other demo data.

#### Load test results

Measured locally (Docker Compose on macOS, Postgres 16, API + 5 worker processes, `sleep` jobs with `seconds: 0`):

| Metric | Result |
|--------|--------|
| Jobs | 500 |
| Workers | 5 |
| Duplicate claims | **0** |
| Submit time | 2.9s |
| Processing time | 54.7s |
| **Throughput** | **~9.1 jobs/sec** |
| Outcomes | 500 succeeded, 0 failed, 0 dead-lettered |

Resume-ready line: *500 jobs / 5 workers, 0 duplicate claims, ~9 jobs/sec (Postgres `SKIP LOCKED`, local Docker).*

## Workers

Start a worker process (requires Postgres running and migrations applied):

```bash
cd backend
source .venv/bin/activate
python -m app.worker.runner --worker-id worker-1
```

Optional flags:

```bash
python -m app.worker.runner --worker-id worker-1 --queue-name default --poll-interval 2
```

The worker registers in the `workers` table, claims pending jobs using Postgres `FOR UPDATE SKIP LOCKED`, runs the matching handler, and marks successful jobs `succeeded`.

### Structured logs

Workers emit **one JSON object per line** (logger: `reliqueue.worker`) for lifecycle events. Core fields: `event`, `worker_id`, `job_id`, `job_type`, `duration_ms`, `status`.

```json
{"timestamp":"2026-07-01T06:30:00.123456+00:00","event":"worker_started","worker_id":"worker-1","queue_name":"default","poll_interval":2.0,"handlers":["sleep","fail_once","fail_always","random_fail","generate_report"],"lease_seconds":60}
{"timestamp":"2026-07-01T06:30:02.456789+00:00","event":"job_claimed","worker_id":"worker-1","job_id":"a1b2c3d4-e5f6-7890-abcd-ef1234567890","job_type":"sleep","attempts":1,"queue_name":"default","status":"running"}
{"timestamp":"2026-07-01T06:30:02.567890+00:00","event":"job_succeeded","worker_id":"worker-1","job_id":"a1b2c3d4-e5f6-7890-abcd-ef1234567890","job_type":"sleep","attempts":1,"status":"succeeded","duration_ms":110.42}
```

Failed jobs include `error` and a terminal or retry `status` (`pending`, `dead_lettered`):

```json
{"timestamp":"2026-07-01T06:30:05.000000+00:00","event":"job_failed","worker_id":"worker-1","job_id":"b2c3d4e5-f6a7-8901-bcde-f12345678901","job_type":"fail_always","attempts":2,"status":"dead_lettered","duration_ms":4.8,"error":"simulated permanent failure"}
```

Other events: `lease_recovered`, `worker_stopped`, `shutdown_signal`.

### Supported demo job types

| `job_type` | Behavior |
|------------|----------|
| `sleep` | Waits `payload.seconds` |
| `fail_once` | Fails on first attempt (`attempts == 1`), succeeds on retry |
| `fail_always` | Always raises an error |
| `random_fail` | Fails with `payload.probability` (default `0.5`) |
| `generate_report` | Simulates report generation for `payload.duration` seconds |

### Multi-worker demo

With API and Postgres running (`docker compose up`), start three workers in separate terminals:

```bash
cd backend
source .venv/bin/activate
python -m app.worker.runner --worker-id worker-1
python -m app.worker.runner --worker-id worker-2
python -m app.worker.runner --worker-id worker-3
```

Seed 20 short sleep jobs (from repo root, with the backend venv activated):

```bash
python scripts/seed_jobs.py --count 20 --job-type sleep
```

Worker stdout is JSON — pipe to `jq` for pretty printing, for example: `python -m app.worker.runner --worker-id worker-1 | jq`.

Verify all jobs completed and no job was claimed twice:

```bash
python scripts/verify_queue.py --expected-succeeded 20
```

The verify script prints status counts, claims per worker, and fails if any job has duplicate `job_claimed` events.

### One-command portfolio demo

**Fully hands-off (Day 27)** — starts Docker, migrates, spawns workers, seeds 35 jobs, waits, and verifies:

```bash
# Requires backend venv: cd backend && python -m venv .venv && pip install -r requirements.txt
./scripts/demo_run.sh
```

Useful flags:

```bash
# Stack already running; only seed + wait + verify
./scripts/demo_run.sh --no-docker

# Leave workers running for dashboard exploration
./scripts/demo_run.sh --keep-workers

# Smaller 15-job batch instead of the full 35-job mix
./scripts/demo_run.sh --profile standard
```

**API-only demo** — if Docker and workers are already running:

```bash
cd backend
source .venv/bin/activate
python -m app.worker.runner --worker-id worker-1
```

From another terminal (repo root, backend venv activated):

```bash
python scripts/run_demo.py
```

`run_demo.py` uses the **standard** profile (15 jobs) by default. For the original Day 27 mix:

```bash
python scripts/run_demo.py --profile full
```

This script:

1. Checks API health
2. Seeds a mixed batch (profile-dependent)
3. Polls `/api/metrics` until the queue is idle (`pending=0`, `running=0`)
4. Runs duplicate-claim verification via `verify_queue.py`
5. Prints the dashboard URL: `http://localhost:8000/dashboard`

| Profile | Job mix |
|---------|---------|
| `standard` (default) | 10 `sleep`, 3 `fail_once`, 2 `fail_always` |
| `full` | 20 `sleep`, 10 `random_fail`, 5 `fail_always` |

Useful flags:

```bash
# Seed only, do not wait for workers
python scripts/run_demo.py --no-wait

# Re-run against an existing batch (skip seed)
python scripts/run_demo.py --skip-seed --no-wait

# Show metrics after manual verification
python scripts/verify_queue.py --show-metrics
```

### How workers claim jobs

ReliQueue uses Postgres row locks instead of a separate coordination service. When a worker polls for work, `claim_next_job` runs a transaction that:

1. Selects one eligible `pending` job (`run_at <= now`) for the worker's queue, ordered by `priority DESC`, then `run_at ASC`.
2. Applies `FOR UPDATE SKIP LOCKED` so concurrent workers skip rows already locked by another open transaction.
3. Updates the claimed row to `running`, sets `locked_by`, `locked_at`, and `lease_expires_at`, and increments `attempts`.
4. Appends a `job_claimed` event with the worker ID and lease metadata.

**Why `SKIP LOCKED` matters**

Without `SKIP LOCKED`, workers contending for the same row would block until the lock holder commits. With `SKIP LOCKED`, a worker that cannot lock the next row immediately moves on to the next available job instead of waiting. That gives non-blocking, work-stealing behavior across many worker processes using only Postgres.

**Concurrency guarantee**

Each job should be claimed at most once per attempt. The automated test `test_concurrent_claiming_no_duplicates` seeds many jobs, runs concurrent claim operations from multiple workers, and asserts:

- every job is claimed exactly once
- no duplicate job IDs appear in claim results
- each job has a single `job_claimed` event

**Lease recovery**

`locked_by`, `locked_at`, and `lease_expires_at` record which worker owns a running job. If a worker crashes, `recover_expired_leases` returns the job to `pending` so another worker can reclaim it.

## Configuration

Copy `.env.example` to `.env` and adjust as needed.

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | Async Postgres URL for the API |
| `TEST_DATABASE_URL` | Postgres URL used by pytest |
| `DEBUG` | Enable FastAPI debug mode |
| `WORKER_LEASE_SECONDS` | Worker lease duration for claimed jobs |
| `WORKER_RECOVERY_INTERVAL_SECONDS` | How often workers scan for expired leases |
| `RETRY_BASE_DELAY_SECONDS` | Base delay for exponential backoff |
| `RETRY_MAX_DELAY_SECONDS` | Cap on retry backoff delay |

## Project structure

```text
ReliQueue/
├── backend/
│   ├── app/
│   │   ├── api/routes/      # HTTP handlers (health, jobs, workers, metrics, dashboard)
│   │   ├── core/            # Settings
│   │   ├── db/              # Engine and session
│   │   ├── models/          # SQLAlchemy models
│   │   ├── schemas/         # Pydantic models
│   │   ├── services/        # Business logic
│   │   ├── static/          # Dashboard HTML
│   │   ├── worker/          # Worker runner CLI + structured JSON logs
│   │   └── main.py
│   ├── alembic/             # Migrations
│   ├── tests/               # Pytest suite
│   ├── Dockerfile
│   ├── pytest.ini
│   └── requirements.txt
├── docker-compose.yml
├── .github/
│   └── workflows/
│       ├── ci.yml           # Postgres CI on push/PR
│       └── slow-tests.yml   # Weekly / manual stress tests
├── docs/
│   ├── test_matrix.md       # Test coverage map
│   ├── tradeoffs.md         # Design tradeoffs vs Celery/BullMQ
│   └── week5-week6-plan.md  # Portfolio roadmap
├── scripts/
│   ├── demo_common.py       # Shared demo helpers (metrics, seed specs)
│   ├── demo_run.sh          # Hands-off demo (Docker + workers + full batch)
│   ├── load_test.py         # API load test (throughput + duplicate-claim check)
│   ├── run_demo.py          # End-to-end portfolio demo via API
│   ├── seed_jobs.py         # Submit demo jobs via API
│   └── verify_queue.py      # Queue summary and duplicate-claim check
├── .env.example
└── README.md
```

## Further reading

| Doc | Contents |
|-----|----------|
| [docs/tradeoffs.md](docs/tradeoffs.md) | Postgres vs Redis/RabbitMQ, at-least-once delivery, Celery/BullMQ feature table, parity roadmap |
| [docs/test_matrix.md](docs/test_matrix.md) | 458 tests mapped to behavior areas, CI commands, overlap notes |
| [docs/week5-week6-plan.md](docs/week5-week6-plan.md) | Week 5–6 portfolio checklist |

## Roadmap

- [x] Week 1 — API foundation, schema, job lifecycle endpoints, tests
- [x] Week 2 — Worker engine and safe concurrent claiming
- [x] Week 3 — Retries, dead-letter queue, lease recovery
- [x] Week 4 — Metrics, dashboard, demo scripts
- [x] Week 5 — CI, load test, structured logging, tradeoffs documentation
- [ ] Week 6 — Portfolio polish (screenshots, deploy, LinkedIn)

## License

MIT
