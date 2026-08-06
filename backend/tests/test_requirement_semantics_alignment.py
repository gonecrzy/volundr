from app.services.projects.requirement_trace_contract import build_requirement_trace_manifest
from types import SimpleNamespace

from app.services.projects.requirement_ledger import (
    _entry_payload,
    apply_requirement_delta,
    build_requirement_ledger,
    requirement_delta_for_message,
)
from app.services.planning.brief import DirectCadBriefBuilder
from app.services.requirements.trace import (
    build_explicit_requirement_inventory,
    explicit_item,
    validate_design_specification_trace,
)


def _capacity_specification(*, requirement_id: str = "storage_capacity") -> dict:
    return {
        "explicit_requirements": [
            {
                "requirement_id": requirement_id,
                "id": requirement_id,
                "label": "Storage capacity",
                "type": "capacity",
                "kind": "capacity",
                "operator": "up_to",
                "value": 5,
                "unit": "item",
                "subject": "storage_holder",
                "object_type": "storage_bin",
                "target": "storage",
                "source": "user",
                "explicit": True,
                "protected": True,
                "raw_evidence": "can hold up to 5 storage bins",
            }
        ]
    }


def _capacity_plan(*, feature_count: int = 1) -> dict:
    features = [
        {
            "id": f"storage_slots_{index}",
            "component_id": "primary",
            "type": "slot_array",
            "semantic_type": "capacity",
            "description": "Repeated storage positions for the supported object type.",
        }
        for index in range(feature_count)
    ]
    return {
        "components": [{"id": "primary", "role": "printable_part", "features": [item["id"] for item in features]}],
        "features": features,
        "printable_outputs": [{"id": "primary_output", "component_ids": ["primary"]}],
        "validation_targets": [
            {
                "id": "verify_storage_capacity",
                "type": "capacity",
                "measurement": "supported_capacity",
                "expected_value": 5,
                "unit": "item",
                "object_type": "storage_bin",
                "description": "Verify supported capacity for the object type.",
            }
        ],
    }


def _trace(specification: dict, plan: dict) -> dict:
    feature_components = {
        str(feature["id"]): str(feature["component_id"])
        for feature in plan.get("features", [])
    }
    feature_symbols = {
        feature_id: f"build_{feature_id}"
        for feature_id in feature_components
    }
    return build_requirement_trace_manifest(
        design_specification_payload=specification,
        design_plan_payload=plan,
        source_component_ids={"primary"},
        source_component_symbols={"primary": "build_primary"},
        source_feature_components=feature_components,
        source_feature_symbols=feature_symbols,
        source_output_ids={"primary_output"},
        source_output_components={"primary_output": ["primary"]},
        source_parameter_ids=set(),
    )


def test_up_to_capacity_preserves_operator_and_object_semantics() -> None:
    item = build_explicit_requirement_inventory(
        "Create a holder that can hold up to 5 3600 size tackle trays."
    )[0]

    assert item["kind"] == "capacity"
    assert item["operator"] == "up_to"
    assert item["value"] == 5
    assert item["unit"] == "tray"
    assert item["object_type"] == "3600_size_tackle_tray"


def test_explicit_item_preserves_semantic_operator_fields() -> None:
    item = explicit_item(
        "storage_capacity",
        5,
        unit="item",
        requirement_type="capacity",
        kind="capacity",
        operator="up_to",
        subject="storage_holder",
        object_type="storage_bin",
        target="storage",
        evidence="can hold up to 5 storage bins",
    )

    assert item["kind"] == "capacity"
    assert item["operator"] == "up_to"
    assert item["subject"] == "storage_holder"
    assert item["object_type"] == "storage_bin"
    assert item["target"] == "storage"
    assert item["raw_evidence"] == "can hold up to 5 storage bins"


def test_unique_typed_capacity_feature_and_target_are_normalized() -> None:
    result = _trace(_capacity_specification(), _capacity_plan())
    obligation = result["normalized"]["obligations"][0]

    assert obligation["status"] == "geometry_verification_target"
    assert obligation["plan_feature_id"] == "storage_slots_0"
    assert obligation["validation_target_id"] == "verify_storage_capacity"
    assert any(
        finding["rule_id"] == "design_artifact.requirement_trace_normalized"
        for finding in result["findings"]
    )


