# ReliQueue

A durable distributed job queue and task scheduler built with FastAPI, Postgres, and Python workers.

## Status

Week 1 — Foundation (in progress)

- [x] Day 1: FastAPI backend with health endpoint
- [x] Day 2: Docker Compose + Postgres
- [x] Day 3: Database schema and migrations
- [ ] Day 4: Job submission API
- [ ] Day 5: Job listing, detail, and events API
- [ ] Day 6: API tests
- [ ] Day 7: Documentation and cleanup

## Features (planned)

- Durable job submission and status tracking
- Transaction-safe multi-worker job claiming
- Retries with exponential backoff
- Dead-letter queue handling
- Worker leases and crash recovery
- Idempotency keys and job event timelines
- Metrics, dashboard, and CI

## Prerequisites

- Python 3.11+
- Docker and Docker Compose (starting Day 2)

## Local setup

### Docker Compose (recommended)

Starts Postgres and the API together:

```bash
docker compose up --build
```

### Local API only

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example ../.env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

For local API + Docker Postgres, start only the database:

```bash
docker compose up db
```

### Database migrations

With Postgres running:

```bash
cd backend
source .venv/bin/activate
alembic upgrade head
```

From Docker:

```bash
docker compose exec api alembic upgrade head
```

## API

### Health check

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status": "ok", "database": "ok"}
```

Interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs)

## Project structure

```text
ReliQueue/
├── backend/
│   ├── app/
│   │   ├── api/routes/   # HTTP route handlers
│   │   ├── core/         # Config and shared utilities
│   │   ├── db/           # Database engine and session
│   │   ├── models/       # SQLAlchemy models and enums
│   │   └── main.py       # FastAPI application entrypoint
│   ├── alembic/          # Database migrations
│   ├── Dockerfile
│   └── requirements.txt
├── docker-compose.yml
├── .env.example
└── README.md
```

## License

MIT
