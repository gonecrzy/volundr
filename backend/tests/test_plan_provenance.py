from __future__ import annotations

from copy import deepcopy

from app.services.projects.plan_provenance import (
    AUTHORITATIVE_PROVENANCE_SOURCES,
    FASTENER_LOOKUP_TABLES,
    normalize_authoritative_provenance,
    normalize_plan_provenance,
    validate_plan_provenance,
)


def test_authoritative_provenance_sources_are_canonicalized_without_changing_value() -> None:
    assert "initial_user" in AUTHORITATIVE_PROVENANCE_SOURCES
    normalized = normalize_authoritative_provenance(
        {
            "id": "bottle_diameter",
            "value": 81,
            "unit": "mm",
            "provenance": {"source": "user"},
        },
        {"bottle_diameter": {"value": 81, "unit": "mm", "source": "initial_user"}},
    )
    assert normalized.value["value"] == 81
    assert normalized.value["provenance"]["source"] == "initial_user"
    assert normalized.findings == ("provenance.source_canonicalized",)


def test_authoritative_provenance_conflict_is_not_rewritten() -> None:
    normalized = normalize_authoritative_provenance(
        {
            "id": "bottle_diameter",
            "value": 81,
            "unit": "mm",
            "provenance": {"source": "volundr_proposal"},
        },
        {"bottle_diameter": {"value": 81, "unit": "mm", "source": "initial_user"}},
    )
    assert normalized.value["provenance"]["source"] == "volundr_proposal"
    assert normalized.findings == ("provenance.proposal_misclassified",)


def test_authoritative_provenance_ambiguous_source_remains_blocking() -> None:
    normalized = normalize_authoritative_provenance(
        {"id": "diameter", "value": 81, "unit": "mm", "provenance": {}},
        {
            "initial": {"value": 81, "unit": "mm", "source": "initial_user"},
            "clarification": {"value": 81, "unit": "mm", "source": "clarification_user"},
        },
    )
    assert normalized.value["provenance"] == {}
    assert normalized.findings == ("provenance.source_conflict",)
from app.services.requirements.trace import build_explicit_requirement_inventory


def _specification() -> dict:
    return {
        "critical_dimensions": [
            {"id": "bottle_diameter", "value": 81, "unit": "mm", "source": "user"},
            {"id": "mounting_screw_designation", "value": "#8", "unit": None, "source": "user"},
        ],
        "parameters": [],
    }


def _base_plan() -> dict:
    return {
        "parameters": [
            {
                "id": "bottle_diameter",
                "label": "Bottle diameter",
                "value": 81,
                "unit": "mm",
                "source_requirement_id": "bottle_diameter",
                "provenance": {"relationship": "direct", "source_requirement_ids": ["bottle_diameter"]},
            },
            {
                "id": "bottle_clearance",
                "label": "Bottle clearance",
                "value": 0.8,
                "unit": "mm",
                "source": "ai_proposal",
                "provenance": {"relationship": "ai_proposal", "explanation": "Proposed removable fit clearance"},
            },
            {
                "id": "bottle_inner_diameter",
                "label": "Bottle opening",
                "value": 81.8,
                "unit": "mm",
                "provenance": {
                    "relationship": "derived_formula",
                    "source_requirement_ids": ["bottle_diameter"],
                    "source_parameter_ids": ["bottle_clearance"],
                    "expression": "bottle_diameter + bottle_clearance",
                },
            },
            {
                "id": "mounting_screw_designation",
                "label": "Mounting screw",
                "value": "#8",
                "provenance": {
                    "relationship": "direct",
                    "source_requirement_ids": ["mounting_screw_designation"],
                },
            },
            {
                "id": "mounting_hole_diameter",
                "label": "Mounting hole diameter",
                "value": 4.2,
                "unit": "mm",
                "provenance": {
                    "relationship": "standard_lookup",
                    "source_requirement_ids": ["mounting_screw_designation"],
                    "lookup": {
                        "table_id": "fastener-clearance-v1",
                        "key": "#8",
                        "variant": "clearance",
                    },
                },
            },
        ],
        "derived_parameters": [],
    }


def test_direct_value_matches_exactly() -> None:
    findings = validate_plan_provenance(_base_plan(), _specification())

    assert findings == []


