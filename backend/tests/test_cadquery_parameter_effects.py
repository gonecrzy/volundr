import json
from copy import deepcopy

import pytest

from app.services.cad.geometry_bodies import (
    GEOMETRY_BODIES_SCHEMA_VERSION,
    GeometryBodyError,
    assemble_geometry_bodies,
    build_geometry_function_inventory,
)
from app.services.cad.cadquery_source_authority import (
    CadQuerySourceAuthorityError,
    build_cadquery_source_authority,
    validate_cadquery_source_authority,
)
from app.services.cad.source_scaffold import render_cadquery_scaffold
from app.services.cad.parameter_effects import (
    PARAMETER_EFFECT_CONTRACT_VERSION,
    build_parameter_effect_contract,
    validate_parameter_effects,
)


PLAN = {
    "parameters": [
        {
            "id": "bottle_diameter",
            "value": 81.0,
            "unit": "mm",
            "protected": True,
            "source_requirement_id": "bottle_diameter",
        },
        {
            "id": "removable_fit_clearance_per_side",
            "value": 0.8,
            "unit": "mm",
            "protected": True,
            "source_requirement_id": "removable_fit_clearance_per_side",
        },
        {
            "id": "mounting_screw_count",
            "value": 2,
            "unit": "count",
            "protected": True,
            "source_requirement_id": "mounting_screw_count",
        },
        {
            "id": "mounting_hole_spacing",
            "value": 50.0,
            "unit": "mm",
            "protected": True,
            "source_requirement_id": "mounting_hole_spacing",
        },
    ],
    "derived_parameters": [
        {
            "id": "bottle_inner_diameter",
            "label": "Bottle inner diameter",
            "expression": "bottle_diameter + 2 * removable_fit_clearance_per_side",
            "depends_on": ["bottle_diameter", "removable_fit_clearance_per_side"],
            "value": 82.6,
            "unit": "mm",
            "provenance": {
                "relationship": "derived_formula",
                "source_parameter_ids": [
                    "bottle_diameter",
                    "removable_fit_clearance_per_side",
                ],
                "expression": "bottle_diameter + 2 * removable_fit_clearance_per_side",
            },
        },
        {
            "id": "bottle_cavity_diameter",
            "label": "Bottle cavity diameter",
            "expression": "bottle_inner_diameter + 1.0",
            "depends_on": ["bottle_inner_diameter"],
            "value": 83.6,
            "unit": "mm",
            "provenance": {
                "relationship": "derived_formula",
                "source_parameter_ids": ["bottle_inner_diameter"],
                "expression": "bottle_inner_diameter + 1.0",
            },
        },
    ],
    "dependency_edges": [
        {"from": "bottle_diameter", "to": "bottle_inner_diameter", "relationship": "diameter"},
        {
            "from": "removable_fit_clearance_per_side",
            "to": "bottle_inner_diameter",
            "relationship": "clearance",
        },
        {"from": "bottle_inner_diameter", "to": "bottle_cavity_diameter", "relationship": "cavity"},
    ],
    "components": [
        {
            "id": "holder_body",
            "parameters": ["bottle_cavity_diameter"],
            "features": ["bottle_cavity", "mounting_holes"],
        }
    ],
    "features": [
        {
            "id": "bottle_cavity",
            "component_id": "holder_body",
            "type": "containment",
            "parameters": ["bottle_cavity_diameter"],
        },
        {
            "id": "mounting_holes",
            "component_id": "holder_body",
            "type": "mounting_hole_group",
            "parameters": ["mounting_screw_count", "mounting_hole_spacing"],
        },
    ],
    "printable_outputs": [
        {
            "id": "holder",
            "component_ids": ["holder_body"],
            "required": True,
            "expected_solid_count": 1,
        }
    ],
}


def _payload(*functions: dict) -> str:
    return json.dumps(
        {"schema_version": GEOMETRY_BODIES_SCHEMA_VERSION, "functions": list(functions)}
    )


def _inventory() -> dict:
    return build_geometry_function_inventory(PLAN)


