"""Execute exactly one authorized P5 L1 repair on the live persisted source.

The runner uses the same Settings -> build_executable_ai_provider ->
GeminiApiProvider -> validated REST path as ordinary executable-CADQuery
generation.  It has no CLI/OAuth fallback and no alternate-model path.
"""

from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from app.api.dependencies import build_executable_ai_provider
from app.core.config import settings
from app.services.ai.gemini_api import GeminiApiProvider
from app.services.ai.provider import ModelGenerationRequest
from app.services.cad.cadquery_runner import CadQueryCliRunner
from app.services.executable_cadquery.contract import parse_executable_cadquery_response
from app.services.executable_cadquery.repair import (
    classify_executable_failure,
    compare_executable_progress,
    decide_executable_repair,
)
from app.services.executable_cadquery.semantic import evaluate_executable_cadquery_semantics_for_outputs
from app.services.executable_cadquery.semantic_policy import derive_candidate_policy, evaluate_semantic_policy
from app.services.executable_cadquery.package_review import build_neutral_measurement_report
from app.services.executable_cadquery.review import build_blind_review_packet, build_blind_review_record
from app.services.geometry.snapshots import SnapshotRenderSettings, render_stl_view
from PIL import Image

from scripts.prepare_authorized_executable_cadquery_p5_l1 import (  # noqa: E402
    ENVELOPE_PATH,
    FROZEN_ROOT,
    GATE_PATH,
    JOB_ROOT,
    PROJECT_ROOT,
    REVISION_ID,
    SOURCE_HASH,
    _read_json,
    _sha256_file,
    _sha256_json,
)
from scripts.run_authorized_executable_cadquery_l3 import (  # noqa: E402
    _copy_worker_artifacts,
    _package,
    _provider_preflight,
    _render_outputs,
    _relative,
    _validate_package,
    _worker_record,
    _write_json,
)
from scripts.reconcile_executable_cadquery_phase0 import _blind_reviewer_result  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "docs/executable-cadquery-topology-replay-v2.json"
MATRIX_PATH = ROOT / "docs/executable-cadquery-phase0-authoritative-matrix.json"
RESULT_ROOT = ROOT / (
    "data/debug-sessions/executable-cadquery/recovery-wave-01/"
    "authorized-l1-results/project-05"
)
RESULT_PATH = RESULT_ROOT / "result.json"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _verify_gate() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    gate = _read_json(GATE_PATH)
    envelope_record = _read_json(ENVELOPE_PATH)
    frozen = _read_json(FROZEN_ROOT / "prompt-contract.json")
    job = _read_json(JOB_ROOT / "job.json")
    source = (PROJECT_ROOT / "source.py").read_text(encoding="utf-8")
    checks = gate.get("authority_verification") or {}
    expected_envelope_hash = str(gate.get("repair_envelope", {}).get("sha256"))
    verify = {
        "gate_status_authorized": gate.get("status") in {"authorized_for_one_bounded_l1", "completed_one_bounded_l1"},
        "gate_checks_all_true": bool(checks) and all(checks.values()),
        "source_hash_matches_gate": _sha256_text(source) == SOURCE_HASH == gate.get("authoritative_source", {}).get("source_hash"),
        "source_hash_matches_job": job.get("source_hash") == SOURCE_HASH,
        "source_path_matches_gate": gate.get("authoritative_source", {}).get("persisted_source_path") == _relative(PROJECT_ROOT / "source.py"),
        "envelope_hash_matches_gate": _sha256_json(envelope_record.get("envelope")) == expected_envelope_hash,
        "envelope_record_hash_matches_gate": envelope_record.get("envelope_sha256") == expected_envelope_hash,
        "envelope_is_l1": envelope_record.get("envelope", {}).get("repair_level") == "L1",
        "envelope_source_hash_matches": envelope_record.get("envelope", {}).get("previous_source_hash") == SOURCE_HASH,
        "contract_prompt_hash_matches": frozen.get("prompt_sha256") == gate.get("contract", {}).get("prompt_sha256"),
        "contract_hash_matches": frozen.get("contract_sha256") == gate.get("contract", {}).get("contract_sha256"),
        "transport_proof_required": gate.get("dispatch_gate", {}).get("provider_transport_required") == "gemini_api_rest",
    }
    if not all(verify.values()):
        raise RuntimeError(f"P5 pre-dispatch verification failed: {verify}")
    return gate, envelope_record, frozen, job


