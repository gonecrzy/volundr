from __future__ import annotations

import ast
import asyncio
import re

import pytest

from app.services.research.geometry_ir_experimental import (
    IR_SCHEMA_ID,
    GeometryIRValidationError,
    UnsupportedIROperation,
    compile_geometry_ir,
    validate_geometry_ir,
)


def number(value: int | float, unit: str = "mm") -> dict:
    return {"type": "number", "value": value, "unit": unit}


def point(x: int | float, y: int | float, z: int | float = 0) -> list[dict]:
    return [number(x), number(y), number(z)]


def base_ir(*operations: dict, outputs: list[dict] | None = None) -> dict:
    return {
        "schema_version": IR_SCHEMA_ID,
        "parameters": {},
        "frames": {
            "world": {
                "origin": point(0, 0),
                "normal": [number(0, "unitless"), number(0, "unitless"), number(1, "unitless")],
                "x_direction": [number(1, "unitless"), number(0, "unitless"), number(0, "unitless")],
                "plane": "XY",
            }
        },
        "operations": list(operations),
        "outputs": outputs or [{"output_id": "body", "result_symbol": "body", "required": True}],
        "revision_obligations": [],
        "provenance": {
            "requirements": ["req-1"],
            "plan": "plan-1",
            "derivation": "counterfactual_manual",
        },
    }


def primitive_box(operation_id: str = "make-body", result_symbol: str = "body") -> dict:
    return {
        "operation_id": operation_id,
        "operation": "primitive",
        "primitive_type": "box",
        "frame": "world",
        "parameters": {
            "length": number(80),
            "width": number(50),
            "height": number(6),
        },
        "result_symbol": result_symbol,
    }


def test_schema_requires_typed_values_and_rejects_ambiguous_fields() -> None:
    document = base_ir(primitive_box())
    document["operations"][0]["parameters"]["length"] = 80

    with pytest.raises(GeometryIRValidationError, match="typed number"):
        validate_geometry_ir(document)

    document = base_ir(primitive_box())
    document["operations"][0]["offset"] = "XY"
    with pytest.raises(GeometryIRValidationError, match="unknown field"):
        validate_geometry_ir(document)


def test_schema_supports_parameter_references_expressions_frames_and_revision_obligations() -> None:
    document = base_ir(
        {
            "operation_id": "make-body",
            "operation": "primitive",
            "primitive_type": "box",
            "frame": "world",
            "parameters": {
                "length": {"type": "parameter_ref", "id": "base_length", "unit": "mm"},
                "width": {"type": "expression", "operator": "+", "operands": [number(40), number(10)], "unit": "mm"},
                "height": number(6),
            },
            "result_symbol": "body",
        }
    )
    document["parameters"] = {
        "base_length": {"type": "number", "unit": "mm", "default": 80, "protected": True}
    }
    document["revision_obligations"] = [
        {"kind": "preserve_parameter", "parameter_id": "base_length"}
    ]

    validated = validate_geometry_ir(document)

    assert validated["schema_version"] == IR_SCHEMA_ID
    assert validated["revision_obligations"][0]["parameter_id"] == "base_length"


def test_compiler_is_deterministic_preserves_values_and_provenance() -> None:
    document = base_ir(primitive_box())

    first = compile_geometry_ir(document)
    second = compile_geometry_ir(document)

    assert first.source == second.source
    assert "80" in first.source
    assert "50" in first.source
    assert "6" in first.source
    assert "volundr-ir: make-body" in first.source
    assert "req-1" in first.source
    assert "output_id=\"body\"" in first.source


def test_compiler_emits_current_public_cadquery_and_no_direct_ocp() -> None:
    source = compile_geometry_ir(base_ir(primitive_box())).source

    ast.parse(source)
    assert "import OCP" not in source
    assert "from OCP" not in source
    assert "combine=False" not in source
    assert "cq.Workplane(\"XY\"" in source


def test_compiler_topologically_orders_dependencies_deterministically() -> None:
    document = base_ir(
        {
            "operation_id": "cut-feature",
            "operation": "cut",
            "target": "body",
            "operand": "hole",
            "result_symbol": "body",
            "depends_on": ["make-body", "make-hole"],
        },
        {
            "operation_id": "make-hole",
            "operation": "primitive",
            "primitive_type": "cylinder",
            "frame": "world",
            "parameters": {"radius": number(3), "height": number(10)},
            "result_symbol": "hole",
            "depends_on": ["make-body"],
        },
        primitive_box(),
    )

    source = compile_geometry_ir(document).source

    assert source.index("volundr-ir: make-body") < source.index("volundr-ir: make-hole") < source.index("volundr-ir: cut-feature")


