import json

from app.services.gemini_integration.adapters import (
    GeminiGeometryContractAdapter,
    GeminiPlanContractAdapter,
    GeminiRequirementsContractAdapter,
)


def _context(**overrides):
    value = {
        "project_id": "project-001",
        "revision_id": "revision-001",
        "operation_id": "operation-001",
        "provenance": {"study_id": "gemini-provider-contract-integration-01"},
    }
    value.update(overrides)
    return value


def test_requirements_adapter_preserves_missing_fit_values_and_operators() -> None:
    raw = {
        "requirements": [
            {"subject": "cable diameter", "value": None, "unit": "mm", "operator": "exact"},
            {"subject": "mounting pattern", "value": None, "operator": "present"},
            {"subject": "guide length", "value": 80, "unit": "mm", "operator": "maximum"},
        ],
        "clarification_required": True,
        "generation_ready": False,
        "clarification_questions": [
            {"question": "What cable diameter should the guide fit?"},
            {"question": "What mounting pattern should be used?"},
        ],
    }
    result = GeminiRequirementsContractAdapter().adapt(
        json.dumps(raw),
        _context(fit_critical_missing=["cable diameter", "mounting pattern"]),
    )

    assert result.accepted is True
    assert result.normalized["requirements"][0]["value"] is None
    assert [item["operator"] for item in result.normalized["requirements"]] == ["exact", "present", "maximum"]
    assert result.volundr_mapping["project_id"] == "project-001"
    assert result.provenance["study_id"] == "gemini-provider-contract-integration-01"


def test_requirements_adapter_rejects_invented_fit_value_and_conflicting_readiness() -> None:
    raw = {
        "requirements": [{"subject": "cable diameter", "value": 8, "unit": "mm", "source": "user"}],
        "clarification_required": True,
        "generation_ready": True,
    }
    result = GeminiRequirementsContractAdapter().adapt(
        raw,
        _context(fit_critical_missing=["cable diameter"]),
    )

    assert result.accepted is False
    assert result.failure_class in {"invented_critical_meaning", "conflicting_readiness"}
    assert result.normalization_actions


def test_requirements_adapter_maps_current_design_specification_records() -> None:
    raw = {
        "critical_dimensions": [{"id": "width", "value": 100, "unit": "mm", "operator": "exact"}],
        "functional_requirements": [{"id": "hole", "description": "through hole", "operator": "present"}],
        "clarification_required": False,
        "generation_ready": True,
    }

    result = GeminiRequirementsContractAdapter().adapt(raw, _context())

    assert result.accepted is True
    assert [item["id"] for item in result.normalized["requirements"]] == ["width", "hole"]
    assert any(action["action_class"] == "semantic_requirement_projection" for action in result.normalization_actions)


def test_plan_adapter_preserves_output_obligations_and_traceability() -> None:
    raw = {
        "components": [{"id": "base", "name": "base"}],
        "features": [{"id": "vent", "component_id": "base", "requirement_ids": ["req-vent"], "description": "ventilation"}],
        "printable_outputs": [{"id": "base-output", "component_id": "base", "description": "base"}],
        "validation_targets": [{"id": "target-vent", "component_id": "base", "requirement_ids": ["req-vent"]}],
        "requirements": [{"id": "req-vent", "description": "ventilation"}],
    }
    result = GeminiPlanContractAdapter().adapt(
        raw,
        _context(expected_output_count=1, required_requirement_ids=["req-vent"]),
    )

    assert result.accepted is True
    assert result.normalized["printable_outputs"][0]["id"] == "base-output"
    assert result.normalized["features"][0]["requirement_ids"] == ["req-vent"]


def test_plan_adapter_accepts_authoritative_output_identity_and_single_output_traceability() -> None:
    result = GeminiPlanContractAdapter().adapt(
        {
            "components": [{"id": "bracket", "name": "bracket"}],
            "printable_outputs": [{"id": "mounting_bracket", "component_id": "bracket"}],
            "design_level": "single_part",
            "assembly_strategy": {"type": "single_part"},
        },
        _context(
            expected_output_count=1,
            required_requirement_ids=["output_id", "single_printable_bracket"],
        ),
    )

    assert result.accepted is True


def test_plan_adapter_rejects_output_identity_aliases_against_frozen_obligations() -> None:
    result = GeminiPlanContractAdapter().adapt(
        {
            "components": [{"id": "base", "name": "base"}],
            "printable_outputs": [{"id": "base_output", "component_id": "base"}],
        },
        _context(
            expected_output_count=1,
            expected_output_ids=["base"],
        ),
    )

    assert result.accepted is False
    assert result.failure_class == "output_identity_failure"
    assert result.validation_result["expected_output_ids"] == ["base"]
    assert result.validation_result["observed_output_ids"] == ["base_output"]


def test_plan_adapter_rejects_empty_records_and_invalid_references() -> None:
    empty = GeminiPlanContractAdapter().adapt(
        {"components": [{}], "printable_outputs": []},
        _context(expected_output_count=1),
    )
    invalid = GeminiPlanContractAdapter().adapt(
        {
            "components": [{"id": "base", "name": "base"}],
            "features": [{"id": "vent", "component_id": "missing", "description": "vent"}],
            "printable_outputs": [{"id": "out", "component_id": "base"}],
        },
        _context(expected_output_count=1),
    )

    assert empty.accepted is False
    assert empty.failure_class == "structurally_empty"
    assert invalid.accepted is False
    assert invalid.failure_class == "invalid_reference"


def test_geometry_adapter_preserves_numeric_literals_and_statement_order() -> None:
    raw = {
        "slots": [
            {
                "slot_id": 1,
                "statements": [
                    "cutter = cq.Workplane('XY').circle(4.25).extrude(10)",
                    "body = body.cut(cutter)",
                ],
                "result_symbol": "body",
            }
        ]
    }
    result = GeminiGeometryContractAdapter().adapt(
        raw,
        _context(expected_slot_ids=[1], allowed_names=["body", "cutter", "cq"]),
    )

    assert result.accepted is True
    assert result.normalized["slots"][0]["statements"] == raw["slots"][0]["statements"]
    assert result.semantic_hash_before == result.semantic_hash_after


def test_geometry_adapter_rejects_undefined_symbols_and_invalid_result_assignment() -> None:
    undefined = GeminiGeometryContractAdapter().adapt(
        {"slots": [{"slot_id": 1, "statements": ["body = body.union(missing_shape)"], "result_symbol": "body"}]},
        _context(expected_slot_ids=[1], allowed_names=["body", "cq"]),
    )
    wrong_result = GeminiGeometryContractAdapter().adapt(
        {"slots": [{"slot_id": 1, "statements": ["shape = body.cut(cutter)"], "result_symbol": "shape"}]},
        _context(expected_slot_ids=[1], allowed_names=["body", "cutter", "cq"]),
    )

    assert undefined.accepted is False
    assert undefined.failure_class == "undefined_symbols"
    assert wrong_result.accepted is False
    assert wrong_result.failure_class == "invalid_result_assignment"


def test_geometry_adapter_does_not_invent_missing_slots_or_geometry() -> None:
    result = GeminiGeometryContractAdapter().adapt(
        {"slots": [{"slot_id": 1, "statements": ["body = body.cut(cutter)"], "result_symbol": "body"}]},
        _context(expected_slot_ids=[1, 2], allowed_names=["body", "cutter"]),
    )

    assert result.accepted is False
    assert result.failure_class == "missing_slots"
    assert result.normalized["slots"] == [{"slot_id": 1, "statements": ["body = body.cut(cutter)"], "result_symbol": "body"}]