def test_unique_validation_target_resolves_supporting_feature_ambiguity() -> None:
    specification = {
        "explicit_requirements": [
            {
                "requirement_id": "carrying_handle",
                "id": "carrying_handle",
                "label": "Carrying handle",
                "type": "feature_presence",
                "kind": "feature",
                "operator": "present",
                "value": True,
                "source": "user",
                "explicit": True,
                "protected": True,
            }
        ]
    }
    plan = {
        "components": [
            {"id": "holder_body", "role": "printable_part", "features": ["handle_mounts"]},
            {"id": "carrying_handle", "role": "printable_part", "features": ["handle_grip"]},
        ],
        "features": [
            {
                "id": "handle_mounts",
                "component_id": "holder_body",
                "type": "bosses",
                "description": "Supporting bosses for the handle",
                "requirement_ids": ["carrying_handle"],
            },
            {
                "id": "handle_grip",
                "component_id": "carrying_handle",
                "type": "solid_bar",
                "description": "The user-gripped carrying handle",
                "requirement_ids": ["carrying_handle"],
            },
        ],
        "printable_outputs": [
            {
                "id": "holder_assembly",
                "component_ids": ["holder_body", "carrying_handle"],
                "required": True,
            }
        ],
        "validation_targets": [
            {
                "id": "validate_carrying_handle",
                "feature_id": "handle_grip",
                "component_id": "carrying_handle",
                "requirement_ids": ["carrying_handle"],
                "measurement": "presence",
                "type": "feature_presence",
            }
        ],
    }
    result = build_requirement_trace_manifest(
        design_specification_payload=specification,
        design_plan_payload=plan,
        source_component_ids={"holder_body", "carrying_handle"},
        source_component_symbols={
            "holder_body": "build_holder_body",
            "carrying_handle": "build_carrying_handle",
        },
        source_feature_components={
            "handle_mounts": "holder_body",
            "handle_grip": "carrying_handle",
        },
        source_feature_symbols={
            "handle_mounts": "apply_handle_mounts",
            "handle_grip": "apply_handle_grip",
        },
        source_output_ids={"holder_assembly"},
        source_output_components={"holder_assembly": ["holder_body", "carrying_handle"]},
        source_parameter_ids=set(),
    )

    obligation = result["normalized"]["obligations"][0]
    assert obligation["plan_feature_id"] == "handle_grip"
    assert obligation["owning_component_id"] == "carrying_handle"
    assert obligation["status"] == "source_trace"
    assert not any(
        finding["rule_id"] == "design_artifact.requirement_trace_ambiguous"
        and finding["is_blocking"]
        for finding in result["findings"]
    )
    normalized = next(
        finding
        for finding in result["findings"]
        if finding["rule_id"] == "design_artifact.requirement_trace_normalized"
    )
    assert normalized["metadata"]["selected_match"]["feature_id"] == "handle_grip"
    assert normalized["metadata"]["rejected_matches"] == ["handle_mounts"]


def test_equal_feature_candidates_without_unique_target_remain_ambiguous() -> None:
    specification = {
        "explicit_requirements": [
            {
                "requirement_id": "carrying_handle",
                "id": "carrying_handle",
                "type": "feature_presence",
                "kind": "feature",
                "operator": "present",
                "value": True,
                "source": "user",
                "explicit": True,
                "protected": True,
            }
        ]
    }
    plan = {
        "components": [{"id": "holder_body", "role": "printable_part"}],
        "features": [
            {"id": "handle_a", "component_id": "holder_body", "type": "solid_bar", "requirement_ids": ["carrying_handle"]},
            {"id": "handle_b", "component_id": "holder_body", "type": "solid_bar", "requirement_ids": ["carrying_handle"]},
        ],
        "printable_outputs": [{"id": "holder_output", "component_ids": ["holder_body"], "required": True}],
        "validation_targets": [],
    }
    result = build_requirement_trace_manifest(
        design_specification_payload=specification,
        design_plan_payload=plan,
        source_component_ids={"holder_body"},
        source_component_symbols={"holder_body": "build_holder_body"},
        source_feature_components={"handle_a": "holder_body", "handle_b": "holder_body"},
        source_feature_symbols={"handle_a": "apply_handle_a", "handle_b": "apply_handle_b"},
        source_output_ids={"holder_output"},
        source_output_components={"holder_output": ["holder_body"]},
        source_parameter_ids=set(),
    )

    obligation = result["normalized"]["obligations"][0]
    assert obligation["blocking"] is True
    assert obligation["status"] == "trace_ambiguous"