def test_formula_derivation_is_recomputed_from_dependencies() -> None:
    plan = _base_plan()
    plan["parameters"][2]["value"] = 82

    findings = validate_plan_provenance(plan, _specification())

    assert any(f["rule_id"] == "design_plan.provenance_formula_mismatch" for f in findings)


def test_unexplained_mismatch_linked_as_direct_is_rejected() -> None:
    plan = _base_plan()
    parameter = plan["parameters"][2]
    parameter["provenance"] = {
        "relationship": "direct",
        "source_requirement_ids": ["bottle_diameter"],
    }
    parameter["source_requirement_id"] = "bottle_diameter"

    findings = validate_plan_provenance(plan, _specification())

    assert any(f["rule_id"] == "design_plan.direct_value_mismatch" for f in findings)


def test_fastener_designation_is_not_numeric_dimension() -> None:
    inventory = build_explicit_requirement_inventory(
        "Create a wall-mounted holder with two #8 mounting screws."
    )

    designation = next(item for item in inventory if item["requirement_id"] == "mounting_screw_designation")
    assert designation["value"] == "#8"
    assert isinstance(designation["value"], str)


def test_standard_lookup_recomputes_configured_diameter() -> None:
    assert FASTENER_LOOKUP_TABLES["fastener-clearance-v1"]["#8"]["clearance"]["diameter_mm"] == 4.2
    findings = validate_plan_provenance(_base_plan(), _specification())

    assert not any(f["rule_id"] == "design_plan.standard_lookup_mismatch" for f in findings)


def test_standard_lookup_can_use_a_resolved_plan_parameter_as_its_key() -> None:
    plan = _base_plan()
    lookup = plan["parameters"][4]["provenance"]
    lookup["source_requirement_ids"] = []
    lookup["source_parameter_ids"] = ["mounting_screw_designation"]

    findings = validate_plan_provenance(plan, _specification())

    assert not any(f["rule_id"] == "design_plan.provenance_source_missing" for f in findings)


def test_missing_lookup_variant_and_unknown_key_are_blocking() -> None:
    plan = _base_plan()
    lookup = plan["parameters"][4]["provenance"]["lookup"]
    lookup["variant"] = "countersink"
    lookup["key"] = "#99"

    findings = validate_plan_provenance(plan, _specification())

    assert {f["rule_id"] for f in findings} >= {
        "design_plan.standard_lookup_unknown_key",
        "design_plan.standard_lookup_variant_missing",
    }


def test_semantic_identity_collision_is_rejected() -> None:
    plan = _base_plan()
    plan["parameters"][3] = {
        "id": "mounting_screw_designation",
        "label": "Mounting screw",
        "value": 4.2,
        "unit": "mm",
        "source_requirement_id": "mounting_screw_designation",
        "provenance": {
            "relationship": "direct",
            "source_requirement_ids": ["mounting_screw_designation"],
        },
    }

    findings = validate_plan_provenance(plan, _specification())

    assert any(f["rule_id"] == "design_plan.semantic_identity_collision" for f in findings)


def test_formula_missing_dependency_and_unsafe_expression_are_rejected() -> None:
    plan = _base_plan()
    derived = plan["parameters"][2]
    derived["provenance"]["source_parameter_ids"] = ["missing_clearance"]
    derived["provenance"]["expression"] = "__import__('os').system('id')"

    findings = validate_plan_provenance(plan, _specification())

    assert {f["rule_id"] for f in findings} >= {
        "design_plan.provenance_dependency_missing",
        "design_plan.provenance_expression_unsafe",
    }


def test_normalization_preserves_user_value_and_records_validator_version() -> None:
    normalized = normalize_plan_provenance(deepcopy(_base_plan()), _specification())

    assert normalized["parameters"][0]["value"] == 81
    assert normalized["parameters"][2]["provenance"]["validator_version"]


def test_normalization_links_same_id_direct_parameter_to_explicit_requirement() -> None:
    plan = _base_plan()
    plan["parameters"][0]["provenance"].pop("source_requirement_ids")
    plan["parameters"][0].pop("source_requirement_id")

    normalized = normalize_plan_provenance(deepcopy(plan), _specification())

    assert normalized["parameters"][0]["provenance"]["source_requirement_ids"] == ["bottle_diameter"]


