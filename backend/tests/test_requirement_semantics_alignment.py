from app.services.projects.requirement_trace_contract import build_requirement_trace_manifest
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
