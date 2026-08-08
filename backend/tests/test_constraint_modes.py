from __future__ import annotations

from types import SimpleNamespace

from app.services.cad.geometry_bodies import assemble_geometry_bodies, build_geometry_function_inventory
from app.services.cad.parameter_effects import build_parameter_effect_contract
from app.services.geometry import functional as functional_geometry
from app.services.projects.plan_constraints import normalize_plan_constraints


def _plan(*, count_mode: str = "fixed_constraint", layout_mode: str = "fixed_positions") -> dict:
    return {
        "parameters": [
            {"id": "hole_count", "label": "Hole count", "value": 2, "unit": "count", "protected": True, "constraint_mode": count_mode},
            {"id": "hole_diameter", "label": "Hole diameter", "value": 4.2, "unit": "mm", "protected": True, "constraint_mode": "fixed_constraint"},
        ],
        "components": [{"id": "body", "parameters": ["hole_count", "hole_diameter"]}],
        "features": [{"id": "holes", "component_id": "body", "type": "hole_group", "description": "Mounting holes", "parameters": ["hole_count", "hole_diameter"]}],
        "feature_layouts": [{
            "feature_id": "holes",
            "owning_component_id": "body",
            "layout_mode": layout_mode,
            "required_count": 2,
            "positions": [{"x": 0.0, "y": 0.0, "z": -25.0}, {"x": 0.0, "y": 0.0, "z": 25.0}],
            "hole_axis": "Y",
            "arrangement_axis": "Z",
            "count_parameter_id": "hole_count",
        }],
        "printable_outputs": [{"id": "output", "component_ids": ["body"]}],
    }


def _geometry_payload() -> str:
    import json

    return json.dumps({
        "schema_version": "cadquery-geometry-bodies-v2",
        "functions": [
            {"function_id": "_ai_component_body", "statements": ["body = cq.Workplane('XY')"], "result_symbol": "body"},
            {
                "function_id": "_ai_feature_holes",
                "statements": [
                    "points = [(0, 0, -25), (0, 0, 25)]",
                    "modified = body.pushPoints(points).hole(params['hole_diameter'])",
                ],
                "result_symbol": "modified",
            },
        ],
    })


def test_fixed_count_does_not_require_sensitivity_to_count() -> None:
    plan = _plan()
    contract = build_parameter_effect_contract(plan)
    holes = next(item for item in contract["functions"] if item["feature_id"] == "holes")
    assert all(item["parameter_id"] != "hole_count" for item in holes["required_parameter_effects"])
    assert assemble_geometry_bodies(_geometry_payload(), build_geometry_function_inventory(plan))


def test_configurable_count_keeps_pattern_effect_obligation() -> None:
    plan = _plan(count_mode="configurable_parameter", layout_mode="uniform_linear")
    plan["patterns"] = [{
        "pattern_id": "hole_pattern",
        "owning_feature_id": "holes",
        "owning_component_id": "body",
        "pattern_type": "linear",
        "point_parameter_id": "hole_points",
        "count_parameter_id": "hole_count",
        "spacing_parameter_id": "hole_spacing",
        "axis": "Z",
    }]
    plan["parameters"].append({"id": "hole_spacing", "label": "Hole spacing", "value": 50.0, "unit": "mm", "constraint_mode": "configurable_parameter"})
    holes = next(item for item in build_parameter_effect_contract(plan)["functions"] if item["feature_id"] == "holes")
    assert {item["parameter_id"] for item in holes["required_parameter_effects"]} >= {"hole_count", "hole_spacing"}


def test_request_context_classifies_fixed_and_explicitly_adjustable_values() -> None:
    base = {
        "parameters": [{"id": "mounting_screw_count", "label": "Mounting screw count", "value": 2, "unit": "count", "source_requirement_id": "mounting_screw_count", "provenance": {"relationship": "direct"}}],
        "features": [],
    }
    fixed = normalize_plan_constraints(base, request_context="Use two mounting screws")
    adjustable = normalize_plan_constraints(base, request_context="Let me change the mounting screw count")
    assert fixed["parameters"][0]["constraint_mode"] == "fixed_constraint"
    assert fixed["parameters"][0]["editable"] is False
    assert adjustable["parameters"][0]["constraint_mode"] == "configurable_parameter"
    assert adjustable["parameters"][0]["editable"] is True


def test_fixed_layout_functional_verification_matches_irregular_positions(monkeypatch) -> None:
    holes = [
        SimpleNamespace(center=(12.0, 3.0, -8.0), diameter=4.2, confidence=0.95),
        SimpleNamespace(center=(-4.0, 3.0, 31.0), diameter=4.2, confidence=0.95),
    ]
    monkeypatch.setattr(functional_geometry, "_detect_axis_aligned_hole_candidates", lambda *_args: holes)
    plan = {
        "feature_layouts": [{
            "feature_id": "holes",
            "owning_component_id": "body",
            "layout_mode": "fixed_positions",
            "required_count": 2,
            "positions": [{"x": 12.0, "y": 0.0, "z": -8.0}, {"x": -4.0, "y": 0.0, "z": 31.0}],
        }],
        "functional_contract": {"mounting_interfaces": [{
            "id": "mount",
            "type": "planar_mount",
            "component_id": "body",
            "feature_id": "holes",
            "hole_axis": "Y",
            "arrangement_axis": "Z",
            "fastener_count": 2,
            "hole_diameter": 4.2,
        }]},
    }
    findings = functional_geometry.MountingHoleVerifier().verify(
        functional_geometry.FunctionalGeometryContext(product_plan=plan, output_shape=object())
    )
    position_finding = next(item for item in findings if item.rule_id == "functional.mounting_hole_positions")
    assert position_finding.verification_state == "unverifiable"
    assert position_finding.metadata["evidence_authority"] == "derived_stl_candidate"