def test_explicit_cross_feature_layout_keeps_all_feature_links() -> None:
    specification = {
        "functional_requirements": [
            {
                "id": "asymmetric_feature_placement",
                "type": "orientation",
                "kind": "orientation",
                "operator": "qualitative",
                "target": "mounting plate",
                "value": "asymmetric",
                "source": "user",
                "explicit": True,
                "protected": True,
            }
        ]
    }
    plan = {
        "components": [
            {"id": "mounting_plate_comp", "label": "Mounting Plate", "role": "printable_part"}
        ],
        "features": [
            {
                "id": "mounting_holes_feature_id",
                "component_id": "mounting_plate_comp",
                "type": "feature",
                "requirement_ids": ["asymmetric_feature_placement"],
            },
            {
                "id": "recessed_slot_feature_id",
                "component_id": "mounting_plate_comp",
                "type": "feature",
                "requirement_ids": ["asymmetric_feature_placement"],
            },
        ],
        "printable_outputs": [
            {"id": "mounting_plate_output", "component_ids": ["mounting_plate_comp"]}
        ],
        "feature_layouts": [
            {
                "id": "mounting_holes_feature_id",
                "feature_id": "mounting_holes_feature_id",
                "layout_mode": "proposed_positions",
                "required_count": 3,
                "requirement_ids": ["asymmetric_feature_placement"],
            },
            {
                "id": "recessed_slot_feature_id",
                "feature_id": "recessed_slot_feature_id",
                "layout_mode": "proposed_positions",
                "required_count": 1,
                "requirement_ids": ["asymmetric_feature_placement"],
            },
        ],
        "validation_targets": [],
    }
    result = build_requirement_trace_manifest(
        design_specification_payload=specification,
        design_plan_payload=plan,
        source_component_ids={"mounting_plate_comp"},
        source_component_symbols={"mounting_plate_comp": "build_mounting_plate"},
        source_feature_components={
            "mounting_holes_feature_id": "mounting_plate_comp",
            "recessed_slot_feature_id": "mounting_plate_comp",
        },
        source_feature_symbols={
            "mounting_holes_feature_id": "apply_mounting_holes",
            "recessed_slot_feature_id": "apply_recessed_slot",
        },
        source_output_ids={"mounting_plate_output"},
        source_output_components={"mounting_plate_output": ["mounting_plate_comp"]},
        source_parameter_ids=set(),
    )

    obligation = result["normalized"]["obligations"][0]
    assert obligation["component_ids"] == ["mounting_plate_comp"]
    assert obligation["plan_feature_id"] is None
    assert obligation["scope"] == "cross_feature_layout"
    assert obligation["plan_feature_ids"] == [
        "mounting_holes_feature_id",
        "recessed_slot_feature_id",
    ]
    assert obligation["output_ids"] == ["mounting_plate_output"]
    assert obligation["status"] == "source_cross_feature_layout_trace"
    assert obligation["validation_target"]["type"] == "layout_constraint"
    assert not any(
        finding["rule_id"] == "design_artifact.requirement_trace_ambiguous"
        and finding["is_blocking"]
        for finding in result["findings"]
    )


