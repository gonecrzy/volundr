"""Run the preregistered T5 parameter/revision validation study."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import subprocess
from dataclasses import asdict
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.services.cad.cadquery_contract import CadQueryContractError, validate_cadquery_source
from app.services.cad.cadquery_runner import CadQueryCliRunner
from app.services.gemini_integration.geometry_prompt_narrow_fix import T5GeometryValidator
from app.services.gemini_integration.profile import GeminiFlashLiteContractV1
from app.services.gemini_integration.prompts import (
    GEOMETRY_T5_PARAMETER_ACCESS_PROMPT_VERSION,
    render_geometry_prompt_parameter_access_v1,
)
from app.services.gemini_integration.transport import SecondaryGeminiClient, SharedIntegrationRateLimiter
from app.services.research.provider_ir_validation import assemble_t5_source, redacted_attempt
from app.services.research.t5_parameter_revision_validation import (
    PROMPT_VERSION,
    STUDY_ID,
    build_candidate_tasks,
    evaluate_revision_preservation,
    load_revision_authority,
    validate_parameter_access,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT_ROOT = REPO_ROOT / (
    "data/debug-sessions/representative-workflow-waves/"
    "representative-workflow-wave-01/reports/t5-parameter-revision-validation-01"
)
DEFAULT_WORKER_ROOT = REPO_ROOT / (
    "data/debug-sessions/representative-workflow-waves/"
    "representative-workflow-wave-01/worker-jobs/t5-parameter-revision-validation-01"
)
ORDER_SEED = "t5-parameter-revision-validation-01-order-v1"
MAX_LOGICAL_OPERATIONS = 6
MAX_PROVIDER_ATTEMPTS = 12
MAX_WORKER_JOBS = 6
REPORT_NAMES = (
    "preregistration.json",
    "repository-snapshot.json",
    "frozen-task-corpus.json",
    "execution-order.json",
    "prompt-contract.json",
    "provider-attempts.json",
    "task-results.json",
    "metrics.json",
    "revision-authority-results.json",
    "worker-results.json",
    "topology-results.json",
    "requirement-verification-results.json",
    "normalization-report.json",
    "rate-limit-report.json",
    "retry-report.json",
    "decision.json",
    "combined-evidence.json",
    "fixture-integrity.json",
    "counterfactual-results.json",
)


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return _json_safe(value.__dict__)
    return value


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")
    ).hexdigest()


def _git(*args: str) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _repository_snapshot() -> dict[str, Any]:
    return {
        "head": _git("rev-parse", "HEAD"),
        "branch": _git("branch", "--show-current"),
        "worktree_status": _git("status", "--porcelain=v1"),
        "migration_head": "0036_benchmark_model_metadata (head)",
        "cadquery": "2.8.0",
        "ocp": "7.9.3.1",
        "production_routing_changed": False,
        "typed_ir_provider_contract_reopened": False,
    }


def build_execution_order(tasks: tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
    tasks = tasks or build_candidate_tasks()
    items = [{"operation_id": task.task_id, "task_id": task.task_id, "task_number": task.task_number} for task in tasks]
    random.Random(ORDER_SEED).shuffle(items)
    for index, item in enumerate(items):
        item["order_index"] = index
    return items


def _parameter_values(task: Any) -> dict[str, Any]:
    return {
        str(item["id"]): item.get("value", item.get("default"))
        for item in (task.request.design_plan or {}).get("parameters", []) or []
        if isinstance(item, dict) and item.get("id") is not None
    }


def _requested_outputs(task: Any) -> list[dict[str, Any]]:
    return [{"output_id": item, "required": True, "expected_solid_count": 1, "allow_disconnected_solids": False} for item in task.output_ids]


def _topology(worker_result: Any, task: Any) -> tuple[bool, list[dict[str, Any]]]:
    outputs: list[dict[str, Any]] = []
    for output in getattr(worker_result, "outputs", []) or []:
        topology = output.topology_metadata if isinstance(output.topology_metadata, dict) else {}
        outputs.append({
            "output_id": output.output_id,
            "success": bool(output.success),
            "valid": topology.get("valid"),
            "solid_count": topology.get("detected_solid_count"),
            "expected_solid_count": topology.get("expected_solid_count"),
            "volume_mm3": topology.get("volume_mm3"),
            "bounding_box_mm": topology.get("bounding_box_mm"),
            "topology": _json_safe(topology),
        })
    passed = bool(outputs) and [item["output_id"] for item in outputs] == list(task.output_ids) and all(
        item["success"] and item["valid"] is True and item["solid_count"] == item["expected_solid_count"] == 1
        for item in outputs
    )
    return passed, outputs


def _strict_payload(raw: str) -> tuple[dict[str, Any] | None, list[str]]:
    failures: list[str] = []
    text = raw.strip()
    if not text.startswith("{") or not text.endswith("}") or "```" in raw:
        return None, ["structural_parse_failure"]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None, ["structural_parse_failure"]
    if not isinstance(payload, dict) or payload.get("schema_version") != "volundr-geometry-slots-v1":
        return None, ["structural_parse_failure"]
    if not isinstance(payload.get("slots"), list):
        return None, ["structural_parse_failure"]
    return payload, failures


def _statements(payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(payload, dict):
        return []
    statements: list[str] = []
    for slot in payload.get("slots", []) or []:
        if isinstance(slot, dict) and isinstance(slot.get("statements"), list):
            statements.extend(item for item in slot["statements"] if isinstance(item, str))
    return statements


def _semantic_score(task: Any, payload: dict[str, Any] | None, validation: dict[str, Any], statements: list[str]) -> dict[str, Any]:
    text = "\n".join(statements).casefold()
    methods = {
        str(call.get("method"))
        for slot in validation.get("slots", []) or []
        for call in slot.get("cadquery_methods_and_arguments", []) or []
    }
    parameter_ids = set(task.semantic_facts.get("required_parameter_ids", []))
    access = validate_parameter_access(statements, {
        str(item["id"])
        for item in (task.request.design_plan or {}).get("parameters", []) or []
        if isinstance(item, dict) and item.get("id") is not None
    })
    missing_parameter_ids = sorted(parameter_ids - set(access.get("observed_ids", [])))
    failures = list(access.get("failures", []))
    if missing_parameter_ids:
        failures.append("required_parameter_access_missing")
    compact_text = text.replace(" ", "")
    for point in task.required_fixed_points:
        if not all(str(value) in compact_text for value in point):
            failures.append(f"required_fixed_point_missing:{list(point)}")
    for token in task.required_t5_tokens:
        if token.casefold() not in text and token not in methods:
            failures.append(f"required_operation_or_value_missing:{token}")
    revision = evaluate_revision_preservation(task, statements) if task.revision_authority else {
        "status": "not_applicable",
        "provider_failure": False,
        "failures": [],
        "unresolved": [],
    }
    failures.extend(revision.get("failures", []))
    if revision.get("status") == "fixture_incomplete":
        failures.append("revision_fixture_incomplete")
    return {
        "passed": not failures and validation.get("passed") is True,
        "failures": sorted(set(failures)),
        "methods": sorted(methods),
        "parameter_access": access,
        "required_parameter_ids": sorted(parameter_ids),
        "missing_parameter_ids": missing_parameter_ids,
        "revision": revision,
    }


def _classify(task: Any, raw: str) -> dict[str, Any]:
    payload, parse_failures = _strict_payload(raw)
    validator = T5GeometryValidator()
    validation = validator.validate(raw, task.request) if payload is not None else {"passed": False, "failure_classes": parse_failures, "slots": []}
    statements = _statements(payload)
    semantic = _semantic_score(task, payload, validation, statements) if payload is not None else {
        "passed": False,
        "failures": parse_failures,
        "parameter_access": {"passed": False, "failures": parse_failures},
        "revision": {"status": "not_measured", "provider_failure": False, "failures": []},
    }
    contract_valid = bool(payload is not None and validation.get("passed"))
    failures = sorted(set(parse_failures + list(validation.get("failure_classes", []) or []) + list(semantic.get("failures", []) or [])))
    return {
        "contract_parse": payload is not None,
        "contract_valid": contract_valid,
        "parameter_access_valid": bool(semantic.get("parameter_access", {}).get("passed")),
        "semantic_obligations": bool(semantic.get("passed")),
        "revision_preservation": semantic.get("revision"),
        "failure_classes": failures,
        "first_incorrect_boundary": (
            "structural_parse" if parse_failures else
            "parameter_access" if not semantic.get("parameter_access", {}).get("passed", False) else
            "contract" if not contract_valid else
            "semantic_obligations" if not semantic.get("passed") else None
        ),
        "payload": payload,
        "statements": statements,
        "validation": validation,
        "semantic": semantic,
    }


def _assemble_and_static(task: Any, classification: dict[str, Any]) -> tuple[str | None, bool, str | None]:
    payload = classification.get("payload")
    if not isinstance(payload, dict):
        return None, False, "no parsed payload"
    try:
        source = assemble_t5_source(task, payload)
        validate_cadquery_source(source, contract_version="cadquery-v1")
    except (CadQueryContractError, KeyError, TypeError, ValueError) as exc:
        return None, False, str(exc)
    return source, True, None


async def _run_worker(task: Any, source: str, worker_root: Path, job_index: int) -> tuple[dict[str, Any], bool, list[dict[str, Any]]]:
    runner = CadQueryCliRunner(workspace_root=worker_root, timeout_seconds=90)
    job_id = f"{STUDY_ID}-{task.task_id}-job-{job_index:02d}"
    result = await runner.compile(source, job_id, parameter_values=_parameter_values(task), requested_outputs=_requested_outputs(task))
    topology_ok, topology = _topology(result, task)
    return {"job_id": job_id, "result": _json_safe(asdict(result))}, bool(result.success and topology_ok), topology


def _profile() -> GeminiFlashLiteContractV1:
    repository_profile = GeminiFlashLiteContractV1.from_repository(REPO_ROOT)
    # The repository production profile intentionally retains its historical
    # stage label.  This research runner is explicitly preregistered against
    # the frozen T5 contract and does not alter production routing.
    return replace(
        repository_profile,
        stage_prompt_versions={
            **repository_profile.stage_prompt_versions,
            "geometry": "T5-geometry-exact-slot-contract-v1",
        },
    )


def _write_preregistration(root: Path, tasks: tuple[Any, ...], *, live_authorized: bool) -> dict[str, Any]:
    profile = _profile()
    prompts = [render_geometry_prompt_parameter_access_v1(profile, task.request) for task in tasks]
    prereg = {
        "schema_version": "volundr-t5-parameter-revision-validation-v1",
        "study_id": STUDY_ID,
        "live_authorized": live_authorized,
        "provider_calls": 0,
        "maximum_provider_attempts": MAX_PROVIDER_ATTEMPTS,
        "maximum_worker_jobs": MAX_WORKER_JOBS,
        "credential_environment": "GEMINI_API_KEY_2",
        "no_primary_credential_fallback": True,
        "no_typed_ir_provider_work": True,
        "profile": {
            "model": profile.model,
            "settings": profile.settings,
            "thinking_configuration": profile.thinking_configuration,
            "stage_prompt_versions": profile.stage_prompt_versions,
        },
        "candidate_prompt_version": GEOMETRY_T5_PARAMETER_ACCESS_PROMPT_VERSION,
        "candidate_prompt_contract_version": PROMPT_VERSION,
        "candidate_prompt_hashes": sorted({prompt.prompt_hash for prompt in prompts}),
        "execution_order_seed": ORDER_SEED,
        "retry_policy": "transport-only 429/timeout/502/503/504 retry once; no semantic or malformed retry",
        "production_routing_changed": False,
    }
    _write_json(root / "preregistration.json", prereg)
    _write_json(root / "repository-snapshot.json", _repository_snapshot())
    _write_json(root / "frozen-task-corpus.json", [
        {
            "task_id": task.task_id,
            "task_number": task.task_number,
            "title": task.title,
            "semantic_facts": task.semantic_facts,
            "semantic_facts_hash": task.semantic_facts_hash,
            "revision_authority": task.revision_authority,
            "request": _json_safe(task.request),
        }
        for task in tasks
    ])
    order = build_execution_order(tasks)
    _write_json(root / "execution-order.json", {"seed": ORDER_SEED, "preregistered_before_live": True, "operations": order})
    _write_json(root / "prompt-contract.json", {
        "version": GEOMETRY_T5_PARAMETER_ACCESS_PROMPT_VERSION,
        "base_contract": "T5-geometry-exact-slot-contract-v1",
        "clarification_only": True,
        "prompt_hashes": [prompt.prompt_hash for prompt in prompts],
        "required_parameter_access": 'params["<authorized_parameter_id>"]',
        "forbidden_parameter_access": "params.<authorized_parameter_id>",
        "geometry_strategy_restriction_added": False,
    })
    _write_json(root / "fixture-integrity.json", {
        "schema_version": "volundr-t5-fixture-integrity-v1",
        "study_id": STUDY_ID,
        "status": "not_invalidated",
        "provider_metrics_eligible": True,
        "raw_provider_outputs_preserved": True,
    })
    _write_json(root / "counterfactual-results.json", {
        "schema_version": "volundr-t5-corrected-fixture-counterfactual-v1",
        "study_id": STUDY_ID,
        "synthetic": True,
        "provider_success_eligible": False,
        "provider_calls": 0,
        "worker_calls": 0,
        "rows": [],
    })
    return prereg


def _write_reports(root: Path, tasks: tuple[Any, ...], records: list[dict[str, Any]], attempts: list[dict[str, Any]], limiter: SharedIntegrationRateLimiter, *, live: bool, worker_calls: int) -> dict[str, Any]:
    by_task = {task.task_id: task for task in tasks}
    rows: list[dict[str, Any]] = []
    topology_rows: list[dict[str, Any]] = []
    verification_rows: list[dict[str, Any]] = []
    worker_rows: list[dict[str, Any]] = []
    for record in records:
        task = by_task[record["task_id"]]
        classification = record.get("classification") or {}
        source, static, static_error = _assemble_and_static(task, classification)
        worker = None
        worker_ok = False
        topology = []
        if classification.get("contract_valid") and source and static:
            if record.get("worker") is not None:
                worker = record["worker"]
                worker_ok = bool(record.get("worker_execution"))
                topology = record.get("topology", [])
        candidate = bool(
            classification.get("contract_valid")
            and classification.get("parameter_access_valid")
            and classification.get("semantic_obligations")
            and source
            and static
            and worker_ok
        )
        row = {
            "operation_id": record["operation_id"],
            "task_id": task.task_id,
            "task_number": task.task_number,
            "raw_output": record.get("raw_provider_output"),
            "raw_output_hash": _hash(record.get("raw_provider_output", "")),
            "prompt_hash": record.get("prompt_hash"),
            "attempt_ids": record.get("attempt_ids", []),
            "contract_parse": classification.get("contract_parse"),
            "contract_valid": classification.get("contract_valid"),
            "parameter_access_valid": classification.get("parameter_access_valid"),
            "semantic_obligations": classification.get("semantic_obligations"),
            "revision_preservation": classification.get("revision_preservation"),
            "source_generation": bool(source),
            "static_validation": static,
            "static_error": static_error,
            "worker_execution": worker_ok,
            "worker": worker,
            "topology": topology,
            "topology_verification": bool(topology and all(item.get("valid") is True for item in topology)),
            "requirement_verification": bool(worker_ok and classification.get("semantic_obligations")),
            "candidate_eligible": candidate,
            "failure_classes": classification.get("failure_classes", []),
            "first_incorrect_boundary": classification.get("first_incorrect_boundary"),
            "semantic": classification.get("semantic"),
        }
        rows.append(row)
        topology_rows.append({"task_id": task.task_id, "topology": topology, "passed": row["topology_verification"]})
        verification_rows.append({"task_id": task.task_id, "passed": row["requirement_verification"], "candidate_eligible": candidate})
        if worker is not None:
            worker_rows.append({"task_id": task.task_id, "worker": worker, "passed": worker_ok})
    def rate(field: str) -> float:
        return round(sum(bool(row.get(field)) for row in rows) / len(rows) * 100, 3) if rows else 0.0
    metrics = {
        "logical_operations": len(rows),
        "structural_contract_pass_rate": rate("contract_valid"),
        "parameter_access_rate": rate("parameter_access_valid"),
        "semantic_obligation_rate": rate("semantic_obligations"),
        "revision_preservation_rate": round(sum(row.get("revision_preservation", {}).get("status") == "pass" for row in rows) / max(1, sum(bool(by_task[row["task_id"]].revision_authority) for row in rows)) * 100, 3),
        "source_generation_rate": rate("source_generation"),
        "static_validation_rate": rate("static_validation"),
        "worker_execution_rate": rate("worker_execution"),
        "topology_verification_rate": rate("topology_verification"),
        "requirement_verification_rate": rate("requirement_verification"),
        "candidate_eligibility_rate": rate("candidate_eligible"),
        "provider_failure_count": sum(
            row.get("first_incorrect_boundary") in {"structural_parse", "parameter_access", "contract", "semantic_obligations"}
            for row in rows
        ),
        "runtime_or_downstream_failure_count": sum(
            row.get("first_incorrect_boundary") in {"source_generation", "static_validation", "worker_execution", "topology", "requirement_verification"}
            or (row.get("contract_valid") and not row.get("candidate_eligible") and not row.get("first_incorrect_boundary"))
            for row in rows
        ),
        "runtime_parameter_access_failures": sum("attribute_access_forbidden" in row.get("failure_classes", []) for row in rows),
        "unresolved_fixture_count": sum(bool(row.get("revision_preservation", {}).get("unresolved")) for row in rows),
    }
    decision = {
        "decision": "insufficient_evidence",
        "reason": "provider validation has not been executed" if not live else "see scored task evidence",
        "wave_02_authorized": False,
        "production_routing_changed": False,
    }
    if live and rows:
        revisions = [row for row in rows if by_task[row["task_id"]].revision_authority]
        if all(row["candidate_eligible"] for row in rows) and all(row.get("revision_preservation", {}).get("status") == "pass" for row in revisions):
            decision = {"decision": "wave_02_ready_under_t5", "reason": "all six candidate operations passed mapping access and complete revision authority checks", "wave_02_authorized": True, "production_routing_changed": False}
        elif any("attribute_access_forbidden" in row.get("failure_classes", []) for row in rows):
            decision = {"decision": "t5_parameter_contract_requires_revision", "reason": "provider emitted invalid params attribute access", "wave_02_authorized": False, "production_routing_changed": False}
        elif any(row.get("revision_preservation", {}).get("status") == "provider_failure" for row in revisions):
            decision = {"decision": "revision_workflow_requires_narrow_fix", "reason": "complete prior geometry authority exposed a bounded revision-preservation failure", "wave_02_authorized": False, "production_routing_changed": False}
        else:
            decision = {"decision": "targeted_t5_followup_required", "reason": "candidate validation did not qualify all preregistered operations", "wave_02_authorized": False, "production_routing_changed": False}
    _write_json(root / "provider-attempts.json", attempts)
    _write_json(root / "task-results.json", rows)
    _write_json(root / "metrics.json", metrics)
    _write_json(root / "revision-authority-results.json", [{"task_id": row["task_id"], "result": row.get("revision_preservation")} for row in rows if by_task[row["task_id"]].revision_authority])
    _write_json(root / "worker-results.json", {"jobs_used": worker_calls, "maximum_jobs": MAX_WORKER_JOBS, "results": worker_rows})
    _write_json(root / "topology-results.json", topology_rows)
    _write_json(root / "requirement-verification-results.json", verification_rows)
    _write_json(root / "normalization-report.json", {"normalization_count": 0, "semantic_repairs": 0, "raw_outputs_unchanged": True})
    _write_json(root / "rate-limit-report.json", {"configuration": {"minimum_start_gap_seconds": limiter.minimum_gap_seconds, "hard_max_requests_per_rolling_60_seconds": limiter.hard_max_requests_per_window}, "starts": len(limiter.starts), "events": limiter.events})
    _write_json(root / "retry-report.json", {"maximum_provider_attempts": MAX_PROVIDER_ATTEMPTS, "attempts_used": len(attempts), "retried_operations": [item["operation_id"] for item in attempts if item.get("attempt_index", 0) > 0]})
    _write_json(root / "decision.json", decision)
    combined = {"schema_version": "volundr-t5-parameter-revision-validation-v1", "study_id": STUDY_ID, "provider_calls": len(records), "worker_calls": worker_calls, "provider_attempts": attempts, "records": rows, "metrics": metrics, "decision": decision, "production_routing_changed": False, "typed_ir_provider_work_reopened": False}
    _write_json(root / "combined-evidence.json", combined)
    prereg = _read_json(root / "preregistration.json", {})
    prereg["live_authorized"] = live
    prereg["provider_calls"] = len(records)
    prereg["worker_calls"] = worker_calls
    _write_json(root / "preregistration.json", prereg)
    return {"provider_calls": len(records), "worker_calls": worker_calls, "records": rows, "metrics": metrics, "decision": decision}


def invalidate_live_evidence(root: Path, *, reason: str) -> dict[str, Any]:
    """Retain raw live captures while excluding a run invalidated by a fixture defect."""

    tasks = build_candidate_tasks()
    profile = _profile()
    current_prompts = {
        task.task_id: render_geometry_prompt_parameter_access_v1(profile, task.request).prompt_hash
        for task in tasks
    }
    captures = {
        str(item.get("operation_id")): item
        for path in (root / "operation-captures").glob("*.json")
        for item in [_read_json(path, {})]
        if isinstance(item, dict) and item.get("operation_id")
    }
    rows = _read_json(root / "task-results.json", [])
    old_metrics = _read_json(root / "metrics.json", {})
    mismatches = []
    for task in tasks:
        capture = captures.get(task.task_id)
        if not capture:
            mismatches.append({"task_id": task.task_id, "kind": "missing_capture"})
            continue
        previous_hash = capture.get("prompt_hash")
        if previous_hash != current_prompts[task.task_id]:
            mismatches.append({
                "task_id": task.task_id,
                "kind": "prompt_fixture_hash_mismatch",
                "captured_prompt_hash": previous_hash,
                "current_prompt_hash": current_prompts[task.task_id],
            })
    integrity = {
        "schema_version": "volundr-t5-fixture-integrity-v1",
        "study_id": STUDY_ID,
        "status": "invalidated_harness_fixture",
        "reason": reason,
        "provider_metrics_eligible": False,
        "raw_provider_outputs_preserved": True,
        "provider_calls_repeated": False,
        "worker_calls_repeated": False,
        "captured_logical_operations": len(captures),
        "captured_task_result_rows": len(rows) if isinstance(rows, list) else 0,
        "prompt_fixture_mismatches": mismatches,
        "corrected_fixture_authority": load_revision_authority(),
        "raw_live_run_metrics": old_metrics,
    }
    counterfactual_rows = []
    for task in tasks:
        capture = captures.get(task.task_id)
        raw = str((capture or {}).get("raw_provider_output") or "")
        classification = _classify(task, raw) if raw else {"failure_classes": ["missing_capture"]}
        counterfactual_rows.append({
            "task_id": task.task_id,
            "synthetic": True,
            "provider_success_eligible": False,
            "captured_prompt_hash": (capture or {}).get("prompt_hash"),
            "corrected_fixture_prompt_hash": current_prompts[task.task_id],
            "raw_output_hash": _hash(raw),
            "failure_classes": classification.get("failure_classes", []),
            "first_incorrect_boundary": classification.get("first_incorrect_boundary"),
            "parameter_access_valid": classification.get("parameter_access_valid"),
            "semantic_obligations": classification.get("semantic_obligations"),
            "revision_preservation": classification.get("revision_preservation"),
        })
    decision = {
        "decision": "insufficient_evidence",
        "production_routing_changed": False,
        "wave_02_authorized": False,
        "provider_metrics_eligible": False,
        "reason": "six raw provider responses were retained, but the live run used an incomplete prior-geometry fixture and cannot support a provider gate decision",
    }
    _write_json(root / "fixture-integrity.json", integrity)
    _write_json(root / "counterfactual-results.json", {
        "schema_version": "volundr-t5-corrected-fixture-counterfactual-v1",
        "study_id": STUDY_ID,
        "synthetic": True,
        "provider_success_eligible": False,
        "provider_calls": 0,
        "worker_calls": 0,
        "rows": counterfactual_rows,
    })
    _write_json(root / "metrics.json", {
        "study_valid": False,
        "provider_metrics_eligible": False,
        "logical_operations_attempted": len(captures),
        "eligible_provider_operations": 0,
        "raw_live_run_metrics": old_metrics,
    })
    _write_json(root / "decision.json", decision)
    combined = _read_json(root / "combined-evidence.json", {})
    combined.update({
        "evidence_status": "invalidated_harness_fixture",
        "provider_metrics_eligible": False,
        "raw_live_run_metrics": old_metrics,
        "decision": decision,
        "fixture_integrity": integrity,
        "provider_attempts": _read_json(root / "provider-attempts.json", []),
    })
    _write_json(root / "combined-evidence.json", combined)
    prereg = _read_json(root / "preregistration.json", {})
    prereg.update({"evidence_status": "invalidated_harness_fixture", "provider_metrics_eligible": False})
    _write_json(root / "preregistration.json", prereg)
    return {"decision": decision, "integrity": integrity}


async def run_study(*, root: Path, live: bool, resume: bool = False, worker_root: Path = DEFAULT_WORKER_ROOT) -> dict[str, Any]:
    tasks = build_candidate_tasks()
    root.mkdir(parents=True, exist_ok=True)
    if not (root / "preregistration.json").is_file():
        _write_preregistration(root, tasks, live_authorized=False)
    order = _read_json(root / "execution-order.json", {}).get("operations", [])
    if not order:
        order = build_execution_order(tasks)
        _write_json(root / "execution-order.json", {"seed": ORDER_SEED, "preregistered_before_live": True, "operations": order})
    task_map = {task.task_id: task for task in tasks}
    profile = _profile()
    prompts = {task.task_id: render_geometry_prompt_parameter_access_v1(profile, task.request) for task in tasks}
    captures = root / "operation-captures"
    captures.mkdir(parents=True, exist_ok=True)
    existing: dict[str, dict[str, Any]] = {}
    for path in captures.glob("*.json"):
        item = _read_json(path, {})
        if isinstance(item, dict) and item.get("operation_id"):
            existing[str(item["operation_id"])] = item
    prior_rows = {
        str(item.get("task_id")): item
        for item in (_read_json(root / "task-results.json", []) or [])
        if isinstance(item, dict) and item.get("task_id")
    }
    attempts: list[dict[str, Any]] = [redacted_attempt(item) for item in _read_json(root / "provider-attempts.json", []) if isinstance(item, dict)]
    limiter = SharedIntegrationRateLimiter()
    records: list[dict[str, Any]] = []
    worker_calls = 0
    if not live:
        for item in order:
            record = existing.get(item["operation_id"])
            if record:
                records.append(record)
        return _write_reports(root, tasks, records, attempts, limiter, live=False, worker_calls=worker_calls)
    if not _read_json(root / "execution-order.json", {}).get("preregistered_before_live"):
        raise RuntimeError("execution order was not preregistered before live calls")
    from app.services.research.provider_ir_validation import require_secondary_credential
    require_secondary_credential()
    recorder: list[dict[str, Any]] = []
    client = SecondaryGeminiClient(profile, limiter=limiter, attempt_recorder=recorder.append)
    for item in order:
        task = task_map[item["task_id"]]
        capture = existing.get(task.task_id)
        if capture is None:
            prompt = prompts[task.task_id]
            result = await client.generate(stage="geometry", prompt=prompt.prompt, operation_id=task.task_id, max_attempts=2)
            raw = result.text or ""
            capture = {
                "operation_id": task.task_id,
                "task_id": task.task_id,
                "prompt_hash": prompt.prompt_hash,
                "prompt_version": prompt.prompt_version,
                "raw_provider_output": raw,
                "raw_output_hash": _hash(raw),
                "attempt_ids": [attempt.get("attempt_id") for attempt in result.attempts],
                "provider_model": result.actual_model,
                "usage_metadata": result.usage_metadata,
                "provider_attempt": True,
                "synthetic": False,
            }
            _write_json(captures / f"{task.task_id}.json", capture)
        raw = str(capture.get("raw_provider_output") or "")
        classification = capture.get("classification") or _classify(task, raw)
        record = {**capture, "classification": classification}
        previous = prior_rows.get(task.task_id)
        if previous and previous.get("worker") is not None:
            record["worker"] = previous.get("worker")
            record["worker_execution"] = bool(previous.get("worker_execution"))
            record["topology"] = previous.get("topology", [])
            worker_calls += 1
        records.append(record)
    attempts.extend(redacted_attempt(item) for item in recorder)
    for record in records:
        if record.get("worker") is not None:
            continue
        if record.get("classification", {}).get("contract_valid"):
            source, static, _ = _assemble_and_static(task_map[record["task_id"]], record["classification"])
            if source and static and worker_calls < MAX_WORKER_JOBS:
                worker, passed, topology = await _run_worker(task_map[record["task_id"]], source, worker_root, worker_calls + 1)
                record["worker"] = worker
                record["worker_execution"] = passed
                record["topology"] = topology
                worker_calls += 1
    return _write_reports(root, tasks, records, attempts, limiter, live=True, worker_calls=worker_calls)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument("--worker-root", type=Path, default=DEFAULT_WORKER_ROOT)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--invalidate-fixture", action="store_true")
    args = parser.parse_args()
    if args.invalidate_fixture:
        result = invalidate_live_evidence(
            args.report_root,
            reason="live provider validation was started before the revision authority fixture was proven complete",
        )
        output = {
            "study_id": STUDY_ID,
            "provider_calls": result["integrity"]["captured_logical_operations"],
            "worker_calls": 0,
            "decision": result["decision"]["decision"],
        }
    else:
        result = asyncio.run(run_study(root=args.report_root, live=args.live, resume=args.resume, worker_root=args.worker_root))
        output = {"study_id": STUDY_ID, "provider_calls": result["provider_calls"], "worker_calls": result["worker_calls"], "decision": result["decision"]["decision"]}
    print(json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()
