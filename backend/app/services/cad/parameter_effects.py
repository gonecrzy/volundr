"""Deterministic parameter-effect contracts for CadQuery geometry functions."""

from __future__ import annotations

import ast
import math
import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from app.services.cad.patterns import (
    build_pattern_manifest,
    exposed_control_ids,
    layout_requires_pattern_effect,
    parameter_requires_effect,
)
PARAMETER_EFFECT_CONTRACT_VERSION = "cadquery-parameter-effects-v1"
PROVENANCE_VERSION = "design-plan-provenance-v1"
DERIVED_DEPENDENCY_CLASSIFICATION_VERSION = "derived-dependency-classification-v1"
SUPPORTED_EFFECT_TYPES = {
    "dimension",
    "diameter",
    "radius_or_diameter",
    "pattern_count",
    "pattern_spacing",
    "translation",
    "rotation",
    "thickness",
    "feature_toggle",
    "boolean_tool_size",
}

_GEOMETRY_METHODS = {
    "box",
    "chamfer",
    "circle",
    "cut",
    "cylinder",
    "extrude",
    "fillet",
    "hole",
    "loft",
    "mirror",
    "polygon",
    "pushPoints",
    "rect",
    "revolve",
    "rotate",
    "rotateAbout",
    "translate",
    "union",
    "workplane",
}
_PATTERN_METHODS = {"hole", "pushPoints", "polarArray", "rarray", "each", "cut", "union"}
_APPROVED_HELPER_RE = re.compile(
    r"(?:pattern|hole|point|position|mount|standoff|fastener|array)", re.IGNORECASE
)
_PARAMETER_ID_RE = re.compile(r"[A-Za-z_]\w*")


