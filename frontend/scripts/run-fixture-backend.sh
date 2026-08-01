#!/usr/bin/env bash
set -euo pipefail

fixture_root="${VOLUNDR_E2E_DATA_DIR:-$(mktemp -d /tmp/volundr-playwright-fixture.XXXXXX)}"
owns_fixture_root="${VOLUNDR_E2E_DATA_DIR:+false}"
backend_pid=""

cleanup() {
  local status=$?
  if [[ -n "$backend_pid" ]] && kill -0 "$backend_pid" 2>/dev/null; then
    kill -TERM -- "-$backend_pid" 2>/dev/null || true
    kill -TERM "$backend_pid" 2>/dev/null || true
    wait "$backend_pid" 2>/dev/null || true
  fi
  if [[ "$owns_fixture_root" == "" ]]; then
    find "$fixture_root" -depth -type f -delete 2>/dev/null || true
    find "$fixture_root" -depth -type d -empty -delete 2>/dev/null || true
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM

setsid env \
  PYTHONPATH=../backend \
  VOLUNDR_E2E_DATA_DIR="$fixture_root" \
  VOLUNDR_E2E_PORT="${VOLUNDR_E2E_PORT:?VOLUNDR_E2E_PORT is required}" \
  ../backend/.venv/bin/python -m app.testing.e2e_fixture_server &
backend_pid=$!
wait "$backend_pid"
