from __future__ import annotations

import pytest

from app.services.ai.gemini_cli import GeminiCliProvider
from app.services.ai.provider import DesignPlanRequest, ModelGenerationRequest
from app.services.cad.geometry_bodies import build_geometry_function_inventory
from app.services.cad.patterns import normalize_pattern_specs, validate_pattern_specs
from app.services.provider_interoperability import (
    ProviderContractError,
    build_focused_plan_repair_context,
    build_provider_contract_manifest,
    compare_plan_repair,
    validate_plan_repair_preservation,
)


PLAN = {
    "schema_version": "compact-cad-plan-v1",
    "components": [
        {
            "id": "primary_part",
            "role": "printable_part",
            "required": True,
        }
    ],
    "features": [
        {
            "id": "mounting_holes",
            "component_id": "primary_part",
            "type": "hole_group",
            "role": "subtractive",
            "layout_mode": "fixed_positions",
            "required": True,
        },
        {
            "id": "rear_rib",
            "component_id": "primary_part",
            "type": "rib",
            "role": "integral_additive",
        },
    ],
    "feature_layouts": [
        {
            "id": "mounting_holes_layout",
            "feature_id": "mounting_holes",
            "layout_mode": "fixed_positions",
            "required_count": 2,
            "positions": [{"x": 0, "z": -20}, {"x": 0, "z": 20}],
        }
    ],
    "parameters": [{"id": "hole_diameter", "value": 5, "unit": "mm"}],
    "exposed_controls": [],
    "relationships": [{"type": "feature_owned_by", "feature_id": "rear_rib", "component_id": "primary_part"}],
    "printable_outputs": [
        {
            "id": "primary_output",
            "component_ids": ["primary_part"],
            "required": True,
        }
    ],
}


def test_contract_manifest_contains_identity_layout_and_local_permissions() -> None:
    manifest = build_provider_contract_manifest(
        PLAN,
        planning_depth="compact_plan",
        geometry_inventory=build_geometry_function_inventory(PLAN),
    )

    assert manifest["schema_version"] == "provider-contract-manifest-v1"
    assert manifest["planning_depth"] == "compact_plan"
    assert manifest["components"] == [{"component_id": "primary_part", "printable": True, "role": "printable_part"}]
    assert manifest["features"][0]["owner_component_id"] == "primary_part"
    assert manifest["features"][0]["layout_mode"] == "fixed_positions"
    assert manifest["layouts"][0]["required_count"] == 2
    assert manifest["outputs"][0]["output_id"] == "primary_output"
    assert manifest["provider_may_create_component_ids"] is False
    assert manifest["provider_may_create_feature_ids"] is False
    assert manifest["provider_may_create_local_names"] is True
    assert manifest["function_inventory"][0]["function_id"] == "_ai_component_primary_part"
    assert manifest["manifest_hash"]


def test_focused_plan_repair_context_preserves_valid_ids_and_allows_integral_features() -> None:
    context = build_focused_plan_repair_context(
        PLAN,
        findings=[{"rule_id": "plan.feature_owner_missing", "feature_id": "rear_rib"}],
    )

    assert context["valid_component_ids"] == ["primary_part"]
    assert context["valid_feature_ids"] == ["mounting_holes", "rear_rib"]
    assert context["valid_output_ids"] == ["primary_output"]
    assert context["affected_feature_ids"] == ["rear_rib"]
    assert "integral" in context["allowed_schema_alternatives"]["feature_ownership"]
    assert context["prohibited_changes"]["create_printable_component"] is True


def test_focused_plan_repair_context_localizes_malformed_layouts() -> None:
    rejected = {
        **PLAN,
        "feature_layouts": [
            {"id": "bad_layout", "feature_id": "", "layout_mode": "fixed_positions", "required_count": 2}
        ],
    }
    context = build_focused_plan_repair_context(rejected, findings=[])

    assert context["affected_layout_ids"] == ["bad_layout"]
    assert context["affected_feature_ids"] == []


def test_focused_plan_repair_context_localizes_malformed_patterns_without_new_ids() -> None:
    rejected = {
        **PLAN,
        "feature_layouts": [],
        "patterns": [
            {
                "pattern_id": "mounting_hole_pattern",
                "owning_feature_id": "mounting_holes",
                "pattern_type": "linear",
                "required_count": 3,
            }
        ],
    }

    context = build_focused_plan_repair_context(rejected, findings=[])

    assert context["affected_layout_ids"] == ["mounting_hole_pattern"]
    assert context["affected_feature_ids"] == ["mounting_holes"]
    assert context["valid_component_ids"] == ["primary_part"]
    assert context["prohibited_changes"]["create_feature_id"] is True


def test_fixed_positions_pattern_alias_normalizes_to_one_off_explicit_layout() -> None:
    plan = {
        "components": [{"id": "part"}],
        "features": [{"id": "holes", "component_id": "part"}],
        "exposed_controls": [],
        "patterns": [{
            "id": "holes_pattern",
            "feature_id": "holes",
            "pattern_type": "fixed_positions",
            "fixed_positions": [[1, 2], [3, 4]],
        }],
    }

    normalized = normalize_pattern_specs(plan)
    validate_pattern_specs(normalized)

    assert normalized["patterns"][0]["pattern_type"] == "explicit"
    assert normalized["patterns"][0]["positions"] == [[1, 2], [3, 4]]


