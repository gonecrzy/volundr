from __future__ import annotations

import json

from app.services.gemini_consistency.study_analyzer import (
    CANONICAL_STAGES,
    FINAL_OUTCOMES,
    build_corrected_study_reports,
    canonical_project_record,
    compare_study_evidence,
    earliest_blocker,
    replay_feature_evidence,
)


def _event(stage: str, event_type: str, *, blocking: bool = False, rule_id: str | None = None, message: str = "") -> dict:
    return {
        "stage": stage,
        "event_type": event_type,
        "blocking": blocking,
        "rule_id": rule_id,
        "message": message,
        "sequence_number": 1,
        "occurred_at": "2026-08-04T00:00:01Z",
    }


def _evidence(**overrides: object) -> dict:
    value = {
        "round": "baseline",
        "case_id": "case-001",
        "repetition": 1,
        "project_id": "project-1",
        "outcome_category": "completed",
        "outcome_state": "blocked_attempt",
        "final_outcome": "blocked",
        "requirements": {
            "requirements": [
                {
                    "requirement_id": "req-a",
                    "record_id": "volatile-a",
                    "created_at": "2026-08-04T00:00:00Z",
                    "kind": "clearance",
                    "type": "exact_dimension",
                    "operator": "minimum",
                    "value": 15,
                    "unit": "mm",
                    "provenance": {"source": "initial_user"},
                    "status": "active",
                    "subject": "stand",
                    "target": "port",
                }
            ]
        },
        "chat_responses": [],
        "generation_attempts": [
            {
                "attempt_id": "attempt-1",
                "status": "succeeded",
                "failure_class": "none",
                "provider_response": {
                    "classification": "valid",
                    "deterministic_normalization": False,
                    "repair_attempted": False,
                    "repair_eligibility": False,
                    "stage": "requirements",
                },
            }
        ],
        "workflow_events": {
            "workflow-1": [
                _event("requirement_extraction", "requirement_extraction.completed"),
                _event("planning", "planning.route.selected"),
            ]
        },
        "revisions": [],
        "workspace": {"artifact_integrity": {"status": "ok", "checked_count": 0, "missing_count": 0}},
    }
    value.update(overrides)
    return value


def test_generated_ids_do_not_affect_semantic_consistency() -> None:
    left = _evidence()
    right = _evidence(project_id="project-2")
    right["requirements"]["requirements"][0]["requirement_id"] = "req-b"
    right["requirements"]["requirements"][0]["record_id"] = "volatile-b"
    right["generation_attempts"][0]["attempt_id"] = "attempt-2"

    result = compare_study_evidence(left, right)

    assert result["fields"]["requirements"]["classification"] == "identical"
    assert result["fields"]["response_structure"]["classification"] == "identical"


def test_exact_clarification_wording_does_not_affect_consistency() -> None:
    left = _evidence(
        chat_responses=[
            {"phase": "clarification-1", "question": "What size should the opening be?", "answer": "15 mm"}
        ],
        workflow_events={"workflow-1": [_event("chat_workflow", "clarification.requested", message="Ask for the opening size.")]},
    )
    right = _evidence(
        chat_responses=[
            {"phase": "clarification-1", "question": "How wide must the port clearance be?", "answer": "15 mm"}
        ],
        workflow_events={"workflow-2": [_event("chat_workflow", "clarification.requested", message="Request the missing clearance measurement.")]},
    )

    assert compare_study_evidence(left, right)["fields"]["clarification"]["classification"] == "identical"


def test_requirement_order_is_ignored_but_value_and_operator_changes_are_not() -> None:
    left = _evidence()
    second = {**_evidence(), "project_id": "project-2"}
    second["requirements"] = {"requirements": list(reversed(left["requirements"]["requirements"]))}
    assert compare_study_evidence(left, second)["fields"]["requirements"]["classification"] == "identical"

    changed = _evidence()
    changed["requirements"]["requirements"][0]["value"] = 20
    assert compare_study_evidence(left, changed)["fields"]["requirements"]["classification"] == "materially_inconsistent"

    changed_operator = _evidence()
    changed_operator["requirements"]["requirements"][0]["operator"] = "maximum"
    assert compare_study_evidence(left, changed_operator)["fields"]["requirements"]["classification"] == "materially_inconsistent"


def test_response_hashes_do_not_determine_structural_consistency() -> None:
    left = _evidence()
    right = _evidence()
    left["generation_attempts"][0]["provider_response"]["raw_hash"] = "hash-a"
    right["generation_attempts"][0]["provider_response"]["raw_hash"] = "hash-b"

    assert compare_study_evidence(left, right)["fields"]["response_structure"]["classification"] == "identical"


