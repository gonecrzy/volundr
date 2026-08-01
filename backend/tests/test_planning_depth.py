from app.services.planning.brief import DirectCadBriefBuilder
from app.services.planning.depth import PlanningDepth, PlanningDepthRouter


def requirement(requirement_id: str, requirement_type: str, value=None, *, importance: str = "important") -> dict:
    return {
        "requirement_id": requirement_id,
        "type": requirement_type,
        "value": value,
        "importance": importance,
        "status": "active",
    }


def test_fully_specified_single_part_routes_to_direct_brief_without_name_matching() -> None:
    router = PlanningDepthRouter()

    decision = router.route(
        active_requirements=[
            requirement("width", "exact_dimension", 80.0, importance="critical"),
            requirement("height", "exact_dimension", 45.0, importance="critical"),
            requirement("thickness", "exact_dimension", 6.0, importance="critical"),
            requirement("hole_count", "count", 2, importance="critical"),
            requirement("hole_diameter", "exact_dimension", 5.0, importance="critical"),
            requirement("hole_positions", "position", [{"x": 12.0}, {"x": 62.0}], importance="critical"),
        ],
        project_state={"printable_component_count": 1, "output_count": 1},
        specification={"functional_requirements": [], "missing_requirements": [], "conflicts": []},
    )

    assert decision.outcome == PlanningDepth.DIRECT_BRIEF
    assert any("single printable component" in reason for reason in decision.reasons)
    assert decision.ambiguous_factors == []


def test_functional_interactions_route_to_compact_plan_without_product_name_logic() -> None:
    router = PlanningDepthRouter()

    decision = router.route(
        active_requirements=[
            requirement("object_fit", "fit", 81.0, importance="critical"),
            requirement("wall_mount", "mounting_interface", "wall", importance="critical"),
            requirement("vertical_support", "support", True, importance="critical"),
            requirement("motion_retention", "retention", "resist movement", importance="critical"),
            requirement("one_hand_removal", "removal_access", True, importance="important"),
        ],
        project_state={"printable_component_count": 1, "output_count": 1},
        specification={"functional_requirements": ["fit", "mount", "support", "retention"], "missing_requirements": [], "conflicts": []},
    )

    assert decision.outcome == PlanningDepth.COMPACT_PLAN
    assert any("interacting functional features" in reason for reason in decision.reasons)


def test_multipart_relationships_route_to_detailed_plan() -> None:
    decision = PlanningDepthRouter().route(
        active_requirements=[requirement("lid_fit", "relationship", "removable lid", importance="critical")],
        project_state={
            "printable_component_count": 2,
            "output_count": 2,
            "assembly_relationships": [{"from": "body", "to": "lid", "type": "mates"}],
            "moving_interfaces": [{"component": "lid", "type": "removable"}],
        },
        specification={"functional_requirements": ["mating interface"], "missing_requirements": [], "conflicts": []},
    )

    assert decision.outcome == PlanningDepth.DETAILED_PLAN
    assert any("multiple printable components" in reason for reason in decision.reasons)


def test_missing_fit_critical_information_routes_to_clarification() -> None:
    decision = PlanningDepthRouter().route(
        active_requirements=[
            requirement("board_fit", "fit", None, importance="critical"),
            requirement("lid", "feature_presence", True, importance="important"),
        ],
        project_state={"printable_component_count": 1, "output_count": 1},
        specification={
            "functional_requirements": ["containment"],
            "missing_requirements": [{"id": "board_fit", "importance": "critical", "reason": "mating dimensions"}],
            "conflicts": [],
        },
    )

    assert decision.outcome == PlanningDepth.CLARIFICATION_REQUIRED
    assert decision.missing_information[0]["requirement_id"] == "board_fit"


def test_direct_brief_is_deterministic_and_keeps_proposals_separate_from_requirements() -> None:
    brief = DirectCadBriefBuilder().build(
        project_id="project-1",
        active_requirements=[
            requirement("width", "exact_dimension", 80.0, importance="critical"),
            requirement("height", "exact_dimension", 45.0, importance="critical"),
            requirement("thickness", "exact_dimension", 6.0, importance="critical"),
        ],
        revision_delta=[],
        preserved_requirements=[],
        project_state={"printable_component_count": 1, "output_count": 1},
    )

    payload = brief.to_payload()
    assert payload["schema_version"] == "cad-brief-v1"
    assert payload["planning_depth"] == "direct_brief"
    assert [item["requirement_id"] for item in payload["requirements"]] == ["width", "height", "thickness"]
    assert all(item["source"] == "requirement_ledger" for item in payload["requirements"])
    assert all(item["source"] == "volundr_proposal" for item in payload["proposals"])
    assert payload["exposed_controls"] == []
