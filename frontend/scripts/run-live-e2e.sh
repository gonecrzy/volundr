#!/usr/bin/env bash
set -euo pipefail

if [[ "${VOLUNDR_RUN_LIVE_E2E:-}" != "true" ]]; then
  printf '%s\n' "Live Gemini E2E is opt-in. Set VOLUNDR_RUN_LIVE_E2E=true." >&2
  exit 2
fi

frontend_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo_root="$(cd "$frontend_root/.." && pwd)"

read_gemini_key() {
  if [[ -n "${GEMINI_API_KEY:-}" ]]; then
    printf '%s' "$GEMINI_API_KEY"
    return
  fi
  if [[ -f "$repo_root/.env" ]]; then
    (
      cd "$repo_root"
      set -a
      # The repository .env is controlled configuration, not arbitrary input.
      # Keep the value in this wrapper only long enough to create the backend-only env file.
      . ./.env
      printf '%s' "${GEMINI_API_KEY:-}"
    ) 2>/dev/null
  fi
}

gemini_key="$(read_gemini_key)"
if [[ -z "$gemini_key" ]]; then
  printf '%s\n' "Live Gemini E2E requires GEMINI_API_KEY in the environment or repository .env." >&2
  exit 2
fi

live_data_dir="$(mktemp -d /tmp/volundr-live-e2e.XXXXXX)"
backend_env_file="$(mktemp /tmp/volundr-live-backend-env.XXXXXX)"
chmod 600 "$backend_env_file"
printf 'export GEMINI_API_KEY=%q\n' "$gemini_key" > "$backend_env_file"

worker_pid=""
cleanup() {
  local test_status=$?
  if [[ -n "$worker_pid" ]]; then
    kill "$worker_pid" 2>/dev/null || true
    wait "$worker_pid" 2>/dev/null || true
  fi

  # Do not print matching lines: the key must never appear in test output.
  if rg -a -F -- "$gemini_key" "$live_data_dir" "$frontend_root/test-results" >/dev/null 2>&1; then
    printf '%s\n' "Live E2E secret scan failed: the Gemini API key was found in generated evidence." >&2
    test_status=1
  fi

  rm -f "$backend_env_file"
  if [[ "${VOLUNDR_KEEP_LIVE_DATA:-}" == "true" ]]; then
    printf '%s\n' "Live E2E data preserved at $live_data_dir" >&2
  else
    rm -rf "$live_data_dir"
  fi
  exit "$test_status"
}
trap cleanup EXIT

(
  cd "$repo_root"
  exec env \
    GEMINI_API_KEY= \
    VOLUNDR_GEMINI_API_KEY= \
    VOLUNDR_AI_PROVIDER=gemini_api \
    VOLUNDR_DATA_DIR="$live_data_dir/data" \
    VOLUNDR_CAD_WORKSPACE_DIR="$live_data_dir/data/jobs" \
    PYTHONPATH="$repo_root/backend" \
    "$repo_root/backend/.venv/bin/python" -m app.workers.cad_worker
) >"$live_data_dir/cad-worker.log" 2>&1 &
worker_pid=$!

cd "$frontend_root"
unset GEMINI_API_KEY VOLUNDR_GEMINI_API_KEY
export VOLUNDR_LIVE_ENV_FILE="$backend_env_file"
export VOLUNDR_LIVE_DATA_DIR="$live_data_dir"

test_status=0
npx playwright test --config=playwright.live.config.ts "$@" || test_status=$?
exit "$test_status"
