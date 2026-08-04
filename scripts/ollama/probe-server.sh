#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/_common.sh"

parse_common_args "$@"
MODEL_FILTER="${MODEL_FILTER:-joshuaokolo/C3Dv0:latest}"
PROBE_ROOT="$OUTPUT_ROOT/server-probe"
mkdir -p "$PROBE_ROOT"

timed_request() {
  local method="$1" path="$2" output="$3" payload="${4:-}"
  local timing
  if [[ "$method" == "GET" ]]; then
    timing="$(curl --fail --silent --show-error --connect-timeout 15 --max-time 120 -o "$output" -w '%{http_code} %{time_total}' "$SERVER_URL$path")"
  else
    timing="$(curl --fail --silent --show-error --connect-timeout 15 --max-time 1800 -o "$output" -w '%{http_code} %{time_total}' \
      -H 'Content-Type: application/json' --data "$payload" "$SERVER_URL$path")"
  fi
  json_record --arg method "$method" --arg path "$path" --arg result "$timing" '{method:$method,path:$path,http_and_seconds:$result}'
}

if [[ "$DRY_RUN" -eq 1 ]]; then
  json_record --arg server "$SERVER_URL" --arg model "$MODEL_FILTER" '{server:$server,model:$model,dry_run:true,host_access:false,disk_information:"unavailable_without_remote_host_access"}' | tee "$PROBE_ROOT/probe.json"
  exit 0
fi

version_meta="$(timed_request GET /api/version "$PROBE_ROOT/version.json")"
tags_meta="$(timed_request GET /api/tags "$PROBE_ROOT/tags.json")"
ps_meta="$(timed_request GET /api/ps "$PROBE_ROOT/ps.json")"
show_payload="$(json_record --arg model "$MODEL_FILTER" '{name:$model}')"
show_meta="$(timed_request POST /api/show "$PROBE_ROOT/show.json" "$show_payload")"
# `/api/show` may echo the host-side Modelfile source path. Keep only a
# redacted copy in durable evidence.
show_redacted="$PROBE_ROOT/show-redacted.json"
jq 'walk(if type == "string" then gsub("(/[Uu]sers/[^\\n]*|/[Hh]ome/[^\\n]*|/[Rr]oot/[^\\n]*|[A-Za-z]:\\\\[^\\n]*)"; "<redacted-path>") else . end)' "$PROBE_ROOT/show.json" > "$show_redacted"
mv "$show_redacted" "$PROBE_ROOT/show.json"
generate_payload="$(json_record --arg model "$MODEL_FILTER" '{model:$model,prompt:"Return only the word ready.",stream:true,keep_alive:"30m",options:{num_ctx:8192,num_predict:16,temperature:0.2}}')"
generate_meta="$(timed_request POST /api/generate "$PROBE_ROOT/generate.ndjson" "$generate_payload")"
chat_payload="$(json_record --arg model "$MODEL_FILTER" '{model:$model,messages:[{role:"user",content:"Return only the word ready."}],stream:true,keep_alive:"30m",options:{num_ctx:8192,num_predict:16,temperature:0.2}}')"
chat_meta="$(timed_request POST /api/chat "$PROBE_ROOT/chat.ndjson" "$chat_payload")"
pull_payload="$(json_record --arg model "$MODEL_FILTER" '{name:$model,stream:true}')"
pull_meta="$(timed_request POST /api/pull "$PROBE_ROOT/pull.ndjson" "$pull_payload")"
proxy_headers="$(curl --silent --show-error --connect-timeout 15 --max-time 30 -D - -o /dev/null "$SERVER_URL/api/version" | tr -d '\r' | grep -iE '^(via|forwarded|x-forwarded-|server):' || true)"

jq -n \
  --arg server "$SERVER_URL" \
  --arg model "$MODEL_FILTER" \
  --argjson version "$version_meta" \
  --argjson tags "$tags_meta" \
  --argjson ps "$ps_meta" \
  --argjson show "$show_meta" \
  --argjson generate "$generate_meta" \
  --argjson chat "$chat_meta" \
  --argjson pull "$pull_meta" \
  --arg proxy_headers "$proxy_headers" \
  '{server:$server,model:$model,version:$version,tags:$tags,ps:$ps,show:$show,generate:$generate,chat:$chat,pull:$pull,proxy_headers:$proxy_headers,proxy_detected:($proxy_headers != ""),host_access:false,disk_information:"unavailable_without_remote_host_access"}' \
  | tee "$PROBE_ROOT/probe.json"
