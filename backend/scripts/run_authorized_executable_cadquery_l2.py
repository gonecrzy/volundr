"""Run the single post-evidence P3 L2 repair authorized by the v2 report."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any

from app.core.config import settings
from app.services.ai.gemini_cli import GeminiCliProvider
from app.services.ai.provider import ModelGenerationRequest
from app.services.cad.cadquery_runner import CadQueryCliRunner
from app.services.executable_cadquery.contract import parse_executable_cadquery_response


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = REPOSITORY_ROOT / "docs/executable-cadquery-topology-replay-v2.json"
OUTPUT_PATH = REPOSITORY_ROOT / (
    "data/debug-sessions/executable-cadquery/topology-evidence-v2/p3-l2-repair.json"
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _relative(path: Path) -> str:
    return str(path.relative_to(REPOSITORY_ROOT))


async def _run(report: dict[str, Any]) -> dict[str, Any]:
    project = next(item for item in report["projects"] if item["project_id"] == "project-03")
    gate = project["repair_gate"]
    if report.get("provider_calls") != 0:
        raise ValueError("the offline topology checkpoint already has provider calls")
    if gate != {
        "action": "one_l2_repair",
        "authorized": True,
        "priority": 1,
        "project_id": "project-03",
    }:
        raise ValueError(f"P3 L2 gate is not authorized: {gate}")
    if OUTPUT_PATH.exists():
        raise ValueError(f"authorized P3 L2 result already exists: {OUTPUT_PATH}")

    contract_path = REPOSITORY_ROOT / (
        "data/debug-sessions/executable-cadquery/recovery-wave-01/"
        "frozen-corpus/project-03/prompt-contract.json"
    )
    source_path = REPOSITORY_ROOT / project["authority"]["source_path"]
    contract_file = _read_json(contract_path)
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
    provider = GeminiCliProvider(
        binary=settings.gemini_binary,
        model=settings.gemini_model,
        timeout_seconds=settings.gemini_timeout_seconds,
        policy_path=settings.gemini_policy_path,
    )

    record: dict[str, Any] = {
        "schema_version": "executable-cadquery-authorized-l2-result-v1",
        "project_id": "project-03",
        "provider_calls_before": 0,
        "provider_call_attempted": 1,
        "gate": gate,
        "authority": project["authority"],
        "prompt_template_version": provider.prompt_template_version_for(request),
        "provider_settings": provider.provider_settings(),
        "request_source_hash": _sha256_text(source),
        "request_envelope_schema": project["new_repair_envelope"]["schema_version"],
    }
    try:
        generated = await provider.generate_cadquery_model(request)
        raw_output = generated.raw_output
        record["provider"] = {
            "provider": generated.provider,
            "provider_model": generated.provider_model,
            "provider_request_id": generated.provider_request_id,
            "usage_metadata": generated.usage_metadata,
            "routing_metadata": generated.routing_metadata,
            "provider_latency_ms": generated.provider_latency_ms,
            "logical_provider_calls": int(
                generated.routing_metadata.get("provider_call_count", 1)
            ),
        }
        record["raw_response_hash"] = _sha256_text(raw_output)
        record["raw_response"] = raw_output
        parsed = parse_executable_cadquery_response(raw_output, contract)
        repaired_source = parsed.outputs[0].source
        record["parsed_source_hash"] = parsed.outputs[0].source_hash
        job = _read_json(
            REPOSITORY_ROOT / project["authority"]["job_path"]
        )
        runner = CadQueryCliRunner(
            workspace_root=Path(tempfile.mkdtemp(prefix="authorized-p3-l2-")),
            timeout_seconds=int(job.get("execution_limits", {}).get("timeout_seconds") or 60),
        )
        worker = await runner.compile(
            repaired_source,
            job_id="project-03-authorized-l2",
            parameter_values=job.get("parameter_values") or {},
            requested_outputs=job.get("requested_outputs") or [],
        )
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
    except Exception as exc:  # Persist the exact bounded repair outcome.
        record["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    report = _read_json(args.report)
    result = asyncio.run(_run(report))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": _relative(args.output),
                "project_id": result["project_id"],
                "provider_calls_before": result["provider_calls_before"],
                "provider_calls_attempted": result["provider_call_attempted"],
                "provider_calls_made": result.get("provider", {}).get(
                    "logical_provider_calls", result["provider_call_attempted"]
                ),
                "worker_success": result.get("worker_result", {}).get("success"),
                "error": result.get("error"),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