def build_parameter_effect_contract(
    plan: dict[str, Any],
    *,
    source_authority: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a stable manifest without changing the approved Design Plan."""

    parameters = _parameter_entries(plan, source_authority)
    parameter_by_id = {item["id"]: item for item in parameters}
    derived_ids = [
        str(item["id"])
        for item in _derived_entries(plan, source_authority)
        if item.get("id")
    ]
    dependencies = _dependency_graph(plan, parameter_by_id, derived_ids)
    resolved_values = _resolved_values(parameters, dependencies)
    derived_manifest = []
    for item in _derived_entries(plan, source_authority):
        parameter_id = str(item.get("id") or "")
        if not parameter_id:
            continue
        provenance = item.get("provenance") if isinstance(item.get("provenance"), dict) else {}
        derived_manifest.append(
            {
                "parameter_id": parameter_id,
                "expression": str(item.get("expression") or provenance.get("expression") or ""),
                "direct_dependencies": sorted(dependencies.get(parameter_id, set())),
                "transitive_protected_dependencies": sorted(
                    _protected_ancestors(parameter_id, dependencies, parameter_by_id)
                ),
                "resolved_value": resolved_values.get(parameter_id, item.get("value")),
                "provenance_version": str(
                    provenance.get("validator_version") or PROVENANCE_VERSION
                ),
            }
        )

    modern_control_contract = "exposed_controls" in plan
    control_ids = exposed_control_ids(plan) if modern_control_contract else None
    effect_required_ids: set[str] | None = None
    if control_ids is not None:
        effect_required_ids = set(control_ids)
        for item in derived_manifest:
            if (
                str(item.get("parameter_id") or "") in control_ids
                or set(item.get("transitive_protected_dependencies", [])) & control_ids
            ):
                effect_required_ids.add(str(item["parameter_id"]))
    pattern_manifest = build_pattern_manifest(plan)
    functions = _function_manifests(
        plan,
        parameter_by_id=parameter_by_id,
        dependencies=dependencies,
        derived_manifest=derived_manifest,
        patterns=pattern_manifest,
        effect_required_ids=effect_required_ids,
    )
    contract = {
        "schema_version": PARAMETER_EFFECT_CONTRACT_VERSION,
        "parametric_validation_active": effect_required_ids is None or bool(effect_required_ids),
        "exposed_control_ids": sorted(control_ids or set()),
        "parameter_modes": {
            item["id"]: str(item.get("constraint_mode") or "legacy_unclassified")
            for item in parameters
            if item.get("id")
        },
        "derived_parameters": derived_manifest,
        "patterns": pattern_manifest,
        "feature_layouts": [
            item for item in plan.get("feature_layouts", []) or [] if isinstance(item, dict)
        ],
        "functions": functions,
        "dependency_findings": _dependency_findings(plan, parameter_by_id),
    }
    contract["dependency_findings"] = classify_derived_dependency_findings(contract)
    return contract


def classify_derived_dependency_findings(
    contract: dict[str, Any],
    *,
    source: str | None = None,
) -> list[dict[str, Any]]:
    """Classify broken derived metadata by its actual execution relevance.

    Planning metadata is intentionally retained even when it is not part of
    the executable contract.  The geometry assembly and source-authority
    layers may call this function again with the assembled source so a value
    that is actually consumed becomes blocking.
    """

    derived = [
        item for item in contract.get("derived_parameters", []) or []
        if isinstance(item, dict) and item.get("parameter_id")
    ]
    derived_ids = {str(item["parameter_id"]) for item in derived}
    dependencies = {
        str(item["parameter_id"]): {
            str(value) for value in item.get("direct_dependencies", []) or [] if value
        }
        for item in derived
    }
    exposed_ids = {
        str(value) for value in contract.get("exposed_control_ids", []) or [] if value
    }
    source_references = _source_parameter_references(source)
    function_required_ids = _required_contract_parameter_ids(contract.get("functions", []))
    pattern_required_ids = _required_pattern_parameter_ids(contract.get("patterns", []))

    classified: list[dict[str, Any]] = []
    for raw in _dependency_findings_from_contract(contract):
        finding = deepcopy(raw)
        parameter_id = str(finding.get("parameter_id") or "")
        reasons: list[str] = []

        if parameter_id in exposed_ids:
            reasons.append("exposed_control")
        if any(control_id in _dependency_ancestors(parameter_id, dependencies) for control_id in exposed_ids):
            reasons.append("supports_exposed_control")
        if parameter_id in pattern_required_ids:
            reasons.append("required_by_configurable_pattern")
        if any(
            parameter_id in _dependency_ancestors(required_id, dependencies)
            for required_id in pattern_required_ids | function_required_ids
        ):
            reasons.append("supports_required_geometry_contract")
        if parameter_id in function_required_ids:
            reasons.append("required_by_geometry_function")
        if parameter_id in source_references:
            reasons.append("referenced_by_geometry")
        if any(
            parameter_id in _dependency_ancestors(referenced_id, dependencies)
            for referenced_id in source_references & derived_ids
        ):
            reasons.append("supports_referenced_geometry")

        blocking = bool(reasons)
        finding.update(
            {
                "classification_version": DERIVED_DEPENDENCY_CLASSIFICATION_VERSION,
                "dependency_status": "broken",
                "blocking": blocking,
                "classification": "blocking_required" if blocking else "diagnostic_only",
                "reasons": list(dict.fromkeys(reasons))
                or [
                    "not_exposed",
                    "not_referenced_by_geometry",
                    "not_required_by_scaffold",
                ],
                "is_blocking": blocking,
                "severity": "critical" if blocking else "warning",
                "category": "geometry_body" if blocking else "planning",
                "rule_id": (
                    "geometry_body.derived_dependency_broken"
                    if blocking
                    else "planning.derived_dependency_unused_or_incomplete"
                ),
            }
        )
        if not blocking:
            finding["message"] = (
                str(raw.get("message") or "Derived parameter metadata is incomplete.")
                + " It is retained as diagnostic evidence because it is not required by the executable geometry contract."
            )
        classified.append(finding)
    return classified


def _dependency_findings_from_contract(contract: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in contract.get("dependency_findings", []) or []
        if isinstance(item, dict)
    ]


def _dependency_ancestors(parameter_id: str, dependencies: dict[str, set[str]]) -> set[str]:
    ancestors: set[str] = set()
    visiting: set[str] = set()

    def visit(current: str) -> None:
        if current in visiting:
            return
        visiting.add(current)
        for dependency in dependencies.get(current, set()):
            if dependency in ancestors:
                continue
            ancestors.add(dependency)
            visit(dependency)
        visiting.remove(current)

    visit(parameter_id)
    return ancestors


def _required_contract_parameter_ids(functions: list[dict[str, Any]] | None) -> set[str]:
    required: set[str] = set()
    for function in functions or []:
        if not isinstance(function, dict):
            continue
        for item in function.get("required_parameter_effects", []) or []:
            if not isinstance(item, dict):
                continue
            if item.get("parameter_id"):
                required.add(str(item["parameter_id"]))
            required.update(str(value) for value in item.get("allowed_via", []) or [] if value)
        required.update(str(value) for value in function.get("required_patterns", []) or [] if value)
    return required


def _required_pattern_parameter_ids(patterns: list[dict[str, Any]] | None) -> set[str]:
    required: set[str] = set()
    for pattern in patterns or []:
        if not isinstance(pattern, dict) or not pattern.get("effect_required"):
            continue
        if pattern.get("point_parameter_id"):
            required.add(str(pattern["point_parameter_id"]))
        for item in pattern.get("required_parameter_effects", []) or []:
            if not isinstance(item, dict):
                continue
            if item.get("parameter_id"):
                required.add(str(item["parameter_id"]))
            required.update(str(value) for value in item.get("allowed_via", []) or [] if value)
    return required


def _source_parameter_references(source: str | None) -> set[str]:
    if not source:
        return set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    references: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "params":
            parameter_id = _string_subscript(node.slice)
            if parameter_id:
                references.add(parameter_id)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "params"
            and node.func.attr == "get"
            and node.args
        ):
            parameter_id = _string_subscript(node.args[0])
            if parameter_id:
                references.add(parameter_id)
    return references


def _string_subscript(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def validate_parameter_effects(
    source: str,
    function_manifest: dict[str, Any],
    *,
    derived_parameters: list[dict[str, Any]] | None = None,
    patterns: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return blocking findings when a function bypasses an obligation."""

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [_finding("geometry_body.effect_unverifiable", function_manifest, f"AST proof failed: {exc.msg}.")]
    function = next((node for node in tree.body if isinstance(node, ast.FunctionDef)), None)
    if function is None:
        function = next((node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)), None)
    if function is None:
        return [_finding("geometry_body.effect_unverifiable", function_manifest, "No function AST was available for effect validation.")]

    required_patterns = [
        pattern
        for pattern in patterns or []
        if isinstance(pattern, dict)
        and str(pattern.get("pattern_id") or "") in {
            str(item) for item in function_manifest.get("required_patterns", []) or []
        }
    ]
    analysis = _analyze(
        function,
        canonical_pattern_parameter_ids={
            str(pattern.get("point_parameter_id"))
            for pattern in required_patterns
            if pattern.get("point_parameter_id")
        },
    )
    derived_values = {
        str(item.get("parameter_id")): item.get("resolved_value")
        for item in derived_parameters or []
        if isinstance(item, dict) and item.get("parameter_id")
    }
    findings: list[dict[str, Any]] = []
    for pattern in required_patterns:
        point_id = str(pattern.get("point_parameter_id") or "")
        pattern_id = str(pattern.get("pattern_id") or "")
        usage = analysis.pattern_point_usage.get(point_id, set())
        if "truncated" in usage:
            findings.append(
                _finding(
                    "pattern.cardinality_mismatch",
                    function_manifest,
                    f"Canonical pattern `{pattern_id}` was sliced or truncated before geometry use.",
                    pattern_id=pattern_id,
                )
            )
            continue
        if "override" in usage:
            findings.append(
                _finding(
                    "pattern.provider_pattern_override",
                    function_manifest,
                    f"Provider geometry replaced canonical pattern `{pattern_id}` with its own point construction.",
                    pattern_id=pattern_id,
                )
            )
            continue
        if "canonical" not in usage:
            findings.append(
                _finding(
                    "pattern.required_pattern_unused",
                    function_manifest,
                    f"Required canonical pattern `{pattern_id}` does not reach the repeated geometry operation.",
                    pattern_id=pattern_id,
                )
            )
    if findings:
        return findings
    for obligation in function_manifest.get("required_parameter_effects", []) or []:
        if not isinstance(obligation, dict) or not obligation.get("parameter_id"):
            continue
        parameter_id = str(obligation["parameter_id"])
        effect_type = str(obligation.get("effect_type") or "dimension")
        allowed_via = [str(item) for item in obligation.get("allowed_via", []) or []]
        candidates = {parameter_id, *allowed_via}
        has_effect = _has_effect(analysis, candidates, effect_type)
        if has_effect:
            continue

        numeric_values = [
            value
            for candidate in (parameter_id, *allowed_via)
            for value in [_parameter_value(candidate, function_manifest, derived_values)]
            if isinstance(value, int | float) and not isinstance(value, bool)
        ]
        if effect_type == "pattern_count":
            if _hardcoded_pattern_count(analysis, numeric_values):
                findings.append(
                    _finding(
                        "geometry_body.pattern_count_hardcoded",
                        function_manifest,
                        f"Pattern count `{parameter_id}` is bypassed by a fixed range, point list, or repeated geometry calls.",
                        obligation=obligation,
                    )
                )
            else:
                findings.append(
                    _finding(
                        "geometry_body.effect_unverifiable",
                        function_manifest,
                        f"Pattern count `{parameter_id}` does not have a statically verifiable geometry effect.",
                        obligation=obligation,
                    )
                )
            continue
        if effect_type == "pattern_spacing" and _hardcoded_pattern_spacing(analysis, numeric_values):
            findings.append(
                _finding(
                    "geometry_body.pattern_spacing_hardcoded",
                    function_manifest,
                    f"Pattern spacing `{parameter_id}` is represented by fixed point geometry.",
                    obligation=obligation,
                )
            )
            continue
        if effect_type in {"dimension", "diameter", "radius_or_diameter", "thickness", "boolean_tool_size"} and _hardcoded_dimension(
            analysis, numeric_values
        ):
            findings.append(
                _finding(
                    "geometry_body.dimension_bypassed_by_literal",
                    function_manifest,
                    f"Parameter `{parameter_id}` is bypassed by a literal matching an approved value.",
                    obligation=obligation,
                )
            )
            continue
        findings.append(
            _finding(
                "geometry_body.required_effect_missing",
                function_manifest,
                f"Required {effect_type} effect for `{parameter_id}` is missing from this function.",
                obligation=obligation,
            )
        )
    return findings