def test_normalization_recovers_matching_same_id_value_from_provider_proposal() -> None:
    plan = _base_plan()
    parameter = plan["parameters"][0]
    parameter.pop("source_requirement_id")
    parameter.pop("provenance")
    parameter["source"] = "ai_proposal"

    normalized = normalize_plan_provenance(deepcopy(plan), _specification())

    assert normalized["parameters"][0]["source_requirement_id"] == "bottle_diameter"
    assert normalized["parameters"][0]["provenance"]["relationship"] == "direct"
    assert any(
        finding["rule_id"] == "plan.provenance_identity_recovered"
        for finding in normalized["normalization_findings"]
    )


def test_normalization_resolves_lookup_value_for_scaffold_parameters() -> None:
    plan = _base_plan()
    lookup_parameter = plan["parameters"][4]
    lookup_parameter.pop("value")
    lookup_parameter["provenance"]["lookup"]["result_field"] = "clearance.diameter_mm"

    normalized = normalize_plan_provenance(deepcopy(plan), _specification())

    assert normalized["parameters"][4]["value"] == 4.2
    assert normalized["parameters"][4]["source"] == "standard_lookup"


def test_standard_lookup_dependency_cannot_be_declared_as_unrelated_calculation() -> None:
    plan = _base_plan()
    plan["parameters"] = plan["parameters"][:3]
    plan["derived_parameters"] = [
        {
            "id": "mounting_hole_diameter",
            "label": "Mounting hole diameter",
            "value": 4.2,
            "unit": "mm",
            "expression": "4.2",
            "depends_on": ["mounting_screw_designation"],
            "provenance": {"relationship": "calculated"},
        }
    ]
    plan["dependency_edges"] = [
        {
            "from": "mounting_screw_designation",
            "to": "mounting_hole_diameter",
            "relationship": "standard_lookup",
        }
    ]

    findings = validate_plan_provenance(plan, _specification())

    assert any(f["rule_id"] == "design_plan.standard_lookup_provenance_missing" for f in findings)


def test_derived_parameter_expression_is_accepted_as_formula_provenance() -> None:
    plan = _base_plan()
    plan["parameters"] = plan["parameters"][:2]
    plan["derived_parameters"] = [
        {
            "id": "bottle_inner_diameter",
            "label": "Bottle opening",
            "value": 81.8,
            "unit": "mm",
            "expression": "bottle_diameter + bottle_clearance",
            "depends_on": ["bottle_diameter", "bottle_clearance"],
            "provenance": {
                "relationship": "derived_formula",
                "source_requirement_ids": ["bottle_diameter"],
                "source_parameter_ids": ["bottle_clearance"],
            },
        }
    ]

    findings = validate_plan_provenance(plan, _specification())

    assert not any(f["rule_id"] == "design_plan.provenance_expression_missing" for f in findings)
    assert not any(f["rule_id"] == "design_plan.provenance_formula_mismatch" for f in findings)


def test_standard_lookup_can_validate_an_explicit_result_field() -> None:
    plan = _base_plan()
    lookup = plan["parameters"][4]["provenance"]["lookup"]
    lookup["variant"] = "clearance"
    lookup["result_field"] = "head_diameter_mm"
    plan["parameters"][4]["value"] = 8.5

    findings = validate_plan_provenance(plan, _specification())

    assert not any(f["rule_id"] == "design_plan.standard_lookup_mismatch" for f in findings)


def test_standard_lookup_can_validate_a_variant_qualified_result_field() -> None:
    plan = _base_plan()
    lookup = plan["parameters"][4]["provenance"]["lookup"]
    lookup["result_field"] = "clearance.diameter_mm"

    findings = validate_plan_provenance(plan, _specification())

    assert not any(f["rule_id"] == "design_plan.standard_lookup_result_missing" for f in findings)
    assert not any(f["rule_id"] == "design_plan.standard_lookup_mismatch" for f in findings)


def test_standard_lookup_supports_configured_standard_variant() -> None:
    plan = _base_plan()
    lookup = plan["parameters"][4]["provenance"]["lookup"]
    lookup["variant"] = "standard"
    lookup["result_field"] = "clearance.diameter_mm"

    findings = validate_plan_provenance(plan, _specification())

    assert findings == []
