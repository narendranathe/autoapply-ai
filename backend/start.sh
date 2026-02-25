#!/bin/sh
set -e

echo "[AutoApply] Running database migrations..."
python -m alembic upgrade head

echo "[AutoApply] Starting API server..."
exec uvicorn app.main:create_app \
    --factory \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers 1 \
    --log-level info
