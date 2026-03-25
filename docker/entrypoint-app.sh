#!/bin/bash
set -e

echo "Running Alembic migrations..."
cd /odit
alembic upgrade head

echo "Starting Odit app server..."
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${APP_PORT:-8000}" \
    --workers 2 \
    --log-level "$(echo ${LOG_LEVEL:-info} | tr '[:upper:]' '[:lower:]')"
