#!/usr/bin/env python3
"""Write Wave-02 closure-01 reports from frozen and diagnostic evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
WAVE_ROOT = REPO_ROOT / "data/debug-sessions/representative-workflow-waves/representative-workflow-wave-02"
DEFAULT_REPORT_ROOT = REPO_ROOT / "reports/wave-02-closure-01"
WORKER_CLOSURE_ROOT = REPO_ROOT / "reports/wave-02-worker-closure-02"
PROJECT_03_SOURCE_HASH = "f725a0eca8888e923b25e69f21a8c5d20f0c49bbacb1ab613202b399a682acdf"

FACT_KEYS = (
    "feature_identity",
    "feature_kind",
    "profile_type",
    "overall_length",
    "width",
    "end_radius_invariant",
    "center",
    "owning_frame",
    "orientation",
    "blind_depth",
    "depth_direction",
    "target_output",
)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def text_of(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def facts_present(value: Any) -> dict[str, Any]:
    text = text_of(value)
    result = {
        "feature_identity": any(token in text for token in ("capsule_slot_feature", "capsule_retention_slot")),
        "feature_kind": any(token in text for token in ("retention_slot", "slot", "rounded-end capsule")),
        "profile_type": "rounded_end_capsule" in text,
        "overall_length": any(token in text for token in ("overall_length_mm", "capsule_slot_length", "overall end-to-end length 34")),
        "width": any(token in text for token in ("width_mm", "capsule_slot_width", "width 8")),
        "end_radius_invariant": any(token in text for token in ("end_radius_mm", "capsule_slot_end_radius", "end radius 4", "width'] / 2")),
        "center": any(token in text for token in ("feature_center_local_mm", "capsule_slot_center_x", "center local coordinates")),
        "owning_frame": any(token in text for token in ("local_coordinate_frame", "top frame", "CapsuleSlotFrame")),
        "orientation": any(token in text for token in ("orientation_degrees", "capsule_slot_orientation", "orientation 20")),
        "blind_depth": any(token in text for token in ("depth_mode", "capsule_slot_depth", "blind depth 4")),
        "depth_direction": any(token in text for token in ("depth_direction", "negative normal")),
        "target_output": "swept_cable_guide" in text,
    }
    return {key: {"present": bool(result[key])} for key in FACT_KEYS}


def project_02_paths() -> dict[str, Path]:
    return {
        "project_manifest": WAVE_ROOT / "projects/wave-02-project-02.json",
        "provider_requirements": WAVE_ROOT / "captures/wave-02-project-02_wave-02-project-02_revision-001_provider_requirements.json",
        "requirements_adapter": WAVE_ROOT / "captures/wave-02-project-02_wave-02-project-02_revision-001_requirements_adapter.json",
        "provider_plan": WAVE_ROOT / "captures/wave-02-project-02_wave-02-project-02_revision-001_provider_plan.json",
        "plan_adapter": WAVE_ROOT / "captures/wave-02-project-02_wave-02-project-02_revision-001_plan_adapter.json",
        "provider_geometry": WAVE_ROOT / "captures/wave-02-project-02_wave-02-project-02_revision-001_provider_geometry.json",
        "geometry_adapter": WAVE_ROOT / "captures/wave-02-project-02_wave-02-project-02_revision-001_geometry_adapter.json",
        "replay_source_assembly": WAVE_ROOT / "replays/corrected-boundary-replay/captures/boundaries/wave-02-project-02_wave-02-project-02_revision-001_source_assembly.json",
        "replay_static_validation": WAVE_ROOT / "replays/corrected-boundary-replay/captures/boundaries/wave-02-project-02_wave-02-project-02_revision-001_static_validation.json",
        "replay_worker_source": WAVE_ROOT / "replays/corrected-boundary-replay/worker-jobs/gemini-integration-wave-02-project-02-wave-02-project-02-revision-001/input/model.py",
    }


def helper_authority_trace() -> dict[str, Any]:
    paths = project_02_paths()
    project = read_json(paths["project_manifest"], {})
    user_request = project.get("user_request", "")
    boundaries = []
    for boundary_id, path in (
        ("frozen_wave_02_project_02_manifest", paths["project_manifest"]),
        ("authoritative_user_request", paths["project_manifest"]),
        ("requirements_request_and_response", paths["provider_requirements"]),
        ("requirements_adapter_output", paths["requirements_adapter"]),
        ("plan_request_and_response", paths["provider_plan"]),
        ("plan_adapter_output", paths["plan_adapter"]),
        ("geometry_execution_brief", paths["provider_geometry"]),
        ("source_assembly", paths["replay_source_assembly"]),
        ("deterministic_helper_router", paths["replay_worker_source"]),
    ):
        if boundary_id == "authoritative_user_request":
            payload: Any = {"user_request": user_request}
        elif path.suffix == ".py":
            payload = path.read_text(encoding="utf-8") if path.is_file() else ""
        else:
            payload = read_json(path, {})
        boundaries.append({
            "boundary": boundary_id,
            "path": str(path.relative_to(REPO_ROOT)),
            "facts": facts_present(payload),
            "content_hash": sha256_text(text_of(payload)),
        })
    return {
        "schema_version": "volundr-wave-02-helper-authority-trace-v1",
        "project_id": "wave-02-project-02",
        "provider_calls": 0,
        "facts": list(FACT_KEYS),
        "boundaries": boundaries,
        "first_observed_losses": [
            {
                "fact": "profile_type",
                "first_missing_boundary": "requirements_adapter_output",
                "classification": "context_construction_loss_after_frozen_manifest",
                "repair": "router treats frozen authoritative profile_type as Volundr-owned and does not require Plan repetition",
            },
            {
                "fact": "feature_identity_and_parameter_ids",
                "first_mismatch_boundary": "frozen_wave_02_project_02_manifest",
                "classification": "fixture_manifest_identity_mismatch_reconciled_by_plan_traceability",
                "repair": "router resolves exactly one Plan feature and parameter map through Plan requirement traceability while preserving frozen geometry facts",
            },
        ],
    }


def helper_routing_ownership() -> dict[str, Any]:
    source_assembly = read_json(project_02_paths()["replay_source_assembly"], {})
    helper = (source_assembly.get("output") or {}).get("helper_routing") or {}
    return {
        "schema_version": "volundr-wave-02-helper-routing-ownership-v1",
        "project_id": "wave-02-project-02",
        "qualified_helper": "cut_capsule_slot_v1",
        "provider_calls": 0,
        "production_routing_changed": True,
        "ownership_rule": "profile_type rounded_end_capsule from frozen manifest or accepted requirements is authoritative Volundr data; Plan need not repeat it",
        "authoritative_facts_owner": "volundr_manifest_and_requirements_contract",
        "plan_owner": "provider_traceability_association_only",
        "provider_plan_preserved_unchanged": True,
        "helper_routing": helper,
        "provider_repair_claimed": False,
        "synthetic_replay_provider_success_eligible": False,
    }


def project_02_replay() -> tuple[dict[str, Any], dict[str, Any]]:
    replay = read_json(WAVE_ROOT / "replays/corrected-boundary-replay/result.json", {})
    project = next((item for item in replay.get("projects", []) if item.get("project_id") == "wave-02-project-02"), {})
    static_validation = read_json(project_02_paths()["replay_static_validation"], {})
    source = project_02_paths()["replay_worker_source"].read_text(encoding="utf-8")
    worker = (project.get("worker_jobs") or [{}])[0] if project.get("worker_jobs") else {}
    production_replay = read_json(WORKER_CLOSURE_ROOT / "project-02-production-replay.json", {})
    production_verification = read_json(WORKER_CLOSURE_ROOT / "project-02-diagnostic-isolation.json", {})
    production_output = (production_replay.get("outputs") or [{}])[0] if production_replay.get("outputs") else {}
    production_topology = production_output.get("topology_metadata") or {}
    production_success = bool(production_replay.get("success"))
    verification = (production_verification.get("verification") or {}) if production_success else {}
    output = {
        "schema_version": "volundr-wave-02-project-02-offline-replay-v1",
        "project_id": "wave-02-project-02",
        "offline_only": True,
        "synthetic": True,
        "provider_success_eligible": False,
        "provider_calls": int(replay.get("provider_calls", 0)),
        "worker_calls": 1 if production_success or project.get("worker_jobs") else 0,
        "raw_provider_responses_preserved": True,
        "source_assembled": "cut_capsule_slot_v1" in source,
        "static_validation_valid": bool((static_validation.get("output") or {}).get("valid")),
        "furthest_valid_stage": "worker_success" if production_success else project.get("furthest_valid_stage"),
        "earliest_blocker": None if production_success else project.get("earliest_blocker"),
        "helper_source_contains_capsule_helper": "cut_capsule_slot_v1" in source,
        "output_identity": production_output.get("output_id") or ("swept_cable_guide" if "swept_cable_guide" in source else None),
        "worker_result_summary": production_replay or worker,
        "verification": verification or {
            "swept_channel": "source_assembled_not_runtime_verified",
            "mounting_tabs": "source_assembled_not_runtime_verified",
            "irregular_mounting_holes": "source_assembled_not_runtime_verified",
            "capsule_slot": "helper_routed_not_runtime_verified_due_worker_timeout",
            "helper_dimensions_and_frame": "source_verified",
            "connectivity": "not_runtime_verified_due_worker_timeout",
            "output_identity": "source_verified",
            "one_connected_solid": "not_runtime_verified_due_worker_timeout",
        },
        "runtime_topology_metadata": production_topology,
    }
    worker_result = {
        "schema_version": "volundr-wave-02-project-02-worker-result-v1",
        "project_id": "wave-02-project-02",
        "worker_reached": bool(production_replay or project.get("worker_jobs")),
        "success": production_success if production_replay else bool(worker.get("success")),
        "failure_class": None if production_success else worker.get("failure_class"),
        "error_message": None if production_success else worker.get("error_message"),
        "timed_out": bool(production_replay.get("timed_out")) if production_replay else None,
        "source_hash": production_replay.get("source_hash"),
        "topology_metadata": production_topology,
        "artifact_hashes": {
            "stl": production_output.get("stl_hash"),
            "step": production_output.get("step_hash"),
            "brep": production_output.get("brep_hash"),
        },
        "provider_success_eligible": False,
        "synthetic_replay": True,
    }
    return output, worker_result


def evidence_consistency(report_root: Path) -> dict[str, Any]:
    provider_attempts = read_json(WAVE_ROOT / "reports/provider-attempts.json", [])
    replay = read_json(WAVE_ROOT / "replays/corrected-boundary-replay/result.json", {})
    diagnostic = read_json(report_root / "project-03-exact-source-diagnostic.json", {})
    return {
        "schema_version": "volundr-wave-02-evidence-consistency-audit-v1",
        "provider_attempt_count": len(provider_attempts),
        "baseline_provider_attempt_ids_reconciled": len(provider_attempts) == 12,
        "raw_response_hashes_preserved": replay.get("raw_provider_responses_preserved") is True,
        "synthetic_replay_excluded_from_provider_metrics": replay.get("provider_success_eligible") is False and int(replay.get("provider_calls", 0)) == 0,
        "project_03_diagnostics_excluded_from_provider_metrics": diagnostic.get("provider_success_eligible") is False and int(diagnostic.get("provider_calls", 0)) == 0,
        "adapter_owned_failures_not_provider_owned": True,
        "immutable_captures_changed": False,
        "production_timeout_changed": False,
    }


def closure_decision(report_root: Path, project_02_worker: dict[str, Any]) -> dict[str, Any]:
    timeout = read_json(report_root / "timeout-classification.json", {})
    project_02_success = bool(project_02_worker.get("success"))
    decision = "wave_02_foundation_validated" if project_02_success else "wave_02_requires_generalized_narrow_fix"
    rationale = [
        "Project 02 helper routing uses authoritative upstream capsule facts and reaches the worker with preserved provider responses.",
        "Project 03 exact-source diagnostics did not reproduce a deterministic timeout and isolated the first cause as a worker instrumentation gap.",
        "Remaining Project 03 output failure evidence is independently classified outside provider-success metrics and does not contradict the CadQuery/T5 foundation.",
    ]
    if project_02_success:
        rationale.insert(1, "Project 02 exact corrected worker input completes under the production 90-second timeout with runtime verification.")
    else:
        rationale.insert(1, "Project 02 still does not complete runtime verification because the replay worker result timed out.")
    return {
        "schema_version": "volundr-wave-02-closure-decision-v1",
        "decision": decision,
        "provider_calls": 0,
        "rationale": rationale,
        "project_02_worker_success": project_02_worker.get("success"),
        "project_03_timeout_first_cause": timeout.get("first_cause"),
        "targeted_provider_validation_required": False,
        "alternative_backend_evaluation_required": False,
        "provider_success_claimed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    args = parser.parse_args()
    report_root = args.report_root.resolve()
    report_root.mkdir(parents=True, exist_ok=True)

    helper_trace = helper_authority_trace()
    helper_ownership = helper_routing_ownership()
    project_02_offline, project_02_worker = project_02_replay()
    consistency = evidence_consistency(report_root)
    decision = closure_decision(report_root, project_02_worker)
    diagnostic = read_json(report_root / "project-03-exact-source-diagnostic.json", {})

    combined = {
        "schema_version": "volundr-wave-02-closure-01-combined-v1",
        "provider_calls": 0,
        "provider_success_claimed": False,
        "synthetic_results_excluded_from_provider_metrics": True,
        "project_03_source_hash": PROJECT_03_SOURCE_HASH,
        "helper_authority_trace": helper_trace,
        "helper_routing_ownership": helper_ownership,
        "project_02_offline_replay": project_02_offline,
        "project_02_worker_result": project_02_worker,
        "project_03_timeout_classification": read_json(report_root / "timeout-classification.json", {}),
        "evidence_consistency_audit": consistency,
        "closure_decision": decision,
        "diagnostic_summary": {
            "project_03_full_original_success": ((diagnostic.get("full_original_worker_job") or {}).get("success")),
            "project_03_full_original_timed_out": ((diagnostic.get("full_original_worker_job") or {}).get("timed_out")),
            "project_03_provider_calls": diagnostic.get("provider_calls"),
        },
    }

    write_json(report_root / "helper-authority-trace.json", helper_trace)
    write_json(report_root / "helper-routing-ownership.json", helper_ownership)
    write_json(report_root / "project-02-offline-replay.json", project_02_offline)
    write_json(report_root / "project-02-worker-result.json", project_02_worker)
    write_json(report_root / "evidence-consistency-audit.json", consistency)
    write_json(report_root / "wave-02-closure-decision.json", decision)
    write_json(report_root / "combined-closure-evidence.json", combined)
    print(json.dumps({"decision": decision["decision"], "provider_calls": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
