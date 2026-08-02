"""Structured, deterministic CadQuery geometry-body assembly."""

from __future__ import annotations

import ast
import hashlib
import json
import keyword
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
    classify_derived_dependency_findings,
    validate_parameter_effects,
)
from app.services.cad.patterns import pattern_parameter_ids
from app.services.cad.python_symbols import (
    allowed_symbol_inventory,
    analyze_function_symbols,
)


GEOMETRY_BODIES_SCHEMA_VERSION = "cadquery-geometry-bodies-v2"
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
    result_symbols: dict[str, str]
    dependency_findings: list[dict[str, Any]]
    symbol_evidence: dict[str, list[dict[str, Any]]]


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
        entry["symbol_inventory"] = allowed_symbol_inventory(
            signature=entry["signature"],
            parameter_ids=set(parameters),
            scaffold_owned_identifiers=_SCAFFOLD_OWNED_NAMES,
        )
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
        entry["symbol_inventory"] = allowed_symbol_inventory(
            signature=entry["signature"],
            parameter_ids=set(parameters),
            scaffold_owned_identifiers=_SCAFFOLD_OWNED_NAMES,
        )
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
    expected = list(inventory.get("expected_function_ids", []))
    specs = {
        str(spec.get("function_id")): spec
        for spec in inventory.get("functions", [])
        if isinstance(spec, dict) and spec.get("function_id")
    }
    original: dict[str, list[str]] = {}
    canonical: dict[str, list[str]] = {}
    functions: dict[str, str] = {}
    result_symbols: dict[str, str] = {}
    symbol_evidence: dict[str, list[dict[str, Any]]] = {}
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
        statements = record.get("statements")
        if not isinstance(statements, list) or not statements or not all(
            isinstance(line, str) for line in statements
        ):
            raise GeometryBodyError(
                "geometry_body.invalid_json",
                f"Geometry function `{function_id}` must contain non-empty string statements.",
            )
        result_symbol = record.get("result_symbol")
        original[function_id] = list(statements)
        canonical_lines, function_source, function_symbol_evidence = _canonicalize_function(
            function_id=function_id,
            statements=statements,
            result_symbol=result_symbol,
            signature=str(spec.get("signature") or "(params)"),
            allowed_parameters={str(item) for item in inventory.get("allowed_parameters", [])},
            scaffold_owned_identifiers={
                str(item) for item in inventory.get("scaffold_owned_identifiers", [])
            },
        )
        canonical[function_id] = canonical_lines
        functions[function_id] = function_source
        result_symbols[function_id] = str(result_symbol)
        symbol_evidence[function_id] = function_symbol_evidence
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
    contract = dict(inventory.get("parameter_effect_contract", {}))
    dependency_findings = classify_derived_dependency_findings(
        contract,
        source="\n\n".join(ordered_functions.values()),
    )
    blocking_dependency_findings = [
        item for item in dependency_findings if item.get("blocking", item.get("is_blocking", True))
    ]
    if blocking_dependency_findings:
        first = blocking_dependency_findings[0]
        raise GeometryBodyError(
            "geometry_body.derived_dependency_broken",
            str(first.get("message") or "Approved derived-parameter dependency path is invalid."),
            details={"findings": dependency_findings},
        )
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
        result_symbols={function_id: result_symbols[function_id] for function_id in expected},
        dependency_findings=dependency_findings,
        symbol_evidence={function_id: symbol_evidence.get(function_id, []) for function_id in expected},
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