def test_slot_is_compiler_owned_and_does_not_encode_slot1d() -> None:
    document = base_ir(
        primitive_box(),
        {
            "operation_id": "cut-upright-slot",
            "operation": "slot",
            "target": "body",
            "frame": "world",
            "center": point(0, 20),
            "length": number(20),
            "width": number(6),
            "depth": {"mode": "blind", "distance": number(10)},
            "result_symbol": "body",
            "depends_on": ["make-body"],
        },
    )

    source = compile_geometry_ir(document).source

    assert ".slot2D(" in source
    assert "slot1D" not in source
    assert "cut-upright-slot" in source


def test_fixed_irregular_layout_stays_fixed() -> None:
    document = base_ir(
        primitive_box(),
        {
            "operation_id": "fixed-holes",
            "operation": "fixed_pattern",
            "target": "body",
            "frame": "world",
            "feature": {"kind": "hole", "diameter": number(5), "depth": {"mode": "through"}},
            "points": [point(-20, -10), point(7, 13), point(19, -4)],
            "result_symbol": "body",
            "depends_on": ["make-body"],
        },
    )

    source = compile_geometry_ir(document).source

    assert "-20" in source and "7" in source and "19" in source
    assert ".rarray(" not in source
    assert ".polarArray(" not in source


def test_unsupported_advanced_operation_fails_closed_without_restricting_schema() -> None:
    document = base_ir(
        {
            "operation_id": "freeform-sweep",
            "operation": "sweep",
            "result_symbol": "body",
            "profile": "profile",
            "path": "path",
        }
    )
    validate_geometry_ir(document)

    with pytest.raises(UnsupportedIROperation, match="sweep"):
        compile_geometry_ir(document)


def test_raw_escape_requires_identity_provenance_and_isolated_result() -> None:
    document = base_ir(
        {
            "operation_id": "advanced-feature",
            "operation": "raw_cadquery",
            "contract_version": "volundr-geometry-slots-v1",
            "required_inputs": [],
            "required_result_symbol": "body",
            "statements": ["body = cq.Workplane('XY').box(1, 2, 3)"],
            "result_symbol": "body",
        }
    )

    source = compile_geometry_ir(document).source

    assert "body = cq.Workplane('XY').box(1, 2, 3)" in source
    assert "advanced-feature" in source
    assert "output_id=\"body\"" in source

    document["operations"][0]["statements"] = ["other_output = cq.Workplane('XY').box(1, 2, 3)"]
    with pytest.raises(GeometryIRValidationError, match="result symbol"):
        validate_geometry_ir(document)


def test_raw_escape_rejects_imports_and_direct_ocp() -> None:
    for statement in [
        "import OCP",
        "body = OCP.BRepPrimAPI_MakeBox(1, 2, 3).Shape()",
        "body = cq.Workplane('XY').box(1, 2, 3); other = body",
    ]:
        document = base_ir(
            {
                "operation_id": "unsafe-raw",
                "operation": "raw_cadquery",
                "contract_version": "volundr-geometry-slots-v1",
                "required_inputs": [],
                "required_result_symbol": "body",
                "statements": [statement],
                "result_symbol": "body",
            }
        )
        with pytest.raises(GeometryIRValidationError):
            validate_geometry_ir(document)


def test_output_assignments_keep_multi_output_identity_separate() -> None:
    document = base_ir(
        primitive_box(result_symbol="base"),
        {
            "operation_id": "make-lid",
            "operation": "primitive",
            "primitive_type": "box",
            "frame": "world",
            "parameters": {"length": number(80), "width": number(50), "height": number(3)},
            "result_symbol": "lid",
        },
        outputs=[
            {"output_id": "enclosure_base", "result_symbol": "base", "required": True},
            {"output_id": "enclosure_lid", "result_symbol": "lid", "required": True},
        ],
    )

    source = compile_geometry_ir(document).source

    assert source.count("PrintableOutput(") == 2
    assert 'output_id="enclosure_base"' in source
    assert 'output_id="enclosure_lid"' in source


def test_invalid_frame_offset_does_not_accept_plane_name_as_numeric_value() -> None:
    document = base_ir(primitive_box())
    document["frames"]["world"]["origin"][2] = "XY"

    with pytest.raises(GeometryIRValidationError, match="typed number"):
        validate_geometry_ir(document)


def test_production_routing_does_not_import_experimental_ir() -> None:
    from app.services import gemini_integration

    assert "geometry_ir_experimental" not in gemini_integration.__dict__


def test_parameter_references_preserve_exact_values_without_rounding() -> None:
    document = base_ir(primitive_box())
    document["parameters"] = {
        "exact_length": {"type": "number", "unit": "mm", "default": 80.123456789, "protected": True}
    }
    document["operations"][0]["parameters"]["length"] = {
        "type": "parameter_ref", "id": "exact_length", "unit": "mm"
    }

    source = compile_geometry_ir(document).source

    assert "80.123456789" in source
    assert "params['exact_length']" in source
    assert "80.123" in source