def test_multiple_compatible_features_without_explicit_multi_target_remain_ambiguous() -> None:
    specification = {
        "functional_requirements": [
            {
                "id": "asymmetric_feature_placement",
                "type": "orientation",
                "kind": "orientation",
                "operator": "qualitative",
                "target": "mounting plate",
                "value": "asymmetric",
                "source": "user",
                "explicit": True,
                "protected": True,
            }
        ]
    }
    plan = {
        "components": [
            {"id": "mounting_plate_comp", "label": "Mounting Plate", "role": "printable_part"}
        ],
        "features": [
            {
                "id": "mounting_holes_feature_id",
                "component_id": "mounting_plate_comp",
                "type": "feature",
                "requirement_ids": ["asymmetric_feature_placement"],
            },
            {
                "id": "recessed_slot_feature_id",
                "component_id": "mounting_plate_comp",
                "type": "feature",
                "requirement_ids": ["asymmetric_feature_placement"],
            },
        ],
        "printable_outputs": [
            {"id": "mounting_plate_output", "component_ids": ["mounting_plate_comp"]}
        ],
        "validation_targets": [],
    }
    result = build_requirement_trace_manifest(
        design_specification_payload=specification,
        design_plan_payload=plan,
        source_component_ids={"mounting_plate_comp"},
        source_component_symbols={"mounting_plate_comp": "build_mounting_plate"},
        source_feature_components={
            "mounting_holes_feature_id": "mounting_plate_comp",
            "recessed_slot_feature_id": "mounting_plate_comp",
        },
        source_feature_symbols={
            "mounting_holes_feature_id": "apply_mounting_holes",
            "recessed_slot_feature_id": "apply_recessed_slot",
        },
        source_output_ids={"mounting_plate_output"},
        source_output_components={"mounting_plate_output": ["mounting_plate_comp"]},
        source_parameter_ids=set(),
    )

    obligation = result["normalized"]["obligations"][0]
    assert obligation["blocking"] is True
    assert obligation["status"] == "trace_ambiguous"


def test_explicit_component_scope_does_not_fabricate_a_feature_target() -> None:
    specification = {
        "functional_requirements": [
            {
                "id": "component_asymmetry",
                "type": "orientation",
                "scope": "component",
                "component_id": "mounting_plate_comp",
                "target": "mounting plate",
                "value": "asymmetric",
                "source": "user",
                "explicit": True,
            }
        ]
    }
    plan = {
        "components": [{"id": "mounting_plate_comp", "label": "Mounting Plate", "role": "printable_part"}],
        "features": [
            {"id": "feature_a", "component_id": "mounting_plate_comp", "type": "feature", "requirement_ids": ["component_asymmetry"]},
            {"id": "feature_b", "component_id": "mounting_plate_comp", "type": "feature", "requirement_ids": ["component_asymmetry"]},
        ],
        "printable_outputs": [{"id": "mounting_plate_output", "component_ids": ["mounting_plate_comp"]}],
        "validation_targets": [],
    }
    result = build_requirement_trace_manifest(
        design_specification_payload=specification,
        design_plan_payload=plan,
        source_component_ids={"mounting_plate_comp"},
        source_component_symbols={"mounting_plate_comp": "build_mounting_plate"},
        source_feature_components={"feature_a": "mounting_plate_comp", "feature_b": "mounting_plate_comp"},
        source_feature_symbols={"feature_a": "apply_feature_a", "feature_b": "apply_feature_b"},
        source_output_ids={"mounting_plate_output"},
        source_output_components={"mounting_plate_output": ["mounting_plate_comp"]},
        source_parameter_ids=set(),
    )

    obligation = result["normalized"]["obligations"][0]
    assert obligation["plan_feature_id"] is None
    assert obligation["plan_feature_ids"] == []
    assert obligation["status"] == "source_component_output_trace"
    assert obligation["scope"] is None


def test_relationship_requirement_keeps_all_named_participants() -> None:
    specification = {
        "functional_requirements": [
            {
                "id": "base_lid_overlap",
                "type": "assembly_relationship",
                "component_ids": ["base", "lid"],
                "source": "user",
                "explicit": True,
            }
        ]
    }
    plan = {
        "components": [
            {"id": "base", "role": "printable_part"},
            {"id": "lid", "role": "printable_part"},
        ],
        "features": [],
        "printable_outputs": [
            {"id": "base_output", "component_ids": ["base"]},
            {"id": "lid_output", "component_ids": ["lid"]},
        ],
        "relationships": [{"id": "base_lid_overlap", "relation_type": "overlaps", "component_ids": ["base", "lid"]}],
        "validation_targets": [],
    }
    result = build_requirement_trace_manifest(
        design_specification_payload=specification,
        design_plan_payload=plan,
        source_component_ids={"base", "lid"},
        source_component_symbols={"base": "build_base", "lid": "build_lid"},
        source_feature_components={},
        source_feature_symbols={},
        source_output_ids={"base_output", "lid_output"},
        source_output_components={"base_output": ["base"], "lid_output": ["lid"]},
        source_parameter_ids=set(),
    )

    obligation = result["normalized"]["obligations"][0]
    assert obligation["component_ids"] == ["base", "lid"]
    assert obligation["output_ids"] == ["base_output", "lid_output"]
    assert obligation["status"] == "source_component_output_trace"
    assert obligation["blocking"] is False


