import json

import pytest

from app.services.ai.gemini_cli import (
    CADQUERY_GEOMETRY_SLOTS_PROMPT_VERSION,
    GeminiCliProvider,
)
from app.services.ai.provider import ModelGenerationRequest
from app.services.cad.geometry_slots import (
    GEOMETRY_SLOTS_SCHEMA_VERSION,
    GeometrySlotError,
    build_geometry_slot_brief,
    build_focused_slot_completion,
    build_focused_slot_repair,
    merge_geometry_slots,
    parse_geometry_slots,
    select_geometry_contract,
)


MANIFEST = {
    "schema_version": GEOMETRY_SLOTS_SCHEMA_VERSION,
    "planning_depth": "direct_brief",
    "slots": [
        {
            "slot_id": 0,
            "function_id": "_ai_component_body",
            "signature": ["params"],
            "owner_component_id": "body",
            "required_feature_ids": [],
            "authorized_parameter_ids": ["width"],
            "approved_helpers": ["resolve_pattern_points"],
            "required_inputs": ["width"],
            "required_result": "component_shape",
        },
        {
            "slot_id": 1,
            "function_id": "_ai_feature_mounting_holes",
            "signature": ["body", "params"],
            "owner_component_id": "body",
            "required_feature_ids": ["mounting_holes"],
            "authorized_parameter_ids": ["width"],
            "approved_helpers": [],
            "required_inputs": ["body"],
            "required_result": "modified_shape",
        },
    ],
}


def _response(*slots: dict) -> str:
    return json.dumps({"schema_version": GEOMETRY_SLOTS_SCHEMA_VERSION, "slots": list(slots)})


def test_provider_response_order_does_not_change_volundr_owned_mapping() -> None:
    result = parse_geometry_slots(
        _response(
            {
                "slot_id": 1,
                "statements": ["modified = body"],
                "result_symbol": "modified",
            },
            {
                "slot_id": 0,
                "statements": ['body = cq.Workplane("XY").box(params["width"], 10, 3)'],
                "result_symbol": "body",
            },
        ),
        MANIFEST,
    )

    assert result.completed_slot_ids == [0, 1]
    assert result.functions["_ai_component_body"].startswith("def _ai_component_body(params)")
    assert result.functions["_ai_feature_mounting_holes"].startswith(
        "def _ai_feature_mounting_holes(body, params)"
    )


@pytest.mark.parametrize(
    ("record", "rule_id"),
    [
        (
            {"slot_id": 0, "statements": ["import os", "body = cq.Workplane('XY')"], "result_symbol": "body"},
            "geometry_slot.invalid_statement",
        ),
        (
            {"slot_id": 0, "statements": ["def nested():", "    pass", "body = cq.Workplane('XY')"], "result_symbol": "body"},
            "geometry_slot.invalid_statement",
        ),
        (
            {"slot_id": 0, "statements": ["body = cq.Workplane('XY')"], "result_symbol": "build"},
            "geometry_slot.result_symbol_invalid",
        ),
        (
            {"slot_id": 0, "statements": ["body = circular_pattern_points(4)"], "result_symbol": "body"},
            "geometry_body.unbound_name",
        ),
    ],
)
def test_slot_validation_rejects_provider_owned_structure_and_unavailable_helpers(
    record: dict, rule_id: str
) -> None:
    result = parse_geometry_slots(_response(record), MANIFEST)
    assert result.completed_slot_ids == []
    assert result.invalid_slots[0]["rule_id"] == rule_id


def test_duplicate_and_unknown_slots_are_rejected() -> None:
    duplicate = _response(
        {"slot_id": 0, "statements": ["body = cq.Workplane('XY')"], "result_symbol": "body"},
        {"slot_id": 0, "statements": ["body = cq.Workplane('XY')"], "result_symbol": "body"},
    )
    with pytest.raises(GeometrySlotError, match="duplicate"):
        parse_geometry_slots(duplicate, MANIFEST)

    unknown = _response(
        {"slot_id": 99, "statements": ["body = cq.Workplane('XY')"], "result_symbol": "body"}
    )
    with pytest.raises(GeometrySlotError, match="unknown"):
        parse_geometry_slots(unknown, MANIFEST)


