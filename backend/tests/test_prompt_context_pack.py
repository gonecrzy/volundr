from app.services.planning.context import PromptContextPackBuilder


def test_context_pack_is_stable_and_excludes_unrelated_history() -> None:
    builder = PromptContextPackBuilder()
    first = builder.build(
        project_id="project-1",
        workflow_run_id="run-1",
        planning_depth="direct_brief",
        active_requirements=[{"requirement_id": "width", "value": 80}],
        revision_delta=[],
        preserved_requirements=[],
        plan_artifact={"artifact_id": "brief-1", "payload": {"schema_version": "cad-brief-v1"}},
        selected_components=["primary_part"],
        selected_features=["body"],
        current_revision_summary={"revision_id": None},
        relevant_findings=[],
        scaffold_contract={"version": "cadquery-v1"},
        exposed_controls=[],
        unrelated_history=[{"event": "old_provider_response"}],
    )
    second = builder.build(
        project_id="project-1",
        workflow_run_id="run-1",
        planning_depth="direct_brief",
        active_requirements=[{"requirement_id": "width", "value": 80}],
        revision_delta=[],
        preserved_requirements=[],
        plan_artifact={"artifact_id": "brief-1", "payload": {"schema_version": "cad-brief-v1"}},
        selected_components=["primary_part"],
        selected_features=["body"],
        current_revision_summary={"revision_id": None},
        relevant_findings=[],
        scaffold_contract={"version": "cadquery-v1"},
        exposed_controls=[],
        unrelated_history=[{"event": "different_old_provider_response"}],
    )

    assert first["context_hash"] == second["context_hash"]
    assert first["excluded_context_categories"] == ["unrelated_history"]
    assert first["included_artifact_ids"] == ["brief-1"]
    assert first["inclusion_reasons"]["active_requirements"]


def test_context_pack_hash_changes_when_relevant_requirements_change() -> None:
    builder = PromptContextPackBuilder()
    base = builder.build(
        project_id="project-1",
        workflow_run_id="run-1",
        planning_depth="compact_plan",
        active_requirements=[{"requirement_id": "width", "value": 80}],
        revision_delta=[],
        preserved_requirements=[],
        plan_artifact={"artifact_id": "plan-1", "payload": {}},
        selected_components=[],
        selected_features=[],
        current_revision_summary={},
        relevant_findings=[],
        scaffold_contract={},
        exposed_controls=[],
    )
    changed = builder.build(
        project_id="project-1",
        workflow_run_id="run-1",
        planning_depth="compact_plan",
        active_requirements=[{"requirement_id": "width", "value": 90}],
        revision_delta=[],
        preserved_requirements=[],
        plan_artifact={"artifact_id": "plan-1", "payload": {}},
        selected_components=[],
        selected_features=[],
        current_revision_summary={},
        relevant_findings=[],
        scaffold_contract={},
        exposed_controls=[],
    )

    assert base["context_hash"] != changed["context_hash"]