def test_cross_feature_layout_rejects_empty_participant_set() -> None:
    specification = {
        "functional_requirements": [
            {
                "id": "layout_requirement",
                "type": "orientation",
                "scope": "cross_feature_layout",
                "target": "mounting plate",
                "value": "asymmetric",
                "source": "user",
                "explicit": True,
            }
        ]
    }
    plan = {
        "components": [{"id": "mounting_plate_comp", "label": "Mounting Plate", "role": "printable_part"}],
        "features": [],
        "printable_outputs": [{"id": "mounting_plate_output", "component_ids": ["mounting_plate_comp"]}],
        "feature_layouts": [],
        "validation_targets": [],
    }
    result = build_requirement_trace_manifest(
        design_specification_payload=specification,
        design_plan_payload=plan,
        source_component_ids={"mounting_plate_comp"},
        source_component_symbols={"mounting_plate_comp": "build_mounting_plate"},
        source_feature_components={},
        source_feature_symbols={},
        source_output_ids={"mounting_plate_output"},
        source_output_components={"mounting_plate_output": ["mounting_plate_comp"]},
        source_parameter_ids=set(),
    )

    obligation = result["normalized"]["obligations"][0]
    assert obligation["blocking"] is True
    assert obligation["status"] == "cross_feature_target_missing"


def test_cross_feature_layout_rejects_incompatible_explicit_participants() -> None:
    specification = {
        "functional_requirements": [
            {
                "id": "layout_requirement",
                "type": "orientation",
                "scope": "cross_feature_layout",
                "feature_ids": ["missing_feature"],
                "target": "mounting plate",
                "value": "asymmetric",
                "source": "user",
                "explicit": True,
            }
        ]
    }
    plan = {
        "components": [{"id": "mounting_plate_comp", "label": "Mounting Plate", "role": "printable_part"}],
        "features": [{"id": "other_feature", "component_id": "mounting_plate_comp", "type": "feature"}],
        "printable_outputs": [{"id": "mounting_plate_output", "component_ids": ["mounting_plate_comp"]}],
        "feature_layouts": [],
        "validation_targets": [],
    }
    result = build_requirement_trace_manifest(
        design_specification_payload=specification,
        design_plan_payload=plan,
        source_component_ids={"mounting_plate_comp"},
        source_component_symbols={"mounting_plate_comp": "build_mounting_plate"},
        source_feature_components={"other_feature": "mounting_plate_comp"},
        source_feature_symbols={"other_feature": "apply_other_feature"},
        source_output_ids={"mounting_plate_output"},
        source_output_components={"mounting_plate_output": ["mounting_plate_comp"]},
        source_parameter_ids=set(),
    )

    obligation = result["normalized"]["obligations"][0]
    assert obligation["blocking"] is True
    assert obligation["status"] == "cross_feature_target_incompatible"


def test_component_target_does_not_hide_cross_component_feature_ambiguity() -> None:
    specification = {
        "functional_requirements": [
            {
                "id": "component_scoped_feature",
                "type": "orientation",
                "kind": "orientation",
                "operator": "qualitative",
                "target": "holder body",
                "value": "asymmetric",
                "source": "user",
                "explicit": True,
                "protected": True,
            }
        ]
    }
    plan = {
        "components": [
            {"id": "holder_body", "label": "Holder Body", "role": "printable_part"},
            {"id": "secondary_body", "label": "Secondary Body", "role": "printable_part"},
        ],
        "features": [
            {
                "id": "holder_feature",
                "component_id": "holder_body",
                "type": "feature",
                "requirement_ids": ["component_scoped_feature"],
            },
            {
                "id": "secondary_feature",
                "component_id": "secondary_body",
                "type": "feature",
                "requirement_ids": ["component_scoped_feature"],
            },
        ],
        "printable_outputs": [
            {"id": "holder_output", "component_ids": ["holder_body"]},
            {"id": "secondary_output", "component_ids": ["secondary_body"]},
        ],
        "validation_targets": [],
    }
    result = build_requirement_trace_manifest(
        design_specification_payload=specification,
        design_plan_payload=plan,
        source_component_ids={"holder_body", "secondary_body"},
        source_component_symbols={"holder_body": "build_holder", "secondary_body": "build_secondary"},
        source_feature_components={
            "holder_feature": "holder_body",
            "secondary_feature": "secondary_body",
        },
        source_feature_symbols={
            "holder_feature": "apply_holder_feature",
            "secondary_feature": "apply_secondary_feature",
        },
        source_output_ids={"holder_output", "secondary_output"},
        source_output_components={
            "holder_output": ["holder_body"],
            "secondary_output": ["secondary_body"],
        },
        source_parameter_ids=set(),
    )

    obligation = result["normalized"]["obligations"][0]
    assert obligation["blocking"] is True
    assert obligation["status"] == "trace_ambiguous"