def test_contract_records_derived_dependency_provenance_and_effect_obligations() -> None:
    contract = build_parameter_effect_contract(PLAN)

    assert contract["schema_version"] == PARAMETER_EFFECT_CONTRACT_VERSION
    derived = {item["parameter_id"]: item for item in contract["derived_parameters"]}
    assert derived["bottle_cavity_diameter"] == {
        "parameter_id": "bottle_cavity_diameter",
        "expression": "bottle_inner_diameter + 1.0",
        "direct_dependencies": ["bottle_inner_diameter"],
        "transitive_protected_dependencies": [
            "bottle_diameter",
            "removable_fit_clearance_per_side",
        ],
        "resolved_value": 83.6,
        "provenance_version": derived["bottle_cavity_diameter"]["provenance_version"],
    }
    cavity = next(item for item in contract["functions"] if item["feature_id"] == "bottle_cavity")
    assert cavity["required_parameter_effects"] == [
        {
            "parameter_id": "bottle_diameter",
            "allowed_via": ["bottle_inner_diameter", "bottle_cavity_diameter"],
            "effect_type": "radius_or_diameter",
        },
        {
            "parameter_id": "removable_fit_clearance_per_side",
            "allowed_via": ["bottle_inner_diameter", "bottle_cavity_diameter"],
            "effect_type": "radius_or_diameter",
        },
    ]


def test_scaffold_calculates_derived_value_instead_of_trusting_stale_value() -> None:
    plan = deepcopy(PLAN)
    plan["derived_parameters"][1]["value"] = 999.0

    contract = build_parameter_effect_contract(plan)

    cavity = next(
        item for item in contract["derived_parameters"] if item["parameter_id"] == "bottle_cavity_diameter"
    )
    assert cavity["resolved_value"] == 83.6


def test_protected_parameters_pass_through_one_derived_value() -> None:
    result = assemble_geometry_bodies(
        _payload(
            {
                "function_id": "_ai_component_holder_body",
                "body_lines": ['return cq.Workplane("XY").cylinder(20, params["bottle_inner_diameter"] / 2)'],
            },
            {
                "function_id": "_ai_feature_bottle_cavity",
                "body_lines": ['return body.cut(cq.Workplane("XY").cylinder(20, params["bottle_cavity_diameter"] / 2))'],
            },
            {
                "function_id": "_ai_feature_mounting_holes",
                "body_lines": [
                    'points = make_hole_pattern(params["mounting_screw_count"], params["mounting_hole_spacing"])',
                    "return body.pushPoints(points).hole(4.2)",
                ],
            },
        ),
        _inventory(),
    )

    assert result.functions["_ai_feature_bottle_cavity"]


def test_direct_parameter_controls_geometry() -> None:
    manifest = {
        "function_id": "build_plate",
        "parameter_values": [{"id": "plate_width", "value": 80.0}],
        "required_parameter_effects": [
            {"parameter_id": "plate_width", "effect_type": "dimension"}
        ],
    }

    assert not validate_parameter_effects(
        'def build_plate(params):\n    return cq.Workplane("XY").box(params["plate_width"], 40, 3)',
        manifest,
    )


@pytest.mark.parametrize(
    ("effect_type", "source", "parameter_id", "value"),
    [
        ("radius_or_diameter", 'return cq.Workplane("XY").cylinder(20, params["diameter"] / 2)', "diameter", 81.0),
        ("translation", 'return body.translate((params["offset"], 0, 0))', "offset", 5.0),
        ("rotation", 'return body.rotate((0, 0, 0), (0, 0, 1), params["angle"])', "angle", 15.0),
        ("thickness", 'return cq.Workplane("XY").box(40, 40, params["thickness"])', "thickness", 3.0),
        ("feature_toggle", 'return body.cut(cq.Workplane("XY").box(2, 2, 2)) if params["enabled"] else body', "enabled", True),
        ("boolean_tool_size", 'return body.cut(cq.Workplane("XY").box(params["tool_size"], 2, 2))', "tool_size", 10.0),
        ("diameter", 'return cq.Workplane("XY").cylinder(20, params["diameter"] / 2)', "diameter", 81.0),
    ],
)
def test_supported_effect_types_are_verified(
    effect_type: str, source: str, parameter_id: str, value: object
) -> None:
    manifest = {
        "function_id": "build_feature",
        "parameter_values": [{"id": parameter_id, "value": value}],
        "required_parameter_effects": [
            {"parameter_id": parameter_id, "effect_type": effect_type}
        ],
    }

    assert not validate_parameter_effects(f"def build_feature(params, body):\n    {source}", manifest)


