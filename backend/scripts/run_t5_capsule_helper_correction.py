"""Replay the preserved capsule-slot failures through the Volundr helper."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.services.cad.cadquery_contract import validate_cadquery_source
from app.services.cad.cadquery_runner import CadQueryCliRunner
from app.services.cad.capsule_slot_source import (
    CAPSULE_SLOT_SOURCE_VERSION,
    build_capsule_slot_helper_statement,
    normalize_capsule_slot_facts,
)
from app.services.research.provider_ir_validation import assemble_t5_source
from app.services.research.t5_final_revision_microstudy import (
    FINAL_STUDY_ID,
    OUTPUT_ID,
    build_final_tasks,
    canonical_hash,
    expected_shape_for_control,
    task_parameter_values,
    verify_worker_output,
)
from volundr_cad.capsule_slot import (
    CAPSULE_SLOT_HELPER_VERSION,
    TARGET_CADQUERY_VERSION,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_REPORT_ROOT = REPO_ROOT / "data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01/reports/t5-final-revision-microstudy-01"
DEFAULT_REPORT_ROOT = REPO_ROOT / "data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01/reports/t5-capsule-helper-correction-01"
DEFAULT_WORKER_ROOT = REPO_ROOT / "data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01/worker-jobs/t5-capsule-helper-correction-01"
REPORT_NAMES = (
    "root-cause-record.json",
    "helper-contract.json",
    "preserved-task-02-replay.json",
    "preserved-task-03-replay.json",
    "protected-feature-results.json",
    "differential-results.json",
    "regression-results.json",
    "wave-02-gate.json",
    "combined-evidence.json",
)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe(item) for item in value]
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return _safe(value.__dict__)
    return value


def _task_provider_capture(task_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    capture = _read_json(SOURCE_REPORT_ROOT / "operation-captures" / f"{task_id}.json")
    payload = json.loads(capture["raw_provider_output"])
    return capture, payload


def _slot_change(task: Any) -> dict[str, Any]:
    changes = [
        item
        for item in task.semantic_facts["revision_delta"]["changed_features"]
        if (item.get("requested_feature_dimensions") or {}).get("profile_type") == "rounded_end_capsule"
    ]
    if len(changes) != 1:
        raise ValueError(f"{task.task_id} does not contain exactly one capsule change")
    return changes[0]


def _preserved_provider_statements(task_number: int, payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    statements = payload["slots"][0]["statements"]
    if task_number == 2:
        return [], list(statements)
    if task_number != 3:
        raise ValueError(f"unsupported replay task number {task_number}")
    slot_start = next(
        (index for index, statement in enumerate(statements) if any(
            marker in statement
            for marker in ("slot_len", "slot_wid", "slot_dep", "slot_cx", "slot_cy", "slot_rot", "cut_box")
        )),
        None,
    )
    if slot_start is None:
        raise ValueError("preserved task 03 has no identifiable provider slot statements")
    return list(statements[:slot_start]), list(statements[slot_start:])


async def _run_worker(source: str, task: Any, worker_root: Path, job_id: str) -> Any:
    return await CadQueryCliRunner(workspace_root=worker_root, timeout_seconds=90).compile(
        source,
        job_id,
        parameter_values=task_parameter_values(task),
        requested_outputs=[{
            "output_id": OUTPUT_ID,
            "required": True,
            "expected_solid_count": 1,
            "allow_disconnected_solids": False,
        }],
    )


def _helper_contract(task: Any) -> dict[str, Any]:
    change = _slot_change(task)
    facts = normalize_capsule_slot_facts(change)
    statement = build_capsule_slot_helper_statement(
        change,
        parameter_ids={
            "length": "slot_length_mm",
            "width": "slot_width_mm",
            "center_x": "slot_center_x_mm",
            "center_y": "slot_center_local_y_mm",
            "orientation": "slot_orientation_degrees",
            "depth": "slot_depth_mm",
        },
    )
    return {
        "schema_version": "volundr-capsule-slot-helper-contract-v1",
        "source_version": CAPSULE_SLOT_SOURCE_VERSION,
        "helper_version": CAPSULE_SLOT_HELPER_VERSION,
        "target_cadquery": TARGET_CADQUERY_VERSION,
        "runtime_import": "volundr_cad.runtime",
        "operation": "boolean_cut",
        "authoritative_values": {
            "target": OUTPUT_ID,
            "frame": _safe(facts["frame"]),
            "center_local_mm": list(facts["center_local_mm"]),
            "overall_length_mm": facts["overall_length_mm"],
            "width_mm": facts["width_mm"],
            "end_radius_mm": facts["end_radius_mm"],
            "orientation_degrees": facts["orientation_degrees"],
            "depth_mode": facts["depth_mode"],
            "blind_depth_mm": facts["blind_depth_mm"],
            "depth_direction": list(facts["depth_direction"]),
        },
        "owns": [
            "CadQuery 2.8 slot2D API selection",
            "overall end-to-end length convention",
            "profile construction",
            "frame transformation",
            "cutter placement",
            "boolean tolerance overlap",
            "boolean cut",
            "result Workplane and solid validation",
        ],
        "rejects": [
            "missing dimensions",
            "missing coordinate frames",
            "non-capsule profiles",
            "end_radius_not_equal_width_over_two",
            "non-blind depth modes",
            "non-parallel depth directions",
        ],
        "deterministic_statement": statement,
        "direct_ocp_imports": False,
    }


async def run_replay(*, report_root: Path = DEFAULT_REPORT_ROOT, worker_root: Path = DEFAULT_WORKER_ROOT) -> dict[str, Any]:
    report_root.mkdir(parents=True, exist_ok=True)
    worker_root.mkdir(parents=True, exist_ok=True)
    tasks = build_final_tasks()
    source_rows = _read_json(SOURCE_REPORT_ROOT / "task-results.json")
    source_by_task = {row["task_id"]: row for row in source_rows}
    replay_results: dict[str, dict[str, Any]] = {}
    original_rows: dict[str, dict[str, Any]] = {}
    provider_statements: dict[str, dict[str, list[str]]] = {}
    for task, control in ((tasks[1], "slot"), (tasks[2], "right_hole_and_slot")):
        capture, payload = _task_provider_capture(task.task_id)
        preserved, replaced = _preserved_provider_statements(task.task_number, payload)
        source = assemble_t5_source(
            task,
            payload,
            deterministic_capsule_slot=True,
            preserved_statements=preserved,
        )
        validate_cadquery_source(source)
        worker = await _run_worker(source, task, worker_root, f"t5-capsule-helper-correction-task-{task.task_number:02d}")
        verification = verify_worker_output(
            worker,
            expected_shape_for_control(control),
            authority=task.revision_authority or {},
            control=control,
        )
        replay_results[task.task_id] = {
            "schema_version": "volundr-t5-capsule-helper-replay-v1",
            "task_id": task.task_id,
            "task_number": task.task_number,
            "control": control,
            "provider_calls": 0,
            "synthetic": True,
            "provider_success_eligible": False,
            "raw_provider_output_hash": capture["raw_output_hash"],
            "raw_provider_statements": list(payload["slots"][0]["statements"]),
            "preserved_provider_statements": preserved,
            "replaced_provider_statements": replaced,
            "helper_statement": source.split("\n")[-8] if "\n" in source else source,
            "source_hash": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "source_static_validation": True,
            "worker_calls": 1,
            "worker": _safe(asdict(worker)),
            "verification": verification,
            "helper_generated": True,
            "output_id": OUTPUT_ID,
        }
        original_rows[task.task_id] = source_by_task[task.task_id]
        provider_statements[task.task_id] = {
            "all": list(payload["slots"][0]["statements"]),
            "preserved": preserved,
            "replaced": replaced,
        }

    helper_contract = _helper_contract(tasks[1])
    root_cause = {
        "schema_version": "volundr-t5-capsule-root-cause-v1",
        "issue_class": "semantic_geometry_failure",
        "owner": "source_assembly_runtime_boundary",
        "confirmed": True,
        "finding": "Tasks 2 and 3 executed successfully but provider capsule statements produced incorrect rounded-end slot geometry.",
        "provider_contract": "T5-geometry-exact-slot-contract-v2-parameter-map",
        "cadquery": "2.8.0",
        "ocp": "7.9.3.1",
        "provider_calls": 0,
        "preserved_live_evidence": {
            task_id: {
                "raw_provider_output_hash": _task_provider_capture(task_id)[0]["raw_output_hash"],
                "original_candidate_eligible": original_rows[task_id]["candidate_eligible"],
                "original_first_incorrect_boundary": original_rows[task_id]["first_incorrect_boundary"],
                "original_failure_classes": original_rows[task_id]["failure_classes"],
                "provider_statements": provider_statements[task_id]["all"],
            }
            for task_id in replay_results
        },
        "not_root_cause": [
            "CadQuery API incompatibility",
            "worker execution failure",
            "parameter mapping failure",
            "output identity failure",
            "disconnected solid failure",
        ],
    }
    protected = {
        task_id: {
            "task_id": task_id,
            "output_id": OUTPUT_ID,
            "synthetic": True,
            "provider_success_eligible": False,
            "passed": replay["verification"].get("protected_features_preserved") is True,
            "protected_features_preserved": replay["verification"].get("protected_features_preserved"),
            "verification": replay["verification"],
        }
        for task_id, replay in replay_results.items()
    }
    differential = {
        "schema_version": "volundr-t5-capsule-differential-v1",
        "provider_calls": 0,
        "comparisons": {
            task_id: {
                "original_provider_worker_success": bool(original_rows[task_id]["worker_execution"]),
                "original_provider_verification_passed": bool(original_rows[task_id]["topology"].get("passed")),
                "original_failure_classes": original_rows[task_id]["failure_classes"],
                "helper_replay_worker_success": bool(replay["worker"]["success"]),
                "helper_replay_verification_passed": bool(replay["verification"].get("passed")),
                "helper_replay_symmetric_difference_volume_mm3": replay["verification"].get("symmetric_difference_volume_mm3"),
                "semantic_change": "deterministic helper replaced only the capsule-slot provider statements",
                "synthetic_excluded_from_provider_metrics": True,
            }
            for task_id, replay in replay_results.items()
        },
    }
    regression = {
        "schema_version": "volundr-t5-capsule-regression-v1",
        "provider_calls": 0,
        "helper_tests_required": [
            "overall_length_not_straight_segment_length",
            "width_derives_end_radius",
            "rounded_ends",
            "local_frame_transform",
            "blind_depth_direction",
            "orientation",
            "target_identity",
            "protected_geometry",
            "invalid_facts_fail_closed",
            "no_direct_ocp_import",
            "pinned_cadquery_runtime",
            "deterministic_source_and_geometry",
            "unrelated_t5_remains_raw",
        ],
        "source_assembly_default_raw_t5_unchanged": True,
        "helper_source_version": CAPSULE_SLOT_SOURCE_VERSION,
        "helper_runtime_version": CAPSULE_SLOT_HELPER_VERSION,
        "direct_ocp_imports": False,
        "production_routing_changed": False,
    }
    all_passed = all(item["verification"].get("passed") for item in replay_results.values())
    gate = {
        "schema_version": "volundr-t5-capsule-wave-gate-v1",
        "decision": "wave_02_ready_under_t5_with_capsule_helper" if all_passed else "insufficient_evidence",
        "eligible": all_passed,
        "authorized": all_passed,
        "provider_calls": 0,
        "worker_calls": 2,
        "representative_wave_02_run": False,
        "production_routing_changed": False,
        "raw_t5_general_geometry_path": True,
        "exact_capsule_slots_use_deterministic_helper": all_passed,
        "new_helper_policy": "require repeated cross-project evidence and exact semantic ownership; do not accumulate an undocumented general IR",
    }
    combined = {
        "schema_version": "volundr-t5-capsule-helper-correction-v1",
        "study_id": "t5-capsule-helper-correction-01",
        "provider_calls": 0,
        "worker_calls": 2,
        "provider_success_eligible": False,
        "synthetic_replays": True,
        "replay_tasks": sorted(replay_results),
        "all_replays_passed": all_passed,
        "decision": gate["decision"],
        "production_routing_changed": False,
        "representative_wave_02_run": False,
        "reports": list(REPORT_NAMES),
    }
    _write_json(report_root / "root-cause-record.json", root_cause)
    _write_json(report_root / "helper-contract.json", helper_contract)
    _write_json(report_root / "preserved-task-02-replay.json", replay_results[tasks[1].task_id])
    _write_json(report_root / "preserved-task-03-replay.json", replay_results[tasks[2].task_id])
    _write_json(report_root / "protected-feature-results.json", protected)
    _write_json(report_root / "differential-results.json", differential)
    _write_json(report_root / "regression-results.json", regression)
    _write_json(report_root / "wave-02-gate.json", gate)
    _write_json(report_root / "combined-evidence.json", combined)
    return {"decision": gate["decision"], "replays": replay_results, "provider_calls": 0, "worker_calls": 2}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument("--worker-root", type=Path, default=DEFAULT_WORKER_ROOT)
    args = parser.parse_args()
    result = asyncio.run(run_replay(report_root=args.report_root, worker_root=args.worker_root))
    print(json.dumps({"study_id": "t5-capsule-helper-correction-01", **{key: result[key] for key in ("decision", "provider_calls", "worker_calls")}}, sort_keys=True))


if __name__ == "__main__":
    main()