def test_multiple_compatible_capacity_features_remain_ambiguous_and_blocking() -> None:
    result = _trace(_capacity_specification(), _capacity_plan(feature_count=2))
    obligation = result["normalized"]["obligations"][0]

    assert obligation["blocking"] is True
    assert any(
        finding["rule_id"] == "design_artifact.requirement_trace_ambiguous"
        for finding in result["findings"]
    )


def test_incompatible_feature_type_does_not_satisfy_capacity() -> None:
    plan = _capacity_plan()
    plan["features"][0]["semantic_type"] = "cosmetic"
    plan["features"][0]["type"] = "fillet"
    result = _trace(_capacity_specification(), plan)
    obligation = result["normalized"]["obligations"][0]

    assert obligation["blocking"] is True
    assert obligation["status"] in {"geometry_verification_unmapped", "trace_ambiguous"}


def test_capacity_operators_remain_distinct() -> None:
    cases = {
        "can hold exactly 5 storage bins": "exact",
        "can hold up to 5 storage bins": "up_to",
        "must hold at least 5 storage bins": "at_least",
        "can hold between 3 and 5 storage bins": "range",
    }
    for text, operator in cases.items():
        item = build_explicit_requirement_inventory(text)[0]
        assert item["kind"] == "capacity"
        assert item["operator"] == operator
        assert item["object_type"] == "storage_bin"


def test_semantic_operator_survives_design_specification_normalization() -> None:
    item = build_explicit_requirement_inventory("can hold up to 5 storage bins")[0]
    normalized, _ = validate_design_specification_trace(
        {"critical_dimensions": [], "functional_requirements": []},
        [item],
    )

    stored = next(
        entry for entry in normalized["critical_dimensions"]
        if entry["requirement_id"] == "bin_capacity"
    )
    assert stored["kind"] == "capacity"
    assert stored["operator"] == "up_to"
    assert stored["object_type"] == "storage_bin"


def test_explicit_linked_capacity_target_is_authoritative() -> None:
    specification = _capacity_specification()
    specification["explicit_requirements"][0]["feature_id"] = "storage_slots_0"
    specification["explicit_requirements"][0]["validation_target_id"] = "verify_storage_capacity"
    result = _trace(specification, _capacity_plan())
    obligation = result["normalized"]["obligations"][0]

    assert obligation["plan_feature_id"] == "storage_slots_0"
    assert obligation["validation_target_id"] == "verify_storage_capacity"
    assert not any(
        finding["rule_id"] == "design_artifact.requirement_trace_ambiguous"
        for finding in result["findings"]
    )


def test_capacity_obligation_is_created_when_unique_feature_has_no_provider_target() -> None:
    plan = _capacity_plan()
    plan["validation_targets"] = []
    result = _trace(_capacity_specification(), plan)

    obligation = result["normalized"]["obligations"][0]
    assert obligation["status"] == "geometry_verification_target"
    assert obligation["validation_target_id"] == "verify_storage_capacity"
    assert result["normalized"]["validation_targets"] == [{
        "id": "verify_storage_capacity",
        "feature_id": "storage_slots_0",
        "requirement_ids": ["storage_capacity"],
        "type": "capacity",
        "measurement": "supported_capacity",
        "operator": "up_to",
        "expected_value": 5,
        "unit": "item",
        "object_type": "storage_bin",
        "source": "volundr_requirement_obligation",
    }]
    assert any(
        finding["rule_id"] == "requirement.verification_obligation_created"
        for finding in result["findings"]
    )


def test_feature_absence_preserves_absent_semantics() -> None:
    item = build_explicit_requirement_inventory("Create a holder without a handle.")[0]

    assert item["requirement_id"] == "handle"
    assert item["type"] == "feature_absence"
    assert item["kind"] == "feature"
    assert item["operator"] == "absent"
    assert item["value"] is False