def _provider_record(provider: GeminiApiProvider, generated: Any, attempts: list[dict[str, Any]]) -> dict[str, Any]:
    routing = dict(generated.routing_metadata or {})
    return {
        "provider": generated.provider,
        "provider_class": type(provider).__name__,
        "transport": "gemini_api_rest",
        "validated_transport": provider.validated_transport is True,
        "auth_header": "x-goog-api-key",
        "provider_model": generated.provider_model,
        "provider_request_id": generated.provider_request_id,
        "usage_metadata": generated.usage_metadata,
        "routing_metadata": routing,
        "provider_latency_ms": generated.provider_latency_ms,
        "provider_call_count": len(attempts) or int(routing.get("provider_call_count") or 1),
        "provider_retry_count": max(0, len(attempts) - 1) if attempts else int(routing.get("provider_retry_count") or 0),
        "attempts": attempts,
        "fallback_used": any(item.get("credential_slot") == "fallback" for item in attempts),
        "fallback_policy": "fallback_only_after_http_429",
        "raw_response_hash": _sha256_text(generated.raw_output),
    }


def _diagnostic_signature(diagnostic: Mapping[str, Any]) -> str:
    value = {
        "active_phase": diagnostic.get("active_phase"),
        "failure_phase": diagnostic.get("failure_phase"),
        "failure_source_function": diagnostic.get("failure_source_function"),
        "failure_source_line": diagnostic.get("failure_source_line"),
        "failure_operation": diagnostic.get("failure_operation"),
        "failure_exception_type": diagnostic.get("failure_exception_type"),
        "failure_message": diagnostic.get("failure_message"),
    }
    return _sha256_json(value)


def _progress_record(worker: Any, outputs: list[Mapping[str, Any]]) -> dict[str, Any]:
    diagnostic = worker.execution_diagnostics if isinstance(worker.execution_diagnostics, Mapping) else {}
    phase = str(diagnostic.get("active_phase") or diagnostic.get("failure_phase") or "")
    phase_index = {"build_function": 1, "topology_analysis": 2, "artifact_export": 3}.get(phase, 0)
    completed = [str(item["output_id"]) for item in outputs if item.get("success") is True]
    error_signature = ":".join(
        str(diagnostic.get(key) or "")
        for key in ("failure_exception_type", "failure_operation", "failure_message")
    )
    return {
        "phase_index": phase_index,
        "completed_output_ids": completed,
        "diagnostic_signature": _diagnostic_signature(diagnostic),
        "error_signature": error_signature,
        "failure_signature": error_signature,
    }


def _previous_progress(gate: Mapping[str, Any]) -> dict[str, Any]:
    diagnostic = gate.get("execution_diagnostic") or {}
    error_signature = ":".join(
        str(diagnostic.get(key) or "")
        for key in ("failure_exception_type", "failure_operation", "failure_message")
    )
    return {
        "phase_index": 1,
        "completed_output_ids": [],
        "diagnostic_signature": _diagnostic_signature(diagnostic),
        "error_signature": error_signature,
        "failure_signature": error_signature,
    }


