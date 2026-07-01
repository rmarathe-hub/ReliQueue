#!/usr/bin/env bash
# Start ReliQueue locally, seed the full Day 27 demo batch, run workers, and verify.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_URL="${API_URL:-http://localhost:8000}"
DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://reliqueue:reliqueue@localhost:5432/reliqueue}"
WORKER_COUNT="${WORKER_COUNT:-3}"
PROFILE="${DEMO_PROFILE:-full}"
TIMEOUT="${DEMO_TIMEOUT:-180}"
POLL_INTERVAL="${DEMO_POLL_INTERVAL:-2}"
START_DOCKER=1
START_WORKERS=1
KEEP_WORKERS=0
SKIP_VERIFY=0

usage() {
  cat <<'EOF'
Usage: scripts/demo_run.sh [options]

Hands-off portfolio demo (original Week 4 Day 27):
  1. docker compose up (API + Postgres)
  2. alembic migrate
  3. start background workers
  4. seed 20 sleep + 10 random_fail + 5 fail_always jobs
  5. wait for queue drain and verify no duplicate claims

Options:
  --no-docker       Skip docker compose up (stack already running)
  --no-workers      Skip starting workers (workers already running)
  --keep-workers    Leave worker processes running after the script exits
  --skip-verify     Skip duplicate-claim verification
  --worker-count N  Number of workers to start (default: 3)
  --profile NAME    Demo profile: full (default) or standard
  --timeout SEC     Wait timeout passed to run_demo.py (default: 180 for full)
  --api-url URL     API base URL (default: http://localhost:8000)
  -h, --help        Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-docker) START_DOCKER=0 ;;
    --no-workers) START_WORKERS=0 ;;
    --keep-workers) KEEP_WORKERS=1 ;;
    --skip-verify) SKIP_VERIFY=1 ;;
    --worker-count)
      WORKER_COUNT="$2"
      shift
      ;;
    --profile)
      PROFILE="$2"
      shift
      ;;
    --timeout)
      TIMEOUT="$2"
      shift
      ;;
    --api-url)
      API_URL="$2"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

VENV_PYTHON="$ROOT/backend/.venv/bin/python"
if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "backend virtualenv not found at backend/.venv" >&2
  echo "create it with:" >&2
  echo "  cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt" >&2
  exit 1
fi

WORKER_PIDS=()

cleanup_workers() {
  if [[ "$KEEP_WORKERS" -eq 1 || ${#WORKER_PIDS[@]} -eq 0 ]]; then
    return
  fi
  echo "stopping demo workers..."
  for pid in "${WORKER_PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  wait "${WORKER_PIDS[@]}" 2>/dev/null || true
}

trap cleanup_workers EXIT

wait_for_api() {
  local attempt=0
  local max_attempts=45
  echo "waiting for API health at $API_URL..."
  until curl -sf "$API_URL/health" >/dev/null; do
    attempt=$((attempt + 1))
    if [[ "$attempt" -ge "$max_attempts" ]]; then
      echo "API did not become healthy in time" >&2
      exit 1
    fi
    sleep 2
  done
  echo "API is healthy"
}

start_workers() {
  echo "starting $WORKER_COUNT worker(s)..."
  for index in $(seq 1 "$WORKER_COUNT"); do
    (
      cd "$ROOT/backend"
      export DATABASE_URL
      exec "$VENV_PYTHON" -m app.worker.runner \
        --worker-id "demo-worker-$index" \
        --poll-interval "$POLL_INTERVAL" \
        >/tmp/reliqueue-demo-worker-"$index".log 2>&1
    ) &
    WORKER_PIDS+=("$!")
    echo "  demo-worker-$index pid=${WORKER_PIDS[$((index - 1))]} log=/tmp/reliqueue-demo-worker-$index.log"
  done
  sleep 2
}

cd "$ROOT"

if [[ "$START_DOCKER" -eq 1 ]]; then
  echo "starting docker compose services..."
  docker compose up --build -d
fi

wait_for_api

echo "running database migrations..."
docker compose exec -T api alembic upgrade head

if [[ "$START_WORKERS" -eq 1 ]]; then
  start_workers
fi

DEMO_ARGS=(
  "$VENV_PYTHON" "$ROOT/scripts/run_demo.py"
  --api-base-url "$API_URL"
  --profile "$PROFILE"
  --timeout "$TIMEOUT"
  --poll-interval "$POLL_INTERVAL"
)

if [[ "$SKIP_VERIFY" -eq 1 ]]; then
  DEMO_ARGS+=(--skip-verify)
fi

echo "running demo seed + wait + verify..."
"${DEMO_ARGS[@]}"
demo_status=$?

echo
echo "ReliQueue demo URLs:"
echo "  dashboard: $API_URL/dashboard"
echo "  api docs:  $API_URL/docs"
echo "  health:    $API_URL/health"
echo "  metrics:   $API_URL/metrics"

if [[ "$KEEP_WORKERS" -eq 1 && ${#WORKER_PIDS[@]} -gt 0 ]]; then
  echo
  echo "workers left running (demo-worker-1..$WORKER_COUNT). stop with:"
  echo "  kill ${WORKER_PIDS[*]}"
fi

exit "$demo_status"
