"""Offline audit and replay of the preserved T5 provider responses."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import cadquery as cq

from app.services.cad.cadquery_contract import CadQueryContractError, validate_cadquery_source
from app.services.cad.cadquery_runner import CadQueryCliRunner
from app.services.gemini_integration.geometry_prompt_narrow_fix import _capabilities
from app.services.research.provider_ir_validation import (
    ProviderStudyTask,
    assemble_t5_source,
    build_frozen_task_corpus,
    classify_t5_response,
)


REVIEW_ID = "t5-corrected-review"
REVIEW_REPORT_NAMES = (
    "original-result-index.json",
    "semantic-operation-recognition.json",
    "evaluator-false-rejections.json",
    "genuine-provider-failures.json",
    "fixture-errors.json",
    "corrected-task-results.json",
    "corrected-metrics.json",
    "worker-rerun-decision.json",
    "wave-02-gate.json",
    "combined-corrected-evidence.json",
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT_ROOT = REPO_ROOT / (
    "data/debug-sessions/representative-workflow-waves/"
    "representative-workflow-wave-01/reports/provider-ir-targeted-validation-01"
)
DEFAULT_REVIEW_ROOT = DEFAULT_REPORT_ROOT / REVIEW_ID
DEFAULT_WORKER_ROOT = REPO_ROOT / (
    "data/debug-sessions/representative-workflow-waves/"
    "representative-workflow-wave-01/worker-jobs/provider-ir-targeted-validation-01"
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


def _hash_text(value: str) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _rate(rows: list[dict[str, Any]], field: str) -> float:
    return round(sum(bool(row.get(field)) for row in rows) / len(rows) * 100, 3) if rows else 0.0


def _parameter_values(task: ProviderStudyTask) -> dict[str, Any]:
    return {
        str(item["id"]): item.get("value", item.get("default"))
        for item in (task.request.design_plan or {}).get("parameters", []) or []
        if isinstance(item, dict) and item.get("id") is not None
    }


def _requested_outputs(task: ProviderStudyTask) -> list[dict[str, Any]]:
    return [
        {
            "output_id": output_id,
            "required": True,
            "expected_solid_count": 1,
            "allow_disconnected_solids": False,
        }
        for output_id in task.output_ids
    ]


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


def _existing_worker_diagnostic(task: ProviderStudyTask, worker_root: Path) -> dict[str, Any] | None:
    job_id = f"{REVIEW_ID}-{task.task_id}"
    stderr_path = worker_root / job_id / "stderr.log"
    if not stderr_path.is_file():
        return None
    return {
        "job_id": job_id,
        "result": {
            "job_id": job_id,
            "source_path": str(worker_root / job_id / "model.py"),
            "stderr_path": str(stderr_path),
            "error_message": stderr_path.read_text(encoding="utf-8"),
            "success": False,
            "diagnostic_replayed_without_worker_call": True,
        },
    }


def _api_compatibility(evidence: dict[str, Any]) -> dict[str, Any]:
    capabilities = _capabilities()
    references: list[dict[str, Any]] = []
    seen: set[str] = set()
    for slot in (evidence.get("t5_validation") or {}).get("slots", []) or []:
        for call in slot.get("cadquery_methods_and_arguments", []) or []:
            method = str(call.get("method"))
            if method in seen:
                continue
            seen.add(method)
            owner: Any = cq.Workplane if hasattr(cq.Workplane, method) else cq
            value = getattr(owner, method, None)
            references.append({
                "method": method,
                "supported": method in capabilities.method_names or method in capabilities.module_names,
                "receiver_owner": "cadquery.Workplane" if owner is cq.Workplane else "cadquery",
                "signature": str(inspect.signature(value)) if callable(value) else None,
                "keywords": list(capabilities.keyword_names.get(method, frozenset())),
            })
    invalid_classes = {"invalid_cadquery_method", "invalid_cadquery_argument"}
    passed = bool(references) and all(item["supported"] for item in references) and not (
        invalid_classes & set(evidence.get("failure_classes", []))
    )
    return {
        "passed": passed,
        "runtime_version": capabilities.version,
        "references": sorted(references, key=lambda item: item["method"]),
    }


def _original_index(report_root: Path, tasks: tuple[ProviderStudyTask, ...]) -> list[dict[str, Any]]:
    arm_rows = {
        str(item.get("task_id")): item
        for item in _read_json(report_root / "arm-a-t5-results.json", [])
        if isinstance(item, dict) and item.get("task_id")
    }
    result: list[dict[str, Any]] = []
    for task in tasks:
        capture_path = report_root / "operation-captures" / f"{task.task_id}_t5.json"
        capture = _read_json(capture_path, {})
        raw = str(capture.get("raw_provider_output") or "")
        original = arm_rows.get(task.task_id, {})
        capture_hash = _hash_text(raw)
        original_hash = str(original.get("raw_response_hash") or capture.get("raw_response_hash") or "")
        if not raw or capture_hash != original_hash:
            raise ValueError(f"immutable raw T5 capture hash mismatch for {task.task_id}")
        result.append({
            "task_id": task.task_id,
            "operation_id": f"{task.task_id}:t5",
            "capture_path": str(capture_path),
            "raw_response_hash": capture_hash,
            "semantic_facts_hash": task.semantic_facts_hash,
            "original_result": {
                key: original.get(key)
                for key in (
                    "contract_parse", "contract_valid", "semantic_obligations", "source_generation",
                    "static_validation", "worker_execution", "topology_verification",
                    "requirement_verification", "candidate_eligible", "failure_classes",
                    "first_incorrect_boundary", "t5_validation",
                )
            },
        })
    return result


async def _run_worker(source: str, task: ProviderStudyTask, worker_root: Path) -> tuple[dict[str, Any], bool, list[dict[str, Any]]]:
    runner = CadQueryCliRunner(workspace_root=worker_root, timeout_seconds=90)
    job_id = f"{REVIEW_ID}-{task.task_id}"
    worker_result = await runner.compile(
        source,
        job_id,
        parameter_values=_parameter_values(task),
        requested_outputs=_requested_outputs(task),
    )
    topology_passed, topology = _topology_evidence(worker_result, task)
    return {
        "job_id": job_id,
        "result": _json_safe(asdict(worker_result)),
    }, bool(worker_result.success and topology_passed), topology


def _worker_requirement(
    task: ProviderStudyTask,
    contract_valid: bool,
    semantic_ok: bool,
    static_ok: bool,
) -> tuple[bool, str]:
    if not contract_valid:
        return False, "runtime/slot contract failure is already established"
    if not static_ok:
        return False, "static validation failed; execution cannot answer the question"
    if not semantic_ok:
        return False, "semantic failure is already independently established"
    if task.task_number == 6:
        return True, "worker is required to settle connectedness of the advanced transition"
    return False, "runtime API, signature, source, and semantic evidence settle this audit question"


def _responsibility_audit(
    task: ProviderStudyTask,
    evidence: dict[str, Any],
    *,
    worker_status: str,
) -> dict[str, Any]:
    recognized = {
        str(item.get("operation")) if isinstance(item, dict) else str(item)
        for item in evidence.get("semantic_operation_recognition", [])
    }
    result_symbol_ok = bool(
        (evidence.get("t5_validation") or {}).get("slots")
        and all(slot.get("observed_result_symbol") == task.output_ids[0] for slot in evidence["t5_validation"]["slots"])
    )
    if task.task_number == 5:
        return {
            "protected_geometry_preservation": "failed_or_unproven",
            "authoritative_locations": "unresolved_fixture_missing_prior_locations",
            "output_identity": "pass" if result_symbol_ok else "fail",
            "hole_diameter_change": "present_as_hole_6mm_but_revision_not_proven",
            "slot_addition": "pass" if "slot" in recognized else "fail",
            "unrelated_geometry_preservation": "unresolved_without_authoritative_prior_geometry",
        }
    if task.task_number == 6:
        return {
            "deterministic_base_exists": "pass" if "box" in {
                call.get("method")
                for slot in (evidence.get("t5_validation") or {}).get("slots", [])
                for call in slot.get("cadquery_methods_and_arguments", [])
            } else "fail",
            "advanced_transition_exists": "pass" if "advanced_transition" in recognized else "fail",
            "connected_geometry": "unresolved_worker_stopped_before_geometry" if worker_status == "prior_diagnostic" else "not_measured",
            "output_identity": "pass" if result_symbol_ok else "fail",
            "unrelated_geometry_substitution": "not_observed",
        }
    return {
        "output_identity": "pass" if result_symbol_ok else "fail",
        "semantic_operation": "pass" if evidence.get("semantic_obligations") else "fail",
    }


def _task_review(
    task: ProviderStudyTask,
    original: dict[str, Any],
    raw: str,
    *,
    execute_worker: bool,
    worker_root: Path,
    prior_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = classify_t5_response(raw, task)
    api = _api_compatibility(evidence)
    runtime_contract_compatibility = "invalid_parameter_access" not in set(evidence.get("failure_classes", []))
    source = evidence.get("assembled_source")
    source_generation = isinstance(source, str) and bool(source)
    static_validation = False
    static_error = None
    if source_generation:
        try:
            validate_cadquery_source(source, contract_version="cadquery-v1")
        except CadQueryContractError as exc:
            static_error = str(exc)
        else:
            static_validation = True
    semantic_ok = bool(evidence.get("semantic_obligations"))
    worker_required, worker_reason = _worker_requirement(
        task,
        bool(evidence.get("contract_valid")),
        semantic_ok,
        static_validation,
    )
    worker_status = "not_run"
    worker_record: dict[str, Any] | None = None
    topology: list[dict[str, Any]] = []
    topology_ok = False
    worker_ok = False
    original_result = original.get("original_result") or {}
    if original_result.get("worker_execution"):
        worker_status = "preserved_success"
        worker_ok = True
        topology_ok = bool(original_result.get("topology_verification"))
        topology = [
            {
                "source": "original provider study report",
                "topology_verification": topology_ok,
            }
        ]
    elif prior_row and prior_row.get("worker_status") in {"executed", "prior_diagnostic"} and prior_row.get("worker"):
        worker_status = "prior_diagnostic"
        worker_record = prior_row.get("worker")
        worker_ok = bool(prior_row.get("worker_execution"))
        topology_ok = bool(prior_row.get("topology_verification"))
        topology = list(prior_row.get("topology") or [])
    elif task.task_number == 6 and (diagnostic := _existing_worker_diagnostic(task, worker_root)):
        worker_status = "prior_diagnostic"
        worker_record = diagnostic
    elif execute_worker and worker_required and source_generation and static_validation:
        worker_record, worker_ok, topology = asyncio.run(_run_worker(source, task, worker_root))
        worker_status = "executed"
        topology_ok = bool(worker_ok)
    candidate = bool(
        evidence.get("contract_valid")
        and semantic_ok
        and api["passed"]
        and source_generation
        and static_validation
        and (worker_ok if worker_required else True)
    )
    recognized = evidence.get("semantic_operation_recognition", [])
    removed_failures = sorted(set(original_result.get("failure_classes") or []) - set(evidence.get("failure_classes") or []))
    evaluator_false_rejections: list[dict[str, Any]] = []
    if removed_failures:
        if task.task_number == 3 and "missing_required_operation" in removed_failures:
            evaluator_false_rejections.append({
                "class": "semantic_operation_alias_gap",
                "removed_failures": removed_failures,
                "recognized": recognized,
                "reason": "slot2D followed by cutBlind is a parsed subtractive slot operation",
            })
        elif task.task_number == 4 and {"missing_required_operation", "required_semantic_operation_missing"} & set(removed_failures):
            evaluator_false_rejections.append({
                "class": "semantic_operation_alias_gap",
                "removed_failures": removed_failures,
                "recognized": recognized,
                "reason": "cboreHole is the pinned-runtime counterbore operation with three positional parameters",
            })
        elif task.task_number == 5:
            evaluator_false_rejections.append({
                "class": "semantic_operation_alias_gap",
                "removed_failures": removed_failures,
                "recognized": recognized,
                "reason": "the added slot is slot2D followed by cutBlind; revision failures remain separate",
            })
        elif task.task_number == 6:
            evaluator_false_rejections.append({
                "class": "raw_escape_fixture_error",
                "removed_failures": removed_failures,
                "recognized": recognized,
                "reason": "T5 already contains raw CadQuery statements and must not require a raw_cadquery label",
            })
    genuine_failures: list[dict[str, Any]] = []
    if not semantic_ok:
        genuine_failures.append({
            "class": "revision_semantic_failure",
            "failure_classes": [
                item for item in evidence.get("failure_classes", [])
                if item in {"authoritative_value_not_preserved", "protected_revision_value_missing", "required_semantic_operation_missing"}
            ],
            "reason": "revision obligations remain independent of valid CadQuery syntax",
        })
    if worker_status in {"executed", "prior_diagnostic"} and not worker_ok:
        worker_error = json.dumps(worker_record or {}, sort_keys=True)
        failure_class = (
            "runtime_parameter_access_mismatch"
            if "ParameterValues" in worker_error and "has no attribute" in worker_error
            else "semantic_geometry_failure"
        )
        genuine_failures.append({
            "class": failure_class,
            "reason": (
                "worker stopped before geometry execution because the T5 source used attribute access on mapping-based ParameterValues"
                if failure_class == "runtime_parameter_access_mismatch"
                else "worker did not produce one valid connected solid for the advanced transition"
            ),
            "topology": topology,
        })
    fixture_errors: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    if task.task_number == 6:
        fixture_errors.append({
            "class": "raw_cadquery_literal_requirement",
            "reason": "the T5 arm is itself the raw-CadQuery escape boundary",
        })
    if task.task_number == 5:
        fixture_errors.append({
            "class": "missing_authoritative_prior_locations",
            "reason": "the frozen revision fixture describes preservation of locations but supplies no authoritative prior location set",
        })
        unresolved.append({
            "class": "authoritative_location_preservation",
            "reason": "cannot compare unchanged locations without prior authoritative locations",
        })
    return {
        "task_id": task.task_id,
        "task_number": task.task_number,
        "title": task.title,
        "raw_response_hash": original["raw_response_hash"],
        "semantic_facts_hash": task.semantic_facts_hash,
        "contract_parse": bool(evidence.get("contract_parse")),
        "contract_valid": bool(evidence.get("contract_valid")),
        "semantic_obligations": semantic_ok,
        "api_compatibility": api,
        "runtime_contract_compatibility": runtime_contract_compatibility,
        "source_generation": source_generation,
        "static_validation": static_validation,
        "static_error": static_error,
        "source_hash": evidence.get("source_hash"),
        "worker_required": worker_required,
        "worker_requirement_reason": worker_reason,
        "worker_status": worker_status,
        "worker_execution": worker_ok,
        "worker": worker_record,
        "topology": topology,
        "topology_verification": topology_ok,
        "responsibility_audit": _responsibility_audit(task, evidence, worker_status=worker_status),
        "candidate_eligible": candidate,
        "first_incorrect_boundary": evidence.get("first_incorrect_boundary"),
        "corrected_failure_classes": evidence.get("failure_classes", []),
        "semantic_operation_recognition": recognized,
        "raw_cadquery_requirement_exempted": any(
            slot.get("raw_cadquery_requirement_exempted")
            for slot in (evidence.get("t5_validation") or {}).get("slots", [])
        ),
        "evaluator_false_rejections": evaluator_false_rejections,
        "genuine_provider_failures": genuine_failures,
        "fixture_errors": fixture_errors,
        "unresolved": unresolved,
        "t5_validation": evidence.get("t5_validation"),
    }


def _corrected_metrics(rows: list[dict[str, Any]], original_index: list[dict[str, Any]]) -> dict[str, Any]:
    original_rows = [item.get("original_result") or {} for item in original_index]
    return {
        "denominator": len(rows),
        "original": {
            "structural_contract_pass_rate": _rate(original_rows, "contract_valid"),
            "semantic_obligation_rate": _rate(original_rows, "semantic_obligations"),
            "api_compatibility_rate": round(sum(
                not ({"invalid_cadquery_method", "invalid_cadquery_argument"} & set(item.get("failure_classes") or []))
                for item in original_rows
            ) / len(original_rows) * 100, 3),
            "runtime_contract_compatibility_rate": "not_measured_by_original_evaluator",
            "source_generation_rate": _rate(original_rows, "source_generation"),
            "static_validation_rate": _rate(original_rows, "static_validation"),
            "worker_execution_rate": _rate(original_rows, "worker_execution"),
            "topology_verification_rate": _rate(original_rows, "topology_verification"),
            "candidate_eligibility_rate": _rate(original_rows, "candidate_eligible"),
        },
        "corrected": {
            "structural_contract_pass_rate": _rate(rows, "contract_valid"),
            "semantic_obligation_rate": _rate(rows, "semantic_obligations"),
            "api_compatibility_rate": _rate(rows, "api_compatibility"),
            "runtime_contract_compatibility_rate": _rate(rows, "runtime_contract_compatibility"),
            "source_generation_rate": _rate(rows, "source_generation"),
            "static_validation_rate": _rate(rows, "static_validation"),
            "worker_execution_rate": _rate(rows, "worker_execution"),
            "topology_verification_rate": _rate(rows, "topology_verification"),
            "candidate_eligibility_rate": _rate(rows, "candidate_eligible"),
        },
        "evaluator_false_rejection_count": sum(bool(item["evaluator_false_rejections"]) for item in rows),
        "evaluator_false_rejection_defect_count": sum(len(item["evaluator_false_rejections"]) for item in rows),
        "genuine_provider_failure_count": sum(bool(item["genuine_provider_failures"]) for item in rows),
        "fixture_error_count": sum(bool(item["fixture_errors"]) for item in rows),
        "unresolved_count": sum(bool(item["unresolved"]) for item in rows),
        "worker_attempt_count": sum(item["worker_status"] in {"executed", "prior_diagnostic"} for item in rows),
        "worker_not_required_count": sum(item["worker_status"] == "not_run" for item in rows),
    }


def run_review(
    *,
    report_root: Path = DEFAULT_REPORT_ROOT,
    review_root: Path = DEFAULT_REVIEW_ROOT,
    execute_worker: bool = False,
    worker_root: Path = DEFAULT_WORKER_ROOT,
) -> dict[str, Any]:
    tasks = build_frozen_task_corpus()
    original_index = _original_index(report_root, tasks)
    prior_rows = {
        str(item.get("task_id")): item
        for item in _read_json(review_root / "corrected-task-results.json", [])
        if isinstance(item, dict) and item.get("task_id")
    }
    task_by_id = {task.task_id: task for task in tasks}
    rows: list[dict[str, Any]] = []
    for original in original_index:
        task = task_by_id[original["task_id"]]
        capture = _read_json(report_root / "operation-captures" / f"{task.task_id}_t5.json", {})
        rows.append(_task_review(
            task,
            original,
            str(capture["raw_provider_output"]),
            execute_worker=execute_worker,
            worker_root=worker_root,
            prior_row=prior_rows.get(task.task_id),
        ))

    false_rejections = [
        {
            "task_id": row["task_id"],
            "items": row["evaluator_false_rejections"],
            "original_failure_classes": next(
                item["original_result"].get("failure_classes", [])
                for item in original_index if item["task_id"] == row["task_id"]
            ),
            "corrected_failure_classes": row["corrected_failure_classes"],
        }
        for row in rows if row["evaluator_false_rejections"]
    ]
    genuine_failures = [
        {"task_id": row["task_id"], "items": row["genuine_provider_failures"]}
        for row in rows if row["genuine_provider_failures"]
    ]
    fixture_errors = [
        {"task_id": row["task_id"], "items": row["fixture_errors"]}
        for row in rows if row["fixture_errors"]
    ]
    unresolved = [
        {"task_id": row["task_id"], "items": row["unresolved"]}
        for row in rows if row["unresolved"]
    ]
    metrics = _corrected_metrics(rows, original_index)
    if metrics["unresolved_count"]:
        decision = "insufficient_evidence"
        reason = "the frozen revision fixture omits authoritative prior locations, so that obligation cannot be audited"
    elif metrics["corrected"]["candidate_eligibility_rate"] >= 66.667:
        decision = "wave_02_ready_under_t5"
        reason = "common T5 operations pass corrected structural, semantic, and runtime-boundary review"
    else:
        decision = "targeted_t5_provider_validation_required"
        reason = "corrected T5 evidence remains below the threshold for a representative wave"
    decision_record = {
        "decision": decision,
        "reason": reason,
        "wave_02_authorized": decision == "wave_02_ready_under_t5",
        "production_routing_changed": False,
        "provider_calls": 0,
        "worker_calls": metrics["worker_attempt_count"],
        "criteria": {
            "all_six_replayed": len(rows) == 6,
            "common_deterministic_tasks_reviewed": all(row["task_number"] <= 4 for row in rows[:4]),
            "unresolved_count_zero": metrics["unresolved_count"] == 0,
            "remaining_limitations_explicit": True,
        },
    }
    worker_decision = {
        "provider_calls": 0,
        "worker_calls": metrics["worker_attempt_count"],
        "policy": "execute only when static and semantic analysis cannot settle a runtime question and the result changes the gate",
        "tasks": [
            {
                "task_id": row["task_id"],
                "worker_required": row["worker_required"],
                "worker_status": row["worker_status"],
                "reason": row["worker_requirement_reason"],
            }
            for row in rows
        ],
    }
    recognition = {
        "runtime_version": _capabilities().version,
        "recognition_policy": {
            "uses_parsed_call_chain": True,
            "uses_receiver_kind": True,
            "uses_runtime_capabilities": True,
            "uses_argument_arity_and_value_expressions": True,
            "uses_boolean_intent": True,
            "uses_authoritative_responsibility": True,
            "literal_substring_matching_for_compound_operations": False,
        },
        "tasks": [
            {
                "task_id": row["task_id"],
                "recognized": row["semantic_operation_recognition"],
                "raw_cadquery_requirement_exempted": row["raw_cadquery_requirement_exempted"],
                "api_compatibility": row["api_compatibility"],
            }
            for row in rows
        ],
    }
    combined = {
        "schema_version": "volundr-t5-corrected-review-v1",
        "review_id": REVIEW_ID,
        "source_study": str(report_root),
        "repository_head": "8d7d93574d0663b0bd42ddf4b3a2db2ccf82b8d0",
        "frozen_contract": "T5-geometry-exact-slot-contract-v1",
        "provider_calls": 0,
        "worker_calls": metrics["worker_attempt_count"],
        "original_evidence_immutable": True,
        "original_result_index": original_index,
        "tasks": rows,
        "metrics": metrics,
        "decision": decision_record,
        "production_routing_changed": False,
        "typed_ir_provider_work_resumed": False,
    }
    _write_json(review_root / "original-result-index.json", original_index)
    _write_json(review_root / "semantic-operation-recognition.json", recognition)
    _write_json(review_root / "evaluator-false-rejections.json", {"count": len(false_rejections), "tasks": false_rejections})
    _write_json(review_root / "genuine-provider-failures.json", {"count": len(genuine_failures), "tasks": genuine_failures})
    _write_json(review_root / "fixture-errors.json", {"count": len(fixture_errors), "tasks": fixture_errors})
    _write_json(review_root / "corrected-task-results.json", rows)
    _write_json(review_root / "corrected-metrics.json", metrics)
    _write_json(review_root / "worker-rerun-decision.json", worker_decision)
    _write_json(review_root / "wave-02-gate.json", decision_record)
    _write_json(review_root / "combined-corrected-evidence.json", combined)
    return {
        "review_id": REVIEW_ID,
        "provider_calls": 0,
        "worker_calls": metrics["worker_attempt_count"],
        "tasks": rows,
        "metrics": metrics,
        "decision": decision_record,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument("--review-root", type=Path, default=DEFAULT_REVIEW_ROOT)
    parser.add_argument("--worker-root", type=Path, default=DEFAULT_WORKER_ROOT)
    parser.add_argument("--execute-worker-task-06", action="store_true")
    args = parser.parse_args()
    result = run_review(
        report_root=args.report_root,
        review_root=args.review_root,
        execute_worker=args.execute_worker_task_06,
        worker_root=args.worker_root,
    )
    print(json.dumps({
        "review_id": result["review_id"],
        "provider_calls": result["provider_calls"],
        "worker_calls": result["worker_calls"],
        "tasks": len(result["tasks"]),
        "decision": result["decision"]["decision"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