def _artifact_records(outputs: list[Mapping[str, Any]], worker: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for record in outputs:
        topology = record.get("topology_metadata") or {}
        paths = record.get("artifact_paths") or {}
        records.append(
            {
                "output_id": record["output_id"],
                "required": record.get("required", True),
                "state": "ready" if record.get("success") else "failed",
                "worker_status": "completed" if record.get("success") else "failed",
                "topology_status": "valid" if topology.get("valid") is True else "invalid",
                "expected_solid_count": topology.get("expected_solid_count"),
                "detected_solid_count": topology.get("detected_solid_count"),
                "artifact_available": all(kind in paths for kind in ("stl", "step", "brep")),
                "artifact_integrity": all(
                    record.get("artifact_hashes", {}).get(kind)
                    and (not record.get(f"{kind}_hash") or record.get("artifact_hashes", {}).get(kind) == record.get(f"{kind}_hash"))
                    for kind in ("stl", "step", "brep")
                ),
                "artifact_paths": {kind: paths.get(kind) for kind in ("stl", "step", "brep") if paths.get(kind)},
                "hashes": {kind: record.get("artifact_hashes", {}).get(kind) for kind in ("stl", "step", "brep")},
                "authoritative_worker_output": {
                    "job_id": worker.job_id,
                    "source_hash": worker.source_hash,
                    "stl_hash": record.get("stl_hash"),
                    "step_hash": record.get("step_hash"),
                    "brep_hash": record.get("brep_hash"),
                },
            }
        )
    return records


def _downstream(
    *,
    frozen: Mapping[str, Any],
    contract: Mapping[str, Any],
    identity: Mapping[str, Any],
    source_path: Path,
    worker_result_path: Path,
    repaired_source_hash: str,
    worker: Any,
    output_records: list[Mapping[str, Any]],
    provider_record: Mapping[str, Any],
    result_root: Path,
) -> dict[str, Any]:
    stl_paths = {
        str(record["output_id"]): ROOT / str((record.get("artifact_paths") or {}).get("stl"))
        for record in output_records
        if (record.get("artifact_paths") or {}).get("stl")
    }
    semantic_raw = evaluate_executable_cadquery_semantics_for_outputs(
        stl_paths=stl_paths,
        design_contract=contract,
    )
    semantic = evaluate_semantic_policy(semantic_raw, contract)
    copied_source_path = result_root / "source" / "source.py"
    copied_worker_result_path = result_root / "worker" / "result.json"
    package_path = result_root / "package.zip"
    provider_provenance = {
        "provider_id": provider_record.get("provider"),
        "provider_transport": "gemini_api_rest",
        "validated_transport": True,
        "contract_version": contract.get("schema_version"),
        "accepted_revision_id": identity["revision_id"],
        "source_hash": repaired_source_hash,
        "output_ids": [str(item["output_id"]) for item in output_records],
        "provider_call_count": provider_record.get("provider_call_count"),
        "provider_retry_count": provider_record.get("provider_retry_count"),
        "fallback_used": provider_record.get("fallback_used"),
    }
    package_manifest = _package(
        package_path=package_path,
        project={"project_id": "project-05"},
        identity=identity,
        contract_file=frozen,
        contract=contract,
        source_path=copied_source_path,
        worker_result_path=copied_worker_result_path,
        output_records=output_records,
        semantic=semantic,
        provider_provenance=provider_provenance,
    )
    package_manifest, neutral, package_checks = _validate_package(
        package_path,
        [str(item["output_id"]) for item in contract.get("outputs", [])],
    )
    render = _render_outputs(output_records, result_root)
    packet = build_blind_review_packet(
        original_prompt=str(frozen["prompt"]),
        final_output_identities=sorted(stl_paths),
        package_manifest=package_manifest,
        neutral_measurement_report=neutral,
        fixed_views=[str(item["path"]) for item in render["views"] if item.get("path")],
        units=str(contract.get("units") or "mm"),
    )
    packet["packet_sha256"] = _sha256_json(packet)
    deterministic_pass = (
        worker.success
        and semantic.get("status") == "passed"
        and package_checks.get("valid") is True
        and render.get("valid") is True
        and all(item.get("topology_status") == "valid" and item.get("artifact_integrity") for item in output_records)
    )
    reviewer_result = _blind_reviewer_result(
        semantic=semantic,
        deterministic_pass=deterministic_pass,
        packet_sha256=packet["packet_sha256"],
    )
    candidate_before_review = derive_candidate_policy(
        outputs=output_records,
        semantic_verification=semantic,
        artifacts={"package_required": True, "package_available": True, "valid": package_checks.get("valid") is True},
    )
    independent_review = build_blind_review_record(
        review_cycle=1,
        reviewer_result=reviewer_result,
        candidate_policy=candidate_before_review,
    )
    candidate = derive_candidate_policy(
        outputs=output_records,
        semantic_verification=semantic,
        artifacts={"package_required": True, "package_available": True, "valid": package_checks.get("valid") is True},
        independent_review={"verdict": independent_review["final_verdict"]},
    )
    return {
        "semantic_verification": semantic,
        "candidate_policy": candidate,
        "package": {
            "path": _relative(package_path),
            "valid": package_checks.get("valid") is True,
            "manifest_sha256": _sha256_json(package_manifest),
            "neutral_measurement_report": neutral,
            "validation": package_checks,
        },
        "render": render,
        "review_packet": packet,
        "independent_review": independent_review,
        "downstream_boundary": "semantic" if semantic.get("failed") else "candidate_review",
        "source_persisted": _relative(copied_source_path),
        "worker_result_persisted": _relative(copied_worker_result_path),
    }


async def _run() -> dict[str, Any]:
    if RESULT_PATH.exists():
        raise RuntimeError(f"bounded P5 L1 operation already persisted: {_relative(RESULT_PATH)}")
    gate, envelope_record, frozen, job = _verify_gate()
    contract = frozen["contract"]
    source = (PROJECT_ROOT / "source.py").read_text(encoding="utf-8")
    provider = build_executable_ai_provider(settings)
    if not isinstance(provider, GeminiApiProvider) or provider.validated_transport is not True:
        raise RuntimeError("P5 L1 did not resolve to the validated Gemini REST provider")
    preflight = _provider_preflight(provider)
    if not preflight["primary_present"] or not preflight["fallback_present"]:
        raise RuntimeError("P5 L1 stopped before request because credential propagation is incomplete")
    attempts: list[dict[str, Any]] = []
    provider._validated_attempt_recorder = lambda record: attempts.append(
        {
            "attempt_index": record.get("attempt_index"),
            "credential_slot": record.get("credential_slot"),
            "credential_present": record.get("credential_present") is True,
            "status_code": record.get("status_code"),
            "failure_class": record.get("failure_class"),
        }
    )
    result_root = RESULT_ROOT
    result_root.mkdir(parents=True, exist_ok=False)
    result: dict[str, Any] = {
        "schema_version": "executable-cadquery-authorized-l1-result-v1",
        "project_id": "project-05",
        "repair_level": "L1",
        "provider_calls_before": 3,
        "worker_calls_before": 3,
        "provider_preflight": preflight,
        "authority_checks": gate["authority_verification"],
        "envelope_checks": {
            "envelope_sha256": _sha256_json(envelope_record["envelope"]) == gate["repair_envelope"]["sha256"],
            "source_hash": envelope_record["envelope"].get("previous_source_hash") == SOURCE_HASH,
            "repair_level": envelope_record["envelope"].get("repair_level") == "L1",
        },
        "authority": gate["authoritative_source"],
        "runtime": gate["runtime"],
    }
    try:
        request = ModelGenerationRequest(
            project_name=str(frozen["title"]),
            original_intent=str(frozen["prompt"]),
            user_instruction=str(frozen["prompt"]),
            current_source=source,
            executable_design_contract=contract,
            executable_repair_envelope=envelope_record["envelope"],
        )
        generated = await provider.generate_cadquery_model(request)
        provider_record = _provider_record(provider, generated, attempts)
        parsed = parse_executable_cadquery_response(generated.raw_output, contract)
        repaired_source = parsed.outputs[0].source
        repaired_source_hash = _sha256_text(repaired_source)
        worker = await CadQueryCliRunner(
            workspace_root=result_root / "worker-workspace",
            timeout_seconds=int(job.get("execution_limits", {}).get("timeout_seconds") or 60),
        ).compile(
            repaired_source,
            job_id="project-05-authorized-l1",
            source_contract_version=str(job.get("source_contract_version") or "cadquery-v1"),
            parameter_values=job.get("parameter_values") or {},
            requested_outputs=job.get("requested_outputs") or [],
        )
        artifact_paths, output_records = _copy_worker_artifacts(worker, result_root)
        copied_source = result_root / "source" / "source.py"
        copied_source.parent.mkdir(parents=True, exist_ok=True)
        copied_source.write_text(repaired_source, encoding="utf-8")
        worker_record = _worker_record(worker, output_records)
        worker_record["schema_version"] = "executable-cadquery-authorized-l1-worker-result-v1"
        worker_result_path = result_root / "worker" / "result.json"
        _write_json(worker_result_path, worker_record)
        worker_record["authority_checks"] = {
            **gate["authority_verification"],
            "repaired_source_hash_matches_worker": worker.source_hash == repaired_source_hash,
            "worker_output_ids_match_job": sorted(item["output_id"] for item in output_records) == sorted(
                str(item["output_id"]) for item in job.get("requested_outputs", [])
            ),
        }
        _write_json(worker_result_path, worker_record)
        current_progress = _progress_record(worker, output_records)
        previous_progress = _previous_progress(gate)
        progress = compare_executable_progress("L1", previous=previous_progress, current=current_progress)
        failure_class = classify_executable_failure("execution", worker.execution_diagnostics or {}) if not worker.success else ""
        decision = decide_executable_repair(
            repair_level="L1",
            repair_ordinal=3,
            source_hash=repaired_source_hash,
            previous_source_hash=SOURCE_HASH,
            failure_class=failure_class,
            previous_failure_class="cadquery_api_error",
            progress=progress,
        ) if not worker.success else {
            "decision": "stop",
            "stop_reason": "one_authorized_l1_operation_complete",
            "progress_result": "progressed" if progress.get("measurable_progress") else "no_progress",
        }
        result.update({
            "provider": provider_record,
            "worker": worker_record,
            "repair": {
                "envelope_sha256": gate["repair_envelope"]["sha256"],
                "previous_source_hash": SOURCE_HASH,
                "repaired_source_hash": repaired_source_hash,
                "progress": progress,
                "decision": decision,
            },
            "outputs": _artifact_records(output_records, worker),
            "provider_calls_made": int(provider_record.get("provider_call_count") or 1),
            "worker_calls_made": 1,
            "fallback_used": provider_record.get("fallback_used") is True,
        })
        if worker.success:
            downstream = _downstream(
                frozen=frozen,
                contract=contract,
                identity={
                    "database_project_id": gate["authoritative_source"]["database_project_id"],
                    "workflow_id": gate["authoritative_source"]["workflow_id"],
                    "revision_id": REVISION_ID,
                },
                source_path=copied_source,
                worker_result_path=worker_result_path,
                repaired_source_hash=repaired_source_hash,
                worker=worker,
                output_records=_artifact_records(output_records, worker),
                provider_record=provider_record,
                result_root=result_root,
            )
            result.update(downstream)
            result["semantic_repair_gate"] = "L3_repair_required" if result["semantic_verification"].get("failed") else "none"
            result["status"] = "completed"
        else:
            result.update({
                "semantic_verification": {"status": "not_reached", "passed": [], "failed": [], "unverifiable": []},
                "candidate_policy": {"state": "candidate_blocked", "reason": "worker_failed_before_topology"},
                "semantic_repair_gate": "not_reached",
                "downstream_boundary": "build_function",
                "status": "completed",
            })
    except Exception as exc:
        result.update({
            "status": "provider_or_contract_failure",
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "provider_attempted": 1,
            "attempts": attempts,
            "provider": {
                "provider": provider.provider_id,
                "transport": "gemini_api_rest",
                "validated_transport": provider.validated_transport is True,
                "provider_call_count": len(attempts),
                "provider_retry_count": max(0, len(attempts) - 1),
                "fallback_used": any(item.get("credential_slot") == "fallback" for item in attempts),
                "fallback_policy": "fallback_only_after_http_429",
            },
            "provider_calls_made": len(attempts) or 1,
            "worker_calls_made": 0,
        })
    _write_json(RESULT_PATH, result)
    _update_gate(result)
    _update_matrix(result)
    return result


def _update_gate(result: Mapping[str, Any]) -> None:
    gate = _read_json(GATE_PATH)
    gate["status"] = "completed_one_bounded_l1"
    gate["provider_calls_made"] = int(result.get("provider_calls_made") or 0)
    gate["worker_calls_made"] = int(result.get("worker_calls_made") or 0)
    gate["topology_reached"] = bool(result.get("worker", {}).get("success") and result.get("outputs"))
    latest_diagnostic = result.get("worker", {}).get("execution_diagnostics")
    if isinstance(latest_diagnostic, Mapping):
        gate["latest_execution_diagnostic"] = {
            "active_phase": latest_diagnostic.get("active_phase"),
            "failure_phase": latest_diagnostic.get("failure_phase"),
            "failure_source_function": latest_diagnostic.get("failure_source_function"),
            "failure_source_line": latest_diagnostic.get("failure_source_line"),
            "failure_operation": latest_diagnostic.get("failure_operation"),
            "failure_exception_type": latest_diagnostic.get("failure_exception_type"),
            "failure_message": latest_diagnostic.get("failure_message"),
            "normalized_exception": latest_diagnostic.get("normalized_exception"),
            "topology_reached": bool(result.get("worker", {}).get("success") and result.get("outputs")),
        }
    gate["latest_source_hash"] = result.get("repair", {}).get("repaired_source_hash")
    gate["result"] = {
        "path": _relative(RESULT_PATH),
        "sha256": _sha256_file(RESULT_PATH),
        "status": result.get("status"),
        "provider_calls_made": result.get("provider_calls_made"),
        "worker_calls_made": result.get("worker_calls_made"),
        "fallback_used": result.get("fallback_used", result.get("provider", {}).get("fallback_used", False)),
        "progress": result.get("repair", {}).get("progress"),
        "decision": result.get("repair", {}).get("decision"),
    }
    gate["dispatch_gate"]["authorized"] = False
    gate["dispatch_gate"]["terminal_after_one_bounded_l1"] = True
    _write_json(GATE_PATH, gate)


def _update_matrix(result: Mapping[str, Any]) -> None:
    matrix = _read_json(MATRIX_PATH)
    gate = _read_json(GATE_PATH)
    authority = gate.get("authoritative_source", {})
    project = dict(matrix["projects"]["project-05"])
    outputs = result.get("outputs") or []
    worker_success = result.get("worker", {}).get("success") is True
    topology_valid = bool(outputs) and all(item.get("topology_status") == "valid" for item in outputs)
    semantic = result.get("semantic_verification") or {}
    project.update(
        {
            "status": "candidate_blocked",
            "untouched": False,
            "provider_calls_made": int(result.get("provider_calls_made") or 0),
            "worker_calls_made": int(result.get("worker_calls_made") or 0),
            "authoritative_source_hash": SOURCE_HASH,
            "complete_source_available_for_dispatch": True,
            "dispatch_gate": "completed_one_bounded_l1",
            "topology": "valid" if topology_valid else "not_reached" if not worker_success else "invalid",
            "topology_evidence_version": "topology-evidence-v2" if topology_valid else None,
            "downstream_boundary": result.get("downstream_boundary", "build_function"),
            "downstream": {
                "semantic_measurement": "passed" if semantic.get("status") == "passed" else "failed" if worker_success else "not_reached",
                "semantic_policy": "passed" if worker_success and not semantic.get("failed") else "failed" if worker_success else "not_reached",
                "artifacts": "passed" if outputs and all(item.get("artifact_available") and item.get("artifact_integrity") for item in outputs) else "not_reached",
                "package": "passed" if result.get("package", {}).get("valid") else "not_reached",
                "render": "passed" if result.get("render", {}).get("valid") else "not_reached",
                "blind_independent_cad_qa": result.get("independent_review", {}).get("final_verdict", "not_reached"),
            },
            "latest_authoritative_worker_result": {
                "path": _relative(RESULT_PATH),
                "sha256": _sha256_file(RESULT_PATH),
                "identity": {
                    "database_project_id": authority.get("database_project_id"),
                    "workflow_id": authority.get("workflow_id"),
                    "revision_id": authority.get("revision_id"),
                    "job_id": authority.get("job_id"),
                },
                "source_hash": result.get("repair", {}).get("repaired_source_hash", SOURCE_HASH),
                "topology_evidence_version": "topology-evidence-v2" if topology_valid else None,
            },
            "next_action": "no_further_p5_provider_call_after_bounded_l1",
        }
    )
    matrix["projects"]["project-05"] = project
    matrix["authorized_provider_calls_made"] = sum(
        int(item.get("provider_calls_made") or 0)
        for item in matrix["projects"].values()
        if isinstance(item, Mapping)
    )
    matrix["authorized_worker_calls_made"] = sum(
        int(item.get("worker_calls_made") or 0)
        for item in matrix["projects"].values()
        if isinstance(item, Mapping)
    )
    matrix["phase_1_started"] = False
    matrix["p5_touched"] = True
    _write_json(MATRIX_PATH, matrix)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    gate, envelope, frozen, job = _verify_gate()
    provider = build_executable_ai_provider(settings)
    if args.verify_only:
        preflight = _provider_preflight(provider) if isinstance(provider, GeminiApiProvider) else {}
        print(json.dumps({
            "project_id": "project-05",
            "authority_checks": all(gate["authority_verification"].values()),
            "envelope_sha256": _sha256_json(envelope["envelope"]),
            "provider_class": type(provider).__name__,
            "transport": preflight.get("transport"),
            "validated_transport": preflight.get("validated_transport"),
            "primary_present": preflight.get("primary_present"),
            "fallback_present": preflight.get("fallback_present"),
            "provider_calls_made": 0,
            "worker_calls_made": 0,
        }, sort_keys=True))
        return 0
    result = asyncio.run(_run())
    print(json.dumps({
        "project_id": "project-05",
        "status": result.get("status"),
        "provider_calls_made": result.get("provider_calls_made", 0),
        "worker_calls_made": result.get("worker_calls_made", 0),
        "transport": result.get("provider", {}).get("transport"),
        "fallback_used": result.get("provider", {}).get("fallback_used", False),
        "worker_success": result.get("worker", {}).get("success"),
        "topology": result.get("outputs"),
        "semantic_status": result.get("semantic_verification", {}).get("status"),
        "blind_qa": result.get("independent_review", {}).get("final_verdict", "not_reached"),
        "result": _relative(RESULT_PATH),
    }, sort_keys=True))
    return 0 if result.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
