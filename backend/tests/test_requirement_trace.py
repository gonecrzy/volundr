import json

import pytest

from app.services.requirements.trace import (
    AUTHORITY_RANKS,
    RequirementTraceError,
    build_explicit_requirement_inventory,
    default_item,
    explicit_item,
    merge_resolved_requirements,
    requirement_trace_payload,
    validate_design_plan_trace,
    validate_design_specification_trace,
    validate_execution_parameters,
    validate_requirement_extraction_trace,
    validate_source_parameter_trace,
)


ORGANIZER_TEXT = (
    "Create a configurable drawer organizer with editable row count, column count, "
    "cell size, wall thickness, and label tabs."
)
ORGANIZER_DIMENSIONS = ["rows=3", "columns=4", "cell=35x25 mm", "wall_thickness=2 mm"]


def by_id(items):
    return {item["requirement_id"]: item for item in items}


def test_inventory_extracts_failed_live_organizer_dimensions() -> None:
    inventory = by_id(
        build_explicit_requirement_inventory(
            ORGANIZER_TEXT,
            supplemental_requirements=ORGANIZER_DIMENSIONS,
        )
    )

    assert inventory["row_count"]["value"] == 3
    assert inventory["row_count"]["type"] == "explicit_count"
    assert inventory["column_count"]["value"] == 4
    assert inventory["cell_width"]["value"] == 35.0
    assert inventory["cell_width"]["unit"] == "mm"
    assert inventory["cell_depth"]["value"] == 25.0
    assert inventory["wall_thickness"]["value"] == 2.0
    assert inventory["label_tabs"]["value"] is True
    assert all(item["protected"] for item in inventory.values())


def test_inventory_extracts_varied_explicit_value_types() -> None:
    inventory = by_id(
        build_explicit_requirement_inventory(
            "Make a rack with slot_count=12, max_width<=180 mm, thread_axis=z, and no lid."
        )
    )

    assert inventory["slot_count"]["type"] == "explicit_count"
    assert inventory["slot_count"]["value"] == 12
    assert inventory["max_width"]["type"] == "explicit_maximum"
    assert inventory["max_width"]["value"] == 180.0
    assert inventory["thread_axis"]["type"] == "explicit_enum"
    assert inventory["thread_axis"]["value"] == "z"
    assert inventory["lid"]["type"] == "explicit_feature"
    assert inventory["lid"]["value"] is False


def test_authority_merge_prevents_defaults_replacing_explicit_values() -> None:
    explicit = explicit_item("wall_thickness", 2.0, unit="mm")
    product_default = default_item("wall_thickness", 3.0, unit="mm", source="product_default")
    printer_default = default_item("wall_thickness", 4.0, unit="mm", source="printer_profile")

    resolved = by_id(merge_resolved_requirements([product_default, explicit, printer_default]))

    assert AUTHORITY_RANKS[resolved["wall_thickness"]["authority"]] == 1
    assert resolved["wall_thickness"]["value"] == 2.0
    assert resolved["wall_thickness"]["source"] == "user"


def test_redundant_clarification_is_rejected_and_suppressed() -> None:
    inventory = build_explicit_requirement_inventory(
        ORGANIZER_TEXT,
        supplemental_requirements=ORGANIZER_DIMENSIONS,
    )
    payload = {
        "clarification_required": True,
        "clarification_questions": [
            {"id": "q_row_count", "question": "What is the desired row count?"},
            {"id": "q_cell_size", "question": "What cell size should each compartment use?"},
        ],
        "missing_requirements": ["Row count", "Cell size"],
        "generation_ready": False,
        "outcome": "clarification_required",
    }

    normalized, trace = validate_requirement_extraction_trace(payload, inventory)

    assert [finding["rule_id"] for finding in trace["findings"]] == ["clarification_redundant"]
    assert normalized["clarification_required"] is False
    assert normalized["clarification_questions"] == []
    assert normalized["generation_ready"] is True
    assert normalized["outcome"] == "generation_ready"


