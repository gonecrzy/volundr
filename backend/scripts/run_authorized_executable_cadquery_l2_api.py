"""Run exactly one P3 L2 continuation through the corrected API transport.

The script performs no CLI/OAuth fallback and never changes credentials or
model selection.  If the frozen API credential slot is unavailable, it
persists a pre-request block instead of consuming a provider operation.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any, Mapping

from app.api.dependencies import build_executable_ai_provider
from app.core.config import settings
from app.services.ai.gemini_api import GeminiApiProvider
from app.services.ai.provider import ModelGenerationRequest
from app.services.cad.cadquery_runner import CadQueryCliRunner
from app.services.executable_cadquery.contract import parse_executable_cadquery_response


ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "docs/executable-cadquery-topology-replay-v2.json"
OUTPUT_PATH = ROOT / (
    "data/debug-sessions/executable-cadquery/topology-evidence-v2/"
    "p3-l2-repair-api-transport.json"
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"expected JSON object: {path}")
    return dict(value)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


async def _run(report: Mapping[str, Any]) -> dict[str, Any]:
    project = next(item for item in report["projects"] if item["project_id"] == "project-03")
    gate = project["repair_gate"]
    if gate != {
        "action": "one_l2_repair",
        "authorized": True,
        "priority": 1,
        "project_id": "project-03",
    }:
        raise ValueError(f"P3 L2 gate is not authorized: {gate}")
    contract_root = ROOT / "data/debug-sessions/executable-cadquery/recovery-wave-01/frozen-corpus/project-03"
    contract_file = _read_json(contract_root / "prompt-contract.json")
    source_path = ROOT / project["authority"]["source_path"]
    source = source_path.read_text(encoding="utf-8")
    contract = contract_file["contract"]
    request = ModelGenerationRequest(
        project_name=contract_file["title"],
        original_intent=contract_file["prompt"],
        user_instruction=contract_file["prompt"],
        current_source=source,
        executable_design_contract=contract,
        executable_repair_envelope=project["new_repair_envelope"],
    )
    provider = build_executable_ai_provider(settings)
    if not isinstance(provider, GeminiApiProvider) or provider.validated_transport is not True:
        raise RuntimeError("executable P3 repair did not resolve to validated Gemini API transport")
    record: dict[str, Any] = {
        "schema_version": "executable-cadquery-authorized-l2-api-result-v1",
        "project_id": "project-03",
        "provider_calls_before": 0,
        "provider_call_attempted": 0,
        "provider_transport": {
            "provider": provider.provider_id,
            "provider_class": type(provider).__name__,
            "validated_transport": provider.validated_transport,
            "auth_header": "x-goog-api-key",
            "endpoint": "/models/{model}:generateContent",
            "credential_slots": ["GEMINI_API_KEY", "GEMINI_API_KEY_2"],
            "provider_settings": provider.provider_settings(),
        },
        "gate": gate,
        "authority": project["authority"],
        "request_source_hash": _sha256_text(source),
        "request_envelope_schema": project["new_repair_envelope"]["schema_version"],
    }
    if not provider.primary_api_key:
        record["status"] = "blocked_before_request_missing_primary_credential"
        record["provider_call_attempted"] = 0
        record["worker_call_made"] = 0
        record["error"] = {
            "type": "MissingProviderCredential",
            "message": "primary Gemini credential is not configured; no API request attempted",
        }
        return record

    record["provider_call_attempted"] = 1
    try:
        generated = await provider.generate_cadquery_model(request)
        record["provider"] = {
            "provider": generated.provider,
            "provider_model": generated.provider_model,
            "provider_request_id": generated.provider_request_id,
            "usage_metadata": generated.usage_metadata,
            "routing_metadata": generated.routing_metadata,
            "provider_latency_ms": generated.provider_latency_ms,
        }
        raw_output = generated.raw_output
        record["raw_response_hash"] = _sha256_text(raw_output)
        parsed = parse_executable_cadquery_response(raw_output, contract)
        repaired_source = parsed.outputs[0].source
        record["parsed_source_hash"] = parsed.outputs[0].source_hash
        job = _read_json(ROOT / project["authority"]["job_path"])
        runner = CadQueryCliRunner(
            workspace_root=Path(tempfile.mkdtemp(prefix="authorized-p3-l2-api-")),
            timeout_seconds=int(job.get("execution_limits", {}).get("timeout_seconds") or 60),
        )
        worker = await runner.compile(
            repaired_source,
            job_id="project-03-authorized-l2-api",
            parameter_values=job.get("parameter_values") or {},
            requested_outputs=job.get("requested_outputs") or [],
        )
        record["worker_call_made"] = 1
        record["worker_result"] = {
            "success": worker.success,
            "error_message": worker.error_message,
            "source_hash": worker.source_hash,
            "outputs": [
                {
                    "output_id": output.output_id,
                    "success": output.success,
                    "compile_error": output.compile_error,
                    "topology_metadata": output.topology_metadata,
                }
                for output in worker.outputs
            ],
        }
        record["status"] = "response_and_worker_recorded"
    except Exception as exc:
        record["status"] = "provider_or_worker_failure"
        record["error"] = {"type": type(exc).__name__, "message": str(exc)}
        record.setdefault("worker_call_made", 0)
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    result = asyncio.run(_run(_read_json(args.report)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": _relative(args.output),
                "status": result["status"],
                "provider_transport": result["provider_transport"]["provider"],
                "provider_call_attempted": result["provider_call_attempted"],
                "worker_call_made": result.get("worker_call_made", 0),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
