from __future__ import annotations

import json
from pathlib import Path

from app.services.gemini_consistency.phase2_audit import (
    aggregate_phase2_projects,
    audit_worker_evidence,
    audit_phase2,
    classify_clarification,
    furthest_valid_stage,
    reconcile_buildability_scores,
    reconstruct_phase2,
    select_earliest_blocker,
)


def test_correct_clarification_request_is_not_a_profile_failure() -> None:
    result = classify_clarification(
        clarification_required=True,
        missing_requirements=["phone_width", "phone_thickness"],
        frozen_facts={"phone_width": 78, "phone_thickness": 8, "case_status": "with_case", "desired_angle": 15},
        answer_submitted=False,
        workflow_resumed=False,
    )

    assert result["decision"] == "clarification_required_correctly"
    assert result["profile_failure"] is False
    assert result["comparison_status"] == "harness_incomplete_after_valid_clarification"


def test_unanswered_clarification_is_harness_incomplete() -> None:
    result = classify_clarification(
        clarification_required=True,
        missing_requirements=["phone_width"],
        frozen_facts={"phone_width": 78},
        answer_submitted=False,
        workflow_resumed=False,
    )

    assert result["outcomes"] == ["clarification_required_correctly", "clarification_not_answered"]
    assert result["comparison_status"] == "harness_incomplete_after_valid_clarification"


def test_identical_clarification_facts_are_required_for_both_arms() -> None:
    facts = {"phone_width": 78, "phone_thickness": 8, "case_status": "with_case", "desired_angle": 15}
    result = classify_clarification(
        clarification_required=True,
        missing_requirements=list(facts),
        frozen_facts=facts,
        answer_submitted=True,
        submitted_facts=facts,
        workflow_resumed=True,
    )

    assert result["answer_facts"] == facts
    assert result["outcomes"][-1] == "clarification_answered"


def test_runtime_exception_implies_worker_reach_but_not_cad_success() -> None:
    result = audit_worker_evidence(
        source_contract={"passed_hard_checks": True},
        job={"job_id": "job-1", "source_hash": "source-1"},
        execution_manifest={"success": False, "failure_class": "execution_failed", "diagnostics": {"exit_code": 1, "message": "ValueError: loft"}},
        output_manifest={"outputs": [{"state": "failed", "topology": None}]},
    )

    assert result["source_contract_passed"] is True
    assert result["worker_ready_valid_source"] is True
    assert result["worker_reached"] is True
    assert result["worker_completed"] is False
    assert result["worker_runtime_failed"] is True
    assert result["topology_valid"] is False
    assert result["cad_success"] is False


def test_submitted_source_that_passed_contract_is_worker_ready() -> None:
    result = audit_worker_evidence(
        source_contract={"passed_hard_checks": True},
        job={"job_id": "job-1", "source_hash": "source-1"},
        execution_manifest={"success": True, "diagnostics": {"exit_code": 0}},
        output_manifest={"outputs": [{"state": "ready_with_warnings", "topology": {"valid": True}}]},
    )

    assert result["worker_ready_valid_source"] is True
    assert result["worker_completed"] is True
    assert result["topology_valid"] is True
    assert result["cad_success"] is False


def test_earliest_blocker_and_furthest_stage_are_deterministic() -> None:
    findings = [
        {"category": "topology", "stage": "topology", "blocking": True, "message": "late"},
        {"category": "planning", "stage": "plan", "blocking": True, "message": "early"},
    ]
    stages = {"project_created": True, "requirements_valid": True, "plan_valid": False, "worker_reached": False}

    assert select_earliest_blocker(findings)["category"] == "planning"
    assert furthest_valid_stage(stages) == "requirements_valid"


def test_aggregate_counts_reconcile_to_five_projects_per_arm() -> None:
    projects = [
        {"arm": arm, "case_id": f"case-{index:03d}", "stages": {"requirements_valid": True}, "clarification": {"decision": "clarification_not_required"}, "earliest_blocker": {"category": "planning"}}
        for arm in ("current-production", "profile-b-sampling")
        for index in range(1, 6)
    ]

    aggregate = aggregate_phase2_projects(projects)

    assert aggregate["current-production"]["project_count"] == 5
    assert aggregate["profile-b-sampling"]["project_count"] == 5


def test_shared_failure_is_not_profile_specific() -> None:
    projects = [
        {"arm": "current-production", "case_id": "case-002", "earliest_blocker": {"category": "provenance", "signature": "trace_ambiguous"}},
        {"arm": "profile-b-sampling", "case_id": "case-002", "earliest_blocker": {"category": "provenance", "signature": "trace_ambiguous"}},
    ]

    aggregate = aggregate_phase2_projects(projects)

    assert aggregate["shared_blocker_signatures"]["trace_ambiguous"]["profile_dependent"] is False


