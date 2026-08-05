from app.services.gemini_integration.forensics import (
    CausalGraph,
    CounterfactualFixture,
    DifferentialReplay,
    IssueRecord,
    IssueRegister,
    count_provider_successes,
    rank_issues,
    replay_evidence_offline,
    replay_captured_evidence_offline,
)


def _issue(issue_id: str, *, stage: str, classification: str = "root_cause", confidence: str = "confirmed") -> IssueRecord:
    return IssueRecord(
        issue_id=issue_id,
        project_id="project-001",
        stage=stage,
        primary_owner="provider_geometry",
        secondary_factors=(),
        classification=classification,
        symptom="invalid geometry response",
        incorrect_behavior="provider omitted required result assignment",
        expected_behavior="geometry assigns body",
        evidence_paths=("captures/provider.json",),
        input_hashes=("input",),
        output_hashes=("output",),
        confidence=confidence,
        recommended_fix_boundary="geometry adapter",
        provider_call_required=False,
    )


def test_issue_register_preserves_multiple_issues_and_earliest_blocker() -> None:
    register = IssueRegister()
    earliest = register.add(_issue("issue-01", stage="geometry"))
    latent = register.add(_issue("issue-02", stage="requirements", classification="latent_independent_defect"))

    assert earliest.issue_id == "issue-01"
    assert latent.issue_id == "issue-02"
    assert len(register.for_project("project-001")) == 2
    assert register.earliest_blocker("project-001").issue_id == "issue-02"


def test_causal_graph_preserves_typed_relationships() -> None:
    graph = CausalGraph()
    graph.add("issue-02", "issue-01", "exposed_after")
    graph.add("issue-03", "issue-01", "independent_of")

    assert graph.as_dict() == {
        "nodes": ["issue-01", "issue-02", "issue-03"],
        "edges": [
            {"source": "issue-02", "target": "issue-01", "relationship": "exposed_after"},
            {"source": "issue-03", "target": "issue-01", "relationship": "independent_of"},
        ],
    }


def test_counterfactuals_are_synthetic_and_excluded_from_provider_success() -> None:
    fixture = CounterfactualFixture(
        fixture_id="cf-001",
        project_id="project-001",
        single_variable_changed="geometry_response",
        evidence={"synthetic": True, "result": "pass"},
    )

    assert fixture.provider_success_eligible is False
    assert count_provider_successes([{"success": True}, fixture.as_dict()]) == 1


def test_differential_replay_does_not_confirm_a_fix_from_advancement_alone() -> None:
    replay = DifferentialReplay(
        before={"furthest_valid_stage": "geometry", "issues": ["issue-01"]},
        after={"furthest_valid_stage": "worker", "issues": ["issue-01"]},
    )

    result = replay.as_dict()

    assert result["changed_outcomes"] == ["furthest_valid_stage"]
    assert result["fix_confirmed"] is False
    assert result["attribution"] == ["furthest_valid_stage"]


def test_offline_replay_makes_no_provider_calls_and_ranking_is_evidence_based() -> None:
    replay = replay_evidence_offline(
        {"provider_attempts": [{"attempt_id": "a1"}], "project_outcomes": [{"project_id": "project-001"}]},
        validators=[lambda value: {"valid": bool(value)}],
    )
    ranked = rank_issues([
        (_issue("issue-01", stage="geometry"), {"frequency": 2, "severity": 3, "confidence": 1, "downstream_impact": 2, "estimated_correction_cost": 1}),
    ])

    assert replay["provider_calls"] == 0
    assert replay["worker_calls"] == 0
    assert replay["offline_only"] is True
    assert ranked[0]["issue_id"] == "issue-01"
    assert ranked[0]["raw_score"] == 12.0


def test_captured_replay_uses_authoritative_geometry_manifest_not_returned_slot_ids() -> None:
    attempt_id = "study:project-003:geometry:attempt-1"
    response = {"candidates": [{"content": {"parts": [{"text": '{"schema_version":"volundr-geometry-slots-v1","slots":[]}' }]}}]}
    evidence = {
        "study": {"study_id": "gemini-provider-contract-integration-01"},
        "projects": [{"project_id": "project-003", "expected_output_count": 1}],
        "provider_attempts": [{"attempt_id": attempt_id, "project_id": "project-003", "revision_id": "project-003:revision-001", "stage": "geometry", "response": response}],
    }
    boundaries = [{
        "boundary": "provider_geometry",
        "project_id": "project-003",
        "output": {"attempt_ids": [attempt_id]},
        "input": {"prompt_hash": "prompt", "request": {"geometry_slot_manifest": {"slots": [{"slot_id": 0}, {"slot_id": 1}]}}},
    }]

    replay = replay_captured_evidence_offline(evidence, boundaries=boundaries)

    record = replay["records"][0]
    assert record["authoritative_context"]["expected_slot_ids"] == [0, 1]
    assert record["adapter"]["accepted"] is False
    assert record["adapter"]["failure_class"] == "missing_slots"