def test_hardcoded_diameter_matching_current_value_is_rejected() -> None:
    with pytest.raises(GeometryBodyError) as error:
        assemble_geometry_bodies(
            _payload(
                {
                    "function_id": "_ai_component_holder_body",
                    "body_lines": ['return cq.Workplane("XY").cylinder(20, 83.6 / 2)'],
                },
                    {"function_id": "_ai_feature_bottle_cavity", "body_lines": ['return body.cut(cq.Workplane("XY").cylinder(20, params["bottle_cavity_diameter"] / 2))']},
                {"function_id": "_ai_feature_mounting_holes", "body_lines": ["return body"]},
            ),
            _inventory(),
        )

    assert error.value.rule_id == "geometry_body.dimension_bypassed_by_literal"


def test_fixed_two_point_pattern_bypassing_count_is_rejected() -> None:
    with pytest.raises(GeometryBodyError) as error:
        assemble_geometry_bodies(
            _payload(
                {"function_id": "_ai_component_holder_body", "body_lines": ['return cq.Workplane("XY").cylinder(20, params["bottle_cavity_diameter"] / 2)']},
                {"function_id": "_ai_feature_bottle_cavity", "body_lines": ['return body.cut(cq.Workplane("XY").cylinder(20, params["bottle_cavity_diameter"] / 2))']},
                {
                    "function_id": "_ai_feature_mounting_holes",
                    "body_lines": [
                        'points = [(-25, 0), (25, 0)]',
                        'return body.pushPoints(points).hole(4.2)',
                    ],
                },
            ),
            _inventory(),
        )

    assert error.value.rule_id == "geometry_body.pattern_count_hardcoded"


def test_range_count_and_approved_helper_receiving_count_pass() -> None:
    for body_lines in (
        [
            'for index in range(params["mounting_screw_count"]):',
            '    body = body.cut(cq.Workplane("XY").cylinder(10, 4.2)).translate((index * params["mounting_hole_spacing"], 0, 0))',
            "return body",
        ],
        [
            'points = make_hole_pattern(params["mounting_screw_count"], params["mounting_hole_spacing"])',
            "return body.pushPoints(points).hole(4.2)",
        ],
    ):
        result = assemble_geometry_bodies(
            _payload(
                {"function_id": "_ai_component_holder_body", "body_lines": ['return cq.Workplane("XY").cylinder(20, params["bottle_cavity_diameter"] / 2)']},
                {"function_id": "_ai_feature_bottle_cavity", "body_lines": ['return body.cut(cq.Workplane("XY").cylinder(20, params["bottle_cavity_diameter"] / 2))']},
                {"function_id": "_ai_feature_mounting_holes", "body_lines": body_lines},
            ),
            _inventory(),
        )
        assert result.functions["_ai_feature_mounting_holes"]


def test_broken_derived_dependency_path_blocks_assembly() -> None:
    plan = deepcopy(PLAN)
    plan["derived_parameters"][0]["depends_on"] = ["missing_bottle_input"]
    inventory = build_geometry_function_inventory(plan)

    with pytest.raises(GeometryBodyError) as error:
        assemble_geometry_bodies(
            _payload(
                {"function_id": "_ai_component_holder_body", "body_lines": ["return cq.Workplane(\"XY\")"]},
                {"function_id": "_ai_feature_bottle_cavity", "body_lines": ["return body"]},
                {"function_id": "_ai_feature_mounting_holes", "body_lines": ["return body"]},
            ),
            inventory,
        )

    assert error.value.rule_id == "geometry_body.derived_dependency_broken"