def test_buildability_score_conflict_is_surfaced_and_authoritative_value_selected() -> None:
    result = reconcile_buildability_scores(
        [
            {"value": 0.9123, "source_file": "docs/GEMINI_PROFILE_B_STABILITY_REVIEW.md", "formula_version": "undocumented"},
            {"value": 0.9789, "source_file": "reports/buildability-scorecard.json", "formula_version": "gemini-profile-ablation-buildability-scorecard-v1", "input_record_count": 6},
        ]
    )

    assert result["conflict"] is True
    assert result["authoritative_value"] == 0.9789
    assert "formula" in result["reason"].lower()


def test_audit_record_contract_is_machine_readable(tmp_path: Path) -> None:
    record = {"arm": "current-production", "case_id": "case-001", "final_outcome": "candidate_ready"}
    output = tmp_path / "reconstruction.json"
    output.write_text(json.dumps({"projects": [record]}), encoding="utf-8")

    assert json.loads(output.read_text(encoding="utf-8"))["projects"][0]["case_id"] == "case-001"


def test_preserved_profile_b_adapter_proves_worker_reach_without_cad_success() -> None:
    root = Path(__file__).parents[2]
    result = reconstruct_phase2(
        root / "data/debug-sessions/gemini-profile-ablation/gemini-profile-ablation-01",
        root / "data/debug-sessions/gemini-flash-lite-study/gemini-flash-lite-study-01",
    )
    adapter = next(item for item in result["projects"] if item["arm"] == "profile-b-sampling" and item["case_id"] == "case-006")

    assert adapter["worker_audit"]["source_contract_passed"] is True
    assert adapter["worker_audit"]["worker_ready_valid_source"] is True
    assert adapter["worker_audit"]["worker_reached"] is True
    assert adapter["worker_audit"]["worker_runtime_failed"] is True
    assert adapter["worker_audit"]["topology_valid"] is False
    assert adapter["worker_audit"]["cad_success"] is False
    assert adapter["furthest_valid_stage"] == "worker_reached"


def test_preserved_scorecard_reconciliation_selects_reproducible_value() -> None:
    root = Path(__file__).parents[2]
    scorecard = json.loads((root / "data/debug-sessions/gemini-profile-ablation/gemini-profile-ablation-01/reports/buildability-scorecard.json").read_text(encoding="utf-8"))
    profile_b = scorecard["profiles"]["profile-b-sampling"]
    result = reconcile_buildability_scores([
        {"value": 0.9123, "source_file": "docs/GEMINI_PROFILE_B_STABILITY_REVIEW.md", "formula_version": "undocumented"},
        {"value": profile_b["buildability_score"], "source_file": "reports/buildability-scorecard.json", "formula_version": scorecard["schema_version"], "input_record_count": profile_b["runs"]},
    ])

    assert result["conflict"] is True
    assert result["authoritative_value"] == 0.9789
    assert result["authoritative_source"] == "reports/buildability-scorecard.json"


def test_preserved_phase2_reconstruction_has_one_outcome_per_case_and_arm() -> None:
    root = Path(__file__).parents[2]
    audit = audit_phase2(
        root / "data/debug-sessions/gemini-profile-ablation/gemini-profile-ablation-01",
        root / "data/debug-sessions/gemini-flash-lite-study/gemini-flash-lite-study-01",
        root,
    )
    projects = audit["reconstruction"]["projects"]

    assert len(projects) == 10
    assert len({(item["arm"], item["case_id"]) for item in projects}) == 10
    assert all(item["final_outcome"] for item in projects)
    assert audit["comparison"]["arms"]["current-production"]["project_count"] == 5
    assert audit["comparison"]["arms"]["profile-b-sampling"]["project_count"] == 5
    assert audit["decision"]["provider_calls_during_audit"] == 0
    assert audit["decision"]["worker_calls_during_audit"] == 0


def test_audited_manual_bundle_preserves_original_and_contains_all_phase2_evidence() -> None:
    root = Path(__file__).parents[2]
    reports = root / "data/debug-sessions/gemini-profile-ablation/gemini-profile-ablation-01/reports"
    original = reports / "all-responses-manual-review.json"
    audited = json.loads((reports / "all-responses-manual-review-audited.json").read_text(encoding="utf-8"))

    assert original.is_file()
    assert audited["schema_version"] == "gemini-profile-ablation-manual-review-audited-v1"
    assert audited["historical_bundle_preserved"] == "reports/all-responses-manual-review.json"
    assert len(audited["phase_2_audit"]["provider_calls"]) == 35
    assert len(audited["phase_2_audit"]["reconstruction"]["projects"]) == 10
    assert "/root/volundr" not in json.dumps(audited)


def test_historical_manual_bundle_hash_matches_preserved_snapshot() -> None:
    import hashlib

    root = Path(__file__).parents[2]
    historical = root / "data/debug-sessions/gemini-profile-ablation/gemini-profile-ablation-01/reports/historical/pre-phase2-audit"
    original = historical / "all-responses-manual-review.json"
    snapshot = json.loads((historical / "audit-snapshot.json").read_text(encoding="utf-8"))

    assert hashlib.sha256(original.read_bytes()).hexdigest() == snapshot["preserved_report_hashes"]["all-responses-manual-review.json"]
