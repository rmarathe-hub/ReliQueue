#!/usr/bin/env sh
# Production entrypoint: migrate then serve API (Railway/Fly/Docker).
set -eu

PORT="${PORT:-8000}"

echo "running alembic migrations..."
alembic upgrade head

echo "starting api on port ${PORT}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"
