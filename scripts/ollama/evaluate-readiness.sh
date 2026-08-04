#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/_common.sh"

parse_common_args "$@"
if [[ -z "$MODEL_FILTER" ]]; then
  printf '%s\n' '--model NAME is required for readiness evaluation' >&2
  exit 2
fi

MODEL_ROOT="$OUTPUT_ROOT/preflight-$(slug_model "$MODEL_FILTER")"
RESULT_PATH="$MODEL_ROOT/readiness.json"
if [[ "$DRY_RUN" -eq 1 ]]; then
  jq -n --arg model "$MODEL_FILTER" --arg root "$MODEL_ROOT" \
    '{model:$model,evidence_root:$root,dry_run:true,verification_status:"pending"}' | tee "$RESULT_PATH"
  exit 0
fi

python3 - "$MODEL_FILTER" "$MODEL_ROOT" "$RESULT_PATH" <<'PY'
import json
import sys
from pathlib import Path

model, root_value, result_value = sys.argv[1:]
root = Path(root_value)
result_path = Path(result_value)

def stream(path: Path) -> dict:
    rows = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                rows.append({"parse_error": True})
    text = "".join(str(row.get("response", "")) for row in rows if isinstance(row, dict))
    terminal = next((row for row in reversed(rows) if isinstance(row, dict) and row.get("done")), {})
    return {
        "rows": len(rows),
        "text": text,
        "completed": bool(terminal.get("done")) and not any(row.get("error") for row in rows if isinstance(row, dict)),
        "eval_count": terminal.get("eval_count", 0),
        "total_duration": terminal.get("total_duration"),
        "parse_errors": sum(1 for row in rows if row.get("parse_error")),
    }

sustained_runs = [stream(root / f"{label}.ndjson") for label in ("cold", "warm-1", "warm-2")]
sustained_pass = all(run["completed"] and run["eval_count"] > 0 and run["parse_errors"] == 0 for run in sustained_runs)
sustained_summary = [
    {key: run[key] for key in ("completed", "eval_count", "total_duration", "parse_errors", "rows")}
    for run in sustained_runs
]

structured = stream(root / "structured-json.ndjson")
try:
    structured_value = json.loads(structured["text"])
    structured_status = "native_schema_success" if isinstance(structured_value, dict) else "structured_output_invalid"
except json.JSONDecodeError:
    structured_status = "structured_output_invalid"

slot = stream(root / "production-slot.ndjson")
try:
    slot_value = json.loads(slot["text"])
    slot_status = "production_slot_compatible" if slot_value.get("schema_version") == "geometry-slots-v1" and isinstance(slot_value.get("slots"), list) else "production_slot_invalid"
except (json.JSONDecodeError, AttributeError):
    slot_status = "production_slot_invalid"

native = stream(root / "native-cad.ndjson")
native_text = native["text"].strip()
forbidden = ("subprocess", "os.system", "requests.", "httpx.", "open(", "socket.")
native_status = "native_cad_compatible" if (
    native["completed"] and "import cadquery as cq" in native_text and "result" in native_text
    and "```" not in native_text and not any(item in native_text for item in forbidden)
) else "native_cad_invalid"

status = "admitted" if sustained_pass and structured_status == "native_schema_success" else "rejected"
record = {
    "schema_version": "ollama-readiness-v1",
    "model": model,
    "verification_status": status,
    "sustained_generation": {"status": "pass" if sustained_pass else "fail", "runs": sustained_summary},
    "structured_output": {"status": structured_status},
    "production_slot": {"status": slot_status},
    "native_cad": {"status": native_status},
    "classification": (
        "production_compatible_pending_cad_quality" if slot_status == "production_slot_compatible" and status == "admitted"
        else "production_incompatible_response_contract" if status == "admitted"
        else "readiness_failed"
    ),
    "evidence_root": str(root),
    "raw_evidence_outside_git": True,
}
result_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(record, indent=2, sort_keys=True))
PY
