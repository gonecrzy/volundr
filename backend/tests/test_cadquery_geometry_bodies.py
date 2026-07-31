import ast
import json

import pytest

from app.services.cad.geometry_bodies import (
    GEOMETRY_BODIES_SCHEMA_VERSION,
    GeometryBodyError,
    assemble_geometry_bodies,
    build_geometry_function_inventory,
)
from app.services.cad.source_scaffold import render_cadquery_scaffold


PLAN = {
    "parameters": [
        {"id": "width", "type": "float", "value": 80.0, "unit": "mm"},
        {"id": "thickness", "type": "float", "value": 3.0, "unit": "mm"},
    ],
    "components": [{"id": "body", "features": ["mounting_holes"]}],
    "features": [{"id": "mounting_holes", "component_id": "body", "type": "mounting"}],
    "printable_outputs": [
        {
            "id": "body_output",
            "component_ids": ["body"],
            "required": True,
            "expected_solid_count": 1,
        }
    ],
}


def _payload(*functions: dict) -> str:
    return json.dumps(
        {
            "schema_version": GEOMETRY_BODIES_SCHEMA_VERSION,
            "functions": list(functions),
        }
    )


def _inventory() -> dict:
    return build_geometry_function_inventory(PLAN)


def test_valid_body_lines_are_assembled_with_scaffold_owned_signatures() -> None:
    result = assemble_geometry_bodies(
        _payload(
            {
                "function_id": "_ai_component_body",
                "body_lines": [
                    'return cq.Workplane("XY").box(params["width"], 20, params["thickness"])',
                ],
            },
            {
                "function_id": "_ai_feature_mounting_holes",
                "body_lines": ["return body"],
            },
        ),
        _inventory(),
    )

    assert ast.parse(result.functions["_ai_component_body"])
    assert "def _ai_component_body(params):" in result.functions["_ai_component_body"]
    assert "def _ai_feature_mounting_holes(body, params):" in result.functions[
        "_ai_feature_mounting_holes"
    ]
    assert result.function_body_hashes["_ai_component_body"]


def test_equivalent_indentation_produces_stable_canonical_source() -> None:
    first = assemble_geometry_bodies(
        _payload(
            {
                "function_id": "_ai_component_body",
                "body_lines": ['    body = cq.Workplane("XY")', "    return body"],
            },
            {"function_id": "_ai_feature_mounting_holes", "body_lines": ["return body"]},
        ),
        _inventory(),
    )
    second = assemble_geometry_bodies(
        _payload(
            {
                "function_id": "_ai_component_body",
                "body_lines": ['body = cq.Workplane("XY")', "return body"],
            },
            {"function_id": "_ai_feature_mounting_holes", "body_lines": ["return body"]},
        ),
        _inventory(),
    )

    assert first.functions == second.functions


def test_tabs_are_normalized_deterministically() -> None:
    result = assemble_geometry_bodies(
        _payload(
            {
                "function_id": "_ai_component_body",
                "body_lines": ["\tbody = cq.Workplane(\"XY\")", "\treturn body"],
            },
            {"function_id": "_ai_feature_mounting_holes", "body_lines": ["return body"]},
        ),
        _inventory(),
    )

    assert "\t" not in result.functions["_ai_component_body"]


def test_fenced_json_is_allowed_but_prose_is_rejected() -> None:
    payload = _payload(
        {"function_id": "_ai_component_body", "body_lines": ["return cq.Workplane(\"XY\")"]},
        {"function_id": "_ai_feature_mounting_holes", "body_lines": ["return body"]},
    )
    result = assemble_geometry_bodies(f"```json\n{payload}\n```", _inventory())
    assert result.payload["schema_version"] == GEOMETRY_BODIES_SCHEMA_VERSION

    with pytest.raises(GeometryBodyError, match="JSON only"):
        assemble_geometry_bodies("Here is the JSON:\n" + payload, _inventory())


@pytest.mark.parametrize(
    ("functions", "rule_id"),
    [
        ([{"function_id": "_ai_component_body", "body_lines": ["return body"]}], "missing_function"),
        (
            [
                {"function_id": "_ai_component_body", "body_lines": ["return body"]},
                {"function_id": "_ai_component_body", "body_lines": ["return body"]},
                {"function_id": "_ai_feature_mounting_holes", "body_lines": ["return body"]},
            ],
            "duplicate_function",
        ),
        (
            [
                {"function_id": "_ai_component_body", "body_lines": ["return body"]},
                {"function_id": "_ai_feature_other", "body_lines": ["return body"]},
            ],
            "unexpected_function",
        ),
    ],
)
def test_function_inventory_is_exact(functions: list[dict], rule_id: str) -> None:
    with pytest.raises(GeometryBodyError) as error:
        assemble_geometry_bodies(_payload(*functions), _inventory())
    assert error.value.rule_id == f"geometry_body.{rule_id}"


@pytest.mark.parametrize(
    ("body_lines", "rule_id"),
    [
        (["def nested(params):", "    return body", "return nested(params)"], "invalid_statement"),
        (["import os", "return body"], "invalid_statement"),
        (["body = cq.Workplane(\"XY\")"], "missing_return"),
        (["return cq.Workplane(\"XY\").box(params[\"unknown\"], 1, 1)"], "undeclared_parameter"),
        (["PARAMETERS = []", "return body"], "scaffold_mutation_attempt"),
    ],
)
def test_body_validation_rejects_unsafe_or_incomplete_bodies(
    body_lines: list[str], rule_id: str
) -> None:
    with pytest.raises(GeometryBodyError) as error:
        assemble_geometry_bodies(
            _payload(
                {"function_id": "_ai_component_body", "body_lines": body_lines},
                {"function_id": "_ai_feature_mounting_holes", "body_lines": ["return body"]},
            ),
            _inventory(),
        )
    assert error.value.rule_id == f"geometry_body.{rule_id}"


def test_scaffold_hash_is_independent_of_provider_body_formatting() -> None:
    result = assemble_geometry_bodies(
        _payload(
            {"function_id": "_ai_component_body", "body_lines": ["return cq.Workplane(\"XY\")"]},
            {"function_id": "_ai_feature_mounting_holes", "body_lines": ["return body"]},
        ),
        _inventory(),
    )
    rendered = render_cadquery_scaffold(PLAN, result.functions)

    assert rendered.scaffold_hash
    assert rendered.scaffold_hash == render_cadquery_scaffold(PLAN, result.functions).scaffold_hash
