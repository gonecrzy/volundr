from __future__ import annotations

import json

import pytest

from app.services.cad.patterns import normalize_pattern_specs, validate_pattern_specs
from volundr_cad.patterns import resolve_pattern_points
from app.services.projects.plan_constraints import (
    normalize_compact_component_feature_semantics,
    normalize_plan_constraints,
)
from app.services.projects.requirement_ledger import requirement_delta_for_message
from app.services.projects.service import ProjectService


def _positions(count: int) -> list[dict[str, float]]:
    return [{"x": float(index * 10), "y": 0.0, "z": 0.0} for index in range(count)]


def test_compact_integral_ribs_are_features_of_the_single_printable_part() -> None:
    plan = normalize_compact_component_feature_semantics(
        {
            "components": [
                {"id": "bracket", "label": "Bracket", "role": "printable_part"},
                {"id": "comp_rib_left", "label": "Left reinforcement rib", "role": "integral_feature"},
                {"id": "comp_rib_right", "label": "Right reinforcement rib", "role": "integral_feature"},
            ],
            "features": [],
            "printable_outputs": [],
            "relationships": [],
        },
        compact=True,
    )

    assert [item["id"] for item in plan["components"]] == ["bracket"]
    assert {item["id"] for item in plan["features"]} == {"comp_rib_left", "comp_rib_right"}
    assert all(item["component_id"] == "bracket" for item in plan["features"])
    assert any(item["rule_id"] == "plan.component_reclassified_as_feature" for item in plan["normalization_findings"])


def test_compact_feature_owner_defaults_only_for_an_unambiguous_single_part() -> None:
    plan = normalize_compact_component_feature_semantics(
        {
            "components": [{"id": "body", "label": "Body"}],
            "features": [{"id": "drain", "type": "opening", "description": "Drain opening"}],
            "printable_outputs": [],
            "relationships": [],
        },
        compact=True,
    )

    assert plan["features"][0]["component_id"] == "body"
    assert any(item["rule_id"] == "plan.feature_owner_defaulted" for item in plan["normalization_findings"])


def test_fixed_repeated_layout_does_not_require_parameter_ids() -> None:
    plan = {
        "components": [{"id": "lid"}],
        "features": [{"id": "ventilation_slots", "component_id": "lid", "type": "ventilation", "description": "Twelve slots"}],
        "feature_layouts": [{
            "feature_id": "ventilation_slots",
            "owning_component_id": "lid",
            "layout_mode": "fixed_positions",
            "required_count": 12,
            "positions": _positions(12),
        }],
        "patterns": [{
            "pattern_id": "ventilation_slot_pattern",
            "owning_feature_id": "ventilation_slots",
            "owning_component_id": "lid",
            "pattern_type": "linear",
            "point_parameter_id": "ventilation_slot_points",
            "count": 12,
            "spacing": 8.0,
            "axis": "X",
        }],
        "parameters": [],
        "derived_parameters": [],
        "exposed_controls": [],
    }

    normalized = normalize_plan_constraints(plan)
    validate_pattern_specs(normalize_pattern_specs(normalized))


def test_proposed_layout_is_not_treated_as_a_configurable_pattern() -> None:
    normalized = normalize_plan_constraints({
        "parameters": [],
        "components": [{"id": "body"}],
        "features": [{"id": "holes", "component_id": "body", "type": "holes", "description": "Two holes"}],
        "feature_layouts": [{
            "feature_id": "holes",
            "owning_component_id": "body",
            "layout_mode": "proposed_positions",
            "required_count": 2,
            "positions": [{"x": -12.0, "y": 0.0, "z": 0.0}, {"x": 14.0, "y": 0.0, "z": 0.0}],
        }],
        "exposed_controls": [],
    })

    assert normalized["feature_layouts"][0]["layout_mode"] == "proposed_positions"


def test_layout_without_mode_is_normalized_from_positions_or_retained_as_proposed() -> None:
    normalized = normalize_plan_constraints({
        "parameters": [],
        "components": [{"id": "body"}],
        "features": [{"id": "holes", "component_id": "body", "type": "holes", "description": "Two holes"}],
        "feature_layouts": [{
            "feature_id": "holes",
            "owning_component_id": "body",
            "required_count": 2,
            "positions": _positions(2),
        }],
        "exposed_controls": [],
    })
    assert normalized["feature_layouts"][0]["layout_mode"] == "fixed_positions"


def test_fixed_count_without_positions_becomes_a_proposed_nonparametric_layout() -> None:
    normalized = normalize_plan_constraints({
        "parameters": [],
        "components": [{"id": "lid"}],
        "features": [{"id": "vents", "component_id": "lid", "type": "ventilation", "description": "Twelve slots"}],
        "feature_layouts": [{
            "feature_id": "vents",
            "layout_mode": "fixed_positions",
            "required_count": 12,
            "positions": [],
        }],
        "exposed_controls": [],
    })
    assert normalized["feature_layouts"][0]["layout_mode"] == "proposed_positions"


