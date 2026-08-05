"""Experimental semantic geometry IR and deterministic CadQuery compiler.

This module is intentionally outside the production geometry/provider path.
The IR owns a small set of explicit CAD semantics; it is not a translation
layer for arbitrary provider CadQuery.  Unsupported or advanced semantics
fail closed, while an explicitly validated raw-CadQuery operation can remain
the bounded escape path.
"""

from __future__ import annotations

import ast
import json
import math
import re
from dataclasses import dataclass
from typing import Any

from app.services.cad.cadquery_contract import CadQueryContractError, validate_cadquery_source


IR_SCHEMA_ID = "volundr-geometry-ir-experimental-v1"
RAW_CADQUERY_CONTRACT_VERSION = "volundr-geometry-slots-v1"
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_UNITS = frozenset({"mm", "degree", "unitless"})
_EXPRESSION_OPERATORS = frozenset({"+", "-", "*", "/"})


class GeometryIRValidationError(ValueError):
    """The experimental IR is malformed or violates an ownership boundary."""


class UnsupportedIROperation(GeometryIRValidationError):
    """The schema is valid, but this compiler intentionally does not own it."""


@dataclass(frozen=True)
class CompiledGeometryIR:
    source: str
    ordered_operation_ids: tuple[str, ...]
    supported_operations: tuple[str, ...]
    trace: tuple[dict[str, str], ...]


_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "parameters",
        "frames",
        "operations",
        "outputs",
        "revision_obligations",
        "provenance",
    }
)
_COMMON_OPERATION_FIELDS = frozenset(
    {"operation_id", "operation", "target", "result_symbol", "depends_on", "frame"}
)
_OPERATION_FIELDS: dict[str, frozenset[str]] = {
    "primitive": _COMMON_OPERATION_FIELDS | {"primitive_type", "parameters"},
    "profile": _COMMON_OPERATION_FIELDS | {"profile_type", "parameters"},
    "extrude": _COMMON_OPERATION_FIELDS | {"length"},
    "revolve": _COMMON_OPERATION_FIELDS | {"angle"},
    "hole": _COMMON_OPERATION_FIELDS | {"center", "diameter", "depth"},
    "counterbore": _COMMON_OPERATION_FIELDS
    | {"center", "diameter", "counterbore_diameter", "counterbore_depth", "depth"},
    "countersink": _COMMON_OPERATION_FIELDS
    | {"center", "diameter", "countersink_diameter", "countersink_angle", "depth"},
    "slot": _COMMON_OPERATION_FIELDS | {"center", "length", "width", "angle", "depth"},
    "transform": _COMMON_OPERATION_FIELDS | {"translation", "rotation"},
    "fixed_pattern": _COMMON_OPERATION_FIELDS | {"feature", "points"},
    "linear_pattern": _COMMON_OPERATION_FIELDS | {"feature", "count", "spacing", "direction"},
    "circular_pattern": _COMMON_OPERATION_FIELDS | {"feature", "count", "angle", "axis"},
    "union": _COMMON_OPERATION_FIELDS | {"operand", "operands"},
    "cut": _COMMON_OPERATION_FIELDS | {"operand", "operands"},
    "intersection": _COMMON_OPERATION_FIELDS | {"operand", "operands"},
    "fillet": _COMMON_OPERATION_FIELDS | {"radius", "selector"},
    "chamfer": _COMMON_OPERATION_FIELDS | {"length", "selector"},
    "shell": _COMMON_OPERATION_FIELDS | {"thickness", "selector"},
    "loft": _COMMON_OPERATION_FIELDS | {"profiles", "solid"},
    "sweep": _COMMON_OPERATION_FIELDS | {"profile", "path", "transition"},
    "output_assignment": _COMMON_OPERATION_FIELDS | {"source"},
    "raw_cadquery": _COMMON_OPERATION_FIELDS
    | {"contract_version", "required_inputs", "required_result_symbol", "statements"},
}


def _fail(message: str) -> None:
    raise GeometryIRValidationError(message)


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        _fail(f"{field} must be an identifier")
    return value


def _id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        _fail(f"{field} must be an ID")
    return value


