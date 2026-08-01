#!/usr/bin/env bash
set -euo pipefail

: "${VOLUNDR_LIVE_ENV_FILE:?VOLUNDR_LIVE_ENV_FILE is required}"
: "${VOLUNDR_LIVE_DATA_DIR:?VOLUNDR_LIVE_DATA_DIR is required}"
: "${VOLUNDR_LIVE_API_PORT:?VOLUNDR_LIVE_API_PORT is required}"

api_pid=""
cleanup() {
  local status=$?
  if [[ -n "$api_pid" ]] && kill -0 "$api_pid" 2>/dev/null; then
    kill -TERM -- "-$api_pid" 2>/dev/null || true
    kill -TERM "$api_pid" 2>/dev/null || true
    wait "$api_pid" 2>/dev/null || true
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../backend" && pwd)"
. "$VOLUNDR_LIVE_ENV_FILE"
export VOLUNDR_AI_PROVIDER=gemini_api
export VOLUNDR_DATA_DIR="$VOLUNDR_LIVE_DATA_DIR/data"
export VOLUNDR_CAD_WORKSPACE_DIR="$VOLUNDR_LIVE_DATA_DIR/data/jobs"
export PYTHONPATH=.
../backend/.venv/bin/alembic upgrade head

setsid env \
  VOLUNDR_AI_PROVIDER=gemini_api \
  VOLUNDR_DATA_DIR="$VOLUNDR_LIVE_DATA_DIR/data" \
  VOLUNDR_CAD_WORKSPACE_DIR="$VOLUNDR_LIVE_DATA_DIR/data/jobs" \
  PYTHONPATH=. \
  ../backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$VOLUNDR_LIVE_API_PORT" \
  >"$VOLUNDR_LIVE_DATA_DIR/api.log" 2>&1 &
api_pid=$!
wait "$api_pid"