def geometry_body_record_hashes(raw_output: str) -> dict[str, str]:
    """Hash provider records before canonicalization for repair-scope evidence."""

    payload = _parse_payload(raw_output)
    records = payload.get("functions")
    if not isinstance(records, list):
        raise GeometryBodyError(
            "geometry_body.invalid_json",
            "Geometry body response must contain a functions array.",
        )
    hashes: dict[str, str] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("function_id"), str):
            raise GeometryBodyError(
                "geometry_body.invalid_json",
                "Each geometry function must contain a string function_id.",
            )
        function_id = record["function_id"]
        if function_id in hashes:
            raise GeometryBodyError(
                "geometry_body.duplicate_function",
                f"Geometry function `{function_id}` was returned more than once.",
            )
        hashes[function_id] = hashlib.sha256(
            json.dumps(
                {
                    "function_id": function_id,
                    "statements": record.get("statements"),
                    "result_symbol": record.get("result_symbol"),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    return hashes


def validate_geometry_body_repair_scope(
    *,
    original_raw_output: str,
    repaired_raw_output: str,
    affected_function_ids: set[str],
) -> dict[str, Any]:
    """Reject a repair that changes any provider body outside its proven scope."""

    original_hashes = geometry_body_record_hashes(original_raw_output)
    repaired_hashes = geometry_body_record_hashes(repaired_raw_output)
    changed = {
        function_id: {
            "original": original_hashes.get(function_id),
            "repaired": repaired_hashes.get(function_id),
        }
        for function_id in sorted(set(original_hashes) | set(repaired_hashes))
        if function_id not in affected_function_ids
        and original_hashes.get(function_id) != repaired_hashes.get(function_id)
    }
    if changed:
        raise GeometryBodyError(
            "geometry_body.repair_scope_violation",
            "Geometry-body repair changed an unaffected provider function.",
            details={
                "affected_function_ids": sorted(affected_function_ids),
                "changed_unaffected_functions": changed,
                "original_function_hashes": original_hashes,
                "repaired_function_hashes": repaired_hashes,
            },
        )
    return {
        "affected_function_ids": sorted(affected_function_ids),
        "original_function_hashes": original_hashes,
        "repaired_function_hashes": repaired_hashes,
        "changed_unaffected_functions": {},
    }


def _canonicalize_function(
    *,
    function_id: str,
    statements: list[str],
    result_symbol: Any,
    signature: str,
    allowed_parameters: set[str],
    scaffold_owned_identifiers: set[str],
) -> tuple[list[str], str, list[dict[str, Any]]]:
    if not isinstance(result_symbol, str) or not result_symbol.strip():
        raise GeometryBodyError(
            "geometry_body.result_symbol_missing",
            f"Geometry function `{function_id}` must declare a result_symbol.",
        )
    result_symbol = result_symbol.strip()
    if (
        not result_symbol.isidentifier()
        or keyword.iskeyword(result_symbol)
        or result_symbol in scaffold_owned_identifiers
    ):
        raise GeometryBodyError(
            "geometry_body.result_symbol_invalid",
            f"Geometry function `{function_id}` has an invalid or scaffold-owned result_symbol `{result_symbol}`.",
        )
    normalized = "\n".join(line.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4) for line in statements)
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
    if any(isinstance(child, ast.Return) for child in ast.walk(node)):
        raise GeometryBodyError(
            "geometry_body.provider_return_forbidden",
            f"Geometry function `{function_id}` must not contain a provider return statement.",
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
        if isinstance(child, ast.Lambda):
            raise GeometryBodyError(
                "geometry_body.invalid_statement",
                f"Geometry function `{function_id}` cannot declare lambda functions.",
            )
    symbol_analysis = analyze_function_symbols(
        node,
        function_id=function_id,
        parameter_ids=allowed_parameters,
        scaffold_owned_identifiers=scaffold_owned_identifiers,
        source_text=f"def {function_id}{signature}:\n{textwrap.indent(normalized, '    ')}\n",
    )
    if symbol_analysis.findings:
        finding = symbol_analysis.findings[0]
        raise GeometryBodyError(
            str(finding["rule_id"]),
            str(finding.get("message") or "Geometry body contains an invalid Python name."),
            details={
                "function_id": function_id,
                "findings": list(symbol_analysis.findings),
                "symbol_evidence": list(symbol_analysis.classifications),
                "affected_function_id": function_id,
            },
        )
    assignment_status = _result_assignment_status(node.body, result_symbol)
    if assignment_status == "missing":
        raise GeometryBodyError(
            "geometry_body.result_symbol_unassigned",
            f"Geometry function `{function_id}` does not assign result_symbol `{result_symbol}`.",
        )
    if assignment_status != "guaranteed":
        raise GeometryBodyError(
            "geometry_body.result_path_unverifiable",
            f"Geometry function `{function_id}` does not assign result_symbol `{result_symbol}` on every path.",
        )
    if not _result_shape_is_verifiable(node, result_symbol, signature):
        raise GeometryBodyError(
            "geometry_body.result_path_unverifiable",
            f"Geometry function `{function_id}` result_symbol `{result_symbol}` is not statically verifiable as a CadQuery shape.",
        )
    node.body.append(ast.Return(value=ast.Name(id=result_symbol, ctx=ast.Load())))
    canonical_function = ast.unparse(node)
    canonical_body = canonical_function.splitlines()[1:]
    return canonical_body, canonical_function, list(symbol_analysis.classifications)


def _result_assignment_status(statements: list[ast.stmt], symbol: str) -> str:
    """Return guaranteed, uncertain, or missing for a result assignment."""

    guaranteed = False
    saw_symbol = False
    for statement in statements:
        if _assigns_symbol(statement, symbol):
            if isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                guaranteed = True
                saw_symbol = True
                continue
            saw_symbol = True
            return "uncertain"
        if isinstance(statement, ast.If):
            body_status = _result_assignment_status(statement.body, symbol)
            else_status = _result_assignment_status(statement.orelse, symbol) if statement.orelse else "missing"
            if body_status != "missing" or else_status != "missing":
                saw_symbol = True
            if body_status == "guaranteed" and else_status == "guaranteed":
                guaranteed = True
            elif body_status != "missing" or else_status != "missing":
                return "uncertain"
            continue
        if isinstance(statement, (ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith)):
            if _contains_symbol_assignment(statement, symbol):
                return "uncertain"
    if guaranteed:
        return "guaranteed"
    return "uncertain" if saw_symbol else "missing"


def _assigns_symbol(statement: ast.stmt, symbol: str) -> bool:
    targets: list[ast.expr] = []
    if isinstance(statement, ast.Assign):
        targets.extend(statement.targets)
    elif isinstance(statement, (ast.AnnAssign, ast.AugAssign)):
        targets.append(statement.target)
    return any(isinstance(target, ast.Name) and target.id == symbol for target in targets)


def _contains_symbol_assignment(node: ast.AST, symbol: str) -> bool:
    return any(
        isinstance(child, ast.Name)
        and isinstance(child.ctx, ast.Store)
        and child.id == symbol
        for child in ast.walk(node)
    )


def _result_shape_is_verifiable(node: ast.FunctionDef, symbol: str, signature: str) -> bool:
    shape_symbols = {"body"} if signature == "(body, params)" else set()
    for statement in node.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        if not any(isinstance(target, ast.Name) and target.id == symbol for target in targets):
            for target in targets:
                if isinstance(target, ast.Name) and _shape_expression(statement.value, shape_symbols):
                    shape_symbols.add(target.id)
            continue
        if _shape_expression(statement.value, shape_symbols):
            return True
    return False


def _shape_expression(expression: ast.AST, shape_symbols: set[str]) -> bool:
    if isinstance(expression, ast.Name):
        return expression.id in shape_symbols
    if isinstance(expression, ast.Attribute):
        if isinstance(expression.value, ast.Name) and expression.value.id == "cq":
            return expression.attr in {"Workplane", "Shape", "Solid", "Compound", "Assembly"}
        return _shape_expression(expression.value, shape_symbols)
    if isinstance(expression, ast.Call):
        if isinstance(expression.func, ast.Attribute):
            if isinstance(expression.func.value, ast.Name) and expression.func.value.id == "cq":
                return expression.func.attr in {"Workplane", "Shape", "Solid", "Compound", "Assembly"}
            return _shape_expression(expression.func.value, shape_symbols)
        return False
    return False


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
