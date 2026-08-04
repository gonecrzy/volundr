#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/_common.sh"

parse_common_args "$@"
require_manifest
if [[ -z "$MODEL_FILTER" ]]; then
  printf '%s\n' '--model NAME is required for verification' >&2
  exit 2
fi

RESULTS="$OUTPUT_ROOT/verification-$(slug_model "$MODEL_FILTER").json"
if [[ "$DRY_RUN" -eq 1 ]]; then
  json_record --arg model "$MODEL_FILTER" '{model:$model,verification_status:"pending",dry_run:true}' | tee "$RESULTS"
  exit 0
fi
version="$(curl --fail --silent --show-error --connect-timeout 15 --max-time 30 "$SERVER_URL/api/version")"
tags="$(curl --fail --silent --show-error --connect-timeout 15 --max-time 60 "$SERVER_URL/api/tags")"
installed="$(jq -c --arg model "$MODEL_FILTER" '[.models[]? | select(.name == $model)][0] // null' <<<"$tags")"
if [[ "$installed" == "null" ]]; then
  json_record --arg model "$MODEL_FILTER" --arg version "$version" '{model:$model,ollama_version:$version,verification_status:"rejected",failure_class:"ollama_model_not_installed"}' > "$RESULTS"
  cat "$RESULTS"
  exit 1
fi

show_payload="$(json_record --arg model "$MODEL_FILTER" '{name:$model}')"
show="$(curl --fail --silent --show-error --connect-timeout 15 --max-time 60 "$SERVER_URL/api/show" \
  -H 'Content-Type: application/json' --data "$show_payload")"
ps="$(curl --fail --silent --show-error --connect-timeout 15 --max-time 30 "$SERVER_URL/api/ps")"
warmup_path="$OUTPUT_ROOT/verification-$(slug_model "$MODEL_FILTER")-warmup.ndjson"
warmup_payload="$(json_record --arg model "$MODEL_FILTER" '{model:$model,prompt:"Return only the word ready.",stream:true,keep_alive:"30m",options:{num_ctx:8192,temperature:0.2,top_p:0.9,top_k:40,num_predict:32}}')"
curl --fail --silent --show-error --no-buffer --connect-timeout 15 --max-time 1800 "$SERVER_URL/api/generate" \
  -H 'Content-Type: application/json' --data "$warmup_payload" > "$warmup_path"

jq -n \
  --arg version "$version" \
  --arg model "$MODEL_FILTER" \
  --argjson installed "$installed" \
  --argjson show "$show" \
  --argjson ps "$ps" \
  --slurpfile warmup "$warmup_path" \
  --arg warmup_path "$warmup_path" \
  'def redact_paths:
     walk(if type == "string" then
       gsub("(/[Uu]sers/[^\\n]*|/[Hh]ome/[^\\n]*|/[Rr]oot/[^\\n]*|[A-Za-z]:\\\\[^\\n]*)"; "<redacted-path>")
     else . end);
   {ollama_version:$version,model:$model,installed:$installed,show:$show,running_models:$ps.models,load_test:$warmup,load_test_path:$warmup_path,verification_status:"identity_verified"} | redact_paths' > "$RESULTS"
cat "$RESULTS"
