#!/usr/bin/env bash
# Week 5 capstone: validate docker compose, demo, load test, and full pytest suite.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_URL="${API_URL:-http://localhost:8000}"
DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://reliqueue:reliqueue@localhost:5432/reliqueue}"
TEST_DATABASE_URL="${TEST_DATABASE_URL:-postgresql+asyncpg://reliqueue:reliqueue@localhost:5432/reliqueue_test}"
LOAD_JOBS="${CAPSTONE_LOAD_JOBS:-500}"
LOAD_WORKERS="${CAPSTONE_LOAD_WORKERS:-5}"
SKIP_DEMO=0
SKIP_LOAD=0
SKIP_PYTEST=0
SKIP_DOCKER=0

usage() {
  cat <<'EOF'
Usage: scripts/capstone.sh [options]

Week 5 validation pipeline:
  1. docker compose up (API + Postgres)
  2. scripts/demo_run.sh (standard profile, faster than full)
  3. scripts/load_test.py
  4. pytest -v

Options:
  --skip-docker   Assume docker compose stack is already running
  --skip-demo     Skip demo_run.sh
  --skip-load     Skip load_test.py
  --skip-pytest   Skip pytest
  --load-jobs N   Load test job count (default: 500)
  --load-workers N  Load test workers (default: 5)
  -h, --help      Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-docker) SKIP_DOCKER=1 ;;
    --skip-demo) SKIP_DEMO=1 ;;
    --skip-load) SKIP_LOAD=1 ;;
    --skip-pytest) SKIP_PYTEST=1 ;;
    --load-jobs)
      LOAD_JOBS="$2"
      shift
      ;;
    --load-workers)
      LOAD_WORKERS="$2"
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
  echo "backend virtualenv not found. create with:" >&2
  echo "  cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt" >&2
  exit 1
fi

wait_for_api() {
  local attempt=0
  echo "waiting for API at $API_URL..."
  until curl -sf "$API_URL/health" >/dev/null; do
    attempt=$((attempt + 1))
    if [[ "$attempt" -ge 45 ]]; then
      echo "API did not become healthy in time" >&2
      exit 1
    fi
    sleep 2
  done
  echo "API is healthy"
}

cd "$ROOT"

if [[ "$SKIP_DOCKER" -eq 0 ]]; then
  echo "=== [1/4] docker compose up ==="
  docker compose up --build -d
  wait_for_api
else
  echo "=== [1/4] docker compose (skipped) ==="
  wait_for_api
fi

if [[ "$SKIP_DEMO" -eq 0 ]]; then
  echo "=== [2/4] demo_run.sh (standard profile) ==="
  DEMO_PROFILE=standard DEMO_TIMEOUT=120 "$ROOT/scripts/demo_run.sh" --no-docker
else
  echo "=== [2/4] demo (skipped) ==="
fi

if [[ "$SKIP_LOAD" -eq 0 ]]; then
  echo "=== [3/4] load_test.py (${LOAD_JOBS} jobs, ${LOAD_WORKERS} workers) ==="
  export DATABASE_URL
  "$VENV_PYTHON" "$ROOT/scripts/load_test.py" --jobs "$LOAD_JOBS" --workers "$LOAD_WORKERS" --api-base-url "$API_URL"
else
  echo "=== [3/4] load test (skipped) ==="
fi

if [[ "$SKIP_PYTEST" -eq 0 ]]; then
  echo "=== [4/4] pytest -v ==="
  cd "$ROOT/backend"
  export TEST_DATABASE_URL
  export DATABASE_URL="$TEST_DATABASE_URL"
  source .venv/bin/activate
  pytest -v
else
  echo "=== [4/4] pytest (skipped) ==="
fi

echo
echo "capstone complete: docker/demo/load/pytest pipeline passed"
