import json
from pathlib import Path

from app.services.cad.geometry_slots import (
    GEOMETRY_SLOTS_SCHEMA_VERSION,
    build_focused_slot_completion,
    merge_geometry_slots,
    parse_geometry_slots,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "geometry_slots"


ORGANIZER_MANIFEST = {
    "schema_version": GEOMETRY_SLOTS_SCHEMA_VERSION,
    "planning_depth": "direct_brief",
    "slots": [
        {
            "slot_id": 0,
            "function_id": "_ai_component_organizer_body",
            "signature": ["params"],
            "owner_component_id": "organizer",
            "required_feature_ids": [],
            "authorized_parameter_ids": ["width"],
            "approved_helpers": ["resolve_pattern_points", "place_pattern_cutters"],
            "required_inputs": ["width"],
            "required_result": "component_shape",
        },
        {
            "slot_id": 1,
            "function_id": "_ai_feature_outer_shell",
            "signature": ["body", "params"],
            "owner_component_id": "organizer",
            "required_feature_ids": ["outer_shell"],
            "authorized_parameter_ids": ["width"],
            "approved_helpers": [],
            "required_inputs": ["body"],
            "required_result": "modified_shape",
        },
        {
            "slot_id": 2,
            "function_id": "_ai_feature_final_cleanup",
            "signature": ["body", "params"],
            "owner_component_id": "organizer",
            "required_feature_ids": ["final_cleanup"],
            "authorized_parameter_ids": ["width"],
            "approved_helpers": [],
            "required_inputs": ["body"],
            "required_result": "modified_shape",
        },
    ],
}


def _load(name: str) -> dict:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def test_frozen_valid_simplified_organizer_replays_as_complete_slots() -> None:
    result = parse_geometry_slots(
        json.dumps(_load("simplified_organizer_valid.json")), ORGANIZER_MANIFEST
    )

    assert result.is_complete
    assert result.completed_slot_ids == [0, 1, 2]
    assert len(result.slot_body_hashes) == 3


def test_frozen_wrong_count_receives_only_missing_slot_scope() -> None:
    result = parse_geometry_slots(
        json.dumps(_load("simplified_organizer_wrong_count.json")), ORGANIZER_MANIFEST
    )
    context = build_focused_slot_completion(result, ORGANIZER_MANIFEST)

    assert result.completed_slot_ids == [0, 1]
    assert result.missing_slot_ids == [2]
    assert context["requested_slot_ids"] == [2]


def test_frozen_organizer_undeclared_parameter_is_invalid_but_other_slots_remain_usable() -> None:
    result = parse_geometry_slots(
        json.dumps(_load("current_organizer_undeclared_corner_radius.json")), ORGANIZER_MANIFEST
    )

    assert result.invalid_slots[0]["slot_id"] == 1
    assert result.invalid_slots[0]["rule_id"] == "geometry_body.undeclared_parameter"
    assert result.completed_slot_ids == [0, 2]


def test_frozen_import_and_provider_signature_responses_are_blocked() -> None:
    imported = parse_geometry_slots(
        json.dumps(_load("simplified_organizer_imports.json")), ORGANIZER_MANIFEST
    )
    unsupported = parse_geometry_slots(
        json.dumps(_load("simplified_organizer_unsupported_arguments.json")), ORGANIZER_MANIFEST
    )

    assert imported.invalid_slots[0]["rule_id"] == "geometry_slot.invalid_statement"
    assert unsupported.invalid_slots[0]["rule_id"] == "geometry_slot.invalid_statement"


def test_frozen_screw_lid_helper_response_is_blocked_before_worker() -> None:
    result = parse_geometry_slots(
        json.dumps(_load("current_screw_lid_unsupported_helper.json")), ORGANIZER_MANIFEST
    )

    assert result.invalid_slots[0]["rule_id"] == "geometry_body.unbound_name"


def test_frozen_wall_repair_changes_only_the_affected_slot() -> None:
    fixture = _load("wall_carrier_worker_repair.json")
    initial = parse_geometry_slots(json.dumps(fixture["initial"]), ORGANIZER_MANIFEST)
    repaired = parse_geometry_slots(json.dumps(fixture["repair"]), {**ORGANIZER_MANIFEST, "slots": [ORGANIZER_MANIFEST["slots"][1]]})
    merged = merge_geometry_slots(initial, repaired, ORGANIZER_MANIFEST)

    assert merged.is_complete
    assert merged.slot_body_hashes[0] == initial.slot_body_hashes[0]
    assert 1 not in initial.slot_body_hashes
    assert merged.slot_body_hashes[1]
