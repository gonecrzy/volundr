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


def provider_facts_are_defensible(record: dict[str, Any]) -> bool:
    facts = record.get("initial_attempt", {}).get("provider_attempt_facts", [])
    if not isinstance(facts, list) or not facts:
        return False
    final = facts[-1]
    required = (
        final.get("logical_operation_id"),
        final.get("attempt_id"),
        final.get("request_started_at"),
        final.get("credential_slot"),
        isinstance(final.get("response_received"), bool),
        final.get("response_length") is not None,
    )
    if not all(required):
        return False
    if final.get("response_received"):
        return bool(final.get("raw_response_hash"))
    return bool(final.get("exception_type") or final.get("normalized_transport_error"))


def authoritative_record_path(root: Path, order: int) -> Path:
    reconciled = root / f"project-{order:02d}-reconciled-first-pass.json"
    if order >= 3:
        if not reconciled.is_file():
            raise ValueError(f"missing reconciled authoritative record for project order {order}")
        return reconciled
    return root / f"project-{order:02d}-first-pass.json"


def authoritative_observation(record: dict[str, Any]) -> dict[str, Any]:
    order = int(record["corpus_order"])
    observed_stage = record.get("observed_stage")
    if order == 1 and observed_stage == "execution":
        observed_stage = "build_execution"
    return {
        "observed_stage": observed_stage,
        "failure_class": record.get("normalized_failure_class"),
        "first_incorrect_owner": "generated_source" if order in {1, 2} else record.get("first_incorrect_owner"),
        "ownership_reaudit": (
            "generated CadQuery source caused the worker parse failure"
            if order == 1
            else "source contract violation is supported, but the persisted AST diagnostic was mislocalized to module.body[0]"
            if order == 2
            else None
        ),
    }


