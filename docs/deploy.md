# Deploying ReliQueue

ReliQueue deploys as a **single API container** plus **managed Postgres**. Workers are not run in the cloud by default — run them locally against the production `DATABASE_URL` (see [Workers in production](#workers-in-production)).

## Railway (recommended)

### 1. Prerequisites

- [Railway account](https://railway.com/)
- [Railway CLI](https://docs.railway.com/develop/cli) (`npm i -g @railway/cli` or `brew install railway`)
- This repo pushed to GitHub

### 2. Create project

```bash
cd ReliQueue
railway login
railway init          # new project
railway add --database postgres
```

### 3. Deploy API service

Link the repo root (uses `railway.toml` → `backend/Dockerfile`):

```bash
railway up
```

Or connect GitHub in the Railway dashboard: **New Project → Deploy from GitHub → ReliQueue**.

### 4. Configure environment variables

In the Railway **API service** (not the Postgres plugin), set:

| Variable | Value |
|----------|--------|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (reference from Postgres plugin) |
| `DEBUG` | `false` |
| `APP_ENV` | `production` |

Railway provides `PORT` automatically. The Docker `entrypoint.sh` runs `alembic upgrade head` then starts uvicorn on that port.

`DATABASE_URL` from Railway uses `postgres://` or `postgresql://` — ReliQueue normalizes this to `postgresql+asyncpg://` at startup.

### 5. Generate public domain

Railway dashboard → your API service → **Settings → Networking → Generate Domain**.

Smoke test:

```bash
export API_URL=https://YOUR-SERVICE.up.railway.app
curl -sf "$API_URL/health"
curl -sf -o /dev/null -w "%{http_code}\n" "$API_URL/dashboard"
```

Expected: health JSON with `"status":"ok"` and dashboard HTTP `200`.

### 6. Update README live link

Replace the placeholder in README **Live demo** with your domain after first successful deploy.

---

## Fly.io (alternative)

Fly requires a Postgres cluster and small config tweaks. Minimal path:

```bash
cd backend
fly launch --no-deploy          # pick app name + region
fly postgres create             # or attach existing
fly secrets set DATABASE_URL="postgresql+asyncpg://..." DEBUG=false APP_ENV=production
fly deploy
```

Use the same `backend/Dockerfile` and `entrypoint.sh`. Set `fly.toml`:

```toml
app = "reliqueue"
primary_region = "iad"

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = "stop"
  auto_start_machines = true
  min_machines_running = 0

  [[http_service.checks]]
    path = "/health"
    interval = "15s"
    timeout = "5s"
```

Map Fly's `PORT` (default 8080) — `entrypoint.sh` already reads `$PORT`.

---

## Workers in production

The hosted deployment exposes the **API + dashboard** only. Background job processing requires a worker process with network access to the same Postgres:

```bash
cd backend
source .venv/bin/activate
export DATABASE_URL="postgresql+asyncpg://..."   # same as production
export DEBUG=false
python -m app.worker.runner --worker-id prod-worker-1 --poll-interval 2
```

For a portfolio demo, running workers on your laptop against Railway Postgres is enough. A second Railway service running `python -m app.worker.runner` is possible but omitted here to keep cost and complexity low.

---

## Security checklist (Day 42)

- [ ] `DEBUG=false` in production  
- [ ] No `.env` committed (only `.env.example`)  
- [ ] Postgres credentials only in platform secrets / `${{Postgres.DATABASE_URL}}`  
- [ ] Public URL uses HTTPS (Railway/Fly default)  
- [ ] Do not expose `TEST_DATABASE_URL` in production services  

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| API crashes on boot | Check deploy logs for migration errors; verify `DATABASE_URL` is set |
| `/health` returns database error | Postgres plugin not linked; use `${{Postgres.DATABASE_URL}}` |
| Jobs stay `pending` | No workers running — start a local worker against prod DB |
| `postgres://` URL errors | Upgrade to latest code (`normalize_async_database_url` in `config.py`) |