def _parameter_entries(
    plan: dict[str, Any], source_authority: dict[str, Any] | None
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for collection in (plan.get("parameters", []), plan.get("derived_parameters", [])):
        entries.extend(item for item in collection or [] if isinstance(item, dict) and item.get("id"))
    if source_authority:
        known = {str(item.get("id")) for item in entries}
        for item in source_authority.get("parameters", []) or []:
            if isinstance(item, dict) and item.get("id") and str(item["id"]) not in known:
                entries.append(deepcopy(item))
    return entries


def _derived_entries(plan: dict[str, Any], source_authority: dict[str, Any] | None) -> list[dict[str, Any]]:
    entries = [item for item in plan.get("derived_parameters", []) or [] if isinstance(item, dict) and item.get("id")]
    for item in plan.get("parameters", []) or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        provenance = item.get("provenance")
        if isinstance(provenance, dict) and provenance.get("relationship") in {"derived_formula", "calculated"}:
            if not any(str(existing.get("id")) == str(item["id"]) for existing in entries):
                entries.append(item)
    if source_authority:
        known = {str(item.get("id")) for item in entries}
        for item in source_authority.get("parameters", []) or []:
            if not isinstance(item, dict) or not item.get("id") or str(item["id"]) in known:
                continue
            provenance = item.get("provenance")
            if isinstance(provenance, dict) and provenance.get("relationship") in {"derived_formula", "calculated"}:
                entries.append(item)
    return entries


def _dependency_graph(
    plan: dict[str, Any], parameter_by_id: dict[str, dict[str, Any]], derived_ids: list[str]
) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {parameter_id: set() for parameter_id in derived_ids}
    declared_ids = set(parameter_by_id)
    for item in _derived_entries(plan, None):
        parameter_id = str(item.get("id") or "")
        if parameter_id not in graph:
            continue
        provenance = item.get("provenance") if isinstance(item.get("provenance"), dict) else {}
        values = [
            *(str(value) for value in item.get("depends_on", []) or [] if value),
            *(str(value) for value in provenance.get("source_parameter_ids", []) or [] if value),
            *(str(value) for value in provenance.get("source_requirement_ids", []) or [] if value),
        ]
        expression = item.get("expression") or provenance.get("expression")
        if isinstance(expression, str):
            values.extend(_expression_symbols(expression))
        graph[parameter_id].update(
            resolved
            for value in values
            for resolved in [_resolve_dependency_id(value, parameter_by_id)]
            if resolved in declared_ids
        )
    for edge in plan.get("dependency_edges", []) or []:
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("from") or edge.get("from_") or "")
        target = str(edge.get("to") or "")
        if target in graph and source in declared_ids:
            graph[target].add(source)
    return graph


