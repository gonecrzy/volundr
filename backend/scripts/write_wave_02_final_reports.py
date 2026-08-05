#!/usr/bin/env python3
"""Materialize final Wave-02 replay, ownership, and decision evidence."""

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


def _differential(before: dict[str, Any], after: dict[str, Any], project_id: str, correction: str | None) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "offline_only": True,
        "synthetic": True,
        "provider_success_eligible": False,
        "single_variable_changed": correction,
        "before": before,
        "after": after,
        "changed_fields": [
            field
            for field in ("earliest_blocker", "furthest_valid_stage", "candidate_decision")
            if before.get(field) != after.get(field)
        ],
        "correction_effect_observed": before != after,
        "semantic_success_claimed": False,
    }


def write_final(root: Path) -> dict[str, Any]:
    reports = root / "reports"
    repository_snapshot = read_json(reports / "repository-snapshot.json", {})
    repository_snapshot["migration_validation"] = {
        "current": "0036_benchmark_model_metadata",
        "head": "0036_benchmark_model_metadata",
        "alembic_check": "known_preexisting_schema_drift",
        "production_migration_changed": False,
        "known_drift_separately_recorded": [
            "created_at/recorded_at nullability differences across existing tables",
            "component_revision_summaries generation_attempt_id index",
            "project_messages client_message_id index shape",
            "projects.slug uniqueness",
        ],
    }
    baseline = read_json(reports / "baseline-project-results.json", [])
    replay = read_json(root / "replays/corrected-boundary-replay/result.json", {})
    corrected = list(replay.get("projects") or [])
    baseline_by_project = {str(item.get("project_id")): item for item in baseline}
    corrected_by_project = {str(item.get("project_id")): item for item in corrected}

    corrections = [
        {
            "correction_id": "wave-02-correction-01",
            "boundary": "source_assembly",
            "scope": "generalized",
            "change": "Geometry slot parse and incomplete/invalid responses now fail closed as source_assembly_failure with validation evidence.",
            "provider_calls": 0,
            "replay_projects": ["wave-02-project-01"],
            "confirmed_effect": "project-01 moved from harness_or_fixture to source_assembly_failure; provider semantic body=None remains visible.",
            "production_routing_changed": False,
        },
        {
            "correction_id": "wave-02-correction-02",
            "boundary": "geometry_adapter",
            "scope": "generalized",
            "change": "The geometry-slot canonicalizer reuses the existing approved safe-Python builtin inventory.",
            "provider_calls": 0,
            "replay_projects": ["wave-02-project-02"],
            "confirmed_effect": "max is no longer rejected as undefined_names:max; the response reaches source assembly, where the qualified helper route fails closed because the Plan omitted profile_type.",
            "production_routing_changed": False,
        },
        {
            "correction_id": "wave-02-correction-03",
            "boundary": "plan_adapter",
            "scope": "generalized",
            "change": "Plan output IDs are checked against the frozen authoritative ordered identity list.",
            "provider_calls": 0,
            "replay_projects": ["wave-02-project-03", "wave-02-project-05"],
            "confirmed_effect": "Suffixed provider aliases are rejected before assembly, preserving exact output identity and exposing the provider-owned Plan defect.",
            "production_routing_changed": False,
        },
    ]

    differential = [
        _differential(
            baseline_by_project[project_id],
            corrected_by_project[project_id],
            project_id,
            correction,
        )
        for project_id, correction in (
            ("wave-02-project-01", "source_assembly_fail_closed"),
            ("wave-02-project-02", "approved_builtin_inventory"),
            ("wave-02-project-03", "exact_output_identity"),
            ("wave-02-project-04", None),
            ("wave-02-project-05", "exact_output_identity"),
        )
        if project_id in baseline_by_project and project_id in corrected_by_project
    ]

    issues = list(read_json(reports / "issue-register.json", []) or [])
    status_by_issue = {
        "wave-02-project-01-issue-01": "fixed_by_generalized_replay",
        "wave-02-project-02-issue-01": "fixed_by_generalized_replay",
        "wave-02-project-03-issue-02": "fixed_by_generalized_replay",
        "wave-02-project-05-issue-02": "fixed_by_generalized_replay",
        "wave-02-project-05-issue-01": "masked_by_earlier_corrected_boundary",
    }
    for issue in issues:
        if issue.get("issue_id") in status_by_issue:
            issue["status"] = status_by_issue[issue["issue_id"]]
        issue["baseline_first_incorrect_boundary"] = issue.get("first_incorrect_boundary")
    unresolved = [
        {
            "unknown_id": "wave-02-project-03-worker-timeout-kernel-cause",
            "project_id": "wave-02-project-03",
            "status": "unresolved",
            "owner": "worker_runtime",
            "reason": "The baseline worker timed out after source/static validation; no isolated kernel failure or corrected replay execution established the cause.",
        },
        {
            "unknown_id": "wave-02-project-02-helper-route-provider-contract",
            "project_id": "wave-02-project-02",
            "status": "understood_provider_boundary",
            "owner": "provider_plan",
            "reason": "The existing qualified helper requires profile_type rounded_end_capsule; the provider Plan omitted that field. No inference or helper broadening was applied.",
        },
        {
            "unknown_id": "wave-02-corrected-worker-coverage",
            "project_id": "wave-02",
            "status": "unresolved",
            "owner": "worker_runtime",
            "reason": "The corrected replay generated zero worker jobs because all five projects stopped before worker; no new worker call was authorized after the baseline timeout.",
        },
    ]
    helper_review = {
        "qualified_helper": "cut_capsule_slot_v1",
        "routing_required_project": "wave-02-project-02",
        "routing_applied_in_corrected_replay": False,
        "routing_failure": "Plan capsule feature omitted profile_type rounded_end_capsule",
        "raw_t5_general_path_preserved": True,
        "new_helpers_added": [],
        "provider_geometry_not_rewritten": True,
        "production_routing_changed": False,
    }
    decision = {
        "phase": "final_wave_decision",
        "decision": "insufficient_evidence",
        "rationale": [
            "All five baseline projects and all five corrected offline replays completed with preserved raw responses.",
            "Three generalized owning-boundary corrections were confirmed without provider calls or production routing changes.",
            "The raw T5 foundation was not disproven, but no corrected project reached worker after the baseline worker timeout and the remaining helper/Plan boundary was not safely inferable offline.",
            "A readiness decision would therefore conflate understood provider/worker blockers with successful representative product support.",
        ],
        "baseline_projects": 5,
        "corrected_replay_projects": len(corrected),
        "provider_calls_during_replay": int(replay.get("provider_calls", 0)),
        "worker_calls_during_replay": int(replay.get("worker_calls", 0)),
        "production_routing_changed": False,
        "representative_wave_02_authorized": False,
        "next_action": "Keep Wave 02 closed; isolate the existing worker timeout and preregister a narrowly scoped follow-up only if that evidence changes the decision.",
    }
    full_replay = {
        **replay,
        "replay_complete": len(corrected) == 5,
        "baseline_outcomes": baseline,
        "corrected_outcomes": corrected,
        "corrections": corrections,
        "decision": decision["decision"],
    }
    ownership = {
        "baseline": read_json(reports / "ownership-analysis.json", {}),
        "correction_owners": {
            "source_assembly_fail_closed": "source_assembly",
            "approved_builtin_inventory": "geometry_adapter",
            "exact_output_identity": "plan_adapter",
        },
        "remaining_provider_owned": [
            "wave-02-project-01 semantic geometry body=None",
            "wave-02-project-02 missing helper traceability field",
            "wave-02-project-04 malformed requirements JSON",
            "wave-02-project-05 missing revision traceability",
        ],
        "remaining_runtime_owned": ["wave-02-project-03 worker timeout; kernel cause unconfirmed"],
    }
    combined = {
        "schema_version": "volundr-representative-wave-02-evidence-v2",
        "wave_id": "wave-02",
        "phase": "final_wave_decision",
        "baseline": {
            "projects": baseline,
            "provider_attempts": len(read_json(reports / "provider-attempts.json", []) or []),
            "worker_jobs": len(read_json(reports / "worker-jobs.json", []) or []),
            "rate_limit": read_json(reports / "rate-limit-report.json", {}),
            "retry": read_json(reports / "retry-report.json", {}),
        },
        "corrected_replay": full_replay,
        "corrections": corrections,
        "differential_replays": differential,
        "issues": issues,
        "causal_graph": read_json(reports / "causal-graph.json", {}),
        "ownership": ownership,
        "unresolved_unknowns": unresolved,
        "helper_policy": helper_review,
        "decision": decision,
        "repository_snapshot": repository_snapshot,
        "raw_provider_responses_preserved": True,
        "raw_provider_statements_unchanged": True,
        "provider_calls_total_live": len(read_json(reports / "provider-attempts.json", []) or []),
        "provider_calls_corrected_replay": int(replay.get("provider_calls", 0)),
        "worker_calls_total_baseline": len(read_json(reports / "worker-jobs.json", []) or []),
        "worker_calls_corrected_replay": int(replay.get("worker_calls", 0)),
        "credential_values_serialized": False,
        "credential_source": "GEMINI_API_KEY_2",
        "production_routing_changed": False,
    }
    write_json(reports / "project-outcomes.json", corrected)
    write_json(reports / "repository-snapshot.json", repository_snapshot)
    write_json(reports / "issue-register.json", issues)
    write_json(reports / "differential-replays.json", differential)
    write_json(reports / "ownership-analysis.json", ownership)
    write_json(reports / "unresolved-unknowns.json", unresolved)
    write_json(reports / "implemented-corrections.json", {"phase": "correction_replay", "authorized": True, "corrections": corrections, "production_routing_changed": False})
    write_json(reports / "full-wave-replay.json", full_replay)
    write_json(reports / "helper-policy-review.json", helper_review)
    write_json(reports / "wave-decision.json", decision)
    write_json(reports / "combined-wave-evidence.json", combined)
    return {"decision": decision["decision"], "projects": len(corrected), "corrections": len(corrections)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    print(json.dumps(write_final(args.root.resolve()), sort_keys=True))


if __name__ == "__main__":
    main()