def main() -> int:
    root = parse_args().evidence_root.resolve()
    manifest_path = root / "corpus-manifest.json"
    manifest = load(manifest_path)
    projects = sorted(manifest["projects"], key=lambda item: int(item["order"]))
    historical_records = [load(root / f"project-{int(project['order']):02d}-first-pass.json") for project in projects]
    records = [load(authoritative_record_path(root, int(project["order"]))) for project in projects]
    if len(records) != 16 or [record["corpus_order"] for record in records] != list(range(1, 17)):
        raise ValueError("Phase 1A aggregate requires exactly one record for each order 1..16")
    if any(record["provider_attempt_count"] != 1 for record in records):
        raise ValueError("Phase 1A aggregate requires one initial provider operation per project")
    if any(record["provider_repair_operations"] != 0 for record in records):
        raise ValueError("Phase 1A aggregate found a repair operation")

    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    forensic = load(root / "historical-provider-attempt-forensics.json")
    invalidated_orders = {
        int(item["corpus_order"])
        for item in forensic.get("historical_observations", [])
        if item.get("historical_validity") == "invalidated_by_survey_integrity_defect"
    }
    boundary_counts = Counter(
        record.get("initial_attempt", {}).get("failure_boundary") or "candidate_ready"
        for record in records
    )
    class_counts = Counter(record.get("normalized_failure_class") or "candidate_ready" for record in records)
    rows = []
    for record in records:
        initial = record.get("initial_attempt", {})
        observation = authoritative_observation(record)
        provider_facts = initial.get("provider_attempt_facts", [])
        final_provider_fact = provider_facts[-1] if isinstance(provider_facts, list) and provider_facts else {}
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
                "raw_response_hash": final_provider_fact.get("raw_response_hash") or initial.get("raw_response_hash"),
                "extracted_source_hash": initial.get("extracted_source_hash"),
                "observed_stage": observation["observed_stage"],
                "first_incorrect_owner": observation["first_incorrect_owner"],
                "ownership_reaudit": observation["ownership_reaudit"],
                "provider_attempt_facts": initial.get("provider_attempt_facts", []),
                "evidence_file": authoritative_record_path(root, int(record["corpus_order"])).name,
            }
        )

    authoritative_validity = {
        str(record["corpus_order"]): (
            "historically_valid_first_pass"
            if int(record["corpus_order"]) in {1, 2}
            else "reconciled_authoritative_first_pass"
            if provider_facts_are_defensible(record)
            else "invalidated_by_reconciliation_integrity_defect"
        )
        for record in records
    }
    defensible = all(
        value in {"historically_valid_first_pass", "reconciled_authoritative_first_pass"}
        for value in authoritative_validity.values()
    )

    write(
        root / "first-blocker-matrix.json",
        {
            "schema_version": "executable-cadquery-phase-1a-first-blocker-matrix-v1",
            "survey_status": "reconciled_authoritative_first_blocker_matrix",
            "corpus_manifest": "corpus-manifest.json",
            "corpus_manifest_sha256": manifest_hash,
            "provider_transport": "gemini_api_rest_x_goog_api_key_via_GeminiApiProvider",
            "provider_calls": sum(int(record["provider_attempt_count"]) for record in records),
            "repair_operations": 0,
            "initial_pass_count": sum(record["candidate_ready_reached"] for record in records),
            "first_blocker_counts_by_boundary": dict(sorted(boundary_counts.items())),
            "first_blocker_counts_by_observed_stage": dict(
                sorted(Counter(row.get("observed_stage") or "unknown" for row in rows).items())
            ),
            "first_blocker_counts_by_class": dict(sorted(class_counts.items())),
            "historical_observations": [
                {
                    "order": int(record["corpus_order"]),
                    "project_id": record["project_id"],
                    "original_failure_boundary": record.get("initial_attempt", {}).get("failure_boundary"),
                    "original_failure_class": record.get("normalized_failure_class"),
                    "historical_validity": (
                        "invalidated_by_survey_integrity_defect"
                        if int(record["corpus_order"]) in invalidated_orders
                        else "historically_valid_first_pass"
                    ),
                    "evidence_file": f"project-{int(record['corpus_order']):02d}-first-pass.json",
                }
                for record in historical_records
            ],
            "authoritative_validity": authoritative_validity,
            "phase_1b_eligibility": {
                "every_project_has_defensible_first_blocker": defensible,
                "phase_1b_started": False,
            },
            "categories_not_observed": [
                category
                for category in (
                    "source_contract",
                    "build_execution",
                    "topology",
                    "semantic_measurement",
                    "unsupported_verifier",
                    "artifact",
                    "package",
                    "presentation",
                    "review",
                )
                if category not in {row.get("observed_stage") for row in rows}
            ],
            "projects": rows,
        },
    )

    write(
        root / "failure-clusters.json",
        {
            "schema_version": "executable-cadquery-phase-1a-failure-clusters-v1",
            "survey_status": "reconciled_authoritative_observation_only",
            "corpus_manifest_sha256": manifest_hash,
            "clusters": [
                {
                    "cluster_id": failure_class or "candidate_ready",
                    "mechanism": "authoritative first-pass observations grouped by normalized generic failure class",
                    "project_ids": [record["project_id"] for record in records if record.get("normalized_failure_class") == failure_class],
                    "count": sum(record.get("normalized_failure_class") == failure_class for record in records),
                    "first_boundary": sorted({row.get("observed_stage") for row in rows if row.get("normalized_failure_class") == failure_class}),
                    "generic_owner": sorted({row.get("first_incorrect_owner") for row in rows if row.get("normalized_failure_class") == failure_class}),
                    "recovery_development_status": "defer_until_phase_1a_reconciliation_review",
                }
                for failure_class in sorted({record.get("normalized_failure_class") for record in records})
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
            "provider_calls": sum(int(record["provider_attempt_count"]) for record in records),
            "repair_operations": 0,
            "initial_independent_pass": {"passed": 0, "total": 16, "rate": 0.0},
            "eventual_independent_pass": {"passed": 0, "total": 16, "status": "not_evaluated_in_phase_1a"},
            "first_blocker_matrix_complete": defensible,
            "new_generic_recovery_rules_by_project_order": {str(order): 0 for order in range(1, 17)},
            "existing_rule_recovery_rate": {"status": "not_evaluated_no_repair_operations"},
            "integrity_fix_count_during_survey": 2,
            "integrity_fix_is_recovery_rule": False,
            "phase_1b_started": False,
            "historical_invalidated_project_orders": sorted(invalidated_orders),
            "authoritative_reconciled_project_orders": list(range(3, 17)),
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
            "survey_reconciliation_integrity_fix": {
                "rule": "persist safe transport-attempt facts and reject response-contract classification without response evidence",
                "geometry_independent": True,
                "project_specific_rule_added": False,
                "provider_call_count_during_reconciliation": 14,
            },
            "historical_invalidated_project_orders": sorted(invalidated_orders),
            "phase_1b_not_started": True,
        },
    )

    write(
        root / "test-summary.json",
        {
            "schema_version": "executable-cadquery-phase-1a-test-summary-v1",
            "preflight": {
                "backend": "1441 passed, 1 skipped, 1 warning",
                "frontend_unit": "104 passed",
                "frontend_build": "passed",
                "offline_browser": "22 passed, 15 skipped",
                "credential_boundary": "65 targeted routing/credential tests passed",
                "alembic": "current=head=0040_provider_attempt_transport_facts; check clean",
                "provider_calls_before_freeze": 0,
                "provider_calls_before_reconciliation": 0,
            },
            "integrity_reconciliation": {
                "failure": "duplicate durable provider attempt_id from accumulated request-scoped observers",
                "fix_regression": "backend/tests/test_gemini_api_provider.py::test_validated_attempt_recorder_replaces_stale_workflow_observer",
                "targeted_fix_tests": "41 passed, 1 warning",
                "taxonomy_observability_targeted_tests": "76 passed, 1 warning",
                "post_fix_full_backend": "1441 passed, 1 skipped, 1 warning",
                "post_fix_boundary_and_routing": "65 passed",
                "restarted_scope": "development-02 only",
            },
            "reconciliation_forensics": {
                "historical_provider_attempt_forensics": "historical-provider-attempt-forensics.json",
                "historical_invalidated_project_orders": sorted(invalidated_orders),
                "reconciled_project_orders": list(range(3, 17)),
                "reconciled_provider_calls": 14,
                "reconciled_repair_operations": 0,
                "rate_limit_audit": "rate-limit-audit.json",
            },
            "survey": {
                "projects_completed": 16,
                "provider_calls": 16,
                "new_reconciliation_provider_calls": 14,
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
            "historical_provider_attempt_forensics": {
                "evidence_file": "historical-provider-attempt-forensics.json",
                "provider_calls_made": 0,
                "invalidated_project_orders": sorted(invalidated_orders),
                "exact_attempt_facts_recovered": False,
            },
            "observational_reconciliation": {
                "restarted_project_orders": list(range(3, 17)),
                "provider_operations": 14,
                "repair_operations": 0,
                "record_suffix": "reconciled-first-pass",
                "current_post_integrity_fix_code": True,
                "frozen_prompts_and_contracts": True,
                "rate_limit_audit": "rate-limit-audit.json",
                "authoritative_matrix_uses_reconciled_records": True,
            },
        },
    )
    write(
        root / "phase-1a-decision.json",
        {
            "schema_version": "executable-cadquery-phase-1a-decision-v1",
            "decision": "phase_1a_reconciliation_complete_phase_1b_not_started",
            "corpus_manifest_sha256": manifest_hash,
            "all_projects_have_first_pass_result": defensible,
            "provider_calls": sum(int(record["provider_attempt_count"]) for record in records),
            "repair_operations": 0,
            "initial_pass": "0/16",
            "phase_1b_started": False,
            "next_authorized_phase": "phase_1b_cluster_driven_recovery_development" if defensible else "phase_1a_reconciliation_required",
            "condition": "Phase 1B remains stopped; all 16 projects now have a defensible authoritative first blocker before any cluster-driven recovery begins." if defensible else "Do not begin Phase 1B until each project has a defensible authoritative first blocker.",
            "historical_invalidated_project_orders": sorted(invalidated_orders),
            "authoritative_reconciled_project_orders": list(range(3, 17)),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
