#!/usr/bin/env bash
# Day 44 final audit: docs, scripts, CI files, and fast test suite.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_URL="${API_URL:-http://localhost:8000}"
FAIL=0

check() {
  local description="$1"
  shift
  if "$@"; then
    echo "  ok  $description"
  else
    echo "  FAIL  $description" >&2
    FAIL=1
  fi
}

echo "ReliQueue final audit"
echo "====================="

echo
echo "Required files"
check "README.md" test -f "$ROOT/README.md"
check "docs/tradeoffs.md" test -f "$ROOT/docs/tradeoffs.md"
check "docs/test_matrix.md" test -f "$ROOT/docs/test_matrix.md"
check "docs/deploy.md" test -f "$ROOT/docs/deploy.md"
check "railway.toml" test -f "$ROOT/railway.toml"
check "backend/entrypoint.sh" test -f "$ROOT/backend/entrypoint.sh"
check ".github/workflows/ci.yml" test -f "$ROOT/.github/workflows/ci.yml"
check "scripts/capstone.sh" test -f "$ROOT/scripts/capstone.sh"
check "scripts/load_test.py" test -f "$ROOT/scripts/load_test.py"
check "scripts/demo_run.sh" test -f "$ROOT/scripts/demo_run.sh"

echo
echo "README links"
README="$ROOT/README.md"
check "tradeoffs link" grep -q "docs/tradeoffs.md" "$README"
check "test_matrix link" grep -q "docs/test_matrix.md" "$README"
check "deploy link" grep -q "docs/deploy.md" "$README"
check "CI badge" grep -q "github.com/.*/actions/workflows/ci.yml/badge.svg" "$README"

echo
echo "Tests (CI-equivalent + doc tests)"
cd "$ROOT/backend"
source .venv/bin/activate
export TEST_DATABASE_URL="${TEST_DATABASE_URL:-postgresql+asyncpg://reliqueue:reliqueue@localhost:5432/reliqueue_test}"
export DATABASE_URL="$TEST_DATABASE_URL"
check "pytest not slow" pytest -m "not slow" -q
check "pytest reliability" pytest -m reliability -q
check "tradeoffs doc tests" pytest tests/test_tradeoffs_doc.py -q
check "readme engineering tests" pytest tests/test_readme_engineering.py -q
check "deploy doc tests" pytest tests/test_deploy_docs.py -q

echo
echo "Live API smoke (optional)"
if curl -sf "$API_URL/health" >/dev/null 2>&1; then
  check "GET /health" curl -sf "$API_URL/health" | grep -q '"status"'
  check "GET /dashboard" curl -sf -o /dev/null -w "" "$API_URL/dashboard"
else
  echo "  skip  API not running at $API_URL (start with: docker compose up -d)"
fi

echo
if [[ "$FAIL" -eq 0 ]]; then
  echo "audit passed"
  exit 0
fi

echo "audit failed" >&2
exit 1