def test_nonzero_coordinate_frame_is_owned_by_compiler() -> None:
    document = base_ir(primitive_box())
    document["frames"]["world"]["origin"] = _frame_origin = point(10, 20, 30)

    source = compile_geometry_ir(document).source

    assert "origin=(10, 20, 30)" in source
    assert "offset='XY'" not in source


def test_hole_counterbore_and_countersink_are_semantic_operations() -> None:
    document = base_ir(
        primitive_box(),
        {
            "operation_id": "plain-hole",
            "operation": "hole",
            "target": "body",
            "frame": "world",
            "center": point(-10, 0),
            "diameter": number(5),
            "depth": {"mode": "through"},
            "result_symbol": "body",
            "depends_on": ["make-body"],
        },
        {
            "operation_id": "counterbore-hole",
            "operation": "counterbore",
            "target": "body",
            "frame": "world",
            "center": point(0, 0),
            "diameter": number(5),
            "counterbore_diameter": number(9),
            "counterbore_depth": number(2),
            "depth": {"mode": "blind", "distance": number(10)},
            "result_symbol": "body",
            "depends_on": ["plain-hole"],
        },
        {
            "operation_id": "countersink-hole",
            "operation": "countersink",
            "target": "body",
            "frame": "world",
            "center": point(10, 0),
            "diameter": number(5),
            "countersink_diameter": number(10),
            "countersink_angle": number(90, "degree"),
            "depth": {"mode": "through"},
            "result_symbol": "body",
            "depends_on": ["counterbore-hole"],
        },
    )

    source = compile_geometry_ir(document).source

    assert ".hole(5)" in source
    assert ".cboreHole(5, 9, 2, depth=10)" in source
    assert ".cskHole(5, 10, 90)" in source


def test_transform_and_boolean_intent_compile_in_order() -> None:
    document = base_ir(
        primitive_box(),
        {
            "operation_id": "move-body",
            "operation": "transform",
            "target": "body",
            "translation": [number(1), number(2), number(3)],
            "result_symbol": "body",
            "depends_on": ["make-body"],
        },
        {
            "operation_id": "cut-feature",
            "operation": "cut",
            "target": "body",
            "operand": "body",
            "result_symbol": "body",
            "depends_on": ["move-body"],
        },
    )

    source = compile_geometry_ir(document).source

    assert ".translate((1, 2, 3))" in source
    assert ".cut(body)" in source
    assert source.index("move-body") < source.index("cut-feature")


def test_stable_all_edge_fillet_and_chamfer_are_supported() -> None:
    document = base_ir(
        primitive_box(),
        {
            "operation_id": "round-edges",
            "operation": "fillet",
            "target": "body",
            "radius": number(1),
            "selector": "all_edges",
            "result_symbol": "body",
            "depends_on": ["make-body"],
        },
        {
            "operation_id": "bevel-edges",
            "operation": "chamfer",
            "target": "body",
            "length": number(1),
            "selector": "all_edges",
            "result_symbol": "body",
            "depends_on": ["round-edges"],
        },
    )

    source = compile_geometry_ir(document).source

    assert ".edges().fillet(1)" in source
    assert ".edges().chamfer(1)" in source


@pytest.mark.parametrize("operation", ["linear_pattern", "circular_pattern", "shell", "loft"])
def test_unimplemented_operation_families_fail_closed(operation: str) -> None:
    fields = {
        "operation_id": f"unsupported-{operation}",
        "operation": operation,
        "result_symbol": "body",
    }
    if operation in {"linear_pattern", "circular_pattern"}:
        fields.update({"target": "body", "feature": "body"})
    document = base_ir(primitive_box(), fields)
    document["operations"][1]["depends_on"] = ["make-body"]

    validate_geometry_ir(document)
    with pytest.raises(UnsupportedIROperation, match=operation):
        compile_geometry_ir(document)


def test_raw_escape_keeps_exact_statement_text_and_trace() -> None:
    statement = "body = cq.Workplane('XY').circle(10.25).extrude(3.75)"
    document = base_ir(
        {
            "operation_id": "raw-exact",
            "operation": "raw_cadquery",
            "contract_version": "volundr-geometry-slots-v1",
            "required_inputs": [],
            "required_result_symbol": "body",
            "statements": [statement],
            "result_symbol": "body",
        }
    )

    compiled = compile_geometry_ir(document)

    assert statement in compiled.source
    assert compiled.trace[0]["operation_id"] == "raw-exact"
    assert compiled.supported_operations == ("raw_cadquery",)
