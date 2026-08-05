"""Run the preregistered provider-emission study.

Default mode is provider-free offline preregistration/replay.  Live calls
require ``--live`` and the secondary-only credential gate.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.services.cad.cadquery_contract import CadQueryContractError, validate_cadquery_source
from app.services.cad.cadquery_runner import CadQueryCliRunner
from app.services.gemini_integration.profile import GeminiFlashLiteContractV1
from app.services.gemini_integration.transport import SecondaryGeminiClient, SharedIntegrationRateLimiter
from app.services.research.geometry_ir_experimental import compile_geometry_ir
from app.services.research.provider_ir_validation import (
    MAX_ATTEMPTS,
    MAX_LOGICAL_OPERATIONS,
    MAX_WORKER_JOBS,
    ORDER_SEED,
    STUDY_ID,
    ProviderStudyOperation,
    ProviderStudyTask,
    build_execution_order,
    build_frozen_task_corpus,
    build_known_good_ir,
    build_paired_operations,
    build_task_report,
    assemble_t5_source,
    classify_candidate_eligibility,
    classify_ir_response,
    classify_t5_response,
    frozen_contract_report,
    redacted_attempt,
    report_names,
    require_secondary_credential,
    summarize_provider_metrics,
    validate_report_completeness,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT_ROOT = REPO_ROOT / "data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01/reports/provider-ir-targeted-validation-01"
DEFAULT_WORKER_ROOT = REPO_ROOT / "data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01/worker-jobs/provider-ir-targeted-validation-01"


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")
    ).hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return _json_safe(value.__dict__)
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(value), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


def _git(*args: str) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _repository_snapshot() -> dict[str, Any]:
    return {
        "head": _git("rev-parse", "HEAD"),
        "head_short": _git("rev-parse", "--short", "HEAD"),
        "branch": _git("branch", "--show-current"),
        "worktree_status": _git("status", "--porcelain=v1"),
        "divergence_from_origin_main": _git("rev-list", "--left-right", "--count", "origin/main...HEAD"),
        "migration_head": "0036_benchmark_model_metadata (head)",
        "production_routing_changed": False,
        "representative_wave_02_authorized": False,
    }


def _operation_records(root: Path) -> dict[str, dict[str, Any]]:
    capture_root = root / "operation-captures"
    records: dict[str, dict[str, Any]] = {}
    for path in sorted(capture_root.glob("*.json")):
        item = _read_json(path, {})
        if isinstance(item, dict) and item.get("operation_id"):
            records[str(item["operation_id"])] = item
    return records


def _derived_records(root: Path) -> dict[str, dict[str, Any]]:
    value = _read_json(root / "derived-records.json", [])
    if not isinstance(value, list):
        return {}
    return {
        str(item["operation_id"]): item
        for item in value
        if isinstance(item, dict) and item.get("operation_id")
    }


def _all_records(root: Path) -> dict[str, dict[str, Any]]:
    records = _operation_records(root)
    records.update(_derived_records(root))
    return records


def _capture_path(root: Path, operation_id: str) -> Path:
    safe = "".join(character if character.isalnum() or character in "._-" else "_" for character in operation_id)
    return root / "operation-captures" / f"{safe}.json"


def _task_by_id(tasks: tuple[ProviderStudyTask, ...]) -> dict[str, ProviderStudyTask]:
    return {task.task_id: task for task in tasks}


def _operation_by_id(operations: tuple[ProviderStudyOperation, ...]) -> dict[str, ProviderStudyOperation]:
    return {operation.operation_id: operation for operation in operations}


def _requested_outputs(task: ProviderStudyTask) -> list[dict[str, Any]]:
    return [{"output_id": output_id, "required": True, "expected_solid_count": 1, "allow_disconnected_solids": False} for output_id in task.output_ids]


def _parameter_values(task: ProviderStudyTask) -> dict[str, Any]:
    return {
        str(item["id"]): item.get("value", item.get("default"))
        for item in (task.request.design_plan or {}).get("parameters", []) or []
        if isinstance(item, dict) and item.get("id") is not None
    }


def _topology_evidence(worker_result: Any, task: ProviderStudyTask) -> tuple[bool, list[dict[str, Any]]]:
    output_records: list[dict[str, Any]] = []
    for output in getattr(worker_result, "outputs", []) or []:
        topology = output.topology_metadata if isinstance(output.topology_metadata, dict) else {}
        output_records.append({
            "output_id": output.output_id,
            "success": bool(output.success),
            "topology": _json_safe(topology),
            "solid_count": topology.get("detected_solid_count"),
            "expected_solid_count": topology.get("expected_solid_count"),
            "valid": topology.get("valid"),
            "volume_mm3": topology.get("volume_mm3"),
            "bounding_box_mm": topology.get("bounding_box_mm"),
        })
    output_ids = [item["output_id"] for item in output_records]
    passed = bool(output_records) and output_ids == list(task.output_ids) and all(
        item["success"] and item["valid"] is True and item["solid_count"] == item["expected_solid_count"] == 1
        for item in output_records
    )
    return passed, output_records


async def _run_downstream(
    *,
    operation: ProviderStudyOperation,
    provider_evidence: dict[str, Any],
    worker_runner: CadQueryCliRunner,
    worker_jobs_used: int,
    job_suffix: str = "",
) -> tuple[dict[str, Any], int]:
    downstream: dict[str, Any] = {
        "source_generation": False,
        "static_validation": False,
        "compiler": operation.arm != "typed_geometry_ir",
        "worker_execution": False,
        "topology_verification": False,
        "requirement_verification": False,
        "worker_job_id": None,
        "source_hash": None,
        "source": None,
        "worker": None,
        "topology": [],
    }
    if not provider_evidence.get("contract_parse") or provider_evidence.get("contract_valid") is False or not provider_evidence.get("semantic_obligations"):
        return downstream, worker_jobs_used
    source: str | None = None
    if operation.arm == "typed_geometry_ir":
        if not provider_evidence.get("compiler"):
            return downstream, worker_jobs_used
        source = provider_evidence.get("compiled_source")
    else:
        source = provider_evidence.get("assembled_source")
    if not isinstance(source, str):
        return downstream, worker_jobs_used
    downstream["source"] = source
    downstream["source_hash"] = provider_evidence.get("source_hash")
    downstream["source_generation"] = True
    try:
        validate_cadquery_source(source, contract_version="cadquery-v1")
    except CadQueryContractError as exc:
        downstream["static_error"] = str(exc)
        return downstream, worker_jobs_used
    downstream["static_validation"] = True
    if worker_jobs_used >= MAX_WORKER_JOBS:
        downstream["worker_cap_reached"] = True
        return downstream, worker_jobs_used
    job_id = f"{STUDY_ID}-{operation.task_id}-{operation.arm}{job_suffix}"
    downstream["worker_job_id"] = job_id
    worker_jobs_used += 1
    worker_result = await worker_runner.compile(
        source,
        job_id,
        parameter_values=_parameter_values(operation.task),
        requested_outputs=_requested_outputs(operation.task),
    )
    topology_passed, topology = _topology_evidence(worker_result, operation.task)
    downstream["worker"] = _json_safe(asdict(worker_result))
    downstream["worker_execution"] = bool(worker_result.success and all(item.get("success") for item in topology))
    downstream["topology"] = topology
    downstream["topology_verification"] = bool(downstream["worker_execution"] and topology_passed)
    downstream["requirement_verification"] = bool(downstream["topology_verification"] and [item.get("output_id") for item in topology] == list(operation.task.output_ids))
    return downstream, worker_jobs_used


def _paired_results(records: list[dict[str, Any]], tasks: tuple[ProviderStudyTask, ...]) -> list[dict[str, Any]]:
    by_key = {(item.get("task_id"), item.get("arm")): item for item in records}
    result: list[dict[str, Any]] = []
    for task in tasks:
        t5 = by_key.get((task.task_id, "t5_raw_cadquery"), {})
        ir = by_key.get((task.task_id, "typed_geometry_ir"), {})
        t5_ok = bool(t5.get("candidate_eligible"))
        ir_ok = bool(ir.get("candidate_eligible"))
        if t5_ok and ir_ok:
            category = "both_arms_succeed"
        elif ir_ok and not t5_ok:
            category = "ir_succeeds_t5_fails"
        elif t5_ok and not ir_ok:
            category = "t5_succeeds_ir_fails"
        elif t5.get("failure_classes") == ir.get("failure_classes") and t5.get("failure_classes"):
            category = "both_fail_same_semantic_reason"
        elif t5.get("failure_classes") or ir.get("failure_classes"):
            category = "both_fail_different_reasons"
        else:
            category = "result_remains_ambiguous"
        result.append({
            "task_id": task.task_id,
            "t5_operation_id": t5.get("operation_id"),
            "ir_operation_id": ir.get("operation_id"),
            "category": category,
            "t5_first_incorrect_boundary": t5.get("first_incorrect_boundary"),
            "ir_first_incorrect_boundary": ir.get("first_incorrect_boundary"),
            "t5_candidate_eligible": t5_ok,
            "ir_candidate_eligible": ir_ok,
            "same_semantic_facts_hash": t5.get("semantic_facts_hash") == ir.get("semantic_facts_hash") == task.semantic_facts_hash,
        })
    return result


def _choose_decision(records: list[dict[str, Any]], paired: list[dict[str, Any]], metrics: dict[str, Any], *, live: bool) -> dict[str, Any]:
    if not live or len(records) < MAX_LOGICAL_OPERATIONS:
        decision = "targeted_followup_required"
        reason = "provider emission was not measured or the complete paired study did not finish"
    else:
        common_ir = sum(bool(item.get("ir_candidate_eligible")) for item in paired[:5])
        common_t5 = sum(bool(item.get("t5_candidate_eligible")) for item in paired[:5])
        ir_task6 = bool(paired[5].get("ir_candidate_eligible")) if len(paired) >= 6 else False
        transport_failures = sum(item.get("first_incorrect_boundary") == "transport" for item in records)
        if transport_failures:
            decision = "insufficient_evidence"
            reason = "transport failures prevented a fair paired comparison"
        elif common_ir >= 4 and ir_task6:
            decision = "hybrid_ir_provider_contract_qualified"
            reason = "IR provider emission qualified across common deterministic tasks and the bounded advanced escape"
        elif common_ir >= 4 and metrics.get("typed_geometry_ir", {}).get("provider_owned_failure_count", 0) <= 1:
            decision = "hybrid_ir_provider_contract_requires_narrow_revision"
            reason = "one narrow provider contract defect remains after otherwise reliable emission"
        elif common_ir >= 2:
            decision = "narrower_ir_scope_required"
            reason = "only a smaller deterministic subset emitted the IR reliably"
        elif common_t5 >= common_ir:
            decision = "raw_cadquery_t5_remains_preferred"
            reason = "IR structural or semantic reliability did not compensate for the established T5 path"
        else:
            decision = "targeted_followup_required"
            reason = "one provider behavior remains unresolved by the paired evidence"
    wave_eligible = decision == "hybrid_ir_provider_contract_qualified"
    return {
        "decision": decision,
        "reason": reason,
        "offline_compiler_assessment": "hybrid_geometry_ir_viable_with_narrower_scope",
        "provider_emission_measured": bool(live),
        "wave_02_eligible": wave_eligible,
        "decision_thresholds": {"common_tasks": 5, "qualification_minimum_common_ir_tasks": 4, "escape_task_required": True, "narrow_revision_replay_required": True},
    }


def _write_all_reports(
    *,
    root: Path,
    profile: GeminiFlashLiteContractV1,
    tasks: tuple[ProviderStudyTask, ...],
    operations: tuple[ProviderStudyOperation, ...],
    execution_order: list[dict[str, Any]],
    records: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
    limiter: SharedIntegrationRateLimiter,
    worker_jobs_used: int,
    live: bool,
    safe_stop: str | None = None,
    counterfactual_extra: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    paired = _paired_results(records, tasks)
    metrics = summarize_provider_metrics(records)
    decision = _choose_decision(records, paired, metrics, live=live)
    ir_records = [item for item in records if item.get("arm") == "typed_geometry_ir"]
    t5_records = [item for item in records if item.get("arm") == "t5_raw_cadquery"]
    compiler_records = [{"task_id": item.get("task_id"), "operation_id": item.get("operation_id"), "synthetic": False, "provider_emission": True, "compiler": item.get("compiler"), "compiler_error": item.get("compiler_error"), "source_hash": item.get("source_hash")} for item in ir_records]
    worker_records = [{"operation_id": item.get("operation_id"), "task_id": item.get("task_id"), "arm": item.get("arm"), "worker_job_id": item.get("worker_job_id"), "worker_execution": item.get("worker_execution"), "worker": item.get("worker")} for item in records if item.get("worker_job_id")]
    topology_records = [{"operation_id": item.get("operation_id"), "task_id": item.get("task_id"), "arm": item.get("arm"), "topology": item.get("topology"), "topology_verification": item.get("topology_verification")} for item in records if item.get("worker_job_id")]
    requirement_records = [{"operation_id": item.get("operation_id"), "task_id": item.get("task_id"), "arm": item.get("arm"), "requirement_verification": item.get("requirement_verification"), "output_ids": item.get("output_ids")} for item in records]
    synthetic_counterfactuals: list[dict[str, Any]] = []
    synthetic_compiler_results: list[dict[str, Any]] = []
    for task in tasks:
        document = build_known_good_ir(task)
        try:
            compiled = compile_geometry_ir(document)
            synthetic_compiler_results.append({"task_id": task.task_id, "synthetic": True, "provider_emission": False, "compiled": True, "source_hash": _hash(compiled.source)})
        except Exception as exc:
            synthetic_compiler_results.append({"task_id": task.task_id, "synthetic": True, "provider_emission": False, "compiled": False, "error": str(exc)})
        synthetic_counterfactuals.append({"task_id": task.task_id, "synthetic": True, "excluded_from_provider_metrics": True, "counterfactual": "known-good IR through compiler and downstream contract", "provider_success": False})
    _write_json(root / "preregistration.json", {"schema_version": "volundr-provider-ir-targeted-validation-v1", "study_id": STUDY_ID, "live": live, "live_authorized": live, "provider_calls": len(records), "worker_jobs": worker_jobs_used, "safe_stop": safe_stop, "contract": frozen_contract_report(profile), "no_wave_02": True})
    _write_json(root / "repository-snapshot.json", _repository_snapshot())
    _write_json(root / "frozen-task-corpus.json", {"schema_version": "volundr-provider-ir-task-corpus-v1", "tasks": [build_task_report(task) for task in tasks]})
    _write_json(root / "execution-order.json", {"seed": ORDER_SEED, "order": execution_order, "preregistered_before_live": True})
    _write_json(root / "prompt-contracts.json", {"t5": {"version": "T5-geometry-exact-slot-contract-v1", "operations": [item.as_dict() for item in operations if item.arm == "t5_raw_cadquery"]}, "ir": {"version": "T6-experimental-typed-geometry-ir-v1", "operations": [item.as_dict() for item in operations if item.arm == "typed_geometry_ir"]}, "frozen_before_live": True})
    _write_json(root / "provider-attempts.json", attempts)
    _write_json(root / "derived-records.json", records)
    _write_json(root / "arm-a-t5-results.json", t5_records)
    _write_json(root / "arm-b-ir-results.json", ir_records)
    _write_json(root / "paired-task-results.json", paired)
    _write_json(root / "semantic-equivalence-results.json", [{"task_id": task.task_id, "semantic_facts_hash": task.semantic_facts_hash, "t5": next((item for item in t5_records if item.get("task_id") == task.task_id), None), "ir": next((item for item in ir_records if item.get("task_id") == task.task_id), None), "comparison": "identity, dimensions, feature obligations, topology, and protected values; source text equality excluded"} for task in tasks])
    _write_json(root / "compiler-results.json", compiler_records + synthetic_compiler_results)
    _write_json(root / "worker-results.json", {"jobs_used": worker_jobs_used, "maximum_jobs": MAX_WORKER_JOBS, "results": worker_records})
    _write_json(root / "topology-results.json", topology_records)
    _write_json(root / "requirement-verification-results.json", requirement_records)
    _write_json(root / "counterfactual-results.json", [*(counterfactual_extra or []), *synthetic_counterfactuals])
    _write_json(root / "normalization-report.json", {"normalization_count": sum(int(item.get("normalization_count") or 0) for item in records), "actions": [{"operation_id": item.get("operation_id"), "count": item.get("normalization_count", 0)} for item in records], "synthetic_excluded": True})
    _write_json(root / "rate-limit-report.json", {"configuration": {"default_starts_per_rolling_60_seconds": 12, "hard_max_starts_per_rolling_60_seconds": 15, "minimum_start_gap_seconds": 5, "concurrency": 1, "clock": "monotonic"}, "events": limiter.events, "starts": len(limiter.events)})
    _write_json(root / "retry-report.json", {"maximum_provider_attempts": MAX_ATTEMPTS, "attempts_used": len(attempts), "retried_operations": sorted({item.get("operation_id") for item in attempts if int(item.get("attempt_index") or 0) > 0}), "attempts": attempts})
    _write_json(root / "provider-ir-decision.json", {**decision, "metrics": metrics, "paired_results": paired})
    _write_json(root / "wave-02-gate.json", {"wave_02_remains_closed": not decision["wave_02_eligible"], "eligible_only_for": ["hybrid_ir_provider_contract_qualified", "hybrid_ir_provider_contract_requires_narrow_revision_with_replay"], "provider_ir_decision": decision["decision"], "authorized": False})
    combined = {"schema_version": "volundr-provider-ir-targeted-validation-v1", "study_id": STUDY_ID, "provider_profile": frozen_contract_report(profile), "repository": _repository_snapshot(), "tasks": [build_task_report(task) for task in tasks], "execution_order": execution_order, "provider_attempts": attempts, "records": records, "metrics": metrics, "decision": decision, "worker_jobs_used": worker_jobs_used, "synthetic_counterfactuals_excluded": True, "production_routing_changed": False, "wave_02_authorized": False, "redaction": {"credential_values_serialized": False, "credential_source": "GEMINI_API_KEY_2"}}
    _write_json(root / "combined-provider-ir-evidence.json", combined)
    missing = validate_report_completeness(root)
    if missing:
        raise RuntimeError(f"provider IR report set is incomplete: {missing}")
    return {"metrics": metrics, "decision": decision, "paired": paired, "records": records, "attempts": attempts, "worker_jobs_used": worker_jobs_used}


async def _replay_existing_captures(
    *,
    root: Path,
    profile: GeminiFlashLiteContractV1,
    tasks: tuple[ProviderStudyTask, ...],
    operations: tuple[ProviderStudyOperation, ...],
    execution_order: list[dict[str, Any]],
    execute_workers: bool = False,
    worker_root: Path = DEFAULT_WORKER_ROOT,
) -> dict[str, Any]:
    """Re-score immutable provider text without provider or worker calls."""

    existing = _all_records(root)
    operation_map = _operation_by_id(operations)
    records: list[dict[str, Any]] = []
    counterfactuals: list[dict[str, Any]] = []
    worker_runner = CadQueryCliRunner(workspace_root=worker_root, timeout_seconds=90) if execute_workers else None
    worker_jobs_used = sum(1 for item in existing.values() if isinstance(item, dict) and item.get("worker_job_id"))
    for order_item in execution_order:
        operation_id = order_item["operation_id"]
        old = existing.get(operation_id)
        operation = operation_map[operation_id]
        if not isinstance(old, dict) or not isinstance(old.get("raw_provider_output"), str):
            continue
        raw = str(old["raw_provider_output"])
        provider_evidence = classify_t5_response(raw, operation.task) if operation.arm == "t5_raw_cadquery" else classify_ir_response(raw, operation.task)
        downstream = {key: old.get(key) for key in ("source_generation", "static_validation", "compiler", "worker_execution", "topology_verification", "requirement_verification", "worker_job_id", "source_hash", "source", "worker", "topology")}
        if provider_evidence.get("semantic_obligations"):
            if operation.arm == "t5_raw_cadquery":
                try:
                    source = assemble_t5_source(operation.task, provider_evidence["payload"])
                    validate_cadquery_source(source, contract_version="cadquery-v1")
                except (KeyError, ValueError, CadQueryContractError) as exc:
                    downstream["source_generation"] = False
                    downstream["static_validation"] = False
                    downstream["replay_source_error"] = str(exc)
                else:
                    downstream["source_generation"] = True
                    downstream["static_validation"] = True
                    downstream["source"] = source
                    downstream["source_hash"] = _hash(source)
            elif provider_evidence.get("compiler"):
                source = provider_evidence.get("compiled_source")
                downstream["source_generation"] = isinstance(source, str)
                downstream["static_validation"] = bool(source)
                downstream["compiler"] = True
                downstream["source"] = source
                downstream["source_hash"] = _hash(source) if isinstance(source, str) else None
        if execute_workers and worker_runner is not None and (downstream.get("worker_job_id") is None or not downstream.get("worker_execution")) and provider_evidence.get("contract_valid") is not False and provider_evidence.get("semantic_obligations"):
            downstream, worker_jobs_used = await _run_downstream(
                operation=operation,
                provider_evidence=provider_evidence,
                worker_runner=worker_runner,
                worker_jobs_used=worker_jobs_used,
                job_suffix="-replay-fixed",
            )
            if downstream.get("worker_job_id"):
                counterfactuals.append({"kind": "worker_replay", "operation_id": operation_id, "task_id": operation.task_id, "arm": operation.arm, "synthetic": True, "excluded_from_provider_metrics": True, "provider_calls": 0})
        candidate = classify_candidate_eligibility(provider_evidence, downstream)
        record = {**old, **provider_evidence, **downstream, **candidate, "provider_owned_failure": bool(provider_evidence.get("failure_classes")), "runtime_api_failure": any(item in {"compiler_failure", "invalid_cadquery_method", "invalid_cadquery_argument"} for item in provider_evidence.get("failure_classes", [])), "evaluator_replay": True, "provider_attempt": True, "synthetic": False}
        records.append(record)
        if operation.arm == "t5_raw_cadquery":
            counterfactuals.append({"kind": "evaluator_replay", "operation_id": operation_id, "task_id": operation.task_id, "arm": operation.arm, "synthetic": True, "excluded_from_provider_metrics": True, "single_variable_changed": "T5 authorized-parameter reference semantic scorer", "raw_response_hash": old.get("raw_response_hash")})
    if execute_workers:
        failed_harness_path = worker_root / f"{STUDY_ID}-provider-ir-validation-task-01-t5_raw_cadquery" / "stderr.log"
        if not failed_harness_path.is_file():
            failed_harness_path = worker_root / f"{STUDY_ID}-provider-ir-validation-task-01-t5_raw_cadquery-replay" / "stderr.log"
        if failed_harness_path.is_file():
            counterfactuals.append({"kind": "harness_defect", "owner": "harness_or_fixture", "classification": "root_cause", "confidence": "confirmed", "status": "corrected", "synthetic": True, "excluded_from_provider_metrics": True, "symptom": "T5 wrapper passed no values for authorized params references", "evidence_path": str(failed_harness_path), "single_variable_changed": "declare T5 ParameterSpec values and pass parameter_values"})
    attempts = [redacted_attempt(item) for item in _read_json(root / "provider-attempts.json", []) if isinstance(item, dict)]
    prior_rate = _read_json(root / "rate-limit-report.json", {})
    limiter = SharedIntegrationRateLimiter()
    limiter.events = list(prior_rate.get("events", []) or []) if isinstance(prior_rate, dict) else []
    return _write_all_reports(root=root, profile=profile, tasks=tasks, operations=operations, execution_order=execution_order, records=records, attempts=attempts, limiter=limiter, worker_jobs_used=worker_jobs_used, live=True, counterfactual_extra=counterfactuals)


async def run_study(*, root: Path, live: bool, resume: bool = False, replay: bool = False, execute_workers: bool = False, worker_root: Path = DEFAULT_WORKER_ROOT) -> dict[str, Any]:
    profile = GeminiFlashLiteContractV1.from_repository(REPO_ROOT)
    tasks = build_frozen_task_corpus()
    operations = build_paired_operations(tasks, profile, REPO_ROOT)
    order = build_execution_order(tasks)
    root.mkdir(parents=True, exist_ok=True)
    if replay:
        return await _replay_existing_captures(root=root, profile=profile, tasks=tasks, operations=operations, execution_order=order, execute_workers=execute_workers, worker_root=worker_root)
    if not live:
        return _write_all_reports(root=root, profile=profile, tasks=tasks, operations=operations, execution_order=order, records=[], attempts=[], limiter=SharedIntegrationRateLimiter(), worker_jobs_used=0, live=False)
    operation_map = _operation_by_id(operations)
    existing = _all_records(root) if resume else {}
    remaining = [item for item in order if item["operation_id"] not in existing]
    if remaining:
        require_secondary_credential()
    attempts = [redacted_attempt(item) for item in _read_json(root / "provider-attempts.json", []) if isinstance(item, dict)]
    attempt_count = len(attempts)
    limiter = SharedIntegrationRateLimiter()
    prior_rate = _read_json(root / "rate-limit-report.json", {})
    if isinstance(prior_rate, dict):
        limiter.events = list(prior_rate.get("events", []) or [])
    worker_runner = CadQueryCliRunner(workspace_root=worker_root, timeout_seconds=90)
    worker_jobs_used = sum(1 for item in existing.values() if item.get("worker_job_id"))
    records = list(existing.values())
    safe_stop: str | None = None
    for order_item in remaining:
        if attempt_count + 2 > MAX_ATTEMPTS:
            safe_stop = "global attempt cap leaves insufficient capacity for the required exact retry policy"
            break
        operation = operation_map[order_item["operation_id"]]
        call_attempts: list[dict[str, Any]] = []

        def record_attempt(attempt: dict[str, Any]) -> None:
            call_attempts.append(redacted_attempt(attempt))

        client = SecondaryGeminiClient(profile, limiter=limiter, attempt_recorder=record_attempt)
        result = await client.generate(stage="geometry", prompt=operation.prompt, operation_id=operation.operation_id, max_attempts=2)
        attempts.extend(call_attempts)
        attempt_count += len(call_attempts)
        provider_evidence = classify_t5_response(result.text, operation.task) if operation.arm == "t5_raw_cadquery" and result.text else classify_ir_response(result.text, operation.task) if operation.arm == "typed_geometry_ir" and result.text else {"arm": operation.arm, "provider_attempt": True, "synthetic": False, "contract_parse": False, "semantic_obligations": False, "failure_classes": ["transport"], "first_incorrect_boundary": "transport", "normalization_count": 0}
        downstream, worker_jobs_used = await _run_downstream(operation=operation, provider_evidence=provider_evidence, worker_runner=worker_runner, worker_jobs_used=worker_jobs_used)
        candidate = classify_candidate_eligibility(provider_evidence, downstream)
        record = {"operation_id": operation.operation_id, "task_id": operation.task_id, "arm": operation.arm, "prompt_version": operation.prompt_version, "prompt_hash": operation.prompt_hash, "semantic_facts_hash": operation.semantic_facts_hash, "provider_attempt": True, "synthetic": False, "raw_provider_output": result.text, "transport_complete": result.complete, "provider_model": result.actual_model, "usage_metadata": result.usage_metadata, "attempt_ids": [item.get("attempt_id") for item in call_attempts], "provider_owned_failure": bool(provider_evidence.get("failure_classes")), "runtime_api_failure": any(item in {"compiler_failure", "invalid_cadquery_method", "invalid_cadquery_argument"} for item in provider_evidence.get("failure_classes", [])), **provider_evidence, **downstream, **candidate, "output_ids": list(operation.task.output_ids)}
        _write_json(_capture_path(root, operation.operation_id), record)
        records.append(record)
        _write_json(root / "provider-attempts.json", attempts)
    records = list(_operation_records(root).values())
    return _write_all_reports(root=root, profile=profile, tasks=tasks, operations=operations, execution_order=order, records=records, attempts=attempts, limiter=limiter, worker_jobs_used=worker_jobs_used, live=True, safe_stop=safe_stop)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="execute the 12 preregistered provider operations")
    parser.add_argument("--resume", action="store_true", help="reuse immutable per-operation captures")
    parser.add_argument("--replay", action="store_true", help="re-score preserved provider captures without provider or worker calls")
    parser.add_argument("--execute-workers", action="store_true", help="only with --replay: run bounded downstream worker counterfactuals")
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument("--worker-root", type=Path, default=DEFAULT_WORKER_ROOT)
    args = parser.parse_args()
    if args.execute_workers and not args.replay:
        parser.error("--execute-workers requires --replay")
    result = asyncio.run(run_study(root=args.report_root, live=args.live, resume=args.resume, replay=args.replay, execute_workers=args.execute_workers, worker_root=args.worker_root))
    print(json.dumps({"study_id": STUDY_ID, "live": args.live, "replay": args.replay, "provider_operations": len(result.get("records", [])), "attempts": len(result.get("attempts", [])), "worker_jobs": result.get("worker_jobs_used", 0), "decision": result.get("decision", {}).get("decision")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
