from app.services.planning.context import normalize_geometry_execution_context


def test_all_plan_shapes_normalize_to_one_execution_context() -> None:
    context = normalize_geometry_execution_context(
        planning_depth="direct_brief",
        plan_artifact_id="artifact-brief",
        plan={
            "schema_version": "cad-brief-v1",
            "components": [{"id": "primary_part", "role": "printable_part"}],
            "required_features": [{"id": "body", "component_id": "primary_part"}],
            "outputs": ["STEP", "STL", "BREP"],
            "validation_targets": [{"type": "solid_count", "value": 1}],
        },
        active_requirements=[{"requirement_id": "width", "type": "exact_dimension", "value": 80}],
        revision_delta=[{"requirement_id": "thickness", "operation": "change", "value": 7}],
        preserved_requirements=[{"requirement_id": "hole_count", "type": "count", "value": 2}],
    )

    assert context["schema_version"] == "geometry-execution-context-v1"
    assert context["planning_depth"] == "direct_brief"
    assert context["plan_artifact_id"] == "artifact-brief"
    assert context["active_requirements"][0]["requirement_id"] == "width"
    assert context["revision_delta"][0]["requirement_id"] == "thickness"
    assert context["preserve_requirements"][0]["requirement_id"] == "hole_count"
    assert context["outputs"] == ["STEP", "STL", "BREP"]