def test_unit_vector_pattern_axis_normalizes_to_canonical_axis() -> None:
    plan = {
        "components": [{"id": "part"}],
        "features": [{"id": "holes", "component_id": "part"}],
        "exposed_controls": [],
        "patterns": [{
            "pattern_id": "holes_pattern",
            "feature_id": "holes",
            "pattern_type": "uniform_linear",
            "count": 2,
            "spacing": 40,
            "axis": [0.0, 1.0, 0.0],
        }],
    }

    normalized = normalize_pattern_specs(plan)
    validate_pattern_specs(normalized)

    assert normalized["patterns"][0]["pattern_type"] == "linear"
    assert normalized["patterns"][0]["axis"] == "Y"


def test_direction_vector_is_accepted_as_pattern_axis_alias() -> None:
    plan = {
        "components": [{"id": "part"}],
        "features": [{"id": "holes", "component_id": "part"}],
        "exposed_controls": [],
        "patterns": [{
            "pattern_id": "holes_pattern",
            "feature_id": "holes",
            "pattern_type": "uniform_linear",
            "count": 2,
            "spacing": 40,
            "direction": [0, 1, 0],
        }],
    }

    normalized = normalize_pattern_specs(plan)
    validate_pattern_specs(normalized)

    assert normalized["patterns"][0]["axis"] == "Y"


def test_plan_repair_comparison_reports_preservation_and_rejects_identity_drift() -> None:
    repaired = {**PLAN, "features": [*PLAN["features"][:-1], {**PLAN["features"][-1], "role": "subtractive"}]}
    comparison = compare_plan_repair(PLAN, repaired, affected_feature_ids={"rear_rib"})

    assert comparison["identities_added"] == []
    assert comparison["identities_removed"] == []
    assert "features.rear_rib.role" in comparison["fields_changed"]
    validate_plan_repair_preservation(PLAN, repaired, affected_feature_ids={"rear_rib"})

    with pytest.raises(ProviderContractError, match="identities"):
        validate_plan_repair_preservation(
            PLAN,
            {**PLAN, "components": [{**PLAN["components"][0], "id": "new_part"}]},
            affected_feature_ids={"rear_rib"},
        )


def test_identical_plan_repair_is_rejected() -> None:
    with pytest.raises(ProviderContractError, match="identical"):
        validate_plan_repair_preservation(PLAN, PLAN, affected_feature_ids={"rear_rib"})


def test_plan_repair_cannot_change_an_unaffected_repeated_layout() -> None:
    original = {
        **PLAN,
        "feature_layouts": [
            *PLAN["feature_layouts"],
            {"id": "rear_rib_layout", "feature_id": "rear_rib", "layout_mode": "fixed_positions", "positions": [{"x": 1}]},
        ],
    }
    repaired = {
        **original,
        "feature_layouts": [
            original["feature_layouts"][0],
            {**original["feature_layouts"][1], "positions": [{"x": 2}]},
        ],
    }

    with pytest.raises(ProviderContractError, match="unaffected"):
        validate_plan_repair_preservation(original, repaired, affected_feature_ids={"mounting_holes"})


def test_plan_repair_allows_equivalent_layout_alias_normalization() -> None:
    original = {
        **PLAN,
        "feature_layouts": [{
            "id": "mounting_holes_layout",
            "feature_id": "mounting_holes",
            "layout_type": "vertical_linear",
            "fixed_positions": [[0, 0, -20], [0, 0, 20]],
        }],
    }
    repaired = {
        **original,
        "feature_layouts": [{
            "id": "mounting_holes_layout",
            "feature_id": "mounting_holes",
            "layout_mode": "fixed_positions",
            "positions": [[0, 0, -20], [0, 0, 20]],
        }],
    }

    comparison = validate_plan_repair_preservation(original, repaired)

    assert comparison["fields_changed"] == []


def test_geometry_prompt_contains_reproducible_contract_manifest() -> None:
    manifest = build_provider_contract_manifest(PLAN, planning_depth="compact_plan")
    request = ModelGenerationRequest(
        project_name="test",
        original_intent="test",
        user_instruction="test",
        design_plan=PLAN,
        generation_contract_version="cadquery-scaffold-v1",
        provider_contract_manifest=manifest,
    )

    prompt = GeminiCliProvider(model="test-model").build_scaffold_geometry_prompt(request)

    assert "provider-contract-manifest-v1" in prompt
    assert '"provider_may_create_component_ids": false' in prompt
    assert '"provider_may_create_local_names": true' in prompt


def test_plan_repair_prompt_contains_focused_repair_boundary() -> None:
    context = build_focused_plan_repair_context(
        PLAN,
        findings=[{"rule_id": "plan.feature_owner_missing", "feature_id": "rear_rib"}],
    )
    request = DesignPlanRequest(
        project_name="test",
        original_intent="test",
        user_instruction="test",
        design_specification={},
        schema_repair_of_raw_output="{}",
        schema_validation_error="owner missing",
        planning_depth="compact_plan",
        plan_repair_context=context,
    )

    prompt = GeminiCliProvider(model="test-model").build_design_plan_prompt(request)

    assert "provider-plan-repair-context-v1" in prompt
    assert "rear_rib" in prompt
    assert "Do not create a new printable component" in prompt