def test_missing_slots_are_classified_and_merge_preserves_completed_hashes() -> None:
    initial = parse_geometry_slots(
        _response(
            {
                "slot_id": 0,
                "statements": ['body = cq.Workplane("XY").box(params["width"], 10, 3)'],
                "result_symbol": "body",
            }
        ),
        MANIFEST,
    )
    assert initial.missing_slot_ids == [1]

    completion = parse_geometry_slots(
        _response({"slot_id": 1, "statements": ["modified = body"], "result_symbol": "modified"}),
        {**MANIFEST, "slots": [MANIFEST["slots"][1]]},
    )
    merged = merge_geometry_slots(initial, completion, MANIFEST)
    assert merged.completed_slot_ids == [0, 1]
    assert merged.slot_body_hashes[0] == initial.slot_body_hashes[0]


def test_completion_cannot_change_completed_slot() -> None:
    initial = parse_geometry_slots(
        _response(
            {"slot_id": 0, "statements": ["body = cq.Workplane('XY')"], "result_symbol": "body"}
        ),
        MANIFEST,
    )
    changed = parse_geometry_slots(
        _response(
            {
                "slot_id": 0,
                "statements": ['body = cq.Workplane("XZ")'],
                "result_symbol": "body",
            }
        ),
        {**MANIFEST, "slots": [MANIFEST["slots"][0]]},
    )
    with pytest.raises(GeometrySlotError, match="completed slot"):
        merge_geometry_slots(initial, changed, MANIFEST)


def test_worker_repair_context_scopes_one_slot_and_preserves_other_hashes() -> None:
    initial = parse_geometry_slots(
        _response(
            {"slot_id": 0, "statements": ["body = cq.Workplane('XY')"], "result_symbol": "body"},
            {"slot_id": 1, "statements": ["modified = body"], "result_symbol": "modified"},
        ),
        MANIFEST,
    )
    context = build_focused_slot_repair(
        initial,
        MANIFEST,
        function_id="_ai_feature_mounting_holes",
        worker_diagnostics="CadQuery traceback",
    )
    repair = parse_geometry_slots(
        _response(
            {
                "slot_id": 1,
                "statements": ["modified = body.translate((1, 0, 0))"],
                "result_symbol": "modified",
            }
        ),
        context["slot_manifest"],
    )

    merged = merge_geometry_slots(
        initial,
        repair,
        MANIFEST,
        replace_slot_ids={1},
    )

    assert context["requested_slot_ids"] == [1]
    assert context["worker_diagnostics"] == "CadQuery traceback"
    assert merged.slot_body_hashes[0] == initial.slot_body_hashes[0]
    assert merged.slot_body_hashes[1] != initial.slot_body_hashes[1]


def test_focused_completion_context_contains_only_unfinished_slots_and_preserved_hashes() -> None:
    initial = parse_geometry_slots(
        _response(
            {"slot_id": 0, "statements": ["body = cq.Workplane('XY')"], "result_symbol": "body"}
        ),
        MANIFEST,
    )

    context = build_focused_slot_completion(initial, MANIFEST)

    assert [item["slot_id"] for item in context["slot_manifest"]["slots"]] == [1]
    assert context["requested_slot_ids"] == [1]
    assert context["preserved_slot_hashes"] == {"0": initial.slot_body_hashes[0]}
    assert context["invalid_slots"] == []


def test_route_policy_selects_slots_for_direct_and_compact_only_by_default() -> None:
    assert select_geometry_contract("direct_brief") == GEOMETRY_SLOTS_SCHEMA_VERSION
    assert select_geometry_contract("compact_plan") == GEOMETRY_SLOTS_SCHEMA_VERSION
    assert select_geometry_contract("detailed_plan") == "legacy_contract"
    assert select_geometry_contract("detailed_plan", "geometry_slots_v1") == GEOMETRY_SLOTS_SCHEMA_VERSION
    assert select_geometry_contract("direct_brief", "legacy_contract") == "legacy_contract"