def _typed_number(value: Any, field: str, *, unit: str | None = None) -> None:
    if not isinstance(value, dict) or value.get("type") != "number":
        _fail(f"{field} must be a typed number")
    if set(value) != {"type", "value", "unit"}:
        _fail(f"{field} typed number has ambiguous fields")
    raw = value["value"]
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
        _fail(f"{field}.value must be a finite number")
    if value["unit"] not in _UNITS:
        _fail(f"{field}.unit is unsupported")
    if unit is not None and value["unit"] != unit:
        _fail(f"{field} must use unit {unit}")


def _validate_value(value: Any, field: str, parameters: dict[str, Any]) -> None:
    if not isinstance(value, dict) or not isinstance(value.get("type"), str):
        _fail(f"{field} must be a typed number, parameter reference, or expression")
    value_type = value["type"]
    if value_type == "number":
        _typed_number(value, field)
        return
    if value_type == "parameter_ref":
        if set(value) != {"type", "id", "unit"}:
            _fail(f"{field} parameter reference has ambiguous fields")
        parameter_id = _identifier(value["id"], f"{field}.id")
        if parameter_id not in parameters:
            _fail(f"{field} references unknown parameter {parameter_id}")
        if value["unit"] not in _UNITS:
            _fail(f"{field}.unit is unsupported")
        return
    if value_type == "expression":
        if set(value) != {"type", "operator", "operands", "unit"}:
            _fail(f"{field} expression has ambiguous fields")
        if value["operator"] not in _EXPRESSION_OPERATORS:
            _fail(f"{field} expression operator is unsupported")
        operands = value["operands"]
        if not isinstance(operands, list) or len(operands) < 1:
            _fail(f"{field}.operands must be non-empty")
        for index, operand in enumerate(operands):
            _validate_value(operand, f"{field}.operands[{index}]", parameters)
        if value["unit"] not in _UNITS:
            _fail(f"{field}.unit is unsupported")
        return
    _fail(f"{field} has unknown value type {value_type}")


def _validate_vector(value: Any, field: str, parameters: dict[str, Any], *, unit: str) -> None:
    if not isinstance(value, list) or len(value) != 3:
        _fail(f"{field} must contain exactly three typed values")
    for index, item in enumerate(value):
        _validate_value(item, f"{field}[{index}]", parameters)
        if item.get("unit") != unit:
            _fail(f"{field}[{index}] must use unit {unit}")


def _validate_frame(name: str, frame: Any, parameters: dict[str, Any]) -> None:
    if not isinstance(frame, dict):
        _fail(f"frame {name} must be an object")
    if set(frame) != {"origin", "normal", "x_direction", "plane"}:
        _fail(f"frame {name} has ambiguous fields")
    _validate_vector(frame["origin"], f"frame {name}.origin", parameters, unit="mm")
    _validate_vector(frame["normal"], f"frame {name}.normal", parameters, unit="unitless")
    _validate_vector(frame["x_direction"], f"frame {name}.x_direction", parameters, unit="unitless")
    if frame["plane"] not in {"XY", "XZ", "YZ"}:
        _fail(f"frame {name}.plane is not a compiler-owned axis-aligned plane")


def _validate_raw_statements(operation: dict[str, Any], output_symbols: set[str]) -> None:
    statements = operation["statements"]
    if not isinstance(statements, list) or not statements or not all(isinstance(item, str) for item in statements):
        _fail(f"raw_cadquery {operation['operation_id']} statements must be non-empty strings")
    required_result = operation["required_result_symbol"]
    assigned: set[str] = set()
    for statement in statements:
        try:
            tree = ast.parse(statement)
        except SyntaxError as exc:
            _fail(f"raw_cadquery statement is invalid Python: {exc.msg}")
        if len(tree.body) != 1:
            _fail("raw_cadquery statements must contain exactly one statement")
        node = tree.body[0]
        if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            _fail("raw_cadquery statements must be single-name assignments")
        name = node.targets[0].id
        if name in output_symbols and name != required_result:
            _fail("raw_cadquery cannot mutate an unrelated output symbol")
        assigned.add(name)
        if any(isinstance(child, (ast.Import, ast.ImportFrom)) for child in ast.walk(node)):
            _fail("raw_cadquery imports are not allowed")
        if any(isinstance(child, ast.Name) and child.id == "OCP" for child in ast.walk(node)):
            _fail("raw_cadquery direct OCP calls are outside the IR escape contract")
    if required_result not in assigned:
        _fail(f"raw_cadquery must assign its result symbol {required_result}")