def _resolved_values(parameters: list[dict[str, Any]], dependencies: dict[str, set[str]]) -> dict[str, Any]:
    derived_ids = set(dependencies)
    values: dict[str, Any] = {}
    for item in parameters:
        parameter_id = str(item.get("id") or "")
        if not parameter_id or item.get("value") is None:
            continue
        provenance = item.get("provenance") if isinstance(item.get("provenance"), dict) else {}
        expression = item.get("expression") or provenance.get("expression")
        if parameter_id in derived_ids and isinstance(expression, str):
            continue
        values[parameter_id] = item.get("value")
    for item in parameters:
        provenance = item.get("provenance") if isinstance(item.get("provenance"), dict) else {}
        if item.get("id") and provenance.get("resolved_result") is not None:
            values[str(item["id"])] = provenance["resolved_result"]
    for _ in range(max(1, len(dependencies))):
        changed = False
        for item in parameters:
            parameter_id = str(item.get("id") or "")
            if parameter_id not in dependencies or parameter_id in values:
                continue
            expression = item.get("expression")
            provenance = item.get("provenance") if isinstance(item.get("provenance"), dict) else {}
            expression = expression or provenance.get("expression")
            if not isinstance(expression, str):
                continue
            try:
                value = _safe_eval(expression, values)
            except (ValueError, KeyError, ZeroDivisionError):
                continue
            values[parameter_id] = value
            changed = True
        if not changed:
            break
    return values


