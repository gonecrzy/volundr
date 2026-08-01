#!/usr/bin/env python3
"""Compare configured Gemini geometry models against frozen holder artifacts.

This diagnostic deliberately skips requirements and Design Plan provider calls.
It uses the exact structured geometry prompt contract and the real CadQuery
worker when a generated body passes the existing source gates.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import re
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from app.core.config import settings
from app.services.ai.gemini_api import GeminiApiProvider
from app.services.ai.model_policy import GeminiModelPolicy
from app.services.ai.provider import ModelGenerationRequest, ModelGenerationResult
from app.services.cad.cadquery_source_authority import (
    CadQuerySourceAuthorityError,
    authority_from_generation_context,
    validate_cadquery_source_authority,
)
from app.services.cad.geometry_bodies import GeometryBodyError, assemble_geometry_bodies, build_geometry_function_inventory
from app.services.cad.source_scaffold import SCAFFOLD_VERSION, render_cadquery_scaffold
from app.services.cad.worker_client import FilesystemCadWorkerRunner
from app.services.functional.intent import validate_functional_plan


REQUEST = (
    "Create a wall-mounted holder for an 81 mm bottle, suitable for a moving "
    "boat, with one-handed removal and two #8 mounting screws."
)


def frozen_request(report: dict[str, Any]) -> ModelGenerationRequest:
    requirements = report.get("requirements") or {}
    plan_record = report.get("design_plan") or {}
    design_specification = requirements.get("specification") or {}
    design_plan = plan_record.get("plan") or {}
    if not design_specification or not design_plan:
        raise ValueError("frozen report must contain requirements.specification and design_plan.plan")
    source_authority = authority_from_generation_context(
        design_plan_payload=design_plan,
        revision_plan_payload=None,
    )
    return ModelGenerationRequest(
        project_name="Frozen bottle-holder comparison",
        original_intent=str(report.get("request") or REQUEST),
        user_instruction=str(report.get("request") or REQUEST),
        design_specification=design_specification,
        design_plan=design_plan,
        source_authority=source_authority,
        generation_contract_version=SCAFFOLD_VERSION,
    )


def parameter_values(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        str(item["id"]): item.get("value")
        for item in plan.get("parameters", []) or []
        if isinstance(item, dict) and item.get("id") and "value" in item
    }


def requested_outputs(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in plan.get("printable_outputs", []) or []
        if isinstance(item, dict) and (item.get("id") or item.get("output_id"))
    ]


def _json_error(exc: Exception) -> dict[str, Any]:
    return {"type": type(exc).__name__, "message": str(exc)}


def _structured_payload(raw_output: str) -> dict[str, Any] | None:
    match = re.search(r"```(?:json)?\s*(.*?)```", raw_output, re.IGNORECASE | re.DOTALL)
    candidate = match.group(1).strip() if match else raw_output.strip()
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


async def run_geometry_attempt(
    *,
    provider: GeminiApiProvider,
    request: ModelGenerationRequest,
    plan: dict[str, Any],
    worker: FilesystemCadWorkerRunner | None,
    model_label: str,
    run_number: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    result: ModelGenerationResult | None = None
    record: dict[str, Any] = {
        "model_label": model_label,
        "run_number": run_number,
        "prompt_mode": "cadquery_geometry_bodies",
        "valid_structured_json": False,
        "required_function_completeness": False,
        "result_symbol_valid": False,
        "scaffold_assembly_success": False,
        "parameter_effect_compliance": False,
        "pattern_count_compliance": False,
        "repair_invocation": False,
        "repair_success": False,
        "worker_reached": False,
        "worker_execution_ms": None,
        "step_produced": False,
        "stl_produced": False,
        "brep_produced": False,
        "topology_result": None,
        "functional_mounting_hole_result": "not_run",
        "functional_floor_result": "not_run",
        "functional_removal_path_result": "not_run",
        "functional_retention_result": "not_run",
        "provider_latency_ms": None,
        "prompt_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "final_candidate_state": "blocked",
        "errors": [],
    }
    try:
        result = await provider.generate_cadquery_model(request)
        record["provider"] = result.provider
        record["selected_model"] = result.routing_metadata.get("selected_model")
        record["actual_model"] = result.routing_metadata.get("actual_model") or result.provider_model
        record["routing_metadata"] = result.routing_metadata
        record["provider_request_id"] = result.provider_request_id
        record["provider_latency_ms"] = result.provider_latency_ms
        usage = result.usage_metadata or {}
        record["prompt_tokens"] = usage.get("promptTokenCount", usage.get("prompt_tokens"))
        record["output_tokens"] = usage.get("candidatesTokenCount", usage.get("output_tokens"))
        record["total_tokens"] = usage.get("totalTokenCount", usage.get("total_tokens"))
        record["raw_output_sha256"] = hashlib.sha256(result.raw_output.encode("utf-8")).hexdigest()
        record["raw_output_bytes"] = len(result.raw_output.encode("utf-8"))

        inventory = build_geometry_function_inventory(plan)
        payload = _structured_payload(result.raw_output)
        if payload is not None:
            record["valid_structured_json"] = True
            records = payload.get("functions")
            if isinstance(records, list):
                expected = set(inventory.get("expected_function_ids", []))
                actual = {
                    item.get("function_id")
                    for item in records
                    if isinstance(item, dict) and item.get("function_id")
                }
                record["required_function_completeness"] = expected == actual
                record["result_symbol_valid"] = all(
                    isinstance(item.get("result_symbol"), str)
                    and bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", item["result_symbol"]))
                    for item in records
                    if isinstance(item, dict)
                )
        assembly = assemble_geometry_bodies(result.raw_output, inventory)
        record["parameter_effect_compliance"] = True
        record["pattern_count_compliance"] = True
        rendered = render_cadquery_scaffold(plan, assembly.functions)
        record["scaffold_assembly_success"] = True
        authority = request.source_authority
        validate_cadquery_source_authority(rendered.source, authority)
        if authority:
            functional_findings = validate_functional_plan(plan)
            record["functional_plan_validation"] = {
                "passed": not any(item.get("is_blocking") for item in functional_findings),
                "findings": functional_findings,
            }
        if worker is not None:
            record["worker_reached"] = True
            worker_started = time.perf_counter()
            worker_result = await worker.compile(
                rendered.source,
                f"geometry-comparison-{model_label}-{run_number}-{uuid4().hex}",
                parameter_values=parameter_values(plan),
                requested_outputs=requested_outputs(plan),
            )
            record["worker_execution_ms"] = round((time.perf_counter() - worker_started) * 1000, 2)
            record["worker_success"] = worker_result.success
            record["worker_error"] = worker_result.error_message
            record["step_produced"] = bool(worker_result.step_path)
            record["stl_produced"] = bool(worker_result.stl_path)
            record["brep_produced"] = any(output.brep_path for output in worker_result.outputs)
            record["topology_result"] = [output.topology_metadata for output in worker_result.outputs]
            if worker_result.success:
                record["final_candidate_state"] = "worker_reached_pending_full_workflow_verification"
    except (GeometryBodyError, CadQuerySourceAuthorityError, ValueError, RuntimeError) as exc:
        record["errors"].append(_json_error(exc))
        record["failure_stage"] = "geometry_source_or_worker"
        if isinstance(exc, GeometryBodyError) and "Pattern count" in str(exc):
            record["pattern_count_compliance"] = False
    finally:
        record["comparison_elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return record


async def compare(
    *,
    report: dict[str, Any],
    models: list[tuple[str, str]],
    runs_per_model: int,
    worker: FilesystemCadWorkerRunner | None,
    provider_factory: Callable[[str], GeminiApiProvider] | None = None,
) -> dict[str, Any]:
    request = frozen_request(report)
    plan = request.design_plan or {}
    attempts: list[dict[str, Any]] = []
    for label, model in models:
        provider = provider_factory(model) if provider_factory else GeminiApiProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            model_policy=GeminiModelPolicy(
                general_model=settings.gemini_model or model,
                geometry_model=model,
                geometry_repair_model=model,
            ),
        )
        for run_number in range(1, runs_per_model + 1):
            attempts.append(
                await run_geometry_attempt(
                    provider=provider,
                    request=request,
                    plan=plan,
                    worker=worker,
                    model_label=label,
                    run_number=run_number,
                )
            )
    return {
        "request": REQUEST,
        "frozen_source": "latest successful requirements and Design Plan live report",
        "frozen_report_keys": ["requirements", "design_plan"],
        "models": [{"label": label, "model": model} for label, model in models],
        "runs_per_model": runs_per_model,
        "prompt_drift": False,
        "upstream_provider_calls": 0,
        "attempts": attempts,
    }


def terminate_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen-report", type=Path, required=True)
    parser.add_argument("--fast-model", default=settings.gemini_model)
    parser.add_argument("--geometry-model", default=settings.gemini_geometry_model)
    parser.add_argument("--runs-per-model", type=int, default=2)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--with-worker", action="store_true")
    parser.add_argument("--keep-data", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.runs_per_model < 2:
        print("--runs-per-model must be at least 2", file=sys.stderr)
        return 2
    if not args.fast_model or not args.geometry_model:
        print("Both --fast-model and --geometry-model are required; no comparison was run.", file=sys.stderr)
        return 2
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("VOLUNDR_GEMINI_API_KEY") or settings.gemini_api_key):
        print("GEMINI_API_KEY or VOLUNDR_GEMINI_API_KEY is required; the key is never written to the report.", file=sys.stderr)
        return 2
    report = json.loads(args.frozen_report.read_text(encoding="utf-8"))
    backend_root = Path(__file__).resolve().parents[1]
    temporary = None if args.keep_data else tempfile.TemporaryDirectory(prefix="volundr-geometry-comparison-")
    root = Path(tempfile.mkdtemp(prefix="volundr-geometry-comparison-")) if args.keep_data else Path(temporary.name)
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(backend_root),
        "VOLUNDR_DATA_DIR": str(data_dir),
        "VOLUNDR_CAD_WORKSPACE_DIR": str(data_dir / "jobs"),
    })
    worker_process = None
    try:
        worker = None
        if args.with_worker:
            worker_log = (data_dir / "cad-worker.log").open("wb")
            worker_process = subprocess.Popen(
                [sys.executable, "-m", "app.workers.cad_worker"],
                cwd=backend_root,
                env=env,
                stdout=worker_log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            worker = FilesystemCadWorkerRunner(data_dir / "jobs")
        result = asyncio.run(
            compare(
                report=report,
                models=[("fast", args.fast_model), ("geometry", args.geometry_model)],
                runs_per_model=args.runs_per_model,
                worker=worker,
            )
        )
        args.report.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({"report": str(args.report), "attempts": len(result["attempts"])}))
        return 0
    finally:
        terminate_process(worker_process)
        if temporary is not None:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
