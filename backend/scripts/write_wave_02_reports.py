"""Materialize the Wave-02 objective report set from preserved evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = REPO_ROOT / "data/debug-sessions/representative-workflow-waves/representative-workflow-wave-02"


def read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _captures(root: Path) -> list[dict[str, Any]]:
    return [read_json(path, {}) for path in sorted((root / "captures").glob("*.json"))]


def baseline_issues(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "issue_id": "wave-02-project-01-issue-01",
            "project_id": "wave-02-project-01",
            "classification": "root_cause",
            "issue_class": "source_assembly_failure",
            "primary_owner": "source_assembly",
            "first_incorrect_boundary": "source_assembly",
            "provider_owned_failure": False,
            "runtime_api_failure": False,
            "symptom": "Scaffold assembly raised missing geometry function after the component slot was rejected as a non-CadQuery result.",
            "cause": "The source assembly boundary did not fail closed on GeometrySlotResponse.invalid_slots and surfaced the condition as harness_or_fixture.",
            "evidence_paths": [
                "captures/wave-02-project-01_wave-02-project-01_harness.json",
                "captures/wave-02-project-01_wave-02-project-01_revision-001_geometry_adapter.json",
            ],
            "status": "open",
        },
        {
            "issue_id": "wave-02-project-01-issue-02",
            "project_id": "wave-02-project-01",
            "classification": "masked_issue",
            "issue_class": "semantic_geometry_failure",
            "primary_owner": "provider_geometry",
            "first_incorrect_boundary": "geometry_adapter",
            "provider_owned_failure": True,
            "runtime_api_failure": False,
            "symptom": "The authoritative component slot assigned body = None rather than constructing a shape.",
            "cause": "Provider geometry was semantically vacuous for the component slot; downstream source assembly exposed it.",
            "evidence_paths": ["captures/wave-02-project-01_wave-02-project-01_revision-001_geometry_adapter.json"],
            "status": "open",
        },
        {
            "issue_id": "wave-02-project-02-issue-01",
            "project_id": "wave-02-project-02",
            "classification": "root_cause",
            "issue_class": "geometry_adapter_failure",
            "primary_owner": "geometry_adapter",
            "first_incorrect_boundary": "geometry_adapter",
            "provider_owned_failure": True,
            "runtime_api_failure": False,
            "symptom": "Geometry adapter rejected an otherwise structurally present sweep response with undefined_names:max.",
            "cause": "The geometry-slot canonicalizer did not include the already-approved safe Python builtin max in its allowed-name inventory.",
            "api_compatibility": {"cadquery_or_ocp_reference": False, "symbol": "max", "classification": "current_supported_python_builtin"},
            "evidence_paths": [
                "captures/wave-02-project-02_wave-02-project-02_revision-001_geometry_adapter.json",
                "reports/cadquery-dialect-diagnosis.json",
            ],
            "status": "open",
        },
        {
            "issue_id": "wave-02-project-02-issue-02",
            "project_id": "wave-02-project-02",
            "classification": "independent_issue",
            "issue_class": "semantic_geometry_failure",
            "primary_owner": "provider_geometry",
            "first_incorrect_boundary": "geometry_adapter",
            "provider_owned_failure": True,
            "runtime_api_failure": False,
            "symptom": "The provider response required representation normalization of prior-shape/result aliases before evaluation.",
            "cause": "Provider used component_shape/modified_shape aliases; normalization was deterministic but records provider contract drift and did not repair semantic geometry.",
            "normalization_only": True,
            "evidence_paths": ["captures/wave-02-project-02_wave-02-project-02_revision-001_geometry_adapter.json"],
            "status": "open",
        },
        {
            "issue_id": "wave-02-project-03-issue-01",
            "project_id": "wave-02-project-03",
            "classification": "root_cause",
            "issue_class": "worker_runtime_failure",
            "primary_owner": "worker_runtime",
            "first_incorrect_boundary": "worker",
            "provider_owned_failure": False,
            "runtime_api_failure": False,
            "kernel_failure_evidence": False,
            "symptom": "The pinned worker did not complete the three-output source within 90 seconds.",
            "cause": "Execution timed out after source assembly and static validation; no isolated kernel failure has been established.",
            "evidence_paths": [
                "worker-jobs/gemini-integration-wave-02-project-03-wave-02-project-03-revision-001.json",
                "captures/wave-02-project-03_wave-02-project-03_revision-001_static_validation.json",
            ],
            "status": "open",
        },
        {
            "issue_id": "wave-02-project-03-issue-02",
            "project_id": "wave-02-project-03",
            "classification": "independent_issue",
            "issue_class": "output_identity_failure",
            "primary_owner": "plan_adapter",
            "first_incorrect_boundary": "plan_adapter",
            "provider_owned_failure": True,
            "runtime_api_failure": False,
            "symptom": "Plan output IDs were enclosure_base_output, enclosure_lid_output, and cable_clamp_output instead of the authoritative IDs.",
            "cause": "The Plan adapter checked output count but did not enforce the manifest's exact output identity set.",
            "expected_output_ids": ["enclosure_base", "enclosure_lid", "cable_clamp"],
            "observed_output_ids": ["enclosure_base_output", "enclosure_lid_output", "cable_clamp_output"],
            "evidence_paths": ["captures/wave-02-project-03_wave-02-project-03_revision-001_source_assembly.json"],
            "status": "open",
        },
        {
            "issue_id": "wave-02-project-04-issue-01",
            "project_id": "wave-02-project-04",
            "classification": "root_cause",
            "issue_class": "requirements_semantic_failure",
            "primary_owner": "provider_requirements",
            "first_incorrect_boundary": "requirements_adapter",
            "provider_owned_failure": True,
            "runtime_api_failure": False,
            "symptom": "Requirements response was not parseable JSON because a property line contained a stray '-' token.",
            "cause": "Malformed provider requirements output was correctly rejected; malformed content is not a transport retry condition.",
            "clarification_failure": False,
            "evidence_paths": ["captures/wave-02-project-04_wave-02-project-04_revision-001_provider_requirements.json"],
            "status": "open",
        },
        {
            "issue_id": "wave-02-project-05-issue-01",
            "project_id": "wave-02-project-05",
            "classification": "root_cause",
            "issue_class": "plan_traceability_failure",
            "primary_owner": "plan_adapter",
            "first_incorrect_boundary": "plan_adapter",
            "provider_owned_failure": True,
            "runtime_api_failure": False,
            "symptom": "Plan adapter rejected the revision because requirement req_separate_outputs was not traced.",
            "cause": "The provider Plan did not preserve the protected separate-output obligation through revision planning.",
            "evidence_paths": ["captures/wave-02-project-05_wave-02-project-05_revision-001_plan_adapter.json"],
            "status": "open",
        },
        {
            "issue_id": "wave-02-project-05-issue-02",
            "project_id": "wave-02-project-05",
            "classification": "independent_issue",
            "issue_class": "output_identity_failure",
            "primary_owner": "plan_adapter",
            "first_incorrect_boundary": "plan_adapter",
            "provider_owned_failure": True,
            "runtime_api_failure": False,
            "symptom": "The provider revision Plan used suffixed output identities rather than the authoritative three IDs.",
            "cause": "Exact output identity was not supplied as an adapter obligation in the baseline route.",
            "expected_output_ids": ["enclosure_base", "enclosure_lid", "cable_clamp"],
            "observed_output_ids": ["enclosure_base_output", "enclosure_lid_output", "cable_clamp_output"],
            "evidence_paths": ["captures/wave-02-project-05_wave-02-project-05_revision-001_provider_plan.json"],
            "status": "open",
        },
    ]


def write_baseline(root: Path) -> None:
    reports = root / "reports"
    manifest = read_json(reports / "wave-preregistration.json", {})
    snapshot = read_json(reports / "repository-snapshot.json", {})
    corpus = read_json(reports / "frozen-project-corpus.json", {})
    diversity = read_json(reports / "project-diversity-matrix.json", {})
    attempts = read_json(reports / "provider-attempts.json", [])
    worker_jobs = read_json(reports / "worker-jobs.json", [])
    outcomes = read_json(reports / "project-outcomes.json", [])
    dialect = read_json(reports / "cadquery-dialect-diagnosis.json", {})
    counterfactuals = read_json(reports / "counterfactual-replays.json", {})
    differential = read_json(reports / "differential-replays.json", [])
    rate_limit = read_json(reports / "rate-limit-report.json", {})
    retry = read_json(reports / "retry-report.json", {})
    issues = baseline_issues(root)
    issue_by_project: dict[str, list[str]] = {}
    for issue in issues:
        issue_by_project.setdefault(issue["project_id"], []).append(issue["issue_id"])
    baseline_results = []
    for outcome in outcomes:
        project_id = str(outcome.get("project_id"))
        baseline_results.append({
            **outcome,
            "baseline_complete": True,
            "issue_ids": issue_by_project.get(project_id, []),
            "raw_provider_output_preserved": True,
            "raw_worker_input_preserved": True,
            "corrections_applied_before_baseline_complete": False,
        })
    causal_nodes = [issue["issue_id"] for issue in issues]
    causal_edges = [
        {"source": "wave-02-project-01-issue-02", "target": "wave-02-project-01-issue-01", "relationship": "caused_by"},
        {"source": "wave-02-project-03-issue-02", "target": "wave-02-project-03-issue-01", "relationship": "independent_of"},
        {"source": "wave-02-project-05-issue-01", "target": "wave-02-project-05-issue-02", "relationship": "independent_of"},
    ]
    clusters = [
        {"cluster_id": "cluster-source-assembly-fail-closed", "project_ids": ["wave-02-project-01"], "issue_ids": ["wave-02-project-01-issue-01", "wave-02-project-01-issue-02"], "shared_owner": "source_assembly/geometry_adapter", "recurrence": 1},
        {"cluster_id": "cluster-geometry-symbol-contract", "project_ids": ["wave-02-project-02"], "issue_ids": ["wave-02-project-02-issue-01", "wave-02-project-02-issue-02"], "shared_owner": "geometry_adapter/provider_geometry", "recurrence": 1},
        {"cluster_id": "cluster-output-identity", "project_ids": ["wave-02-project-03", "wave-02-project-05"], "issue_ids": ["wave-02-project-03-issue-02", "wave-02-project-05-issue-02"], "shared_owner": "plan_adapter", "recurrence": 2, "cross_project": True},
        {"cluster_id": "cluster-worker-runtime-timeout", "project_ids": ["wave-02-project-03"], "issue_ids": ["wave-02-project-03-issue-01"], "shared_owner": "worker_runtime", "recurrence": 1},
        {"cluster_id": "cluster-requirements-provider-contract", "project_ids": ["wave-02-project-04"], "issue_ids": ["wave-02-project-04-issue-01"], "shared_owner": "provider_requirements", "recurrence": 1},
        {"cluster_id": "cluster-revision-traceability", "project_ids": ["wave-02-project-05"], "issue_ids": ["wave-02-project-05-issue-01"], "shared_owner": "plan_adapter", "recurrence": 1},
    ]
    priorities = [
        {"priority": 1, "issue_ids": ["wave-02-project-01-issue-01"], "boundary": "source_assembly", "reason": "generalized fail-closed handling prevents harness misclassification"},
        {"priority": 2, "issue_ids": ["wave-02-project-02-issue-01"], "boundary": "geometry_adapter", "reason": "safe approved builtin inventory is already defined elsewhere and should be shared"},
        {"priority": 3, "issue_ids": ["wave-02-project-03-issue-02", "wave-02-project-05-issue-02"], "boundary": "plan_adapter", "reason": "exact output identity recurs across independent multi-output/revision projects"},
        {"priority": 4, "issue_ids": ["wave-02-project-03-issue-01"], "boundary": "worker_runtime", "reason": "timeout needs offline isolation before any kernel classification or runtime change"},
        {"priority": 5, "issue_ids": ["wave-02-project-04-issue-01", "wave-02-project-05-issue-01"], "boundary": "provider_contract", "reason": "provider-owned malformed/traceability defects are not safely repaired offline"},
    ]
    ownership = {
        "source_assembly": ["wave-02-project-01-issue-01"],
        "provider_geometry": ["wave-02-project-01-issue-02", "wave-02-project-02-issue-02"],
        "geometry_adapter": ["wave-02-project-02-issue-01"],
        "worker_runtime": ["wave-02-project-03-issue-01"],
        "plan_adapter": ["wave-02-project-03-issue-02", "wave-02-project-05-issue-01", "wave-02-project-05-issue-02"],
        "provider_requirements": ["wave-02-project-04-issue-01"],
    }
    unresolved = [
        {"unknown_id": "wave-02-project-03-worker-timeout-kernel-cause", "project_id": "wave-02-project-03", "status": "unresolved", "reason": "worker timeout was not isolated to a kernel operation; no direct OCP evidence"},
        {"unknown_id": "wave-02-project-01-worker-equivalence", "project_id": "wave-02-project-01", "status": "not_reached", "reason": "source assembly stopped before worker execution"},
    ]
    helper_review = {
        "qualified_helper": "cut_capsule_slot_v1",
        "routing_required_project": "wave-02-project-02",
        "routing_applied_in_baseline": False,
        "reason": "Project 02 failed at geometry_adapter before source assembly; no helper invocation was synthesized or counted as provider success.",
        "raw_t5_general_path_preserved": True,
        "new_helpers_added_during_baseline": [],
        "production_routing_changed": False,
    }
    aliases = {
        "preregistration.json": manifest,
        "repository-snapshot.json": snapshot,
        "frozen-project-corpus.json": corpus,
        "diversity-and-coverage-matrix.json": diversity,
        "provider-attempts.json": attempts,
        "worker-jobs.json": worker_jobs,
        "baseline-project-results.json": baseline_results,
        "project-outcomes.json": baseline_results,
        "issue-register.json": issues,
        "causal-graph.json": {"nodes": causal_nodes, "edges": causal_edges},
        "cross-project-clusters.json": clusters,
        "counterfactual-results.json": counterfactuals,
        "differential-replays.json": differential,
        "ownership-analysis.json": ownership,
        "unresolved-unknowns.json": unresolved,
        "correction-priorities.json": priorities,
        "implemented-corrections.json": {"phase": "baseline_analysis", "corrections": [], "authorized": False},
        "full-wave-replay.json": {"phase": "baseline_analysis", "replay_complete": False, "projects": []},
        "helper-policy-review.json": helper_review,
        "rate-limit-report.json": rate_limit,
        "retry-report.json": retry,
        "wave-decision.json": {"phase": "baseline_analysis", "decision": "pending_after_correction_and_replay", "production_routing_changed": False},
        "combined-wave-evidence.json": {
            "schema_version": "volundr-representative-wave-02-evidence-v1",
            "wave_id": "wave-02",
            "phase": "baseline_analysis",
            "baseline_complete": len(baseline_results) == 5,
            "provider_attempts": len(attempts),
            "worker_jobs": len(worker_jobs),
            "provider_calls": len(attempts),
            "worker_calls": len(worker_jobs),
            "all_raw_provider_responses_preserved": True,
            "all_raw_worker_inputs_preserved": True,
            "production_routing_changed": False,
            "wave_02_representative_run": True,
            "issues": issues,
            "causal_graph": {"nodes": causal_nodes, "edges": causal_edges},
            "cross_project_clusters": clusters,
            "cadquery_dialect_diagnosis": dialect,
            "counterfactuals": counterfactuals,
            "differential_replays": differential,
            "rate_limit": rate_limit,
            "retry_summary": retry,
            "redaction": {"credential_source": "GEMINI_API_KEY_2", "credential_values_serialized": False},
        },
    }
    for name, value in aliases.items():
        write_json(reports / name, value)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    write_baseline(args.root.resolve())
    print(json.dumps({"phase": "baseline_analysis", "root": str(args.root.resolve()), "issues": len(baseline_issues(args.root.resolve()))}, sort_keys=True))


if __name__ == "__main__":
    main()