def test_genuine_missing_critical_clarification_is_preserved() -> None:
    inventory = build_explicit_requirement_inventory("Make a shelf bracket.")
    payload = {
        "clarification_required": True,
        "clarification_questions": [
            {"id": "q_load", "question": "What load must the shelf carry?"}
        ],
        "missing_requirements": ["Load"],
        "generation_ready": False,
        "outcome": "clarification_required",
    }

    normalized, trace = validate_requirement_extraction_trace(payload, inventory)

    assert normalized["clarification_required"] is True
    assert trace["status"] == "passed"


def test_design_specification_validation_restores_missing_explicit_values() -> None:
    inventory = build_explicit_requirement_inventory(
        ORGANIZER_TEXT,
        supplemental_requirements=ORGANIZER_DIMENSIONS,
    )
    payload = {
        "critical_dimensions": [
            {
                "id": "wall_thickness_mm",
                "label": "Wall thickness",
                "value": 3.0,
                "unit": "mm",
                "source": "printer_profile",
                "importance": "critical",
                "protected": True,
            }
        ],
        "parameters": [],
        "functional_requirements": [],
        "clarification_required": False,
        "clarification_questions": [],
        "generation_ready": True,
        "outcome": "generation_ready",
    }

    normalized, trace = validate_design_specification_trace(payload, inventory)
    dimensions = by_id(normalized["explicit_requirements"])

    assert trace["status"] == "repaired"
    assert dimensions["wall_thickness"]["value"] == 2.0
    assert dimensions["wall_thickness"]["source"] == "user"
    assert by_id(normalized["critical_dimensions"])["cell_width"]["value"] == 35.0


def test_design_plan_missing_protected_requirement_blocks() -> None:
    inventory = build_explicit_requirement_inventory(
        ORGANIZER_TEXT,
        supplemental_requirements=ORGANIZER_DIMENSIONS,
    )
    plan = {
        "outcome": "plan_ready",
        "parameters": [
            {"id": "row_count", "value": 3, "unit": "count", "source_requirement_id": "row_count"},
            {"id": "column_count", "value": 3, "unit": "count", "source_requirement_id": None},
            {"id": "cell_size_mm", "value": 50, "unit": "mm", "source_requirement_id": None},
        ],
        "derived_parameters": [],
    }

    with pytest.raises(RequirementTraceError) as exc:
        validate_design_plan_trace(plan, inventory)

    assert "design_plan.explicit_value_mismatch" in str(exc.value)
    assert "design_plan.explicit_requirement_missing" in str(exc.value)


def test_source_parameter_mismatch_blocks_execution() -> None:
    inventory = build_explicit_requirement_inventory(
        ORGANIZER_TEXT,
        supplemental_requirements=ORGANIZER_DIMENSIONS,
    )
    metadata = {
        "parameter_ids": ["row_count", "column_count", "cell_width", "cell_depth", "wall_thickness"],
        "parameter_defaults": {
            "row_count": 2,
            "column_count": 4,
            "cell_width": 35.0,
            "cell_depth": 25.0,
            "wall_thickness": 2.0,
        },
    }

    with pytest.raises(RequirementTraceError) as exc:
        validate_source_parameter_trace(metadata, inventory)

    assert "source_parameter.explicit_value_mismatch" in str(exc.value)


def test_execution_manifest_mismatch_blocks_worker_submission() -> None:
    inventory = build_explicit_requirement_inventory(
        ORGANIZER_TEXT,
        supplemental_requirements=ORGANIZER_DIMENSIONS,
    )

    with pytest.raises(RequirementTraceError) as exc:
        validate_execution_parameters({"row_count": 3, "column_count": 3}, inventory)

    assert "execution_parameter.explicit_value_mismatch" in str(exc.value)
    assert "execution_parameter.protected_parameter_missing" in str(exc.value)


def test_requirement_trace_artifact_is_reproducible() -> None:
    inventory = build_explicit_requirement_inventory(
        ORGANIZER_TEXT,
        supplemental_requirements=ORGANIZER_DIMENSIONS,
    )
    payload = requirement_trace_payload(
        inventory=inventory,
        resolved_requirements=merge_resolved_requirements(inventory),
        stages=[{"stage": "requirements", "status": "passed", "findings": []}],
    )

    first = json.dumps(payload, sort_keys=True)
    second = json.dumps(payload, sort_keys=True)

    assert payload["schema_version"] == "requirement-trace-v1"
    assert first == second
