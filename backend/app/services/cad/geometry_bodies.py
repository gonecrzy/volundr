"""Structured, deterministic CadQuery geometry-body assembly."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import textwrap
from dataclasses import dataclass
from typing import Any

from app.services.cad.source_scaffold import (
    ScaffoldSourceError,
    _component_geometry_name,
    _feature_geometry_name,
)
from app.services.cad.parameter_effects import (
    build_parameter_effect_contract,
    validate_parameter_effects,
)
from app.services.cad.patterns import pattern_parameter_ids


GEOMETRY_BODIES_SCHEMA_VERSION = "cadquery-geometry-bodies-v1"
_FENCED_JSON_RE = re.compile(
    r"\A\s*```(?:json)?\s*(?P<payload>.*?)```\s*\Z",
    re.IGNORECASE | re.DOTALL,
)
_DISALLOWED_CALLS = {
    "__import__",
    "compile",
    "eval",
    "exec",
    "getattr",
    "globals",
    "locals",
    "open",
    "setattr",
    "vars",
}
_SCAFFOLD_OWNED_NAMES = {
    "PARAMETERS",
    "Product",
    "PrintableOutput",
    "ParameterSpec",
    "build",
    "component",
    "feature",
    "shared_helper",
    "protected_interface",
}


class GeometryBodyError(ScaffoldSourceError):
    """A deterministic rejection of a structured geometry-body response."""

    def __init__(self, rule_id: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        self.rule_id = rule_id
        self.details = details or {}
        super().__init__(message)


@dataclass(frozen=True)
class GeometryBodyAssembly:
    payload: dict[str, Any]
    functions: dict[str, str]
    original_body_lines: dict[str, list[str]]
    canonical_body_lines: dict[str, list[str]]
    function_body_hashes: dict[str, str]


def build_geometry_function_inventory(plan: dict[str, Any]) -> dict[str, Any]:
    """Build the scaffold-owned function inventory supplied to the provider."""

    parameters = [
        str(parameter["id"])
        for parameter in plan.get("parameters", []) or []
        if isinstance(parameter, dict) and parameter.get("id")
    ]
    parameters.extend(
        str(parameter["id"])
        for parameter in plan.get("derived_parameters", []) or []
        if isinstance(parameter, dict)
        and parameter.get("id")
        and str(parameter["id"]) not in parameters
    )
    parameters.extend(sorted(pattern_parameter_ids(plan) - set(parameters)))
    entries: list[dict[str, Any]] = []
    effect_contract = build_parameter_effect_contract(plan)
    effect_by_function = {
        str(item.get("function_id")): item
        for item in effect_contract.get("functions", [])
        if isinstance(item, dict) and item.get("function_id")
    }
    component_ids = {
        str(component["id"])
        for component in plan.get("components", []) or []
        if isinstance(component, dict) and component.get("id")
    }
    for component in plan.get("components", []) or []:
        if not isinstance(component, dict) or not component.get("id"):
            continue
        component_id = str(component["id"])
        entry = {
                "function_id": _component_geometry_name(component_id),
                "signature": "(params)",
                "owner_component_id": component_id,
                "feature_id": None,
                "required_return": "component_shape",
                "allowed_parameters": parameters,
                "required_parameters": [
                    str(parameter_id)
                    for parameter_id in component.get("parameters", []) or []
                    if parameter_id
                ],
            }
        entry.update(_effect_inventory_fields(effect_by_function.get(entry["function_id"])))
        entries.append(entry)
    for feature in plan.get("features", []) or []:
        if not isinstance(feature, dict) or not feature.get("id"):
            continue
        component_id = str(feature.get("component_id") or "")
        if component_id not in component_ids:
            continue
        entry = {
                "function_id": _feature_geometry_name(str(feature["id"])),
                "signature": "(body, params)",
                "owner_component_id": component_id,
                "feature_id": str(feature["id"]),
                "required_return": "modified_shape",
                "allowed_parameters": parameters,
                "required_parameters": [
                    str(parameter_id)
                    for parameter_id in feature.get("parameters", []) or []
                    if parameter_id
                ],
            }
        entry.update(_effect_inventory_fields(effect_by_function.get(entry["function_id"])))
        entries.append(entry)
    return {
        "schema_version": GEOMETRY_BODIES_SCHEMA_VERSION,
        "functions": entries,
        "expected_function_ids": [entry["function_id"] for entry in entries],
        "allowed_parameters": parameters,
        "parameter_effect_contract": effect_contract,
        "scaffold_owned_identifiers": sorted(
            _SCAFFOLD_OWNED_NAMES
            | {entry["function_id"] for entry in entries}
        ),
    }


def assemble_geometry_bodies(
    raw_output: str,
    inventory: dict[str, Any],
) -> GeometryBodyAssembly:
    """Parse, validate, and canonically assemble provider body statements."""

    payload = _parse_payload(raw_output)
    records = payload.get("functions")
    if not isinstance(records, list) or not records:
        raise GeometryBodyError(
            "geometry_body.invalid_json",
            "Geometry body response must contain a non-empty functions array.",
        )
    dependency_findings = list(inventory.get("parameter_effect_contract", {}).get("dependency_findings", []))
    if dependency_findings:
        raise GeometryBodyError(
            "geometry_body.derived_dependency_broken",
            str(dependency_findings[0].get("message") or "Approved derived-parameter dependency path is invalid."),
            details={"findings": dependency_findings},
        )
    expected = list(inventory.get("expected_function_ids", []))
    specs = {
        str(spec.get("function_id")): spec
        for spec in inventory.get("functions", [])
        if isinstance(spec, dict) and spec.get("function_id")
    }
    original: dict[str, list[str]] = {}
    canonical: dict[str, list[str]] = {}
    functions: dict[str, str] = {}
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("function_id"), str):
            raise GeometryBodyError(
                "geometry_body.invalid_json",
                "Each geometry function must contain a string function_id.",
            )
        function_id = record["function_id"]
        if function_id in seen:
            raise GeometryBodyError(
                "geometry_body.duplicate_function",
                f"Geometry function `{function_id}` was returned more than once.",
            )
        seen.add(function_id)
        spec = specs.get(function_id)
        if spec is None:
            raise GeometryBodyError(
                "geometry_body.unexpected_function",
                f"Unexpected geometry function `{function_id}`.",
            )
        body_lines = record.get("body_lines")
        if not isinstance(body_lines, list) or not body_lines or not all(
            isinstance(line, str) for line in body_lines
        ):
            raise GeometryBodyError(
                "geometry_body.invalid_json",
                f"Geometry function `{function_id}` must contain non-empty string body_lines.",
            )
        original[function_id] = list(body_lines)
        canonical_lines, function_source = _canonicalize_function(
            function_id=function_id,
            body_lines=body_lines,
            signature=str(spec.get("signature") or "(params)"),
            allowed_parameters={str(item) for item in inventory.get("allowed_parameters", [])},
            scaffold_owned_identifiers={
                str(item) for item in inventory.get("scaffold_owned_identifiers", [])
            },
        )
        canonical[function_id] = canonical_lines
        functions[function_id] = function_source
        effect_findings = validate_parameter_effects(
            function_source,
            spec,
            derived_parameters=list(inventory.get("parameter_effect_contract", {}).get("derived_parameters", [])),
            patterns=list(inventory.get("parameter_effect_contract", {}).get("patterns", [])),
        )
        if effect_findings:
            finding = effect_findings[0]
            raise GeometryBodyError(
                str(finding["rule_id"]),
                str(finding.get("message") or "Geometry function parameter effect validation failed."),
                details={"findings": effect_findings, "function_id": function_id},
            )

    missing = [function_id for function_id in expected if function_id not in seen]
    if missing:
        raise GeometryBodyError(
            "geometry_body.missing_function",
            "Missing geometry functions: " + ", ".join(missing),
            details={"missing_function_ids": missing},
        )
    if set(seen) != set(expected):
        raise GeometryBodyError(
            "geometry_body.unexpected_function",
            "Geometry response does not match the required function inventory.",
        )
    ordered_functions = {function_id: functions[function_id] for function_id in expected}
    ordered_original = {function_id: original[function_id] for function_id in expected}
    ordered_canonical = {function_id: canonical[function_id] for function_id in expected}
    return GeometryBodyAssembly(
        payload=payload,
        functions=ordered_functions,
        original_body_lines=ordered_original,
        canonical_body_lines=ordered_canonical,
        function_body_hashes={
            function_id: hashlib.sha256(
                "\n".join(ordered_canonical[function_id]).encode("utf-8")
            ).hexdigest()
            for function_id in expected
        },
    )


def _parse_payload(raw_output: str) -> dict[str, Any]:
    text = raw_output.strip()
    match = _FENCED_JSON_RE.fullmatch(text)
    if match:
        text = match.group("payload").strip()
    elif text.startswith("```") or not text.startswith("{"):
        raise GeometryBodyError(
            "geometry_body.invalid_json",
            "Geometry body response must be JSON only; prose and source wrappers are not allowed.",
        )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GeometryBodyError(
            "geometry_body.invalid_json",
            f"Geometry body response is not valid JSON: {exc.msg}.",
        ) from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != GEOMETRY_BODIES_SCHEMA_VERSION:
        raise GeometryBodyError(
            "geometry_body.invalid_json",
            f"Geometry body response must use schema_version {GEOMETRY_BODIES_SCHEMA_VERSION}.",
        )
    return payload


def _canonicalize_function(
    *,
    function_id: str,
    body_lines: list[str],
    signature: str,
    allowed_parameters: set[str],
    scaffold_owned_identifiers: set[str],
) -> tuple[list[str], str]:
    normalized = "\n".join(line.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4) for line in body_lines)
    normalized = textwrap.dedent(normalized).strip("\n")
    if not normalized.strip():
        raise GeometryBodyError(
            "geometry_body.invalid_statement",
            f"Geometry function `{function_id}` has an empty body.",
        )
    try:
        tree = ast.parse(f"def {function_id}{signature}:\n{textwrap.indent(normalized, '    ')}\n")
    except SyntaxError as exc:
        raise GeometryBodyError(
            "geometry_body.syntax_error",
            f"Geometry function `{function_id}` has invalid syntax: {exc.msg}.",
        ) from exc
    node = tree.body[0]
    if not isinstance(node, ast.FunctionDef):
        raise GeometryBodyError("geometry_body.invalid_statement", "Geometry body did not form a function.")
    if not any(isinstance(child, ast.Return) for child in ast.walk(node)):
        raise GeometryBodyError(
            "geometry_body.missing_return",
            f"Geometry function `{function_id}` must return a shape.",
        )
    for child in ast.walk(node):
        if child is node:
            continue
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)):
            raise GeometryBodyError(
                "geometry_body.invalid_statement",
                f"Geometry function `{function_id}` cannot declare functions, classes, or imports.",
            )
        if isinstance(child, (ast.Global, ast.Nonlocal)):
            raise GeometryBodyError(
                "geometry_body.invalid_statement",
                f"Geometry function `{function_id}` cannot mutate global state.",
            )
        if isinstance(child, ast.Call):
            name = _call_name(child.func)
            if name in _DISALLOWED_CALLS or name in {"system", "popen", "run", "Popen"}:
                raise GeometryBodyError(
                    "geometry_body.invalid_statement",
                    f"Geometry function `{function_id}` contains a prohibited operation.",
                )
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            if child.id in scaffold_owned_identifiers:
                raise GeometryBodyError(
                    "geometry_body.scaffold_mutation_attempt",
                    f"Geometry body cannot redefine scaffold-owned identifier `{child.id}`.",
                )
        if isinstance(child, ast.Subscript) and isinstance(child.value, ast.Name) and child.value.id == "params":
            parameter_id = _string_slice(child.slice)
            if parameter_id is not None and parameter_id not in allowed_parameters:
                raise GeometryBodyError(
                    "geometry_body.undeclared_parameter",
                    f"Geometry body references undeclared parameter `{parameter_id}`.",
                )
        if isinstance(child, ast.Call) and _call_name(child.func) == "get":
            if isinstance(child.func, ast.Attribute) and isinstance(child.func.value, ast.Name) and child.func.value.id == "params":
                if child.args:
                    parameter_id = _string_node(child.args[0])
                    if parameter_id is not None and parameter_id not in allowed_parameters:
                        raise GeometryBodyError(
                            "geometry_body.undeclared_parameter",
                            f"Geometry body references undeclared parameter `{parameter_id}`.",
                        )
    canonical_function = ast.unparse(node)
    canonical_body = canonical_function.splitlines()[1:]
    return canonical_body, canonical_function


def _string_slice(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Index):  # pragma: no cover - Python < 3.9 compatibility
        return _string_node(node.value)
    return None


def _string_node(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _effect_inventory_fields(effect_manifest: dict[str, Any] | None) -> dict[str, Any]:
    if not effect_manifest:
        return {
            "parameter_values": [],
            "required_direct_parameters": [],
            "allowed_derived_parameters": [],
            "required_parameter_effects": [],
            "required_inputs": [],
            "required_patterns": [],
        }
    return {
        "parameter_values": list(effect_manifest.get("parameter_values", [])),
        "required_direct_parameters": list(effect_manifest.get("required_direct_parameters", [])),
        "allowed_derived_parameters": list(effect_manifest.get("allowed_derived_parameters", [])),
        "required_parameter_effects": list(effect_manifest.get("required_parameter_effects", [])),
        "required_inputs": list(effect_manifest.get("required_inputs", [])),
        "required_patterns": list(effect_manifest.get("required_patterns", [])),
    }
