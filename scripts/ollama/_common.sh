#!/usr/bin/env bash
set -euo pipefail

SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_ROOT/../.." && pwd)"
MANIFEST_PATH="${OLLAMA_MODEL_MANIFEST:-$REPO_ROOT/benchmarks/ollama-models-v1.yaml}"
SERVER_URL="${VOLUNDR_OLLAMA_BENCHMARK_BASE_URL:-http://10.1.20.25:11434}"
OUTPUT_ROOT="${VOLUNDR_OLLAMA_EVIDENCE_ROOT:-$REPO_ROOT/data/debug-sessions/ollama-only/setup}"
MODEL_FILTER=""
ALL_MODELS=0
RESUME=0
DRY_RUN=0

parse_common_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --server) SERVER_URL="$2"; shift 2 ;;
      --model) MODEL_FILTER="$2"; shift 2 ;;
      --all) ALL_MODELS=1; shift ;;
      --resume) RESUME=1; shift ;;
      --dry-run) DRY_RUN=1; shift ;;
      --output) OUTPUT_ROOT="$2"; shift 2 ;;
      --help)
        printf '%s\n' 'Options: --server URL --model NAME --all --resume --dry-run --output PATH'
        exit 0
        ;;
      *) printf 'unknown option: %s\n' "$1" >&2; exit 2 ;;
    esac
  done
  mkdir -p "$OUTPUT_ROOT"
}

slug_model() {
  printf '%s' "$1" | tr '/:' '__' | tr -c 'A-Za-z0-9_.-' '_'
}

manifest_models() {
  jq -r --arg model "$MODEL_FILTER" --argjson all "$ALL_MODELS" '
    .models[]
    | select(.installation_status != "excluded")
    | select(($all == 1) or ($model != "" and .ollama_name == $model))
    | .ollama_name
  ' "$MANIFEST_PATH"
}

require_manifest() {
  [[ -f "$MANIFEST_PATH" ]] || { printf 'manifest not found: %s\n' "$MANIFEST_PATH" >&2; exit 1; }
  jq empty "$MANIFEST_PATH"
}

json_record() {
  jq -cn "$@"
}