def test_compact_single_part_defaults_an_equivalent_unknown_feature_owner() -> None:
    normalized = normalize_compact_component_feature_semantics({
        "components": [{"id": "holder", "role": "printable_part"}],
        "features": [{"id": "mounting_holes", "component_id": "provider_alias", "type": "holes"}],
        "printable_outputs": [{"id": "holder_print", "component_ids": ["holder"]}],
    }, compact=True)
    assert normalized["features"][0]["component_id"] == "holder"
    assert any(item["rule_id"] == "plan.feature_owner_defaulted" for item in normalized["normalization_findings"])


def test_legacy_fixed_position_pattern_fields_are_normalized_without_sensitivity() -> None:
    normalized = normalize_plan_constraints({
        "parameters": [],
        "components": [{"id": "bracket"}],
        "features": [{"id": "holes", "component_id": "bracket", "type": "holes"}],
        "patterns": [{
            "id": "hole_layout",
            "feature_id": "holes",
            "layout_type": "fixed_positions",
            "positions": _positions(3),
        }],
        "feature_layouts": [{
            "feature_id": "holes",
            "strategy": "fixed_positions",
            "fixed_positions": _positions(3),
        }],
        "exposed_controls": [],
    })
    normalized = normalize_pattern_specs(normalized)
    validate_pattern_specs(normalized)
    assert normalized["patterns"][0]["pattern_id"] == "hole_layout"
    assert normalized["patterns"][0]["owning_feature_id"] == "holes"
    assert normalized["feature_layouts"][0]["layout_mode"] == "fixed_positions"


def test_integer_valued_float_count_parameter_resolves_as_a_count() -> None:
    resolved = resolve_pattern_points({
        "pattern_id": "vents",
        "pattern_type": "linear",
        "count_parameter_id": "ventilation_slot_count",
        "spacing": 5.0,
        "axis": "X",
    }, {"ventilation_slot_count": 12.0})
    assert len(resolved.points) == 12


def test_pattern_type_aliases_include_vertical_linear_provider_wording() -> None:
    normalized = normalize_pattern_specs({
        "components": [{"id": "body"}],
        "features": [{"id": "holes", "component_id": "body", "type": "holes"}],
        "patterns": [{
            "pattern_id": "holes_pattern",
            "owning_feature_id": "holes",
            "pattern_type": "vertical_linear",
            "axis": "Z",
            "count": 2,
            "spacing": 20.0,
        }],
        "parameters": [],
        "exposed_controls": [],
    })
    validate_pattern_specs(normalized)
    assert normalized["patterns"][0]["pattern_type"] == "linear"


def test_pattern_type_is_inferred_from_fixed_layout_positions() -> None:
    normalized = normalize_pattern_specs({
        "components": [{"id": "disk"}],
        "features": [{"id": "holes", "component_id": "disk", "type": "holes"}],
        "patterns": [{"id": "hole_pattern", "feature_id": "holes", "type": "fixed_positions"}],
        "feature_layouts": [{
            "feature_id": "holes",
            "layout_mode": "fixed_positions",
            "positions": [{"radius": 21.0, "angle": 20.0}, {"radius": 21.0, "angle": 145.0}],
        }],
        "parameters": [],
        "exposed_controls": [],
    })
    validate_pattern_specs(normalized)
    assert normalized["patterns"][0]["pattern_type"] == "explicit"
    assert normalized["patterns"][0]["positions"][0]["x"] == pytest.approx(21.0 * 0.93969262)


def test_ordinary_locals_are_not_plan_identities_in_source_authority() -> None:
    from app.services.cad.cadquery_source_authority import validate_cadquery_source_authority

    authority = {
        "exposed_control_ids": [],
        "parameters": [],
        "components": [{"id": "organizer", "required": True}],
        "features": [],
        "outputs": [{"id": "body", "component_ids": ["organizer"], "required": True, "expected_solid_count": 1}],
    }
    source = '''
import cadquery as cq
from volundr_cad.runtime import PrintableOutput, Product, component

PARAMETERS = []

@component("organizer")
def build_organizer(params):
    front_left_width = 60.0
    front_right_width = 180.0 - front_left_width
    body = cq.Workplane("XY").box(front_right_width, 120.0, 35.0)
    return body

def build(params):
    body = build_organizer(params)
    return Product(outputs=[PrintableOutput(output_id="body", component_id="organizer", label="Body", model=body, expected_solid_count=1, allow_disconnected_solids=False)], parameters=PARAMETERS)
'''

    result = validate_cadquery_source_authority(source, authority)
    assert result["passed_hard_checks"] is True
    assert any(
        finding["rule_id"] == "source.local_implementation_variable"
        and finding["symbol"] == "front_right_width"
        for finding in result["diagnostic_findings"]
    )


