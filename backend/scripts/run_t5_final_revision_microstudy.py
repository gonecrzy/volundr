"""Certify the T5 revision fixture and run the final three-operation microstudy."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
from dataclasses import asdict, replace
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
from app.services.research.provider_ir_validation import (
    assemble_t5_source,
    redacted_attempt,
    require_secondary_credential,
)
from app.services.research.t5_final_revision_microstudy import (
    AUTHORITY_PATH,
    FINAL_STUDY_ID,
    OUTPUT_ID,
    PROMPT_VERSION,
    authority_source_expression,
    build_final_tasks,
    build_product_source,
    canonical_hash,
    expected_prior_shape,
    expected_shape_for_control,
    file_hash,
    known_good_statements,
    known_good_body_initializer,
    requested_outputs,
    revision_delta_report,
    task_parameter_values,
    verify_worker_output,
)
from app.services.research.t5_parameter_revision_validation import validate_parameter_access


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT_ROOT = REPO_ROOT / "data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01/reports/t5-final-revision-microstudy-01"
DEFAULT_WORKER_ROOT = REPO_ROOT / "data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01/worker-jobs/t5-final-revision-microstudy-01"
ORDER_SEED = "t5-final-revision-microstudy-01-order-v1"
MAX_LOGICAL_OPERATIONS = 3
MAX_PROVIDER_ATTEMPTS = 6
MAX_WORKER_JOBS = 7
REPORT_NAMES = (
    "fixture-certification.json",
    "authority-worker-result.json",
    "feature-verification.json",
    "frozen-hashes.json",
    "known-good-counterfactuals.json",
    "preregistration.json",
    "provider-attempts.json",
    "task-results.json",
    "protected-feature-results.json",
    "wave-02-gate.json",
    "combined-evidence.json",
)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


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


def _git(*args: str) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _profile() -> GeminiFlashLiteContractV1:
    repository_profile = GeminiFlashLiteContractV1.from_repository(REPO_ROOT)
    return replace(
        repository_profile,
        stage_prompt_versions={
            **repository_profile.stage_prompt_versions,
            "geometry": "T5-geometry-exact-slot-contract-v1",
        },
    )


def _repository_snapshot() -> dict[str, Any]:
    return {
        "head": _git("rev-parse", "HEAD"),
        "branch": _git("branch", "--show-current"),
        "worktree_status": _git("status", "--porcelain=v1"),
        "migration_head": "0036_benchmark_model_metadata (head)",
        "cadquery": "2.8.0",
        "ocp": "7.9.3.1",
        "production_routing_changed": False,
        "typed_ir_provider_work_reopened": False,
    }


def _authority_product_source() -> str:
    return build_product_source(
        build_final_tasks()[0],
        [],
    )


def _authority_product_source_without_parameters() -> str:
    return (
        "import cadquery as cq\n"
        "from volundr_cad.runtime import PrintableOutput, Product\n"
        "PARAMETERS = []\n\n"
        "def build(params):\n"
        f"    body = {authority_source_expression()}\n"
        "    return Product(parameters=PARAMETERS, outputs=[PrintableOutput("
        f"output_id={OUTPUT_ID!r}, component_id={OUTPUT_ID!r}, label='Certified prior output', model=body, required=True, expected_solid_count=1, allow_disconnected_solids=False)])\n"
    )


def _worker_payload(result: Any) -> dict[str, Any]:
    return _json_safe(asdict(result))


async def _run_worker(source: str, job_id: str, worker_root: Path, *, parameter_values: dict[str, Any] | None = None) -> Any:
    return await CadQueryCliRunner(workspace_root=worker_root, timeout_seconds=90).compile(
        source,
        job_id,
        parameter_values=parameter_values or {},
        requested_outputs=[{
            "output_id": OUTPUT_ID,
            "required": True,
            "expected_solid_count": 1,
            "allow_disconnected_solids": False,
        }],
    )


def _hash_bundle(tasks: tuple[Any, ...], profile: GeminiFlashLiteContractV1, *, authority_source: str) -> dict[str, Any]:
    prompts = {
        task.task_id: render_geometry_prompt_parameter_access_v1(profile, task.request).prompt_hash
        for task in tasks
    }
    parameter_hashes = {
        task.task_id: canonical_hash(task_parameter_values(task))
        for task in tasks
    }
    manifest_hashes = {
        task.task_id: canonical_hash(task.request.geometry_slot_manifest)
        for task in tasks
    }
    source_assembly = {
        "output_id": OUTPUT_ID,
        "result_symbol": "body",
        "authority_source": authority_source,
    }
    return {
        "fixture_hash": file_hash(AUTHORITY_PATH),
        "authority_source_hash": hashlib.sha256(authority_source_expression().encode("utf-8")).hexdigest(),
        "authority_product_source_hash": hashlib.sha256(authority_source.encode("utf-8")).hexdigest(),
        "manifest_hash": canonical_hash(manifest_hashes),
        "manifest_hashes": manifest_hashes,
        "rendered_prompt_hash": canonical_hash(prompts),
        "rendered_prompt_hashes": prompts,
        "parameter_values_hash": canonical_hash(parameter_hashes),
        "parameter_values_hashes": parameter_hashes,
        "source_assembly_hash": canonical_hash(source_assembly),
        "source_assembly": source_assembly,
        "output_id": OUTPUT_ID,
        "result_symbol": "body",
        "prompt_version": PROMPT_VERSION,
    }


def _hashes_match(root: Path, current: dict[str, Any]) -> dict[str, Any]:
    frozen = _read_json(root / "frozen-hashes.json", {})
    keys = (
        "fixture_hash",
        "authority_source_hash",
        "authority_product_source_hash",
        "manifest_hash",
        "rendered_prompt_hash",
        "parameter_values_hash",
        "source_assembly_hash",
        "output_id",
        "result_symbol",
    )
    mismatches = [key for key in keys if frozen.get(key) != current.get(key)]
    return {"passed": not mismatches, "mismatches": mismatches, "frozen": frozen, "current": current}


def _write_empty_provider_reports(root: Path) -> None:
    _write_json(root / "provider-attempts.json", [])
    _write_json(root / "task-results.json", [])
    _write_json(root / "protected-feature-results.json", [])
    _write_json(root / "wave-02-gate.json", {
        "decision": "insufficient_evidence",
        "eligible": False,
        "authorized": False,
        "reason": "provider microstudy has not run",
        "production_routing_changed": False,
    })


async def run_certification(*, root: Path, worker_root: Path) -> dict[str, Any]:
    """Run the authority worker and all three known-good controls without a provider."""

    root.mkdir(parents=True, exist_ok=True)
    worker_root.mkdir(parents=True, exist_ok=True)
    tasks = build_final_tasks()
    authority_source = _authority_product_source_without_parameters()
    authority_expected = expected_prior_shape()
    authority_worker = await _run_worker(authority_source, f"{FINAL_STUDY_ID}-authority", worker_root)
    authority_verification = verify_worker_output(
        authority_worker,
        authority_expected,
        authority=tasks[0].revision_authority or {},
        control="prior",
    )

    controls: list[dict[str, Any]] = []
    controls_by_task = {
        tasks[0].task_id: "left_hole",
        tasks[1].task_id: "slot",
        tasks[2].task_id: "right_hole_and_slot",
    }
    for task in tasks:
        control = controls_by_task[task.task_id]
        source = build_product_source(
            task,
            known_good_statements(control),
            body_initializer=known_good_body_initializer(control),
        )
        validate_cadquery_source(source, contract_version="cadquery-v1")
        worker = await _run_worker(
            source,
            f"{FINAL_STUDY_ID}-control-{control}",
            worker_root,
            parameter_values=task_parameter_values(task),
        )
        verification = verify_worker_output(
            worker,
            expected_shape_for_control(control),
            authority=task.revision_authority or {},
            control=control,
        )
        controls.append({
            "task_id": task.task_id,
            "control": control,
            "synthetic": True,
            "provider_success_eligible": False,
            "output_id": OUTPUT_ID,
            "source_hash": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "worker": _worker_payload(worker),
            "verification": verification,
        })

    profile = _profile()
    hashes = _hash_bundle(tasks, profile, authority_source=authority_source)
    certification_passed = bool(
        authority_worker.success
        and authority_verification.get("passed")
        and len(controls) == 3
        and all(item["verification"].get("passed") for item in controls)
        and all(item["output_id"] == OUTPUT_ID for item in controls)
    )
    certification = {
        "schema_version": "volundr-t5-final-fixture-certification-v1",
        "study_id": FINAL_STUDY_ID,
        "status": "passed" if certification_passed else "failed",
        "provider_calls": 0,
        "worker_calls": 4,
        "authority_id": tasks[0].revision_authority["authority_id"],
        "output_id": OUTPUT_ID,
        "result_symbol": "body",
        "hashes": hashes,
        "authority_verification_passed": authority_verification.get("passed"),
        "known_good_controls_passed": all(item["verification"].get("passed") for item in controls),
        "no_provider_call_started": True,
    }
    _write_json(root / "fixture-certification.json", certification)
    _write_json(root / "authority-worker-result.json", {
        "output_id": OUTPUT_ID,
        "source_hash": hashes["authority_product_source_hash"],
        "worker": _worker_payload(authority_worker),
        "verification": authority_verification,
    })
    _write_json(root / "feature-verification.json", {
        "authority": authority_verification,
        "known_good_controls": [{"task_id": item["task_id"], "control": item["control"], "verification": item["verification"]} for item in controls],
        "output_id": OUTPUT_ID,
        "protected_features_verified": bool(authority_verification.get("passed") and all(item["verification"].get("passed") for item in controls)),
    })
    _write_json(root / "frozen-hashes.json", hashes)
    _write_json(root / "known-good-counterfactuals.json", {
        "schema_version": "volundr-t5-known-good-counterfactuals-v1",
        "provider_calls": 0,
        "worker_calls": 3,
        "controls": controls,
        "synthetic": True,
        "provider_success_eligible": False,
    })
    _write_json(root / "preregistration.json", {
        "schema_version": "volundr-t5-final-revision-microstudy-v1",
        "study_id": FINAL_STUDY_ID,
        "live_authorized": certification_passed,
        "provider_calls": 0,
        "logical_provider_operations": MAX_LOGICAL_OPERATIONS,
        "maximum_provider_attempts": MAX_PROVIDER_ATTEMPTS,
        "maximum_worker_jobs": MAX_WORKER_JOBS,
        "execution_order_seed": ORDER_SEED,
        "execution_order": [task.task_id for task in tasks],
        "credential_environment": "GEMINI_API_KEY_2",
        "no_primary_credential_fallback": True,
        "model": profile.model,
        "provider_profile": profile.profile_id,
        "settings": profile.settings,
        "thinkingConfig": "omitted",
        "stage_prompt_versions": {"requirements": "T2-requirements-missing-fit-v1", "plan": "T0-current", "geometry": "T5-geometry-exact-slot-contract-v1"},
        "candidate_prompt_version": GEOMETRY_T5_PARAMETER_ACCESS_PROMPT_VERSION,
        "output_id": OUTPUT_ID,
        "result_symbol": "body",
        "production_routing_changed": False,
        "certification_status": certification["status"],
    })
    _write_empty_provider_reports(root)
    _write_json(root / "combined-evidence.json", {
        "schema_version": "volundr-t5-final-revision-microstudy-v1",
        "study_id": FINAL_STUDY_ID,
        "fixture_certification": certification,
        "provider_calls": 0,
        "worker_calls": 4,
        "provider_metrics_eligible": False,
        "production_routing_changed": False,
        "decision": "insufficient_evidence" if not certification_passed else "pending_provider_microstudy",
    })
    return {"certification": certification, "controls": controls, "hashes": hashes}


def _strict_payload(raw: str) -> tuple[dict[str, Any] | None, list[str]]:
    text = raw.strip()
    if not text.startswith("{") or not text.endswith("}") or "```" in raw:
        return None, ["structural_parse_failure"]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None, ["structural_parse_failure"]
    if not isinstance(payload, dict) or payload.get("schema_version") != "volundr-geometry-slots-v1" or not isinstance(payload.get("slots"), list):
        return None, ["structural_parse_failure"]
    return payload, []


def _statements(payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(payload, dict):
        return []
    statements: list[str] = []
    for slot in payload.get("slots", []) or []:
        if isinstance(slot, dict) and isinstance(slot.get("statements"), list):
            statements.extend(item for item in slot["statements"] if isinstance(item, str))
    return statements


def _semantic_revision_check(task: Any, statements: list[str]) -> dict[str, Any]:
    authorized = {
        str(item["id"])
        for item in (task.request.design_plan or {}).get("parameters", []) or []
        if isinstance(item, dict) and item.get("id") is not None
    }
    access = validate_parameter_access(statements, authorized)
    required = set(task.semantic_facts.get("required_parameter_ids", []))
    missing = sorted(required - set(access.get("observed_ids", [])))
    failures = list(access.get("failures", []))
    if missing:
        failures.append("required_parameter_access_missing")
    if not any(statement.lstrip().startswith("body =") for statement in statements):
        failures.append("result_symbol_not_assigned")
    if any(statement.lstrip().startswith("body = cq.") for statement in statements):
        failures.append("protected_prior_body_reconstructed")
    if any(token in "\n".join(statements) for token in ("body.translate(", "body.rotate(", "body.scale(")):
        failures.append("protected_prior_body_transformed")
    delta = task.semantic_facts["revision_delta"]
    for change in delta["changed_features"]:
        if change.get("changed_feature_id") == "cable_retention_slot":
            requested = change["requested_feature_dimensions"]
            if requested.get("profile_type") != "rounded_end_capsule":
                failures.append("slot_profile_not_capsule")
            if requested.get("end_radius_mm") != requested.get("width_mm", 0) / 2:
                failures.append("slot_end_radius_not_derived")
            if not all(
                str(parameter_id) in access.get("observed_ids", [])
                for parameter_id in ("slot_length_mm", "slot_width_mm", "slot_depth_mm", "slot_center_x_mm", "slot_center_local_y_mm", "slot_orientation_degrees")
            ):
                failures.append("slot_parameter_access_incomplete")
        else:
            parameter_id = change.get("parameter_id")
            if parameter_id not in access.get("observed_ids", []):
                failures.append(f"changed_feature_parameter_missing:{parameter_id}")
    return {
        "passed": not failures,
        "failures": sorted(set(failures)),
        "parameter_access": access,
        "required_parameter_ids": sorted(required),
        "missing_parameter_ids": missing,
        "revision_delta": revision_delta_report(task),
    }


def _classify_provider_response(task: Any, raw: str) -> dict[str, Any]:
    payload, parse_failures = _strict_payload(raw)
    if payload is None:
        return {
            "contract_parse": False,
            "contract_valid": False,
            "parameter_access_valid": False,
            "semantic_obligations": False,
            "failure_classes": parse_failures,
            "first_incorrect_boundary": "structural_parse",
            "payload": None,
            "statements": [],
            "validation": {"passed": False, "failure_classes": parse_failures},
            "semantic": {"passed": False, "failures": parse_failures},
        }
    validation = T5GeometryValidator().validate(raw, task.request)
    statements = _statements(payload)
    semantic = _semantic_revision_check(task, statements)
    failures = sorted(set(list(validation.get("failure_classes", []) or []) + list(semantic.get("failures", []) or [])))
    contract_valid = bool(validation.get("passed"))
    parameter_valid = bool(semantic.get("parameter_access", {}).get("passed"))
    first_boundary = None
    if not contract_valid:
        first_boundary = "contract"
    elif not parameter_valid:
        first_boundary = "parameter_access"
    elif not semantic.get("passed"):
        first_boundary = "semantic_obligations"
    return {
        "contract_parse": True,
        "contract_valid": contract_valid,
        "parameter_access_valid": parameter_valid,
        "semantic_obligations": bool(semantic.get("passed")),
        "failure_classes": failures,
        "first_incorrect_boundary": first_boundary,
        "payload": payload,
        "statements": statements,
        "validation": validation,
        "semantic": semantic,
    }


def _assemble_static(task: Any, classification: dict[str, Any]) -> tuple[str | None, bool, str | None]:
    payload = classification.get("payload")
    if not isinstance(payload, dict):
        return None, False, "no parsed payload"
    try:
        source = assemble_t5_source(task, payload)
        validate_cadquery_source(source, contract_version="cadquery-v1")
    except (CadQueryContractError, KeyError, TypeError, ValueError) as exc:
        return None, False, str(exc)
    return source, True, None


def _task_row(task: Any, record: dict[str, Any], *, expected: Any, worker_calls: int) -> dict[str, Any]:
    classification = record.get("classification") or {}
    source, static, static_error = _assemble_static(task, classification)
    worker_payload = record.get("worker")
    worker_ok = bool(record.get("worker_execution"))
    feature_verification = record.get("feature_verification") or {"passed": False, "failures": ["worker_not_run"]}
    output_identity = feature_verification.get("output_identity") == OUTPUT_ID
    candidate = bool(
        classification.get("contract_valid")
        and classification.get("parameter_access_valid")
        and classification.get("semantic_obligations")
        and source
        and static
        and worker_ok
        and feature_verification.get("passed")
        and output_identity
    )
    first_boundary = classification.get("first_incorrect_boundary")
    if first_boundary is None and not source:
        first_boundary = "source_assembly"
    elif first_boundary is None and not static:
        first_boundary = "static_validation"
    elif first_boundary is None and not worker_ok:
        first_boundary = "worker_execution"
    elif first_boundary is None and not feature_verification.get("passed"):
        first_boundary = "topology_or_feature_verification"
    failure_classes = list(classification.get("failure_classes", []))
    if not feature_verification.get("passed") and worker_ok:
        failure_classes.append("semantic_geometry_failure")
    return {
        "operation_id": record["operation_id"],
        "task_id": task.task_id,
        "task_number": task.task_number,
        "output_id": OUTPUT_ID,
        "result_symbol": "body",
        "raw_provider_output": record.get("raw_provider_output"),
        "raw_output_hash": canonical_hash(record.get("raw_provider_output", "")),
        "prompt_hash": record.get("prompt_hash"),
        "attempt_ids": record.get("attempt_ids", []),
        "contract_parse": classification.get("contract_parse"),
        "contract_valid": classification.get("contract_valid"),
        "parameter_access_valid": classification.get("parameter_access_valid"),
        "authorized_parameter_ids": classification.get("semantic", {}).get("parameter_access", {}).get("authorized_ids", []),
        "observed_parameter_ids": classification.get("semantic", {}).get("parameter_access", {}).get("observed_ids", []),
        "runtime_api_receiver_compatibility": bool(
            classification.get("contract_valid")
            and not any(item in classification.get("failure_classes", []) for item in ("invalid_cadquery_method", "invalid_cadquery_argument"))
        ),
        "revision_delta_fulfillment": classification.get("semantic", {}).get("revision_delta"),
        "protected_feature_preservation": feature_verification.get("protected_features_preserved", False),
        "source_assembly": {"passed": bool(source), "source_hash": hashlib.sha256(source.encode("utf-8")).hexdigest() if source else None, "output_id": OUTPUT_ID, "result_symbol": "body"},
        "static_validation": static,
        "static_error": static_error,
        "worker_execution": worker_ok,
        "worker_calls_used": worker_calls,
        "worker": worker_payload,
        "solid_count": feature_verification.get("solid_count"),
        "topology": feature_verification,
        "changed_feature_verification": feature_verification,
        "output_identity": output_identity,
        "candidate_eligible": candidate,
        "failure_classes": sorted(set(failure_classes)),
        "first_incorrect_boundary": first_boundary,
        "semantic": classification.get("semantic"),
        "semantic_obligations": bool(classification.get("semantic_obligations")),
        "topology_verification": bool(feature_verification.get("passed")),
        "provider_owned_failure": bool(
            not candidate
            and first_boundary in {"semantic_obligations", "topology_or_feature_verification"}
        ),
        "runtime_api_failure": bool(
            any(item in classification.get("failure_classes", []) for item in ("invalid_cadquery_method", "invalid_cadquery_argument"))
        ),
        "normalization_count": int(classification.get("validation", {}).get("parse_fence_normalizations") or 0),
        "unrecoverable_ambiguity": bool("ambiguous" in classification.get("failure_classes", [])),
        "synthetic": False,
        "provider_success_eligible": True,
        "expected_control": expected,
    }


def _decision(rows: list[dict[str, Any]], certification: dict[str, Any]) -> dict[str, Any]:
    if certification.get("status") != "passed":
        return {"decision": "insufficient_evidence", "wave_02_authorized": False, "reason": "fixture certification did not pass", "production_routing_changed": False}
    eligible = sum(bool(row.get("candidate_eligible")) for row in rows)
    if eligible >= 2:
        return {"decision": "wave_02_ready_under_t5", "wave_02_authorized": True, "reason": f"{eligible} of 3 certified revision operations were eligible", "production_routing_changed": False}
    boundaries = [row.get("first_incorrect_boundary") for row in rows if not row.get("candidate_eligible")]
    if boundaries and len(set(boundaries)) == 1 and boundaries[0] in {"parameter_access", "semantic_obligations", "contract"}:
        return {"decision": "revision_workflow_requires_narrow_fix", "wave_02_authorized": False, "reason": f"shared provider revision boundary failure: {boundaries[0]}", "production_routing_changed": False}
    if any(boundary in {"worker_execution", "topology_or_feature_verification"} for boundary in boundaries) and eligible < 2:
        if all(boundary == "topology_or_feature_verification" for boundary in boundaries):
            return {
                "decision": "targeted_t5_followup_required",
                "wave_02_authorized": False,
                "reason": "provider responses executed, but the capsule-slot semantic obligation failed downstream",
                "production_routing_changed": False,
            }
        return {"decision": "insufficient_evidence", "wave_02_authorized": False, "reason": "worker failures prevented interpretation", "production_routing_changed": False}
    return {"decision": "targeted_t5_followup_required", "wave_02_authorized": False, "reason": "one precise provider behavior remains unresolved", "production_routing_changed": False}


def replay_live_report(*, root: Path) -> dict[str, Any]:
    """Reclassify captured live responses without contacting the provider.

    This is intentionally separate from ``run_live``: it may correct report
    boundary accounting after an offline harness bug, but it never regenerates
    or changes provider output.
    """
    certification = _read_json(root / "fixture-certification.json", {})
    if certification.get("status") != "passed":
        raise RuntimeError("live replay refused: fixture certification did not pass")
    old_rows = _read_json(root / "task-results.json", [])
    if not isinstance(old_rows, list) or len(old_rows) != MAX_LOGICAL_OPERATIONS:
        raise RuntimeError("live replay refused: exactly three captured task results are required")
    tasks = build_final_tasks()
    task_map = {task.task_id: task for task in tasks}
    controls = {
        tasks[0].task_id: "left_hole",
        tasks[1].task_id: "slot",
        tasks[2].task_id: "right_hole_and_slot",
    }
    rows: list[dict[str, Any]] = []
    for old in old_rows:
        task = task_map[old["task_id"]]
        capture = _read_json(root / "operation-captures" / f"{task.task_id}.json", {})
        classification = _classify_provider_response(task, str(capture.get("raw_provider_output") or ""))
        saved_worker = old.get("worker")
        saved_verification = old.get("topology") or {"passed": False, "failures": ["missing_saved_verification"]}
        record = {
            **capture,
            "operation_id": task.task_id,
            "task_id": task.task_id,
            "classification": classification,
            "worker": saved_worker,
            "worker_execution": bool(isinstance(saved_worker, dict) and saved_worker.get("success")),
            "feature_verification": saved_verification,
        }
        rows.append(_task_row(task, record, expected=controls[task.task_id], worker_calls=3))
    decision = _decision(rows, certification)
    attempts = _read_json(root / "provider-attempts.json", [])
    protected = [{
        "task_id": row["task_id"],
        "output_id": OUTPUT_ID,
        "protected_feature_preservation": row.get("protected_feature_preservation"),
        "changed_feature_verification": row.get("changed_feature_verification"),
        "passed": row.get("candidate_eligible"),
    } for row in rows]
    _write_json(root / "task-results.json", rows)
    _write_json(root / "protected-feature-results.json", protected)
    _write_json(root / "wave-02-gate.json", {
        "decision": decision["decision"],
        "eligible": decision["decision"] == "wave_02_ready_under_t5",
        "authorized": bool(decision.get("wave_02_authorized")),
        "representative_wave_02_run": False,
        "provider_operations": len(rows),
        "production_routing_changed": False,
        "reason": decision["reason"],
    })
    prereg = _read_json(root / "preregistration.json", {})
    _write_json(root / "preregistration.json", {**prereg, "final_decision": decision["decision"], "report_replay_provider_calls": 0})
    combined = _read_json(root / "combined-evidence.json", {})
    combined.update({
        "records": rows,
        "decision": decision,
        "provider_calls": 3,
        "worker_calls": 7,
        "report_replay_provider_calls": 0,
        "production_routing_changed": False,
        "representative_wave_02_run": False,
    })
    _write_json(root / "combined-evidence.json", combined)
    return {"records": rows, "decision": decision, "provider_calls": 0}


async def run_live(*, root: Path, worker_root: Path) -> dict[str, Any]:
    tasks = build_final_tasks()
    certification = _read_json(root / "fixture-certification.json", {})
    if certification.get("status") != "passed":
        raise RuntimeError("live provider call refused: fixture certification did not pass")
    profile = _profile()
    current_hashes = _hash_bundle(tasks, profile, authority_source=_authority_product_source_without_parameters())
    hash_check = _hashes_match(root, current_hashes)
    if not hash_check["passed"]:
        raise RuntimeError(f"live provider call refused: frozen hashes disagree: {hash_check['mismatches']}")
    prereg = _read_json(root / "preregistration.json", {})
    if prereg.get("live_authorized") is not True:
        raise RuntimeError("live provider call refused: preregistration is not authorized")
    order = prereg.get("execution_order") or [task.task_id for task in tasks]
    if len(order) != MAX_LOGICAL_OPERATIONS or set(order) != {task.task_id for task in tasks}:
        raise RuntimeError("live provider call refused: execution order is not the frozen three-operation order")

    require_secondary_credential()
    limiter = SharedIntegrationRateLimiter()
    attempts: list[dict[str, Any]] = []
    client = SecondaryGeminiClient(profile, limiter=limiter, attempt_recorder=attempts.append)
    task_map = {task.task_id: task for task in tasks}
    prompts = {task.task_id: render_geometry_prompt_parameter_access_v1(profile, task.request) for task in tasks}
    records: list[dict[str, Any]] = []
    worker_calls = 0
    controls = {
        tasks[0].task_id: "left_hole",
        tasks[1].task_id: "slot",
        tasks[2].task_id: "right_hole_and_slot",
    }
    for task_id in order:
        task = task_map[task_id]
        prompt = prompts[task_id]
        result = await client.generate(
            stage="geometry",
            prompt=prompt.prompt,
            operation_id=task_id,
            max_attempts=2,
        )
        raw = result.text or ""
        capture = {
            "operation_id": task_id,
            "task_id": task_id,
            "prompt_hash": prompt.prompt_hash,
            "prompt_version": prompt.prompt_version,
            "raw_provider_output": raw,
            "raw_output_hash": canonical_hash(raw),
            "attempt_ids": [attempt.get("attempt_id") for attempt in result.attempts],
            "provider_model": result.actual_model,
            "usage_metadata": result.usage_metadata,
            "provider_attempt": True,
            "synthetic": False,
            "output_id": OUTPUT_ID,
        }
        _write_json(root / "operation-captures" / f"{task_id}.json", capture)
        classification = _classify_provider_response(task, raw)
        record = {**capture, "classification": classification}
        if classification.get("contract_valid"):
            source, static, static_error = _assemble_static(task, classification)
            if source and static:
                try:
                    worker = await _run_worker(
                        source,
                        f"{FINAL_STUDY_ID}-{task.task_number:02d}-provider",
                        worker_root,
                        parameter_values=task_parameter_values(task),
                    )
                    worker_calls += 1
                    verification = verify_worker_output(
                        worker,
                        expected_shape_for_control(controls[task_id]),
                        authority=task.revision_authority or {},
                        control=controls[task_id],
                    )
                    record.update({
                        "worker": _worker_payload(worker),
                        "worker_execution": bool(
                            worker.success
                            and any(bool(output.success) for output in worker.outputs)
                        ),
                        "feature_verification": verification,
                    })
                except Exception as exc:  # preserve one task's downstream failure and continue the fixed study
                    worker_calls += 1
                    record.update({
                        "worker": None,
                        "worker_execution": False,
                        "feature_verification": {"passed": False, "failures": ["worker_exception"], "error": str(exc), "output_id": OUTPUT_ID},
                    })
            else:
                record.update({
                    "worker": None,
                    "worker_execution": False,
                    "feature_verification": {"passed": False, "failures": ["static_validation"], "error": static_error, "output_id": OUTPUT_ID},
                })
        records.append(record)

    redacted_attempts = [redacted_attempt(item) for item in attempts]
    rows = []
    for record in records:
        task = task_map[record["task_id"]]
        row = _task_row(task, record, expected=controls[task.task_id], worker_calls=worker_calls)
        rows.append(row)
    decision = _decision(rows, certification)
    protected = [{
        "task_id": row["task_id"],
        "output_id": OUTPUT_ID,
        "protected_feature_preservation": row.get("protected_feature_preservation"),
        "changed_feature_verification": row.get("changed_feature_verification"),
        "passed": row.get("candidate_eligible"),
    } for row in rows]
    _write_json(root / "provider-attempts.json", redacted_attempts)
    _write_json(root / "task-results.json", rows)
    _write_json(root / "protected-feature-results.json", protected)
    _write_json(root / "wave-02-gate.json", {
        "decision": decision["decision"],
        "eligible": decision["decision"] == "wave_02_ready_under_t5",
        "authorized": bool(decision.get("wave_02_authorized")),
        "representative_wave_02_run": False,
        "provider_operations": len(rows),
        "production_routing_changed": False,
        "reason": decision["reason"],
    })
    _write_json(root / "preregistration.json", {**prereg, "provider_calls": len(records), "worker_calls": worker_calls, "final_decision": decision["decision"]})
    combined = {
        "schema_version": "volundr-t5-final-revision-microstudy-v1",
        "study_id": FINAL_STUDY_ID,
        "fixture_certification": certification,
        "frozen_hashes": current_hashes,
        "hash_check": hash_check,
        "provider_attempts": redacted_attempts,
        "records": rows,
        "provider_calls": len(records),
        "worker_calls": worker_calls + 4,
        "provider_metrics_eligible": True,
        "decision": decision,
        "output_id": OUTPUT_ID,
        "production_routing_changed": False,
        "representative_wave_02_run": False,
    }
    _write_json(root / "combined-evidence.json", combined)
    return {"records": rows, "attempts": redacted_attempts, "decision": decision, "worker_calls": worker_calls}


async def run_study(*, root: Path, worker_root: Path, live: bool) -> dict[str, Any]:
    if not live:
        return await run_certification(root=root, worker_root=worker_root)
    return await run_live(root=root, worker_root=worker_root)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument("--worker-root", type=Path, default=DEFAULT_WORKER_ROOT)
    parser.add_argument("--certify", action="store_true", help="run offline certification only")
    parser.add_argument("--live", action="store_true", help="run exactly three provider operations after certification")
    parser.add_argument("--replay-live", action="store_true", help="reclassify captured live results without provider calls")
    args = parser.parse_args()
    if sum(bool(item) for item in (args.certify, args.live, args.replay_live)) > 1:
        raise SystemExit("choose --certify, --live, or --replay-live")
    result = replay_live_report(root=args.report_root) if args.replay_live else asyncio.run(run_study(root=args.report_root, worker_root=args.worker_root, live=args.live))
    if "decision" in result:
        decision = result["decision"].get("decision") if isinstance(result["decision"], dict) else result["decision"]
    else:
        decision = result["certification"]["status"]
    print(json.dumps({"study_id": FINAL_STUDY_ID, "live": args.live, "decision": decision}, sort_keys=True))


if __name__ == "__main__":
    main()