def test_provider_brief_is_reduced_to_geometry_relevant_fields() -> None:
    brief = build_geometry_slot_brief(
        planning_depth="direct_brief",
        active_requirements=[{"id": "req_width", "subject": "width", "value": 80, "unit": "mm"}],
        requirement_delta=[{"id": "req_width", "change": "preserve"}],
        preserved_requirements=[{"id": "req_height"}],
        proposals=[{"id": "proposal_clearance", "value": 1.5}],
        design_plan={
            "components": [{"id": "body", "name": "body"}],
            "features": [{"id": "mounting_holes", "component_id": "body", "role": "mount"}],
            "printable_outputs": [{"id": "body_output", "component_ids": ["body"]}],
            "coordinate_frames": [{"id": "frame_xy", "plane": "XY"}],
            "relationships": [{"type": "supports", "source": "body", "target": "mounting_holes"}],
            "validation_targets": [{"id": "internal-only", "rule": "hidden"}],
        },
        slot_manifest=MANIFEST,
        exposed_controls=[{"id": "control_width"}],
    )

    assert set(brief) == {
        "schema_version",
        "planning_depth",
        "active_requirements",
        "revision_delta",
        "preserved_requirements",
        "proposals",
        "components",
        "features",
        "printable_outputs",
        "coordinate_frames",
        "relationships",
        "exposed_controls",
        "slots",
        "output_obligations",
        "restrictions",
    }
    assert "validation_targets" not in brief
    assert "internal-only" not in json.dumps(brief)


def test_one_part_obligation_requires_integral_features_and_declares_cuts() -> None:
    brief = build_geometry_slot_brief(
        planning_depth="compact_plan",
        active_requirements=[],
        requirement_delta=[],
        preserved_requirements=[],
        proposals=[],
        design_plan={
            "features": [
                {"id": "base", "component_id": "body", "operation": "extrude_boss"},
                {"id": "handle", "component_id": "body", "operation": "extrude_boss"},
                {"id": "notch", "component_id": "body", "operation": "extrude_cut"},
            ],
            "printable_outputs": [
                {
                    "id": "body_output",
                    "component_ids": ["body"],
                    "expected_solid_count": 1,
                }
            ],
        },
        slot_manifest={**MANIFEST, "output_obligations": [{"output_id": "body_output"}]},
    )

    assert brief["output_obligations"] == [{"output_id": "body_output"}]
    assert "raw full chat" in " ".join(brief["restrictions"])


def test_slot_prompt_has_provider_only_response_authority() -> None:
    provider = GeminiCliProvider(binary="gemini-test", model="model-test")
    request = ModelGenerationRequest(
        project_name="Organizer",
        original_intent="organizer",
        user_instruction="build it",
        generation_contract_version="cadquery-scaffold-v1",
        geometry_contract=GEOMETRY_SLOTS_SCHEMA_VERSION,
        geometry_slot_manifest=MANIFEST,
        geometry_slot_brief=build_geometry_slot_brief(
            planning_depth="direct_brief",
            active_requirements=[],
            requirement_delta=[],
            preserved_requirements=[],
            proposals=[],
            design_plan={"components": [], "features": [], "printable_outputs": []},
            slot_manifest=MANIFEST,
        ),
    )

    prompt = provider.build_cadquery_prompt(request)

    assert CADQUERY_GEOMETRY_SLOTS_PROMPT_VERSION in prompt
    assert GEOMETRY_SLOTS_SCHEMA_VERSION in prompt
    assert '"slot_id": 0' in prompt
    assert "def _ai_component_body" not in prompt
    assert "function_id" not in prompt
    assert "Return only statements and result_symbol" in prompt
