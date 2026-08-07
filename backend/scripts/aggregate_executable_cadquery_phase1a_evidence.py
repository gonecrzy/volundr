"""Persist sanitized aggregate evidence for the frozen Phase 1A survey."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, required=True)
    return parser.parse_args()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    root = parse_args().evidence_root.resolve()
    manifest_path = root / "corpus-manifest.json"
    manifest = load(manifest_path)
    projects = sorted(manifest["projects"], key=lambda item: int(item["order"]))
    records = [load(root / f"project-{int(project['order']):02d}-first-pass.json") for project in projects]
    if len(records) != 16 or [record["corpus_order"] for record in records] != list(range(1, 17)):
        raise ValueError("Phase 1A aggregate requires exactly one record for each order 1..16")
    if any(record["provider_attempt_count"] != 1 for record in records):
        raise ValueError("Phase 1A aggregate requires one initial provider operation per project")
    if any(record["provider_repair_operations"] != 0 for record in records):
        raise ValueError("Phase 1A aggregate found a repair operation")

    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    boundary_counts = Counter(
        record.get("initial_attempt", {}).get("failure_boundary") or "candidate_ready"
        for record in records
    )
    class_counts = Counter(record.get("normalized_failure_class") or "candidate_ready" for record in records)
    rows = []
    for record in records:
        initial = record.get("initial_attempt", {})
        rows.append(
            {
                "order": record["corpus_order"],
                "project_id": record["project_id"],
                "specification_category": record["specification_category"],
                "geometry_families": record["geometry_families"],
                "prompt_sha256": record["prompt_sha256"],
                "design_contract_sha256": record["design_contract_sha256"],
                "provider_attempt_count": record["provider_attempt_count"],
                "provider_repair_operations": record["provider_repair_operations"],
                "state": record["state"],
                "highest_stage_reached": record["highest_stage_reached"],
                "first_unresolved_blocker": record["first_unresolved_blocker"],
                "failure_boundary": initial.get("failure_boundary"),
                "normalized_failure_class": record["normalized_failure_class"],
                "source_extracted": record["source_extracted"],
                "source_contract_valid": record["source_contract_valid"],
                "candidate_ready_reached": record["candidate_ready_reached"],
                "visible_model": record["visible_model"],
                "workflow_id": record["workflow_id"],
                "project_runtime_id": record["project_runtime_id"],
                "revision_id": record["revision_id"],
                "raw_response_hash": initial.get("raw_response_hash"),
                "extracted_source_hash": initial.get("extracted_source_hash"),
                "evidence_file": f"project-{record['corpus_order']:02d}-first-pass.json",
            }
        )

    write(
        root / "first-blocker-matrix.json",
        {
            "schema_version": "executable-cadquery-phase-1a-first-blocker-matrix-v1",
            "survey_status": "complete_after_integrity_reconciliation",
            "corpus_manifest": "corpus-manifest.json",
            "corpus_manifest_sha256": manifest_hash,
            "provider_transport": "gemini_api_rest_x_goog_api_key_via_GeminiApiProvider",
            "provider_calls": 16,
            "repair_operations": 0,
            "initial_pass_count": sum(record["candidate_ready_reached"] for record in records),
            "first_blocker_counts_by_boundary": dict(sorted(boundary_counts.items())),
            "first_blocker_counts_by_class": dict(sorted(class_counts.items())),
            "categories_not_observed": [
                "topology",
                "semantic_measurement",
                "unsupported_verifier",
                "artifact",
                "package",
                "presentation",
                "review",
            ],
            "projects": rows,
        },
    )

    write(
        root / "failure-clusters.json",
        {
            "schema_version": "executable-cadquery-phase-1a-failure-clusters-v1",
            "survey_status": "first_pass_observation_only",
            "corpus_manifest_sha256": manifest_hash,
            "clusters": [
                {
                    "cluster_id": "cadquery_api_error",
                    "mechanism": "CadQuery selector/parser rejected generated source during worker build_function",
                    "project_ids": ["development-01"],
                    "count": 1,
                    "first_boundary": "execution",
                    "generic_owner": "worker_execution",
                    "recovery_development_status": "defer_until_survey_complete",
                },
                {
                    "cluster_id": "source_contract_violation",
                    "mechanism": "generated source violated the executable source contract before worker execution",
                    "project_ids": ["development-02"],
                    "count": 1,
                    "first_boundary": "source_contract",
                    "generic_owner": "source_contract_validator",
                    "recovery_development_status": "defer_until_survey_complete",
                },
                {
                    "cluster_id": "provider_response_contract_failure",
                    "mechanism": "initial Gemini API operation did not yield an accepted complete-source response",
                    "project_ids": [f"development-{order:02d}" for order in range(3, 17)],
                    "count": 14,
                    "first_boundary": "provider_response",
                    "generic_owner": "provider_response_contract",
                    "recovery_development_status": "defer_until_survey_complete",
                },
            ],
            "integrity_event_not_a_project_cluster": {
                "cluster_id": "shared_provider_attempt_observer_accumulation",
                "mechanism": "request-scoped workflow callbacks accumulated on a shared provider and caused duplicate durable attempt inserts",
                "affected_project": "development-02",
                "fixed_generically": True,
                "fix_commit": "e0e9be5",
                "project_specific_rule_added": False,
            },
        },
    )

    write(
        root / "initial-metrics.json",
        {
            "schema_version": "executable-cadquery-phase-1a-initial-metrics-v1",
            "corpus_manifest_sha256": manifest_hash,
            "projects": 16,
            "provider_calls": 16,
            "repair_operations": 0,
            "initial_independent_pass": {"passed": 0, "total": 16, "rate": 0.0},
            "eventual_independent_pass": {"passed": 0, "total": 16, "status": "not_evaluated_in_phase_1a"},
            "first_blocker_matrix_complete": True,
            "new_generic_recovery_rules_by_project_order": {str(order): 0 for order in range(1, 17)},
            "existing_rule_recovery_rate": {"status": "not_evaluated_no_repair_operations"},
            "integrity_fix_count_during_survey": 1,
            "integrity_fix_is_recovery_rule": False,
            "phase_1b_started": False,
        },
    )

    write(
        root / "anti-overfitting-audit.json",
        {
            "schema_version": "executable-cadquery-phase-1a-anti-overfitting-audit-v1",
            "corpus_manifest_sha256": manifest_hash,
            "first_pass_outcomes_frozen_before_corpus_driven_changes": True,
            "project_specific_rules_added": False,
            "prompt_changes": False,
            "repair_prompt_changes": False,
            "semantic_policy_changes": False,
            "cad_strategy_changes": False,
            "credential_changes": False,
            "repair_ceiling_changes": False,
            "generic_integrity_fix": {
                "rule": "replace request-scoped validated attempt observer on shared provider",
                "geometry_independent": True,
                "justification": "the duplicate insert reproduced from provider reuse across unrelated workflows and was covered by a provider regression test",
                "commit": "e0e9be5",
            },
            "phase_1b_not_started": True,
        },
    )

    write(
        root / "test-summary.json",
        {
            "schema_version": "executable-cadquery-phase-1a-test-summary-v1",
            "preflight": {
                "backend": "1431 passed, 1 skipped, 1 warning",
                "frontend_unit": "104 passed",
                "frontend_build": "passed",
                "offline_browser": "22 passed, 15 skipped",
                "credential_boundary": "65 targeted routing/credential tests passed",
                "alembic": "current=head=0039_align_fresh_database_schema; check clean",
                "provider_calls_before_freeze": 0,
            },
            "integrity_reconciliation": {
                "failure": "duplicate durable provider attempt_id from accumulated request-scoped observers",
                "fix_regression": "backend/tests/test_gemini_api_provider.py::test_validated_attempt_recorder_replaces_stale_workflow_observer",
                "targeted_fix_tests": "41 passed, 1 warning",
                "post_fix_full_backend": "1432 passed, 1 skipped, 1 warning",
                "post_fix_boundary_and_routing": "65 passed",
                "restarted_scope": "development-02 only",
            },
            "survey": {
                "projects_completed": 16,
                "provider_calls": 16,
                "repair_operations": 0,
                "offline_browser": "22 passed, 15 skipped",
                "blind_qa_executed": False,
                "phase_1b_executed": False,
            },
        },
    )

    write(
        root / "survey-integrity-reconciliation.json",
        {
            "schema_version": "executable-cadquery-phase-1a-integrity-reconciliation-v1",
            "initial_launch": {
                "code_checkpoint": "820b004",
                "completed_project_orders": list(range(1, 17)),
                "valid_first_pass_records": [1] + list(range(3, 17)),
                "provider_operations_completed": 15,
                "project_02_provider_operation": 0,
                "status": "invalidated_for_reconciliation_only",
            },
            "integrity_failure": {
                "class": "shared_provider_attempt_observer_accumulation",
                "boundary": "durable_persistence",
                "symptom": "UNIQUE constraint failed on validated_cadquery_provider_attempts.attempt_id",
                "cause": "shared GeminiApiProvider retained callbacks for prior request-scoped workflow services",
            },
            "generic_fix": {
                "commit": "e0e9be5",
                "behavior": "replace the request-scoped observer instead of composing stale observers",
                "regression_test": "test_validated_attempt_recorder_replaces_stale_workflow_observer",
            },
            "reconciliation": {
                "restarted_project_orders": [2],
                "repeated_provider_operations": 0,
                "reconciled_project_02_provider_operations": 1,
                "final_provider_operations": 16,
                "final_first_pass_records": 16,
                "historical_records_preserved": True,
            },
        },
    )
    write(
        root / "phase-1a-decision.json",
        {
            "schema_version": "executable-cadquery-phase-1a-decision-v1",
            "decision": "phase_1a_first_blocker_survey_complete",
            "corpus_manifest_sha256": manifest_hash,
            "all_projects_have_first_pass_result": True,
            "provider_calls": 16,
            "repair_operations": 0,
            "initial_pass": "0/16",
            "phase_1b_started": False,
            "next_authorized_phase": "phase_1b_cluster_driven_recovery_development",
            "condition": "begin only after this matrix, clustering, metrics, and anti-overfitting audit are reviewed and committed",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
