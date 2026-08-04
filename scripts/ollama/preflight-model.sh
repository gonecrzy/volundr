#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/_common.sh"

parse_common_args "$@"
if [[ -z "$MODEL_FILTER" ]]; then
  printf '%s\n' '--model NAME is required for preflight' >&2
  exit 2
fi

MODEL_ROOT="$OUTPUT_ROOT/preflight-$(slug_model "$MODEL_FILTER")"
mkdir -p "$MODEL_ROOT"
PROMPT='Generate a single compact CadQuery object from this geometry request. Return only the requested output. Request: a rectangular desktop organizer with a 220 mm by 140 mm by 65 mm envelope, 4 mm base, 3 mm walls, a 180 mm rear slot, three front compartments, and a 12 mm rear cable notch.'
run_generation() {
  local label="$1"
  local payload
  payload="$(json_record --arg model "$MODEL_FILTER" --arg prompt "$PROMPT" '{model:$model,prompt:$prompt,stream:true,keep_alive:"30m",options:{num_ctx:8192,temperature:0.2,top_p:0.9,top_k:40,num_predict:8192}}')"
  curl --fail --silent --show-error --no-buffer --connect-timeout 15 --max-time 1800 \
    "$SERVER_URL/api/generate" -H 'Content-Type: application/json' \
    --data "$payload" \
    > "$MODEL_ROOT/${label}.ndjson"
  curl --fail --silent --show-error --connect-timeout 15 --max-time 30 "$SERVER_URL/api/ps" > "$MODEL_ROOT/${label}-ps.json"
}

run_contract_probe() {
  local label="$1"
  local payload="$2"
  curl --fail --silent --show-error --no-buffer --connect-timeout 15 --max-time 1800 \
    "$SERVER_URL/api/generate" -H 'Content-Type: application/json' --data "$payload" \
    > "$MODEL_ROOT/${label}.ndjson"
  curl --fail --silent --show-error --connect-timeout 15 --max-time 30 "$SERVER_URL/api/ps" \
    > "$MODEL_ROOT/${label}-ps.json"
}

if [[ "$DRY_RUN" -eq 1 ]]; then
  dry_run_payload="$(json_record --arg model "$MODEL_FILTER" --arg prompt "$PROMPT" '{model:$model,context_length:8192,prompt:$prompt,dry_run:true}')"
  printf '%s\n' "$dry_run_payload" | tee "$MODEL_ROOT/preflight.json"
  exit 0
fi

run_generation cold
run_generation warm-1
run_generation warm-2
structured_payload="$(json_record --arg model "$MODEL_FILTER" '{model:$model,prompt:"Return exactly this object and no other text: status ok, items 1 2 3.",stream:true,format:{type:"object",properties:{status:{type:"string"},items:{type:"array",items:{type:"integer"}}},required:["status","items"],additionalProperties:false},keep_alive:"30m",options:{num_ctx:8192,temperature:0.2,num_predict:128}}')"
run_contract_probe structured-json "$structured_payload"
slot_payload="$(json_record --arg model "$MODEL_FILTER" '{model:$model,prompt:"You supply geometry statements for Volundr-owned CadQuery slots. Return JSON only with schema_version geometry-slots-v1 and exactly one slot: slot_id base, statements containing a CadQuery assignment only, result_symbol result. Do not include imports, functions, return statements, prose, files, network, or shell. The frozen desktop organizer has a 220 mm by 140 mm by 65 mm envelope, 4 mm base, 3 mm walls, 180 mm rear slot, three front compartments, and a 12 mm rear cable notch.",stream:true,format:{type:"object",properties:{schema_version:{type:"string"},slots:{type:"array"}},required:["schema_version","slots"],additionalProperties:false},keep_alive:"30m",options:{num_ctx:8192,temperature:0.2,num_predict:2048}}')"
run_contract_probe production-slot "$slot_payload"
native_payload="$(json_record --arg model "$MODEL_FILTER" '{model:$model,prompt:"Generate one self-contained CadQuery Python script for this frozen desktop organizer: 220 mm by 140 mm by 65 mm envelope, 4 mm base, 3 mm walls, 180 mm rear slot, three front compartments, 12 mm rear cable notch. Use import cadquery as cq, assign final printable result to result, no Markdown, files, network, subprocess, or unapproved packages.",stream:true,keep_alive:"30m",options:{num_ctx:8192,temperature:0.2,num_predict:4096}}')"
run_contract_probe native-cad "$native_payload"
jq -n --arg model "$MODEL_FILTER" --arg root "$MODEL_ROOT" \
  '{model:$model,context_length:8192,run_count:3,contract_probe_count:3,stream:true,evidence_root:$root,verification_status:"pending_readiness_evaluation"}' \
  | tee "$MODEL_ROOT/preflight.json"