def test_revision_capacity_and_dimension_operators_are_preserved() -> None:
    capacity_changes, _ = requirement_delta_for_message("The holder must hold at least 4 trays.")
    assert capacity_changes[0]["requirement_id"] == "tray_capacity"
    assert capacity_changes[0]["kind"] == "capacity"
    assert capacity_changes[0]["operator"] == "at_least"
    assert capacity_changes[0]["object_type"] == "tray"

    height_changes, _ = requirement_delta_for_message("Reduce the maximum height to 80 mm.")
    assert height_changes[0]["requirement_id"] == "height"
    assert height_changes[0]["operator"] == "maximum"
    assert height_changes[0]["type"] == "maximum_dimension"

    opening_changes, _ = requirement_delta_for_message("Make the opening approximately 20 mm.")
    assert opening_changes[0]["requirement_id"] == "opening"
    assert opening_changes[0]["operator"] == "approximately"


def test_persisted_legacy_type_exposes_normalized_capacity_semantics() -> None:
    row = SimpleNamespace(
        id="record-1",
        requirement_id="tray_capacity",
        source="initial_user",
        target_json='"tray_storage"',
        requirement_type="exact_dimension",
        value_json="5",
        unit="tray",
        tolerance_json=None,
        explicit=True,
        status="active",
        originating_message="can hold up to 5 trays",
        originating_revision_id=None,
        supersedes_requirement_id=None,
        superseded_by=None,
        verification_evidence_json=(
            '{"evidence": null, "semantic": {'
            '"kind": "capacity", "operator": "up_to", '
            '"object_type": "3600_size_tackle_tray"}}'
        ),
        created_at=None,
        updated_at=None,
    )

    payload = _entry_payload(row)

    assert payload["type"] == "capacity"
    assert payload["kind"] == "capacity"
    assert payload["operator"] == "up_to"


def test_revision_delta_supersedes_old_operator_without_creating_a_control() -> None:
    ledger = build_requirement_ledger([{
        "requirement_id": "tray_capacity",
        "type": "capacity",
        "kind": "capacity",
        "operator": "up_to",
        "value": 5,
        "unit": "tray",
        "object_type": "tray",
        "source": "initial_user",
        "explicit": True,
    }])
    changes, _ = requirement_delta_for_message("The holder must hold at least 4 trays.")
    revised = apply_requirement_delta(ledger, changes, originating_message="Increase the minimum capacity.")

    active = [item for item in revised["requirements"] if item["status"] == "active"]
    assert len(active) == 1
    assert active[0]["operator"] == "at_least"
    assert active[0]["value"] == 4
    assert active[0]["object_type"] == "tray"
    assert active[0].get("exposed_control") is not True
    assert any(item["status"] == "superseded" for item in revised["requirements"])


def test_direct_brief_retains_capacity_semantics_and_target() -> None:
    item = build_explicit_requirement_inventory("Create a holder that can hold up to 5 storage bins.")[0]
    brief = DirectCadBriefBuilder().build(
        project_id="project",
        active_requirements=[item],
    ).to_payload()

    assert brief["requirements"][0]["operator"] == "up_to"
    target = brief["validation_targets"][0]
    assert target["measurement"] == "supported_capacity"
    assert target["operator"] == "up_to"
    assert target["expected_value"] == 5


def test_semantically_duplicate_functional_requirement_is_normalized_to_ledger_identity() -> None:
    specification = _capacity_specification()
    specification["functional_requirements"] = [{
        "id": "req_storage_capacity",
        "source": "user",
        "protected": True,
        "type": "capacity",
        "kind": "capacity",
        "operator": "up_to",
        "value": 5,
        "unit": "item",
        "object_type": "storage_bin",
        "description": "The holder can hold up to 5 storage bins.",
    }]
    result = _trace(specification, _capacity_plan())

    assert [item["requirement_id"] for item in result["normalized"]["obligations"]] == ["storage_capacity"]
    assert not any(item["is_blocking"] for item in result["findings"])
    aliases = result["normalized"]["requirement_aliases"]
    assert aliases[0]["canonical_requirement_id"] == "storage_capacity"
    assert aliases[0]["aliases"][0]["requirement_id"] == "req_storage_capacity"
