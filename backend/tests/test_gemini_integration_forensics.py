from app.services.gemini_integration.forensics import (
    CausalGraph,
    CounterfactualFixture,
    DifferentialReplay,
    IssueRecord,
    IssueRegister,
    count_provider_successes,
    rank_issues,
    replay_evidence_offline,
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

