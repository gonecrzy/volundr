#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_root="${VOLUNDR_EXTERNAL_CAD_SURVEY_OUTPUT_ROOT:-$repo_root/data/debug-sessions/external-benchmarks/cad-50-v1.1/development-first-pass}"

if [[ "$(git -C "$repo_root" branch --show-current)" != "experiment/gemini-executable-cadquery-v1" ]]; then
  printf '%s\n' "External CAD survey must run on experiment/gemini-executable-cadquery-v1." >&2
  exit 2
fi
if [[ -n "${VOLUNDR_EXECUTABLE_CADQUERY_CORPUS_MANIFEST_PATH:-}" ]]; then
  printf '%s\n' "External CAD survey forbids corpus-manifest injection." >&2
  exit 2
fi
if [[ -d "$output_root" ]] && [[ -n "$(find "$output_root" -mindepth 1 -print -quit 2>/dev/null)" ]]; then
  printf '%s\n' "Survey output root is non-empty: $output_root" >&2
  exit 2
fi

read_gemini_credentials() {
  local process_fallback="${GEMINI_API_KEY_2:-}"
  local process_primary="${GEMINI_API_KEY:-}"
  if [[ -f "$repo_root/.env" ]]; then
    (
      cd "$repo_root"
      set -a
      . ./.env
      printf 'export VOLUNDR_GEMINI_PRIMARY_API_KEY=%q\n' "${GEMINI_API_KEY:-}"
      printf 'export VOLUNDR_GEMINI_FALLBACK_API_KEY=%q\n' "${GEMINI_API_KEY_2:-}"
    ) 2>/dev/null
    return
  fi
  printf 'export VOLUNDR_GEMINI_PRIMARY_API_KEY=%q\n' "$process_primary"
  printf 'export VOLUNDR_GEMINI_FALLBACK_API_KEY=%q\n' "$process_fallback"
}

gemini_credentials_file="$(mktemp)"
backend_env_file="$(mktemp)"
live_data_dir="$(mktemp -d /tmp/volundr-external-cad-survey.XXXXXX)"
chmod 600 "$gemini_credentials_file" "$backend_env_file"
cleanup() {
  local status=$?
  if [[ -n "${worker_pid:-}" ]]; then
    kill -TERM -- "-$worker_pid" 2>/dev/null || true
    kill -TERM "$worker_pid" 2>/dev/null || true
    sleep 0.2
    kill -KILL -- "-$worker_pid" 2>/dev/null || true
    kill -KILL "$worker_pid" 2>/dev/null || true
    wait "$worker_pid" 2>/dev/null || true
  fi
  rm -f "$gemini_credentials_file" "$backend_env_file"
  if [[ "${VOLUNDR_KEEP_EXTERNAL_CAD_SURVEY_DATA:-false}" != "true" ]]; then
    find "$live_data_dir" -depth -type f -delete 2>/dev/null || true
    find "$live_data_dir" -depth -type d -empty -delete 2>/dev/null || true
  else
    printf '%s\n' "External CAD survey runtime data preserved at $live_data_dir" >&2
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

read_gemini_credentials >"$gemini_credentials_file"
if ! ( . "$gemini_credentials_file"; [[ -n "${VOLUNDR_GEMINI_PRIMARY_API_KEY:-}" ]] ); then
  printf '%s\n' "External CAD survey requires a primary Gemini API credential." >&2
  exit 2
fi
cp "$gemini_credentials_file" "$backend_env_file"

(
  cd "$repo_root/backend"
  . "$backend_env_file"
  export VOLUNDR_AI_PROVIDER=gemini_api
  export VOLUNDR_DATA_DIR="$live_data_dir/data"
  export VOLUNDR_CAD_WORKSPACE_DIR="$live_data_dir/data/jobs"
  export VOLUNDR_EXECUTABLE_CADQUERY_FLOW_ENABLED=true
  export VOLUNDR_DEVELOPER_TOOLS_ENABLED=true
  export VOLUNDR_GEMINI_API_MAX_RETRIES=1
  unset VOLUNDR_EXECUTABLE_CADQUERY_CORPUS_MANIFEST_PATH
  export PYTHONPATH="$repo_root/backend"
  "$repo_root/backend/.venv/bin/alembic" upgrade head
)

(
  cd "$repo_root"
  exec setsid env \
    GEMINI_API_KEY= \
    GEMINI_API_KEY_2= \
    VOLUNDR_GEMINI_PRIMARY_API_KEY= \
    VOLUNDR_GEMINI_FALLBACK_API_KEY= \
    VOLUNDR_AI_PROVIDER=gemini_api \
    VOLUNDR_DATA_DIR="$live_data_dir/data" \
    VOLUNDR_CAD_WORKSPACE_DIR="$live_data_dir/data/jobs" \
    VOLUNDR_EXECUTABLE_CADQUERY_FLOW_ENABLED=true \
    VOLUNDR_DEVELOPER_TOOLS_ENABLED=true \
    PYTHONPATH="$repo_root/backend" \
    "$repo_root/backend/.venv/bin/python" -m app.workers.cad_worker \
    >"$live_data_dir/cad-worker.log" 2>&1
) &
worker_pid=$!

(
  cd "$repo_root"
  . "$backend_env_file"
  export VOLUNDR_AI_PROVIDER=gemini_api
  export VOLUNDR_DATA_DIR="$live_data_dir/data"
  export VOLUNDR_CAD_WORKSPACE_DIR="$live_data_dir/data/jobs"
  export VOLUNDR_EXECUTABLE_CADQUERY_FLOW_ENABLED=true
  export VOLUNDR_DEVELOPER_TOOLS_ENABLED=true
  export VOLUNDR_GEMINI_API_MAX_RETRIES=1
  unset VOLUNDR_EXECUTABLE_CADQUERY_CORPUS_MANIFEST_PATH
  export PYTHONPATH="$repo_root/backend"
  exec "$repo_root/backend/.venv/bin/python" \
    "$repo_root/backend/scripts/run_external_cad_development_survey.py" \
    --output-root "$output_root"
)