def test_earliest_blocker_is_selected_from_authoritative_event_order() -> None:
    evidence = _evidence(
        workflow_events={
            "workflow-1": [
                {**_event("worker", "worker.failed", blocking=True, rule_id="worker.runtime"), "sequence_number": 9},
                {**_event("source_validation", "source_contract.failed", blocking=True, rule_id="source_contract.failed"), "sequence_number": 7},
            ]
        }
    )

    blocker = earliest_blocker(evidence)

    assert blocker is not None
    assert blocker["stage"] == "source_validation"
    assert blocker["signature"] == "source_contract"


def test_canonical_record_has_full_funnel_and_non_worker_blocker() -> None:
    record = canonical_project_record(_evidence())

    assert tuple(record["stage_funnel"]) == CANONICAL_STAGES
    assert record["earliest_blocker"] is not None
    assert record["final_outcome"] in FINAL_OUTCOMES
    assert record["stage_funnel"]["worker"]["status"] != "passed"


def test_failure_signature_totals_reconcile_with_terminal_projects() -> None:
    records = [canonical_project_record(_evidence(case_id=f"case-{index:03d}", repetition=1)) for index in range(1, 4)]
    report = {"projects": records}
    signatures = {record["earliest_blocker"]["signature"]: 0 for record in records if record["earliest_blocker"]}
    for record in records:
        if record["earliest_blocker"]:
            signatures[record["earliest_blocker"]["signature"]] += 1

    assert sum(signatures.values()) == len(report["projects"])


def test_valid_source_requires_worker_ready_source_not_any_succeeded_attempt() -> None:
    record = canonical_project_record(_evidence())
    assert record["stage_funnel"]["source_validation"]["status"] != "passed"
    assert record["metrics"]["worker_ready_valid_source"] is False

    ready = _evidence(
        workflow_events={
            "workflow-1": [
                _event("source_contract_validation", "source_contract.passed"),
                _event("worker_submission", "worker.submitted"),
            ]
        },
        revisions=[
            {
                "status": "succeeded",
                "is_accepted": True,
                "metadata": {"connected_components": 1, "is_watertight": True},
            }
        ],
        outcome_state="working_version",
    )
    assert canonical_project_record(ready)["metrics"]["worker_ready_valid_source"] is True


def test_verification_not_run_differs_from_feature_absent() -> None:
    not_run = canonical_project_record(_evidence())
    assert not_run["feature_evidence"]["status"] == "verification_not_run"

    absent = _evidence(
        workflow_events={"workflow-1": [_event("topology_validation", "topology.passed")]},
        revisions=[
            {
                "status": "succeeded",
                "is_accepted": True,
                "metadata": {"connected_components": 1, "is_watertight": True},
                "functional_status": "functionally_verified",
            }
        ],
        outcome_state="working_version",
    )
    assert canonical_project_record(absent)["feature_evidence"]["status"] == "no_verification_target"


def test_replay_reconstructs_available_feature_evidence() -> None:
    evidence = _evidence(
        revisions=[
            {
                "status": "succeeded",
                "is_accepted": True,
                "metadata": {"connected_components": 1, "is_watertight": True},
                "feature_measurements": [{"feature": "hole", "status": "measured", "value": 5}],
            }
        ],
        outcome_state="working_version",
    )
    result = replay_feature_evidence(evidence)
    assert result["status"] == "measured"
    assert result["measurements"] == [{"feature": "hole", "status": "measured", "value": 5}]


def test_offline_regeneration_writes_reports_without_provider_calls(tmp_path) -> None:
    root = tmp_path / "study"
    for round_name in ("baseline", "validation"):
        path = root / round_name / "repetition-01" / "projects" / "case-001" / "project-1" / "evidence.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(_evidence(round=round_name)), encoding="utf-8")

    result = build_corrected_study_reports(root, preserve_history=False)
    assert result["provider_calls"] == 0
    assert result["rounds"]["baseline"]["record_count"] == 1
    assert (root / "reports" / "corrected" / "baseline.json").is_file()


def test_historical_reports_are_preserved(tmp_path) -> None:
    root = tmp_path / "study"
    old = root / "reports" / "baseline.json"
    old.parent.mkdir(parents=True)
    old.write_text('{"historical": true}\n', encoding="utf-8")
    path = root / "baseline" / "repetition-01" / "projects" / "case-001" / "project-1" / "evidence.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_evidence()), encoding="utf-8")

    build_corrected_study_reports(root)

    historical = list((root / "reports" / "historical").rglob("baseline.json"))
    assert historical
    assert json.loads(historical[0].read_text())["historical"] is True


def test_baseline_and_validation_evidence_remain_separate(tmp_path) -> None:
    root = tmp_path / "study"
    for round_name in ("baseline", "validation"):
        path = root / round_name / "repetition-01" / "projects" / "case-001" / "project-1" / "evidence.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(_evidence(round=round_name)), encoding="utf-8")

    result = build_corrected_study_reports(root, preserve_history=False)
    assert result["rounds"]["baseline"]["round"] == "baseline"
    assert result["rounds"]["validation"]["round"] == "validation"