def test_unrelated_derived_parameter_does_not_satisfy_protected_requirement() -> None:
    plan = deepcopy(PLAN)
    plan["derived_parameters"].append(
        {
            "id": "unrelated_dimension",
            "label": "Unrelated dimension",
            "expression": "mounting_hole_spacing + 10",
            "depends_on": ["mounting_hole_spacing"],
            "value": 60.0,
            "unit": "mm",
        }
    )
    plan["features"][0]["parameters"].append("unrelated_dimension")

    with pytest.raises(GeometryBodyError) as error:
        assemble_geometry_bodies(
            _payload(
                {"function_id": "_ai_component_holder_body", "body_lines": ['return cq.Workplane("XY").cylinder(20, params["bottle_cavity_diameter"] / 2)']},
                {
                    "function_id": "_ai_feature_bottle_cavity",
                    "body_lines": ['return body.cut(cq.Workplane("XY").cylinder(20, params["unrelated_dimension"] / 2))'],
                },
                {
                    "function_id": "_ai_feature_mounting_holes",
                    "body_lines": [
                        'points = make_hole_pattern(params["mounting_screw_count"], params["mounting_hole_spacing"])',
                        "return body.pushPoints(points).hole(4.2)",
                    ],
                },
            ),
            build_geometry_function_inventory(plan),
        )

    assert error.value.rule_id == "geometry_body.required_effect_missing"


def test_fixed_pattern_spacing_is_reported_separately() -> None:
    with pytest.raises(GeometryBodyError) as error:
        assemble_geometry_bodies(
            _payload(
                {"function_id": "_ai_component_holder_body", "body_lines": ['return cq.Workplane("XY").cylinder(20, params["bottle_cavity_diameter"] / 2)']},
                {"function_id": "_ai_feature_bottle_cavity", "body_lines": ['return body.cut(cq.Workplane("XY").cylinder(20, params["bottle_cavity_diameter"] / 2))']},
                {
                    "function_id": "_ai_feature_mounting_holes",
                    "body_lines": [
                        'for index in range(params["mounting_screw_count"]):',
                        '    body = body.cut(cq.Workplane("XY").cylinder(10, 4.2)).translate((index * 50.0, 0, 0))',
                        "return body",
                    ],
                },
            ),
            _inventory(),
        )

    assert error.value.rule_id == "geometry_body.pattern_spacing_hardcoded"


def _rendered_source() -> str:
    return render_cadquery_scaffold(PLAN, _geometry_functions()).source


def _geometry_functions() -> dict[str, str]:
    return {
        "_ai_component_holder_body": 'def _ai_component_holder_body(params):\n    return cq.Workplane("XY").cylinder(20, params["bottle_cavity_diameter"] / 2)',
        "_ai_feature_bottle_cavity": 'def _ai_feature_bottle_cavity(body, params):\n    return body.cut(cq.Workplane("XY").cylinder(20, params["bottle_cavity_diameter"] / 2))',
        "_ai_feature_mounting_holes": 'def _ai_feature_mounting_holes(body, params):\n    for index in range(params["mounting_screw_count"]):\n        body = body.cut(cq.Workplane("XY").cylinder(10, 4.2)).translate((index * params["mounting_hole_spacing"], 0, 0))\n    return body',
    }


def test_scaffold_persists_resolved_derived_and_effect_manifests() -> None:
    rendered = render_cadquery_scaffold(PLAN, _geometry_functions())

    assert rendered.derived_parameter_manifest[0]["parameter_id"] == "bottle_inner_diameter"
    assert rendered.derived_parameter_manifest[1]["resolved_value"] == 83.6
    assert any(item["function_id"] == "_ai_feature_mounting_holes" for item in rendered.parameter_effect_manifest)


def test_assembled_source_uses_the_same_effect_contract_as_body_assembly() -> None:
    source = _rendered_source()
    authority = build_cadquery_source_authority(PLAN)

    result = validate_cadquery_source_authority(source, authority)

    assert result["passed_hard_checks"] is True
    assert authority["derived_parameter_manifest"][1]["resolved_value"] == 83.6


def test_source_effect_validation_rejects_literal_diameter_bypass() -> None:
    source = _rendered_source().replace(
        'params["bottle_cavity_diameter"] / 2',
        "83.6 / 2",
        1,
    )
    authority = build_cadquery_source_authority(PLAN)

    with pytest.raises(CadQuerySourceAuthorityError) as error:
        validate_cadquery_source_authority(source, authority)

    assert "geometry_body.dimension_bypassed_by_literal" in {
        finding["rule_id"] for finding in error.value.findings
    }
