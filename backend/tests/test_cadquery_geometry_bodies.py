import ast
import json

import pytest

from app.services.cad.geometry_bodies import (
    GEOMETRY_BODIES_SCHEMA_VERSION,
    GeometryBodyError,
    assemble_geometry_bodies,
    build_geometry_function_inventory,
    validate_geometry_body_repair_scope,
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
    normalized_functions = []
    for function in functions:
        item = dict(function)
        legacy_lines = item.pop("body_lines", None)
        if legacy_lines is not None:
            result_symbol = "body" if "component" in str(item.get("function_id")) else "modified"
            statements = []
            for line in legacy_lines:
                prefix = line[: len(line) - len(line.lstrip())]
                stripped = line.strip()
                if stripped.startswith("return "):
                    expression = stripped[len("return "):]
                    if expression == "body" and result_symbol == "body":
                        expression = 'cq.Workplane("XY")'
                    statements.append(f"{prefix}{result_symbol} = {expression}")
                else:
                    statements.append(line)
            if not statements:
                statements = [
                    f'{result_symbol} = cq.Workplane("XY")'
                    if result_symbol == "body"
                    else f"{result_symbol} = body"
                ]
            item["statements"] = statements
            item["result_symbol"] = result_symbol
        normalized_functions.append(item)
    return json.dumps(
        {
            "schema_version": GEOMETRY_BODIES_SCHEMA_VERSION,
            "functions": normalized_functions,
        }
    )


def _inventory() -> dict:
    return build_geometry_function_inventory(PLAN)


def _assemble_component(statements: list[str], *, result_symbol: str = "body"):
    return assemble_geometry_bodies(
        _payload(
            {
                "function_id": "_ai_component_body",
                "statements": statements,
                "result_symbol": result_symbol,
            },
            {
                "function_id": "_ai_feature_mounting_holes",
                "statements": ["modified = body"],
                "result_symbol": "modified",
            },
        ),
        _inventory(),
    )


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


def test_function_argument_and_straight_line_locals_are_valid() -> None:
    result = _assemble_component(
        [
            'width = params["width"]',
            'body = cq.Workplane("XY").box(width, 20, params["thickness"])',
        ]
    )

    assert "width = params['width']" in result.functions["_ai_component_body"]


@pytest.mark.parametrize(
    ("statements", "rule_id"),
    [
        (
            ['body = cq.Workplane("XY").box(width, 20, 3)'],
            "geometry_body.invalid_parameter_access",
        ),
        (
            ['body = cq.Workplane("XY").box(unknown_width, 20, 3)'],
            "geometry_body.unbound_name",
        ),
        (
            [
                'body = cq.Workplane("XY").box(local_width, 20, 3)',
                'local_width = 40',
            ],
            "geometry_body.unbound_name",
        ),
        (
            [
                'if params["width"] > 0:',
                '    width = params["width"]',
                'body = cq.Workplane("XY").box(width, 20, 3)',
            ],
            "geometry_body.conditionally_bound_name",
        ),
    ],
)
def test_loaded_names_require_a_valid_definite_binding(
    statements: list[str], rule_id: str
) -> None:
    with pytest.raises(GeometryBodyError) as error:
        _assemble_component(statements)

    assert error.value.rule_id == rule_id
    assert error.value.details.get("function_id") == "_ai_component_body"


def test_assignment_in_all_branches_is_definitely_bound() -> None:
    result = _assemble_component(
        [
            'if params["width"] > 0:',
            '    width = params["width"]',
            "else:",
            "    width = 1",
            'body = cq.Workplane("XY").box(width, 20, 3)',
        ]
    )

    assert result.functions["_ai_component_body"].endswith("return body")


def test_tuple_unpacking_and_loop_binding_are_scoped_correctly() -> None:
    result = _assemble_component(
        [
            "x, y = (1, 2)",
            "for index in range(2):",
            "    point = (index + x, y)",
            'body = cq.Workplane("XY").box(x, 20, 3)',
        ]
    )

    assert result.functions["_ai_component_body"]


def test_comprehension_targets_do_not_leak() -> None:
    with pytest.raises(GeometryBodyError) as error:
        _assemble_component(
            [
                "points = [index for index in range(2)]",
                'body = cq.Workplane("XY").box(index + 1, 20, 3)',
            ]
        )

    assert error.value.rule_id == "geometry_body.unbound_name"


def test_comprehension_target_is_available_inside_comprehension() -> None:
    result = _assemble_component(
        [
            "points = [(index, index + 1) for index in range(2)]",
            'body = cq.Workplane("XY").box(len(points), 20, 3)',
        ]
    )

    assert result.functions["_ai_component_body"]


def test_exception_handler_name_is_available_only_inside_handler() -> None:
    with pytest.raises(GeometryBodyError) as error:
        _assemble_component(
            [
                "try:",
                "    width = 1",
                "except Exception as error:",
                "    width = len(str(error))",
                'body = cq.Workplane("XY").box(len(str(error)), 20, 3)',
            ]
        )

    assert error.value.rule_id == "geometry_body.unbound_name"


def test_approved_alias_helpers_and_builtins_are_allowed() -> None:
    result = _assemble_component(
        [
            'points = make_hole_pattern(params["width"], 2)',
            'width = max(1, len(points))',
            'body = cq.Workplane("XY").box(width, 20, 3)',
        ]
    )

    assert result.functions["_ai_component_body"]


def test_prohibited_name_and_nested_lambda_remain_blocked() -> None:
    with pytest.raises(GeometryBodyError) as prohibited:
        _assemble_component(
            [
                'body = cq.Workplane("XY").box(os.path.getsize("x"), 20, 3)',
            ]
        )
    assert prohibited.value.rule_id == "geometry_body.prohibited_name"

    with pytest.raises(GeometryBodyError):
        _assemble_component(
            [
                "make_box = lambda value: value",
                'body = cq.Workplane("XY").box(make_box(1), 20, 3)',
            ]
        )


def test_symbol_evidence_is_stable_and_persisted_in_assembly() -> None:
    first = _assemble_component(
        [
            'width = params["width"]',
            'body = cq.Workplane("XY").box(width, 20, 3)',
        ]
    )
    second = _assemble_component(
        [
            'width = params["width"]',
            'body = cq.Workplane("XY").box(width, 20, 3)',
        ]
    )

    assert first.symbol_evidence == second.symbol_evidence
    assert any(
        item["classification"] == "approved_module"
        for item in first.symbol_evidence["_ai_component_body"]
    )


def test_repair_scope_preserves_unaffected_function_hashes() -> None:
    original = _payload(
        {
            "function_id": "_ai_component_body",
            "statements": ['body = cq.Workplane("XY").box(width, 20, 3)'],
            "result_symbol": "body",
        },
        {
            "function_id": "_ai_feature_mounting_holes",
            "statements": ["modified = body"],
            "result_symbol": "modified",
        },
    )
    repaired = _payload(
        {
            "function_id": "_ai_component_body",
            "statements": ['body = cq.Workplane("XY").box(params["width"], 20, 3)'],
            "result_symbol": "body",
        },
        {
            "function_id": "_ai_feature_mounting_holes",
            "statements": ["modified = body"],
            "result_symbol": "modified",
        },
    )

    evidence = validate_geometry_body_repair_scope(
        original_raw_output=original,
        repaired_raw_output=repaired,
        affected_function_ids={"_ai_component_body"},
    )

    assert evidence["changed_unaffected_functions"] == {}


def test_repair_scope_rejects_changes_to_unaffected_function() -> None:
    original = _payload(
        {
            "function_id": "_ai_component_body",
            "statements": ['body = cq.Workplane("XY")'],
            "result_symbol": "body",
        },
        {
            "function_id": "_ai_feature_mounting_holes",
            "statements": ["modified = body"],
            "result_symbol": "modified",
        },
    )
    repaired = _payload(
        {
            "function_id": "_ai_component_body",
            "statements": ['body = cq.Workplane("XY")'],
            "result_symbol": "body",
        },
        {
            "function_id": "_ai_feature_mounting_holes",
            "statements": ["modified = body.translate((1, 0, 0))"],
            "result_symbol": "modified",
        },
    )

    with pytest.raises(GeometryBodyError) as error:
        validate_geometry_body_repair_scope(
            original_raw_output=original,
            repaired_raw_output=repaired,
            affected_function_ids={"_ai_component_body"},
        )

    assert error.value.rule_id == "geometry_body.repair_scope_violation"