def _validate_operation(operation: dict[str, Any], parameters: dict[str, Any], frames: dict[str, Any], output_symbols: set[str]) -> None:
    if not isinstance(operation, dict):
        _fail("each operation must be an object")
    operation_id = _id(operation.get("operation_id"), "operation_id")
    name = operation.get("operation")
    if name not in _OPERATION_FIELDS:
        _fail(f"{operation_id} has unknown operation {name}")
    unknown = set(operation) - _OPERATION_FIELDS[name]
    if unknown:
        _fail(f"{operation_id} has unknown field {sorted(unknown)[0]}")
    _identifier(operation.get("result_symbol"), f"{operation_id}.result_symbol")
    if "target" in operation:
        _identifier(operation["target"], f"{operation_id}.target")
    dependencies = operation.get("depends_on", [])
    if not isinstance(dependencies, list) or not all(isinstance(item, str) for item in dependencies):
        _fail(f"{operation_id}.depends_on must be a list of operation IDs")
    if "frame" in operation:
        frame_name = _identifier(operation["frame"], f"{operation_id}.frame")
        if frame_name not in frames:
            _fail(f"{operation_id} references unknown frame {frame_name}")

    if name == "primitive":
        if operation.get("primitive_type") not in {"box", "cylinder"}:
            _fail(f"{operation_id} primitive type is outside the experimental scope")
        required = {"length", "width", "height"} if operation["primitive_type"] == "box" else {"radius", "height"}
        values = operation.get("parameters")
        if not isinstance(values, dict) or set(values) != required:
            _fail(f"{operation_id}.parameters must contain {sorted(required)}")
        for key, value in values.items():
            _validate_value(value, f"{operation_id}.parameters.{key}", parameters)
    elif name == "profile":
        if operation.get("profile_type") not in {"rectangle", "circle"}:
            _fail(f"{operation_id} profile type is outside the experimental scope")
        required = {"width", "height"} if operation["profile_type"] == "rectangle" else {"radius"}
        values = operation.get("parameters")
        if not isinstance(values, dict) or set(values) != required:
            _fail(f"{operation_id}.parameters must contain {sorted(required)}")
        for key, value in values.items():
            _validate_value(value, f"{operation_id}.parameters.{key}", parameters)
    elif name in {"extrude", "revolve"}:
        field = "length" if name == "extrude" else "angle"
        _identifier(operation.get("target"), f"{operation_id}.target")
        _validate_value(operation.get(field), f"{operation_id}.{field}", parameters)
    elif name in {"hole", "counterbore", "countersink", "slot"}:
        _identifier(operation.get("target"), f"{operation_id}.target")
        _validate_vector(operation.get("center"), f"{operation_id}.center", parameters, unit="mm")
        if name == "hole":
            _validate_value(operation.get("diameter"), f"{operation_id}.diameter", parameters)
        elif name == "counterbore":
            for field in ("diameter", "counterbore_diameter", "counterbore_depth"):
                _validate_value(operation.get(field), f"{operation_id}.{field}", parameters)
        elif name == "countersink":
            for field in ("diameter", "countersink_diameter", "countersink_angle"):
                _validate_value(operation.get(field), f"{operation_id}.{field}", parameters)
        else:
            for field in ("length", "width"):
                _validate_value(operation.get(field), f"{operation_id}.{field}", parameters)
            if "angle" in operation:
                _validate_value(operation["angle"], f"{operation_id}.angle", parameters)
        depth = operation.get("depth")
        if not isinstance(depth, dict) or depth.get("mode") not in {"blind", "through"}:
            _fail(f"{operation_id}.depth must declare blind or through mode")
        if depth["mode"] == "blind":
            _validate_value(depth.get("distance"), f"{operation_id}.depth.distance", parameters)
    elif name == "transform":
        _identifier(operation.get("target"), f"{operation_id}.target")
        if "translation" not in operation and "rotation" not in operation:
            _fail(f"{operation_id} transform must declare translation or rotation")
        if "translation" in operation:
            _validate_vector(operation["translation"], f"{operation_id}.translation", parameters, unit="mm")
        if "rotation" in operation:
            _validate_vector(operation["rotation"], f"{operation_id}.rotation", parameters, unit="degree")
    elif name == "fixed_pattern":
        _identifier(operation.get("target"), f"{operation_id}.target")
        points = operation.get("points")
        if not isinstance(points, list) or not points:
            _fail(f"{operation_id}.points must be a non-empty fixed list")
        for index, item in enumerate(points):
            _validate_vector(item, f"{operation_id}.points[{index}]", parameters, unit="mm")
        feature = operation.get("feature")
        if not isinstance(feature, dict) or feature.get("kind") != "hole":
            _fail(f"{operation_id}.feature must be a semantic hole for the narrow compiler")
        _validate_value(feature.get("diameter"), f"{operation_id}.feature.diameter", parameters)
        depth = feature.get("depth", {"mode": "through"})
        if not isinstance(depth, dict) or depth.get("mode") not in {"blind", "through"}:
            _fail(f"{operation_id}.feature.depth must declare blind or through mode")
    elif name in {"linear_pattern", "circular_pattern"}:
        _identifier(operation.get("target"), f"{operation_id}.target")
        _identifier(operation.get("feature"), f"{operation_id}.feature")
    elif name in {"union", "cut", "intersection"}:
        _identifier(operation.get("target"), f"{operation_id}.target")
        operands = operation.get("operands")
        if operands is None:
            operands = [operation.get("operand")]
        if not isinstance(operands, list) or not operands or not all(isinstance(item, str) for item in operands):
            _fail(f"{operation_id} must name one or more operands")
    elif name in {"fillet", "chamfer"}:
        _identifier(operation.get("target"), f"{operation_id}.target")
        value_field = "radius" if name == "fillet" else "length"
        _validate_value(operation.get(value_field), f"{operation_id}.{value_field}", parameters)
        if operation.get("selector") != "all_edges":
            _fail(f"{operation_id} selector is unsupported; only all_edges is stable")
    elif name == "output_assignment":
        _identifier(operation.get("source"), f"{operation_id}.source")
    elif name == "raw_cadquery":
        if operation.get("contract_version") != RAW_CADQUERY_CONTRACT_VERSION:
            _fail(f"{operation_id} raw escape has the wrong contract version")
        required_inputs = operation.get("required_inputs")
        if not isinstance(required_inputs, list) or not all(isinstance(item, str) for item in required_inputs):
            _fail(f"{operation_id}.required_inputs must be a list")
        _identifier(operation.get("required_result_symbol"), f"{operation_id}.required_result_symbol")
        if operation["required_result_symbol"] != operation["result_symbol"]:
            _fail(f"{operation_id} result_symbol must equal required_result_symbol")
        _validate_raw_statements(operation, output_symbols)