def _dependency_findings(
    plan: dict[str, Any], parameter_by_id: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    declared_ids = set(parameter_by_id)
    findings: list[dict[str, Any]] = []
    for item in _derived_entries(plan, None):
        parameter_id = str(item.get("id") or "")
        provenance = item.get("provenance") if isinstance(item.get("provenance"), dict) else {}
        declared_raw = {
            *(str(value) for value in item.get("depends_on", []) or [] if value),
            *(str(value) for value in provenance.get("source_parameter_ids", []) or [] if value),
            *(str(value) for value in provenance.get("source_requirement_ids", []) or [] if value),
        }
        declared = {
            _resolve_dependency_id(value, parameter_by_id)
            for value in declared_raw
        }
        expression = item.get("expression") or provenance.get("expression")
        symbols = _expression_symbols(expression) if isinstance(expression, str) else set()
        unresolved_declared = sorted(value for value in declared if value not in declared_ids)
        missing = sorted(set(unresolved_declared) | (symbols - declared_ids))
        undeclared_symbols = sorted(symbols - declared)
        if missing or undeclared_symbols:
            findings.append(
                {
                    "rule_id": "geometry_body.derived_dependency_broken",
                    "category": "geometry_body",
                    "severity": "critical",
                    "is_blocking": True,
                    "parameter_id": parameter_id,
                    "missing_dependencies": missing,
                    "undeclared_expression_dependencies": undeclared_symbols,
                    "message": f"Derived parameter `{parameter_id}` has an incomplete approved dependency path.",
                }
            )
    graph = _dependency_graph(plan, parameter_by_id, [str(item.get("id")) for item in _derived_entries(plan, None)])
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(parameter_id: str) -> None:
        if parameter_id in visiting:
            findings.append(
                {
                    "rule_id": "geometry_body.derived_dependency_broken",
                    "category": "geometry_body",
                    "severity": "critical",
                    "is_blocking": True,
                    "parameter_id": parameter_id,
                    "message": f"Derived parameter dependency cycle includes `{parameter_id}`.",
                }
            )
            return
        if parameter_id in visited:
            return
        visiting.add(parameter_id)
        for dependency in graph.get(parameter_id, set()):
            if dependency in graph:
                visit(dependency)
        visiting.remove(parameter_id)
        visited.add(parameter_id)

    for parameter_id in graph:
        visit(parameter_id)
    return findings


def _resolve_dependency_id(value: str, parameter_by_id: dict[str, dict[str, Any]]) -> str:
    if value in parameter_by_id:
        return value
    for parameter_id, parameter in parameter_by_id.items():
        if str(parameter.get("source_requirement_id") or "") == value:
            return parameter_id
    return value


def _protected_ancestors(
    parameter_id: str,
    dependencies: dict[str, set[str]],
    parameter_by_id: dict[str, dict[str, Any]],
) -> set[str]:
    protected: set[str] = set()
    visiting: set[str] = set()

    def walk(current: str) -> None:
        if current in visiting:
            return
        visiting.add(current)
        for dependency in dependencies.get(current, set()):
            entry = parameter_by_id.get(dependency, {})
            if entry.get("protected"):
                protected.add(dependency)
            if dependency in dependencies:
                walk(dependency)
        visiting.remove(current)

    walk(parameter_id)
    return protected


def _function_manifests(
    plan: dict[str, Any],
    *,
    parameter_by_id: dict[str, dict[str, Any]],
    dependencies: dict[str, set[str]],
    derived_manifest: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
    effect_required_ids: set[str] | None,
) -> list[dict[str, Any]]:
    derived_by_id = {item["parameter_id"]: item for item in derived_manifest}
    functional_ids = _functional_parameter_ids(plan, parameter_by_id)
    manifests: list[dict[str, Any]] = []
    components = [item for item in plan.get("components", []) or [] if isinstance(item, dict) and item.get("id")]
    features = [item for item in plan.get("features", []) or [] if isinstance(item, dict) and item.get("id")]
    for component in components:
        component_id = str(component["id"])
        ids = [str(item) for item in component.get("parameters", []) or [] if str(item) in parameter_by_id]
        ids.extend(functional_ids.get(component_id, set()))
        manifests.append(_function_manifest(_component_function_id(component_id), component_id, None, ids, parameter_by_id, dependencies, derived_by_id, patterns=patterns, effect_required_ids=effect_required_ids))
    component_ids = {str(item.get("id")) for item in components}
    for feature in features:
        component_id = str(feature.get("component_id") or "")
        if component_id not in component_ids:
            continue
        feature_id = str(feature["id"])
        ids = [str(item) for item in feature.get("parameters", []) or [] if str(item) in parameter_by_id]
        for pattern in patterns:
            if not isinstance(pattern, dict) or str(pattern.get("owning_feature_id") or "") != feature_id:
                continue
            if not bool(pattern.get("effect_required", True)):
                continue
            for key in (
                "count_parameter_id",
                "spacing_parameter_id",
                "rows_parameter_id",
                "columns_parameter_id",
                "row_spacing_parameter_id",
                "column_spacing_parameter_id",
                "radius_parameter_id",
            ):
                parameter_id = str(pattern.get("specification", pattern).get(key) or "")
                if parameter_id and parameter_id in parameter_by_id:
                    ids.append(parameter_id)
        ids.extend(functional_ids.get(feature_id, set()))
        manifests.append(_function_manifest(_feature_function_id(feature_id), component_id, feature_id, ids, parameter_by_id, dependencies, derived_by_id, feature=feature, patterns=patterns, effect_required_ids=effect_required_ids))
    return manifests


def _function_manifest(
    function_id: str,
    component_id: str,
    feature_id: str | None,
    ids: list[str] | set[str],
    parameter_by_id: dict[str, dict[str, Any]],
    dependencies: dict[str, set[str]],
    derived_by_id: dict[str, dict[str, Any]],
    *,
    feature: dict[str, Any] | None = None,
    patterns: list[dict[str, Any]] | None = None,
    effect_required_ids: set[str] | None = None,
) -> dict[str, Any]:
    selected = set(ids)
    obligations: dict[str, dict[str, Any]] = {}
    for selected_id in selected:
        if selected_id not in parameter_by_id:
            continue
        entry = parameter_by_id[selected_id]
        ancestors = _protected_ancestors(selected_id, dependencies, parameter_by_id)
        selected_is_derived = selected_id in derived_by_id or str(entry.get("constraint_mode") or "") == "derived_parameter"
        if effect_required_ids is not None:
            if selected_id in effect_required_ids:
                obligations[selected_id] = {
                    "parameter_id": selected_id,
                    "allowed_via": [],
                    "effect_type": _effect_type(selected_id, feature),
                }
                for parameter_id in ancestors & effect_required_ids:
                    via = [
                        item["parameter_id"]
                        for item in derived_by_id.values()
                        if parameter_id in item.get("transitive_protected_dependencies", [])
                    ]
                    obligations[parameter_id] = {
                        "parameter_id": parameter_id,
                        "allowed_via": via,
                        "effect_type": _effect_type(parameter_id, feature),
                    }
            continue
        explicit_modes = any(
            isinstance(item, dict) and item.get("constraint_mode")
            for item in parameter_by_id.values()
        )
        if ancestors and selected_is_derived and explicit_modes:
            obligations[selected_id] = {
                "parameter_id": selected_id,
                "allowed_via": [],
                "effect_type": _effect_type(selected_id, feature),
            }
            for parameter_id in ancestors:
                if not parameter_requires_effect(parameter_by_id.get(parameter_id, {}), legacy_default=True):
                    continue
                via = [
                    item["parameter_id"]
                    for item in derived_by_id.values()
                    if parameter_id in item.get("transitive_protected_dependencies", [])
                ]
                obligations[parameter_id] = {
                    "parameter_id": parameter_id,
                    "allowed_via": via,
                    "effect_type": _effect_type(parameter_id, feature),
                }
        elif ancestors and selected_is_derived:
            for parameter_id in ancestors:
                via = [
                    item["parameter_id"]
                    for item in derived_by_id.values()
                    if parameter_id in item.get("transitive_protected_dependencies", [])
                ]
                obligations[parameter_id] = {
                    "parameter_id": parameter_id,
                    "allowed_via": via,
                    "effect_type": _effect_type(parameter_id, feature),
                }
        elif parameter_requires_effect(entry, legacy_default=True):
            obligations[selected_id] = {
                "parameter_id": selected_id,
                "allowed_via": [],
                "effect_type": _effect_type(selected_id, feature),
            }
    owned_patterns = [
        pattern
        for pattern in patterns or []
        if feature_id and str(pattern.get("owning_feature_id")) == feature_id
    ]
    required_patterns = [
        pattern for pattern in owned_patterns
        if bool(pattern.get("effect_required", True))
    ]
    for pattern in required_patterns:
        point_id = str(pattern.get("point_parameter_id") or "")
        for pattern_effect in pattern.get("required_parameter_effects", []) or []:
            parameter_id = pattern_effect.get("parameter_id") if isinstance(pattern_effect, dict) else None
            if not parameter_id or str(parameter_id) not in obligations:
                continue
            obligation = obligations[str(parameter_id)]
            obligation["allowed_via"] = sorted(set(obligation.get("allowed_via", [])) | {point_id})
    effect_priority = {
        "pattern_count": 0,
        "pattern_spacing": 1,
    }
    ordered = sorted(
        obligations.values(),
        key=lambda item: (effect_priority.get(item["effect_type"], 2), item["parameter_id"]),
    )
    allowed_derived = sorted({via for item in ordered for via in item["allowed_via"]})
    return {
        "function_id": function_id,
        "owner_component_id": component_id,
        "feature_id": feature_id,
        "parameter_values": [
            {"id": parameter_id, "value": parameter_by_id[parameter_id].get("value")}
            for parameter_id in sorted(selected)
            if parameter_id in parameter_by_id
        ],
        "required_direct_parameters": [item["parameter_id"] for item in ordered],
        "allowed_derived_parameters": allowed_derived,
        "required_inputs": sorted({
            *selected,
            *(str(pattern.get("point_parameter_id")) for pattern in required_patterns if pattern.get("point_parameter_id")),
        }),
        "required_patterns": [str(pattern["pattern_id"]) for pattern in required_patterns],
        "required_parameter_effects": ordered,
    }


def _functional_parameter_ids(
    plan: dict[str, Any], parameter_by_id: dict[str, dict[str, Any]]
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    contract = plan.get("functional_contract")
    if not isinstance(contract, dict):
        return result
    parameter_ids = set(parameter_by_id)
    for collection in ("mounting_interfaces", "support_interfaces", "containment_interfaces", "retention_interfaces"):
        for interface in contract.get(collection, []) or []:
            if not isinstance(interface, dict):
                continue
            owner = str(interface.get("feature_id") or interface.get("component_id") or "")
            if not owner:
                continue
            found = _strings_matching_ids(interface, parameter_ids)
            if interface.get("fastener_count") is not None:
                found.update(item for item in parameter_ids if item.endswith("_count") and any(token in item for token in ("mount", "screw", "fastener", "hole")))
            if interface.get("spacing") is not None and str(interface.get("layout_mode") or "") in {
                "parameterized_positions",
                "uniform_linear",
                "rectangular_grid",
                "circular",
            }:
                found.update(item for item in parameter_ids if "spacing" in item)
            if interface.get("bottom_support_required"):
                found.update(item for item in parameter_ids if "thickness" in item or "floor" in item)
            result.setdefault(owner, set()).update(found)
    return result


def _strings_matching_ids(value: Any, parameter_ids: set[str]) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for child in value.values():
            found.update(_strings_matching_ids(child, parameter_ids))
    elif isinstance(value, list):
        for child in value:
            found.update(_strings_matching_ids(child, parameter_ids))
    elif isinstance(value, str) and value in parameter_ids:
        found.add(value)
    return found


def _effect_type(parameter_id: str, feature: dict[str, Any] | None) -> str:
    normalized = parameter_id.lower()
    feature_text = " ".join(str(feature.get(key) or "") for key in ("id", "type", "description")) if feature else ""
    if normalized.endswith("_count") or normalized in {"count", "quantity"}:
        return "pattern_count"
    if "spacing" in normalized or "pitch" in normalized or "spacing" in feature_text.lower():
        return "pattern_spacing"
    if any(token in normalized for token in ("diameter", "_dia", "radius", "hole", "clearance")):
        return "radius_or_diameter"
    if any(token in normalized for token in ("thickness", "wall", "floor")):
        return "thickness"
    if any(token in normalized for token in ("rotate", "rotation", "angle")):
        return "rotation"
    if any(token in normalized for token in ("translate", "offset", "position", "location")):
        return "translation"
    if any(token in normalized for token in ("enabled", "enable", "toggle", "has_", "use_")):
        return "feature_toggle"
    if any(token in normalized for token in ("tool", "boolean", "cut")):
        return "boolean_tool_size"
    return "dimension"


def _analyze(
    function: ast.FunctionDef,
    *,
    canonical_pattern_parameter_ids: set[str] | None = None,
) -> "_Analysis":
    aliases: dict[str, set[str]] = {}
    assignments = [node for node in ast.walk(function) if isinstance(node, ast.Assign)]
    for _ in range(len(assignments) + 1):
        changed = False
        for assignment in assignments:
            if len(assignment.targets) != 1 or not isinstance(assignment.targets[0], ast.Name):
                continue
            dependencies = _expression_dependencies(assignment.value, aliases)
            target = assignment.targets[0].id
            if dependencies and aliases.get(target) != dependencies:
                aliases[target] = dependencies
                changed = True
        if not changed:
            break
    analysis = _Analysis()
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            name = _call_name(node.func)
            dependencies = _expression_dependencies_from_call(node, aliases)
            if name in _GEOMETRY_METHODS:
                analysis.geometry_dependencies.update({dependency: name for dependency in dependencies})
                analysis.geometry_operations[name] = analysis.geometry_operations.get(name, 0) + 1
                for value in _numeric_constants(node):
                    analysis.geometry_literals.append(value)
                if name in _PATTERN_METHODS:
                    analysis.pattern_dependencies.update(dependencies)
                if name == "pushPoints" and node.args:
                    argument = node.args[0]
                    point_id, truncated = _pattern_argument(argument)
                    canonical_ids = canonical_pattern_parameter_ids or set()
                    if point_id in canonical_ids:
                        if truncated:
                            analysis.pattern_point_usage.setdefault(point_id, set()).add("truncated")
                        else:
                            analysis.pattern_point_usage.setdefault(point_id, set()).add("canonical")
                    elif canonical_ids:
                        analysis.pattern_point_overrides += 1
                        for canonical_id in canonical_ids:
                            analysis.pattern_point_usage.setdefault(canonical_id, set()).add("override")
            elif name == "range":
                literal = _literal_int(node.args[0]) if node.args else None
                analysis.ranges.append((dependencies, literal))
                analysis.pattern_dependencies.update(dependencies)
            elif dependencies and _APPROVED_HELPER_RE.search(name or ""):
                analysis.helper_dependencies.update(dependencies)
                analysis.pattern_dependencies.update(dependencies)
        if isinstance(node, ast.For):
            dependencies = _expression_dependencies(node.iter, aliases)
            analysis.pattern_dependencies.update(dependencies)
            if isinstance(node.iter, (ast.List, ast.Tuple)):
                analysis.fixed_list_lengths.append(len(node.iter.elts))
        if isinstance(node, ast.List | ast.Tuple):
            if node.elts and all(isinstance(item, ast.Tuple | ast.List) for item in node.elts):
                analysis.fixed_list_lengths.append(len(node.elts))
        if isinstance(node, ast.If | ast.IfExp):
            test = node.test
            analysis.control_dependencies.update(_expression_dependencies(test, aliases))
        if isinstance(node, ast.Call) and _call_name(node.func) in {"pushPoints", "hole"}:
            analysis.pattern_literals.extend(_numeric_constants(node))
    return analysis


@dataclass
class _Analysis:
    geometry_dependencies: dict[str, str] = field(default_factory=dict)
    geometry_operations: dict[str, int] = field(default_factory=dict)
    geometry_literals: list[float] = field(default_factory=list)
    pattern_dependencies: set[str] = field(default_factory=set)
    helper_dependencies: set[str] = field(default_factory=set)
    control_dependencies: set[str] = field(default_factory=set)
    ranges: list[tuple[set[str], int | None]] = field(default_factory=list)
    fixed_list_lengths: list[int] = field(default_factory=list)
    pattern_literals: list[float] = field(default_factory=list)
    pattern_point_usage: dict[str, set[str]] = field(default_factory=dict)
    pattern_point_overrides: int = 0


def _params_subscript_id(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Subscript):
        return None
    if not isinstance(node.value, ast.Name) or node.value.id != "params":
        return None
    if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
        return node.slice.value
    return None


def _pattern_argument(node: ast.AST) -> tuple[str | None, bool]:
    direct = _params_subscript_id(node)
    if direct is not None:
        return direct, False
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
        return _params_subscript_id(node.value), True
    return None, False


def _is_slice(node: ast.Subscript) -> bool:
    return isinstance(node.slice, ast.Slice)


def _has_effect(analysis: _Analysis, candidates: set[str], effect_type: str) -> bool:
    if effect_type == "diameter":
        effect_type = "radius_or_diameter"
    if effect_type == "pattern_count":
        return bool(analysis.pattern_dependencies.intersection(candidates))
    if effect_type == "pattern_spacing":
        return bool(
            analysis.pattern_dependencies.intersection(candidates)
            or set(analysis.geometry_dependencies).intersection(candidates)
        )
    if effect_type == "translation":
        return bool(
            any(parameter in candidates and operation in {"translate"} for parameter, operation in analysis.geometry_dependencies.items())
        )
    if effect_type == "rotation":
        return bool(
            any(parameter in candidates and operation in {"rotate", "rotateAbout", "mirror"} for parameter, operation in analysis.geometry_dependencies.items())
        )
    if effect_type == "feature_toggle":
        return bool(analysis.control_dependencies.intersection(candidates))
    if effect_type == "boolean_tool_size":
        return bool(analysis.geometry_dependencies.keys() & candidates) and bool(
            analysis.geometry_operations.keys() & {"cut", "union", "chamfer", "fillet", "hole"}
        )
    return bool(analysis.geometry_dependencies.keys() & candidates)


def _hardcoded_pattern_count(analysis: _Analysis, numeric_values: list[float | int]) -> bool:
    expected_counts = {int(value) for value in numeric_values if float(value).is_integer() and value > 0}
    if not expected_counts:
        return bool(analysis.fixed_list_lengths or analysis.ranges)
    if any(length in expected_counts for length in analysis.fixed_list_lengths):
        return True
    if any(literal is not None for _, literal in analysis.ranges):
        return True
    if any(literal in expected_counts for _, literal in analysis.ranges):
        return True
    return any(
        operation in {"hole", "pushPoints", "cut", "union"} and count > 1
        for operation, count in analysis.geometry_operations.items()
    )


def _hardcoded_pattern_spacing(analysis: _Analysis, numeric_values: list[float | int]) -> bool:
    literals = [*analysis.pattern_literals, *analysis.geometry_literals]
    return any(math.isclose(float(value), float(literal), rel_tol=0, abs_tol=1e-9) for value in numeric_values for literal in literals)


def _hardcoded_dimension(analysis: _Analysis, numeric_values: list[float | int]) -> bool:
    return any(math.isclose(float(value), float(literal), rel_tol=0, abs_tol=1e-9) for value in numeric_values for literal in analysis.geometry_literals)


def _parameter_value(parameter_id: str, function_manifest: dict[str, Any], derived_values: dict[str, Any]) -> Any:
    if parameter_id in derived_values:
        return derived_values[parameter_id]
    for item in function_manifest.get("parameter_values", []) or []:
        if isinstance(item, dict) and item.get("id") == parameter_id:
            return item.get("value")
    for item in function_manifest.get("required_parameter_effects", []) or []:
        if isinstance(item, dict) and item.get("parameter_id") == parameter_id:
            return item.get("value")
    return None


def _finding(rule_id: str, function_manifest: dict[str, Any], message: str, **extra: Any) -> dict[str, Any]:
    obligation = extra.pop("obligation", None) or {}
    return {
        "rule_id": rule_id,
        "category": "geometry_body",
        "severity": "critical",
        "is_blocking": True,
        "function_id": function_manifest.get("function_id"),
        "parameter_id": obligation.get("parameter_id"),
        "effect_type": obligation.get("effect_type"),
        "allowed_via": list(obligation.get("allowed_via", []) or []),
        "message": message,
        **extra,
    }


def _expression_symbols(expression: str) -> set[str]:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        return set()
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id not in {"True", "False"}}


def _safe_eval(expression: str, values: dict[str, Any]) -> Any:
    tree = ast.parse(expression, mode="eval")
    return _safe_eval_node(tree.body, values)


def _safe_eval_node(node: ast.AST, values: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in values:
            raise KeyError(node.id)
        return values[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in {ast.Add, ast.Sub, ast.Mult, ast.Div}:
        left = _safe_eval_node(node.left, values)
        right = _safe_eval_node(node.right, values)
        if type(node.op) is ast.Add:
            return left + right
        if type(node.op) is ast.Sub:
            return left - right
        if type(node.op) is ast.Mult:
            return left * right
        return left / right
    if isinstance(node, ast.UnaryOp) and type(node.op) in {ast.UAdd, ast.USub}:
        value = _safe_eval_node(node.operand, values)
        return value if type(node.op) is ast.UAdd else -value
    raise ValueError("unsupported expression")


def _expression_dependencies(expression: ast.AST, aliases: dict[str, set[str]]) -> set[str]:
    dependencies: set[str] = set()
    for node in ast.walk(expression):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "params":
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                dependencies.add(node.slice.value)
        elif isinstance(node, ast.Name):
            dependencies.update(aliases.get(node.id, set()))
    return dependencies


def _expression_dependencies_from_call(node: ast.Call, aliases: dict[str, set[str]]) -> set[str]:
    dependencies: set[str] = set()
    for argument in [*node.args, *(keyword.value for keyword in node.keywords)]:
        dependencies.update(_expression_dependencies(argument, aliases))
    return dependencies


def _numeric_constants(node: ast.AST) -> list[float]:
    return [
        float(child.value)
        for child in ast.walk(node)
        if isinstance(child, ast.Constant) and isinstance(child.value, int | float) and not isinstance(child.value, bool)
    ]


def _literal_int(node: ast.AST) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    return None


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _component_function_id(component_id: str) -> str:
    return "_ai_component_" + _safe_identifier(component_id)


def _feature_function_id(feature_id: str) -> str:
    return "_ai_feature_" + _safe_identifier(feature_id)


def _safe_identifier(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]", "_", value)
    return "id_" + normalized if not normalized or normalized[0].isdigit() else normalized
