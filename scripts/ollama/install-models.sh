#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/_common.sh"

parse_common_args "$@"
require_manifest

if [[ "$ALL_MODELS" -eq 0 && -z "$MODEL_FILTER" ]]; then
  printf '%s\n' 'select --model NAME or --all' >&2
  exit 2
fi

RESULTS="$OUTPUT_ROOT/installation-results.ndjson"
: > "$RESULTS"
while IFS= read -r model; do
  [[ -n "$model" ]] || continue
  slug="$(slug_model "$model")"
  pull_log="$OUTPUT_ROOT/pull-${slug}.ndjson"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    json_record --arg model "$model" --arg status "pending" '{model:$model,installation_status:$status,action:"pull",dry_run:true}' >> "$RESULTS"
    continue
  fi
  if [[ "$RESUME" -eq 1 && -s "$pull_log" ]]; then
    json_record --arg model "$model" --arg status "resumed_existing" '{model:$model,status:$status,log_path:"'"$pull_log"'"}' >> "$RESULTS"
    continue
  fi
  payload="$(json_record --arg model "$model" '{name:$model,stream:true}')"
  set +e
  curl --fail --silent --show-error --no-buffer --connect-timeout 15 --max-time 7200 \
    "$SERVER_URL/api/pull" -H 'Content-Type: application/json' --data "$payload" > "$pull_log"
  rc=$?
  set -e
  if [[ "$rc" -eq 0 ]]; then
    final_status="$(jq -r 'select(.status == "success") | .status' "$pull_log" | tail -1 || true)"
    [[ "$final_status" == "success" ]] || final_status="completed_without_success_marker"
    json_record --arg model "$model" --arg status "$final_status" --arg path "$pull_log" '{model:$model,status:$status,log_path:$path}' >> "$RESULTS"
  else
    json_record --arg model "$model" --arg status "failed" --arg path "$pull_log" --argjson code "$rc" '{model:$model,status:$status,exit_code:$code,log_path:$path}' >> "$RESULTS"
  fi
done < <(manifest_models)

printf '%s\n' "installation results: $RESULTS"
