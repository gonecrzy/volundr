#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/_common.sh"

parse_common_args "$@"
if [[ -z "$MODEL_FILTER" ]]; then
  printf '%s\n' '--model NAME is required to unload' >&2
  exit 2
fi

curl --fail --silent --show-error --connect-timeout 15 --max-time 120 \
  "$SERVER_URL/api/generate" -H 'Content-Type: application/json' \
  --data "$(json_record --arg model "$MODEL_FILTER" '{model:$model,prompt:"",stream:false,keep_alive:0}')"
