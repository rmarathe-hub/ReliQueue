# ReliQueue

A durable distributed job queue and task scheduler built with FastAPI, Postgres, and Python workers.

## Status

Week 1 — Foundation (in progress)

- [x] Day 1: FastAPI backend with health endpoint
- [ ] Day 2: Docker Compose + Postgres
- [ ] Day 3: Database schema and migrations
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

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example ../.env    # optional; defaults work for Day 1
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## API

### Health check

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status": "ok"}
```

Interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs)

## Project structure

```text
ReliQueue/
├── backend/
│   ├── app/
│   │   ├── api/routes/   # HTTP route handlers
│   │   ├── core/         # Config and shared utilities
│   │   └── main.py       # FastAPI application entrypoint
│   └── requirements.txt
├── .env.example
└── README.md
```

## License

MIT