def validate_geometry_ir(document: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(document, dict):
        _fail("IR document must be an object")
    unknown = set(document) - _TOP_LEVEL_FIELDS
    if unknown:
        _fail(f"IR document has unknown field {sorted(unknown)[0]}")
    if document.get("schema_version") != IR_SCHEMA_ID:
        _fail(f"IR document must use {IR_SCHEMA_ID}")
    parameters = document.get("parameters")
    if not isinstance(parameters, dict):
        _fail("parameters must be an object")
    for parameter_id, spec in parameters.items():
        _identifier(parameter_id, "parameter ID")
        if not isinstance(spec, dict) or spec.get("type") != "number":
            _fail(f"parameter {parameter_id} must be a typed number specification")
        allowed = {"type", "unit", "default", "protected", "source_requirement_id"}
        if set(spec) - allowed or not {"type", "unit", "default"}.issubset(spec):
            _fail(f"parameter {parameter_id} has ambiguous fields")
        if spec["unit"] not in _UNITS:
            _fail(f"parameter {parameter_id} has unsupported unit")
        if isinstance(spec["default"], bool) or not isinstance(spec["default"], (int, float)):
            _fail(f"parameter {parameter_id}.default must be numeric")
    frames = document.get("frames")
    if not isinstance(frames, dict) or not frames:
        _fail("frames must be a non-empty object")
    for name, frame in frames.items():
        _identifier(name, "frame ID")
        _validate_frame(name, frame, parameters)
    outputs = document.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        _fail("outputs must be a non-empty list")
    output_symbols: set[str] = set()
    output_ids: set[str] = set()
    for output in outputs:
        if not isinstance(output, dict) or set(output) - {"output_id", "result_symbol", "required", "label"}:
            _fail("output assignment has ambiguous fields")
        output_id = _id(output.get("output_id"), "output_id")
        result_symbol = _identifier(output.get("result_symbol"), f"output {output_id}.result_symbol")
        if output_id in output_ids or result_symbol in output_symbols:
            _fail("output identities and result symbols must be unique")
        output_ids.add(output_id)
        output_symbols.add(result_symbol)
        if not isinstance(output.get("required", True), bool):
            _fail(f"output {output_id}.required must be boolean")
    operations = document.get("operations")
    if not isinstance(operations, list) or not operations:
        _fail("operations must be a non-empty list")
    operation_ids: set[str] = set()
    operation_symbols: set[str] = set()
    for operation in operations:
        operation_id = _id(operation.get("operation_id"), "operation_id") if isinstance(operation, dict) else None
        if operation_id in operation_ids:
            _fail(f"duplicate operation ID {operation_id}")
        if operation_id:
            operation_ids.add(operation_id)
        _validate_operation(operation, parameters, frames, output_symbols)
        operation_symbols.add(operation["result_symbol"])
    for operation in operations:
        for dependency in operation.get("depends_on", []):
            if dependency not in operation_ids:
                _fail(f"{operation['operation_id']} depends on unknown operation {dependency}")
    for output_symbol in output_symbols:
        if output_symbol not in operation_symbols:
            _fail(f"output result symbol {output_symbol} is not produced by an operation")
    revision_obligations = document.get("revision_obligations")
    if not isinstance(revision_obligations, list):
        _fail("revision_obligations must be a list")
    for obligation in revision_obligations:
        if not isinstance(obligation, dict) or obligation.get("kind") not in {"preserve_parameter", "preserve_output", "preserve_operation"}:
            _fail("revision obligation is ambiguous or unsupported")
    provenance = document.get("provenance")
    if not isinstance(provenance, dict) or not provenance.get("requirements") or not provenance.get("plan") or not provenance.get("derivation"):
        _fail("provenance must identify requirements, Plan, and derivation")
    return document


def _render_value(value: dict[str, Any]) -> str:
    value_type = value["type"]
    if value_type == "number":
        return repr(value["value"])
    if value_type == "parameter_ref":
        return f'params[{value["id"]!r}]'
    operator = value["operator"]
    operands = [_render_value(item) for item in value["operands"]]
    if len(operands) == 1:
        return f"({operator}{operands[0]})"
    return "(" + f" {operator} ".join(operands) + ")"


def _render_vector(values: list[dict[str, Any]]) -> str:
    return "(" + ", ".join(_render_value(item) for item in values) + ")"


def _workplane(document: dict[str, Any], frame_name: str | None) -> str:
    frame = document["frames"][frame_name or next(iter(document["frames"]))]
    return f'cq.Workplane("{frame["plane"]}", origin={_render_vector(frame["origin"])})'


def _depth_expression(depth: dict[str, Any], *, fallback: str = "1000.0") -> str:
    return _render_value(depth["distance"]) if depth["mode"] == "blind" else fallback


def _ordered_operations(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {operation["operation_id"]: operation for operation in operations}
    order = {operation["operation_id"]: index for index, operation in enumerate(operations)}
    remaining = set(by_id)
    emitted: list[dict[str, Any]] = []
    while remaining:
        ready = sorted(
            (by_id[operation_id] for operation_id in remaining if set(by_id[operation_id].get("depends_on", [])) <= {item["operation_id"] for item in emitted}),
            key=lambda item: order[item["operation_id"]],
        )
        if not ready:
            raise GeometryIRValidationError("operation dependencies contain a cycle")
        for operation in ready:
            emitted.append(operation)
            remaining.remove(operation["operation_id"])
    return emitted


def _render_output_metadata(document: dict[str, Any]) -> str:
    provenance = {
        "schema_version": document["schema_version"],
        "requirements": document["provenance"]["requirements"],
        "plan": document["provenance"]["plan"],
        "derivation": document["provenance"]["derivation"],
        "revision_obligations": document["revision_obligations"],
    }
    return repr(provenance)


def compile_geometry_ir(document: dict[str, Any]) -> CompiledGeometryIR:
    validate_geometry_ir(document)
    operations = _ordered_operations(document["operations"])
    symbols: dict[str, str] = {}
    lines = [
        "import cadquery as cq",
        "from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product",
        "",
        "PARAMETERS = [",
    ]
    for parameter_id in sorted(document["parameters"]):
        spec = document["parameters"][parameter_id]
        lines.append(
            "    ParameterSpec("
            f"id={parameter_id!r}, label={parameter_id!r}, type='float', "
            f"default={spec['default']!r}, unit={spec['unit']!r}, "
            f"protected={bool(spec.get('protected', False))!r}),"
        )
    lines.extend(["]", "", "def build(params):"])
    trace: list[dict[str, str]] = []
    supported: list[str] = []
    for operation in operations:
        operation_id = operation["operation_id"]
        name = operation["operation"]
        result = operation["result_symbol"]
        lines.append(f"    # volundr-ir: {operation_id} ({name})")
        lines.append(f"    # provenance: {json.dumps(document['provenance'], sort_keys=True)}")
        if name == "primitive":
            wp = _workplane(document, operation.get("frame"))
            values = operation["parameters"]
            if operation["primitive_type"] == "box":
                expression = f"{wp}.box({_render_value(values['length'])}, {_render_value(values['width'])}, {_render_value(values['height'])}, centered=(True, True, False))"
            else:
                expression = f"{wp}.cylinder({_render_value(values['height'])}, {_render_value(values['radius'])}, centered=(True, True, False))"
            lines.append(f"    {result} = {expression}")
        elif name == "profile":
            wp = _workplane(document, operation.get("frame"))
            values = operation["parameters"]
            if operation["profile_type"] == "rectangle":
                expression = f"{wp}.rect({_render_value(values['width'])}, {_render_value(values['height'])})"
            else:
                expression = f"{wp}.circle({_render_value(values['radius'])})"
            lines.append(f"    {result} = {expression}")
        elif name == "extrude":
            lines.append(f"    {result} = {operation['target']}.extrude({_render_value(operation['length'])})")
        elif name == "revolve":
            lines.append(f"    {result} = {operation['target']}.revolve({_render_value(operation['angle'])})")
        elif name in {"hole", "counterbore", "countersink"}:
            center = operation["center"][:2]
            expression = f"{operation['target']}.faces('>Z').workplane().center({_render_value(center[0])}, {_render_value(center[1])} )"
            depth = operation["depth"]
            if name == "hole":
                arguments = f"{_render_value(operation['diameter'])}"
                if depth["mode"] == "blind":
                    arguments += f", depth={_render_value(depth['distance'])}"
                expression += f".hole({arguments})"
            elif name == "counterbore":
                arguments = ", ".join(
                    _render_value(operation[field])
                    for field in ("diameter", "counterbore_diameter", "counterbore_depth")
                )
                if depth["mode"] == "blind":
                    arguments += f", depth={_render_value(depth['distance'])}"
                expression += f".cboreHole({arguments})"
            else:
                arguments = ", ".join(
                    _render_value(operation[field])
                    for field in ("diameter", "countersink_diameter", "countersink_angle")
                )
                if depth["mode"] == "blind":
                    arguments += f", depth={_render_value(depth['distance'])}"
                expression += f".cskHole({arguments})"
            lines.append(f"    {result} = {expression}")
        elif name == "slot":
            wp = _workplane(document, operation.get("frame"))
            center = operation["center"]
            angle = _render_value(operation["angle"]) if "angle" in operation else "0.0"
            cutter = f"{wp}.center({_render_value(center[0])}, {_render_value(center[1])}).slot2D({_render_value(operation['length'])}, {_render_value(operation['width'])}, angle={angle}).extrude({_depth_expression(operation['depth'])})"
            lines.append(f"    {result} = {operation['target']}.cut({cutter})")
        elif name == "transform":
            expression = operation["target"]
            if "translation" in operation:
                expression += f".translate({_render_vector(operation['translation'])})"
            if "rotation" in operation:
                raise UnsupportedIROperation(f"rotation is not yet compiler-owned for {operation_id}")
            lines.append(f"    {result} = {expression}")
        elif name == "fixed_pattern":
            points = "[" + ", ".join(_render_vector(point) for point in operation["points"]) + "]"
            feature = operation["feature"]
            depth = feature.get("depth", {"mode": "through"})
            expression = f"{operation['target']}.faces('>Z').workplane().pushPoints({points}).hole({_render_value(feature['diameter'])}"
            if depth["mode"] == "blind":
                expression += f", depth={_render_value(depth['distance'])}"
            expression += ")"
            lines.append(f"    {result} = {expression}")
        elif name in {"union", "cut", "intersection"}:
            method = {"union": "union", "cut": "cut", "intersection": "intersect"}[name]
            operands = operation.get("operands") or [operation["operand"]]
            expression = operation["target"]
            for operand in operands:
                expression += f".{method}({operand})"
            lines.append(f"    {result} = {expression}")
        elif name in {"fillet", "chamfer"}:
            method = "fillet" if name == "fillet" else "chamfer"
            value = operation["radius"] if name == "fillet" else operation["length"]
            lines.append(f"    {result} = {operation['target']}.edges().{method}({_render_value(value)})")
        elif name == "output_assignment":
            lines.append(f"    {result} = {operation['source']}")
        elif name == "raw_cadquery":
            for statement in operation["statements"]:
                lines.append(f"    {statement}")
            lines.append(f"    {result} = {operation['required_result_symbol']}")
        else:
            raise UnsupportedIROperation(f"{name} is outside the compiler-owned scope")
        symbols[result] = result
        supported.append(name)
        trace.append({"operation_id": operation_id, "operation": name, "result_symbol": result})
    lines.append("    return Product(")
    lines.append("        parameters=PARAMETERS,")
    lines.append("        outputs=[")
    for output in document["outputs"]:
        lines.append(
            "            PrintableOutput("
            f"output_id={json.dumps(output['output_id'])}, "
            f"component_id={json.dumps(output.get('output_id'))}, "
            f"label={output.get('label', output['output_id'])!r}, "
            f"model={output['result_symbol']}, "
            f"required={bool(output.get('required', True))!r}, "
            "expected_solid_count=1, allow_disconnected_solids=False, "
            f"metadata={{'ir_provenance': {_render_output_metadata(document)}}}),"
        )
    lines.extend(
        [
            "        ],",
            f"        metadata={{'ir_schema_version': {IR_SCHEMA_ID!r}, 'ir_provenance': {_render_output_metadata(document)}}},",
            "    )",
        ]
    )
    source = "\n".join(lines) + "\n"
    if "OCP" in source:
        raise GeometryIRValidationError("compiler emitted direct OCP code")
    try:
        validate_cadquery_source(source, contract_version="cadquery-v1")
    except CadQueryContractError as exc:
        raise GeometryIRValidationError(f"compiler emitted invalid CadQuery contract: {exc}") from exc
    return CompiledGeometryIR(
        source=source,
        ordered_operation_ids=tuple(item["operation_id"] for item in operations),
        supported_operations=tuple(supported),
        trace=tuple(trace),
    )


__all__ = [
    "IR_SCHEMA_ID",
    "RAW_CADQUERY_CONTRACT_VERSION",
    "CompiledGeometryIR",
    "GeometryIRValidationError",
    "UnsupportedIROperation",
    "compile_geometry_ir",
    "validate_geometry_ir",
]