def test_physical_feedback_hole_change_persists_observation_and_delta() -> None:
    changes, observation = requirement_delta_for_message(
        "The printed holes are too tight. Increase both hole diameters from 5 mm to 5.4 mm. Keep their current positions and preserve every other dimension."
    )

    assert observation is not None
    assert observation["observation_type"] == "fit_too_tight"
    assert {change["requirement_id"] for change in changes} == {"hole_diameter"}
    assert changes[0]["value"] == 5.4


def test_compact_parser_emits_one_printable_part_for_integral_component_records() -> None:
    service = ProjectService(db=None, ai_provider=None)  # type: ignore[arg-type]
    specification = type("Spec", (), {"id": "spec-1"})()
    normalized = service._parse_compact_plan_payload(
        json.dumps({
            "schema_version": "compact-cad-plan-v1",
            "components": [
                {"id": "bracket", "label": "Bracket", "role": "printable_part"},
                {"id": "rib", "label": "Reinforcement rib", "role": "integral_feature"},
            ],
            "features": [],
            "printable_outputs": [],
        }),
        project=type("Project", (), {"id": "project-1"})(),
        specification=specification,
        active_requirements=[],
        revision_delta=[],
        preserved_requirements=[],
    )

    assert [item["id"] for item in normalized["components"]] == ["bracket"]
    assert normalized["printable_outputs"][0]["component_ids"] == ["bracket"]


def test_ordinary_physical_feedback_is_not_required_to_match_a_preexisting_control() -> None:
    changes, _ = requirement_delta_for_message(
        "The printed holes are too tight. Increase both hole diameters from 5 mm to 5.4 mm. Keep their current positions and preserve every other dimension."
    )
    assert changes[0]["source"] == "physical_test_feedback"


def test_observation_without_a_requested_correction_stays_feedback_only() -> None:
    changes, observation = requirement_delta_for_message("The test print shows the snap is too stiff.")
    assert changes == []
    assert observation is not None
    assert observation["observation_type"] == "physical_test_observation"


def test_revision_scope_targets_only_affected_component_and_output() -> None:
    service = ProjectService(db=None, ai_provider=None)  # type: ignore[arg-type]
    scope = service._revision_preservation_envelope(
        {
            "parameters": [{"id": "plate_thickness", "component_id": "plate"}, {"id": "lid_thickness", "component_id": "lid"}],
            "components": [{"id": "plate"}, {"id": "lid"}],
            "features": [{"id": "plate_holes", "component_id": "plate"}, {"id": "lid_fit", "component_id": "lid"}],
            "printable_outputs": [{"id": "plate_output", "component_ids": ["plate"]}, {"id": "lid_output", "component_ids": ["lid"]}],
        },
        [{"requirement_id": "plate_thickness", "target": "plate", "value": 8}],
    )

    assert scope["targeted_components"] == ["plate"]
    assert scope["targeted_outputs"] == ["plate_output"]
    assert scope["protected_components"] == ["lid"]
    assert scope["protected_outputs"] == ["lid_output"]


def test_unknown_pattern_with_fixed_positions_is_normalized_to_layout_evidence() -> None:
    normalized = normalize_pattern_specs({
        "components": [{"id": "body"}],
        "features": [{"id": "holes", "component_id": "body", "type": "holes", "description": "holes"}],
        "feature_layouts": [{"feature_id": "holes", "layout_mode": "fixed_positions", "required_count": 2, "positions": _positions(2)}],
        "patterns": [{"pattern_id": "holes_pattern", "owning_feature_id": "holes", "pattern_type": "vertical"}],
    })
    assert normalized["patterns"][0]["pattern_type"] == "linear"


def test_fixed_count_pattern_without_spacing_control_becomes_a_proposed_layout() -> None:
    normalized = normalize_pattern_specs({
        "components": [{"id": "lid"}],
        "features": [{"id": "vents", "component_id": "lid", "type": "ventilation", "description": "Twelve vents"}],
        "patterns": [{
            "pattern_id": "ventilation_slot_pattern",
            "owning_feature_id": "vents",
            "owning_component_id": "lid",
            "pattern_type": "linear",
            "point_parameter_id": "vent_points",
            "count": 12,
            "axis": "X",
        }],
        "parameters": [],
        "derived_parameters": [],
        "exposed_controls": [],
    })
    validate_pattern_specs(normalized)
    assert normalized["patterns"][0]["layout_mode"] == "proposed_positions"
