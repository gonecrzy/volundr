"""Deterministic provenance validation for Design Plan values."""

from __future__ import annotations

import ast
import operator
from copy import deepcopy
from typing import Any

from app.services.workflow.provider_response import ProvenanceCompletion

PROVENANCE_VERSION = "design-plan-provenance-v1"
PROVENANCE_RELATIONSHIPS = {
    "direct",
    "derived_formula",
    "calculated",
    "standard_lookup",
    "product_default",
    "printer_default",
    "ai_proposal",
    "user_override",
}

AUTHORITATIVE_PROVENANCE_SOURCES = frozenset(
    {
        "initial_user",
        "clarification_user",
        "revision_user",
        "physical_feedback_user",
        "volundr_proposal",
        "derived_calculation",
        "standard_lookup",
        "exposed_control",
        "deterministic_default",
    }
)

_PROVENANCE_SOURCE_ALIASES = {
    "user": "initial_user",
    "initial": "initial_user",
    "clarification": "clarification_user",
    "revision": "revision_user",
    "physical_feedback": "physical_feedback_user",
    "ai_proposal": "volundr_proposal",
    "calculated": "derived_calculation",
    "product_default": "deterministic_default",
    "printer_default": "deterministic_default",
}


def normalize_authoritative_provenance(
    record: dict[str, Any],
    authoritative_sources: dict[str, dict[str, Any]],
) -> ProvenanceCompletion:
    """Normalize a source label only when its authority is unambiguous."""

    normalized = deepcopy(record)
    provenance = normalized.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
        normalized["provenance"] = provenance
    findings: list[str] = []
    raw_source = provenance.get("source")
    canonical_source = _PROVENANCE_SOURCE_ALIASES.get(str(raw_source), str(raw_source)) if raw_source else None
    if canonical_source and canonical_source not in AUTHORITATIVE_PROVENANCE_SOURCES:
        return ProvenanceCompletion(normalized, ("provenance.source_invalid",))

    record_id = str(normalized.get("source_requirement_id") or normalized.get("id") or "")
    candidates = [
        (source_id, source)
        for source_id, source in authoritative_sources.items()
        if _values_match(normalized.get("value"), source.get("value"))
        and _units_match(normalized.get("unit"), source.get("unit"))
    ]
    if record_id in authoritative_sources:
        candidates = [(record_id, authoritative_sources[record_id])]

    if canonical_source:
        if raw_source != canonical_source:
            provenance["source"] = canonical_source
            findings.append("provenance.source_canonicalized")
        if len(candidates) == 1 and candidates[0][1].get("source") != canonical_source:
            findings.append(
                "provenance.proposal_misclassified"
                if canonical_source == "volundr_proposal"
                else "provenance.user_input_misclassified"
            )
        return ProvenanceCompletion(normalized, tuple(findings), bool(findings))

    if len(candidates) != 1:
        return ProvenanceCompletion(
            normalized,
            ("provenance.source_conflict",) if len(candidates) > 1 else ("provenance.derived_source_missing",),
        )
    source_id, source = candidates[0]
    provenance["source"] = source["source"]
    provenance["source_id"] = source_id
    return ProvenanceCompletion(normalized, ("provenance.source_completed",), True)

FASTENER_LOOKUP_TABLES: dict[str, dict[str, dict[str, dict[str, Any]]]] = {
    "fastener-clearance-v1": {
        "#6": {"clearance": {"diameter_mm": 3.5}},
        "#8": {
            "clearance": {"diameter_mm": 4.2, "head_diameter_mm": 8.5},
            "head": {"diameter_mm": 8.5},
            "standard": {
                "diameter_mm": 4.2,
                "head_diameter_mm": 8.5,
                "clearance": {"diameter_mm": 4.2},
                "head": {"diameter_mm": 8.5},
            },
        },
        "#10": {
            "clearance": {"diameter_mm": 4.8, "head_diameter_mm": 9.5},
            "head": {"diameter_mm": 9.5},
            "standard": {
                "diameter_mm": 4.8,
                "head_diameter_mm": 9.5,
                "clearance": {"diameter_mm": 4.8},
                "head": {"diameter_mm": 9.5},
            },
        },
    }
}

_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def normalize_plan_provenance(
    plan: dict[str, Any],
    specification: dict[str, Any] | None,
) -> dict[str, Any]:
    """Copy a Plan and add only deterministic provenance bookkeeping."""

    normalized = deepcopy(plan)
    requirements = _requirements(specification)
    authoritative_sources = {
        requirement_id: {
            "value": requirement.get("value"),
            "unit": requirement.get("unit"),
            "source": _requirement_provenance_source(requirement),
        }
        for requirement_id, requirement in requirements.items()
    }
    normalization_findings = normalized.setdefault("normalization_findings", [])
    for parameter in normalized.get("parameters", []) or []:
        if not isinstance(parameter, dict):
            continue
        provenance_completion = normalize_authoritative_provenance(parameter, authoritative_sources)
        parameter.clear()
        parameter.update(provenance_completion.value)
        normalization_findings.extend(
            {
                "rule_id": finding,
                "severity": "warning" if finding in {"provenance.source_completed", "provenance.source_canonicalized"} else "critical",
                "blocking": finding not in {"provenance.source_completed", "provenance.source_canonicalized"},
                "parameter_id": parameter.get("id"),
            }
            for finding in provenance_completion.findings
        )
        provenance = parameter.get("provenance")
        if not isinstance(provenance, dict) or not provenance.get("relationship"):
            provenance = _infer_provenance(parameter)
            parameter["provenance"] = provenance
        if provenance.get("relationship") == "direct" and not provenance.get("source_requirement_ids"):
            parameter_id = str(parameter.get("id") or "")
            if parameter_id in requirements:
                provenance["source_requirement_ids"] = [parameter_id]
                parameter.setdefault("source_requirement_id", parameter_id)
        parameter_id = str(parameter.get("id") or "")
        requirement = requirements.get(parameter_id)
        if (
            requirement
            and not parameter.get("source_requirement_id")
            and str(provenance.get("relationship") or "") in {"ai_proposal", ""}
            and _values_match(parameter.get("value"), requirement.get("value"))
            and _units_match(parameter.get("unit"), requirement.get("unit"))
        ):
            # A provider may omit provenance on a same-named value while
            # copying the explicit requirement exactly.  Restore the
            # authoritative ledger link deterministically; a differing value
            # remains a provider/provenance failure and is not relinked.
            provenance["relationship"] = "direct"
            provenance["source_requirement_ids"] = [parameter_id]
            parameter["source_requirement_id"] = parameter_id
            parameter.setdefault("source", "requirement_ledger")
            normalization_findings.append({
                "rule_id": "plan.provenance_identity_recovered",
                "severity": "warning",
                "blocking": False,
                "parameter_id": parameter_id,
                "source_requirement_id": parameter_id,
                "reason": "same-named Plan value matched an explicit requirement value and unit",
            })
        provenance.setdefault("validator_version", PROVENANCE_VERSION)
    for parameter in normalized.get("derived_parameters", []) or []:
        if not isinstance(parameter, dict):
            continue
        provenance = parameter.setdefault("provenance", {})
        if isinstance(provenance, dict):
            provenance.setdefault("relationship", "calculated")
            provenance.setdefault("validator_version", PROVENANCE_VERSION)
            if isinstance(parameter.get("expression"), str):
                provenance.setdefault("expression", parameter["expression"])
    values = {
        str(parameter.get("id")): parameter.get("value")
        for parameter in normalized.get("parameters", []) or []
        if isinstance(parameter, dict) and parameter.get("id")
    }
    values.update(
        {
            requirement_id: requirement.get("value")
            for requirement_id, requirement in requirements.items()
        }
    )
    entries = list(normalized.get("parameters", []) or []) + list(normalized.get("derived_parameters", []) or [])
    for parameter in entries:
        if not isinstance(parameter, dict):
            continue
        provenance = parameter.get("provenance")
        if isinstance(provenance, dict) and provenance.get("relationship") == "standard_lookup":
            result = _resolve_standard_lookup(parameter, provenance, values)
            if result is not _MISSING:
                values[str(parameter["id"])] = result
    for _ in range(max(1, len(entries))):
        changed = False
        for parameter in normalized.get("derived_parameters", []) or []:
            if not isinstance(parameter, dict) or parameter.get("value") is not None:
                continue
            expression = parameter.get("expression")
            if not isinstance(expression, str) or not expression.strip():
                continue
            try:
                result, symbols = _safe_expression(expression, values)
            except (ValueError, ZeroDivisionError):
                continue
            parameter["value"] = result
            parameter["source"] = "calculated"
            provenance = parameter.setdefault("provenance", {})
            provenance["resolved_inputs"] = {key: values[key] for key in symbols if key in values}
            provenance["resolved_result"] = result
            values[str(parameter["id"])] = result
            changed = True
        if not changed:
            break
    return normalized


def validate_plan_provenance(
    plan: dict[str, Any],
    specification: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    requirements = _requirements(specification)
    parameters = [
        parameter
        for parameter in plan.get("parameters", []) or []
        if isinstance(parameter, dict) and parameter.get("id")
    ]
    derived_parameters = [
        parameter
        for parameter in plan.get("derived_parameters", []) or []
        if isinstance(parameter, dict) and parameter.get("id")
    ]
    entries = parameters + derived_parameters
    findings: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    values: dict[str, Any] = {}
    units: dict[str, str | None] = {}
    for parameter in parameters:
        parameter_id = str(parameter["id"])
        if parameter_id in seen_ids:
            findings.append(_finding("design_plan.semantic_identity_collision", f"Parameter ID {parameter_id} is declared more than once."))
        seen_ids.add(parameter_id)
        values[parameter_id] = parameter.get("value")
        units[parameter_id] = parameter.get("unit")
    for parameter in derived_parameters:
        parameter_id = str(parameter["id"])
        if parameter_id in seen_ids:
            findings.append(_finding("design_plan.semantic_identity_collision", f"Parameter ID {parameter_id} is declared more than once."))
        seen_ids.add(parameter_id)
        values[parameter_id] = parameter.get("value")
        units[parameter_id] = parameter.get("unit")
    for requirement_id, requirement in requirements.items():
        values.setdefault(requirement_id, requirement.get("value"))
        units.setdefault(requirement_id, requirement.get("unit"))

    for parameter in entries:
        parameter_id = str(parameter["id"])
        provenance = parameter.get("provenance")
        if not isinstance(provenance, dict):
            findings.append(_finding("design_plan.provenance_missing", f"Parameter {parameter_id} has no provenance relationship."))
            continue
        relationship = str(provenance.get("relationship") or "")
        if relationship not in PROVENANCE_RELATIONSHIPS:
            findings.append(_finding("design_plan.provenance_relationship_invalid", f"Parameter {parameter_id} has unsupported provenance relationship {relationship!r}."))
            continue
        source = str(provenance.get("source") or "")
        canonical_source = _PROVENANCE_SOURCE_ALIASES.get(source, source) if source else ""
        if canonical_source and canonical_source not in AUTHORITATIVE_PROVENANCE_SOURCES:
            findings.append(_finding("provenance.source_invalid", f"Parameter {parameter_id} has unsupported provenance source {source!r}."))
        if canonical_source and canonical_source != source:
            findings.append(_finding("provenance.source_noncanonical", f"Parameter {parameter_id} uses legacy provenance source {source!r}."))
        source_ids_for_authority = _string_list(provenance.get("source_requirement_ids"))
        if source_ids_for_authority:
            source_requirement = requirements.get(source_ids_for_authority[0])
            expected_source = _requirement_provenance_source(source_requirement) if source_requirement else None
            if expected_source and canonical_source and expected_source != canonical_source:
                findings.append(
                    _finding(
                        "provenance.proposal_misclassified"
                        if canonical_source == "volundr_proposal"
                        else "provenance.user_input_misclassified",
                        f"Parameter {parameter_id} labels authoritative requirement {source_ids_for_authority[0]} as {canonical_source!r}.",
                    )
                )
        source_ids = _string_list(provenance.get("source_requirement_ids"))
        source_parameter_ids = _string_list(provenance.get("source_parameter_ids"))
        if relationship == "direct":
            _validate_direct(parameter, parameter_id, source_ids, requirements, findings)
        elif relationship in {"derived_formula", "calculated"}:
            _validate_formula(
                parameter,
                parameter_id,
                provenance,
                source_ids,
                source_parameter_ids,
                _string_list(parameter.get("depends_on")),
                values,
                units,
                findings,
            )
        elif relationship == "standard_lookup":
            _validate_lookup(
                parameter,
                parameter_id,
                provenance,
                source_ids,
                source_parameter_ids,
                requirements,
                values,
                findings,
            )
        elif relationship in {"product_default", "printer_default", "ai_proposal"}:
            if any(_is_explicit(requirement) for requirement in requirements.values() if parameter_id == str(requirement.get("id"))):
                findings.append(_finding("design_plan.default_overrode_explicit", f"Lower-authority provenance replaced explicit parameter {parameter_id}."))
        elif relationship == "user_override":
            if not provenance.get("override_recorded") and not provenance.get("source_requirement_ids"):
                findings.append(_finding("design_plan.user_override_unrecorded", f"User override for {parameter_id} is not linked to an explicit source or override record."))
        _validate_identity_collision(parameter, parameter_id, relationship, source_ids, requirements, findings)

    _validate_dependency_relationships(plan, entries, findings)

    return findings


def _validate_direct(
    parameter: dict[str, Any],
    parameter_id: str,
    source_ids: list[str],
    requirements: dict[str, dict[str, Any]],
    findings: list[dict[str, Any]],
) -> None:
    source_id = str(parameter.get("source_requirement_id") or (source_ids[0] if source_ids else ""))
    if not source_id or source_id not in requirements:
        findings.append(_finding("design_plan.provenance_source_missing", f"Direct parameter {parameter_id} has no valid source requirement."))
        return
    if parameter.get("source_requirement_id") and parameter["source_requirement_id"] != source_id:
        findings.append(_finding("design_plan.provenance_source_mismatch", f"Direct parameter {parameter_id} has inconsistent source IDs."))
    requirement = requirements[source_id]
    if not _values_match(parameter.get("value"), requirement.get("value")):
        findings.append(_finding("design_plan.direct_value_mismatch", f"Direct parameter {parameter_id} does not match requirement {source_id}.", expected=requirement.get("value"), detected=parameter.get("value")))
    if requirement.get("unit") and parameter.get("unit") and requirement["unit"] != parameter["unit"]:
        findings.append(_finding("design_plan.direct_unit_mismatch", f"Direct parameter {parameter_id} has incompatible units.", expected=requirement.get("unit"), detected=parameter.get("unit")))


def _validate_formula(
    parameter: dict[str, Any],
    parameter_id: str,
    provenance: dict[str, Any],
    source_ids: list[str],
    source_parameter_ids: list[str],
    declared_dependencies: list[str],
    values: dict[str, Any],
    units: dict[str, str | None],
    findings: list[dict[str, Any]],
) -> None:
    expression = provenance.get("expression") or parameter.get("expression")
    if not isinstance(expression, str) or not expression.strip():
        findings.append(_finding("design_plan.provenance_expression_missing", f"Formula provenance for {parameter_id} is missing an expression."))
        return
    dependencies = source_ids + source_parameter_ids + declared_dependencies
    missing = [dependency for dependency in dependencies if dependency not in values]
    if missing:
        findings.append(_finding("design_plan.provenance_dependency_missing", f"Formula for {parameter_id} references missing dependencies: {', '.join(missing)}."))
    try:
        result, symbols = _safe_expression(expression, values)
    except (ValueError, ZeroDivisionError) as exc:
        findings.append(_finding("design_plan.provenance_expression_unsafe", f"Formula for {parameter_id} is not a permitted deterministic expression: {exc}."))
        return
    undeclared = sorted(symbols - set(dependencies))
    if undeclared:
        findings.append(_finding("design_plan.provenance_dependency_missing", f"Formula for {parameter_id} uses undeclared dependencies: {', '.join(undeclared)}."))
    provenance["resolved_inputs"] = {key: values[key] for key in symbols if key in values}
    provenance["resolved_result"] = result
    provenance["validator_version"] = PROVENANCE_VERSION
    if not _values_match(parameter.get("value"), result):
        findings.append(_finding("design_plan.provenance_formula_mismatch", f"Formula for {parameter_id} does not produce the proposed value.", expected=result, detected=parameter.get("value")))
    parameter_unit = parameter.get("unit")
    for dependency in dependencies:
        if parameter_unit and units.get(dependency) and parameter_unit != units[dependency]:
            findings.append(_finding("design_plan.provenance_unit_mismatch", f"Formula for {parameter_id} has incompatible units for dependency {dependency}."))


def _validate_dependency_relationships(
    plan: dict[str, Any],
    entries: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> None:
    by_id = {str(entry.get("id")): entry for entry in entries if entry.get("id")}
    for edge in plan.get("dependency_edges", []) or []:
        if not isinstance(edge, dict):
            continue
        target_id = str(edge.get("to") or "")
        relationship = str(edge.get("relationship") or "").lower()
        target = by_id.get(target_id)
        if target is None or "standard_lookup" not in relationship:
            continue
        provenance = target.get("provenance")
        if not isinstance(provenance, dict) or provenance.get("relationship") != "standard_lookup":
            findings.append(
                _finding(
                    "design_plan.standard_lookup_provenance_missing",
                    f"Dependency edge for {target_id} declares a standard lookup but the target provenance does not.",
                )
            )


def _validate_lookup(
    parameter: dict[str, Any],
    parameter_id: str,
    provenance: dict[str, Any],
    source_ids: list[str],
    source_parameter_ids: list[str],
    requirements: dict[str, dict[str, Any]],
    values: dict[str, Any],
    findings: list[dict[str, Any]],
) -> None:
    lookup = provenance.get("lookup")
    if not isinstance(lookup, dict):
        findings.append(_finding("design_plan.standard_lookup_missing", f"Standard lookup provenance for {parameter_id} is missing lookup metadata."))
        return
    table_id = lookup.get("table_id")
    key = lookup.get("key")
    variant = lookup.get("variant")
    table = FASTENER_LOOKUP_TABLES.get(str(table_id), {})
    row = table.get(str(key), {}) if isinstance(table, dict) else {}
    if not row:
        findings.append(_finding("design_plan.standard_lookup_unknown_key", f"Standard lookup {table_id!r} does not contain key {key!r}."))
    if not variant or not isinstance(row, dict) or variant not in row:
        findings.append(_finding("design_plan.standard_lookup_variant_missing", f"Standard lookup for {parameter_id} has no configured variant {variant!r}."))
        return
    source_id = (source_ids or source_parameter_ids or [""])[0]
    requirement = requirements.get(source_id)
    source_value = requirement.get("value") if requirement else values.get(source_id)
    if requirement is None and source_id not in values:
        findings.append(_finding("design_plan.provenance_source_missing", f"Standard lookup {parameter_id} has no source requirement."))
    elif str(source_value) != str(key):
        findings.append(_finding("design_plan.standard_lookup_key_mismatch", f"Lookup key {key!r} does not match requirement {source_id}."))
    result = row[variant]
    result_field = str(lookup.get("result_field") or "diameter_mm")
    resolved_result = _lookup_result(row, result, str(variant), result_field)
    if resolved_result is _MISSING:
        findings.append(_finding("design_plan.standard_lookup_result_missing", f"Standard lookup variant {variant!r} has no result field {result_field!r}."))
        return
    expected = resolved_result
    provenance["resolved_inputs"] = {source_id: source_value} if source_id else {}
    provenance["resolved_result"] = expected
    provenance["validator_version"] = PROVENANCE_VERSION
    if not _values_match(parameter.get("value"), expected):
            findings.append(_finding("design_plan.standard_lookup_mismatch", f"Standard lookup for {parameter_id} does not produce the proposed value.", expected=expected, detected=parameter.get("value")))


def _resolve_standard_lookup(
    parameter: dict[str, Any],
    provenance: dict[str, Any],
    values: dict[str, Any],
) -> Any:
    lookup = provenance.get("lookup")
    if not isinstance(lookup, dict):
        return _MISSING
    table = FASTENER_LOOKUP_TABLES.get(str(lookup.get("table_id")), {})
    row = table.get(str(lookup.get("key")), {}) if isinstance(table, dict) else {}
    variant = str(lookup.get("variant") or "")
    if not isinstance(row, dict) or variant not in row:
        return _MISSING
    result = _lookup_result(
        row,
        row[variant],
        variant,
        str(lookup.get("result_field") or "diameter_mm"),
    )
    if result is _MISSING:
        return _MISSING
    parameter["value"] = result
    parameter["source"] = "standard_lookup"
    source_ids = _string_list(provenance.get("source_requirement_ids")) + _string_list(provenance.get("source_parameter_ids"))
    provenance["resolved_inputs"] = {source_id: values[source_id] for source_id in source_ids if source_id in values}
    provenance["resolved_result"] = result
    return result


def _validate_identity_collision(
    parameter: dict[str, Any],
    parameter_id: str,
    relationship: str,
    source_ids: list[str],
    requirements: dict[str, dict[str, Any]],
    findings: list[dict[str, Any]],
) -> None:
    if relationship != "direct" or not source_ids:
        return
    requirement = requirements.get(source_ids[0])
    if requirement and isinstance(requirement.get("value"), str) and isinstance(parameter.get("value"), (int, float)):
        findings.append(_finding("design_plan.semantic_identity_collision", f"Parameter {parameter_id} uses a numeric geometry value for string designation {source_ids[0]}."))


def _infer_provenance(parameter: dict[str, Any]) -> dict[str, Any]:
    source = str(parameter.get("source") or "")
    relationship = {
        "product_default": "product_default",
        "printer_profile": "printer_default",
        "calculated": "calculated",
        "ai_assumption": "ai_proposal",
    }.get(source)
    if relationship is None and parameter.get("source_requirement_id"):
        relationship = "direct"
    relationship = relationship or "ai_proposal"
    result: dict[str, Any] = {"relationship": relationship, "validator_version": PROVENANCE_VERSION}
    if parameter.get("source_requirement_id"):
        result["source_requirement_ids"] = [parameter["source_requirement_id"]]
    return result


def _requirement_provenance_source(requirement: dict[str, Any]) -> str:
    provenance = requirement.get("provenance")
    provenance_source = provenance.get("source") if isinstance(provenance, dict) else None
    source = str(requirement.get("source") or provenance_source or "")
    return _PROVENANCE_SOURCE_ALIASES.get(source, source or "initial_user")


def _requirements(specification: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for collection in (specification or {}).get("critical_dimensions", []), (specification or {}).get("parameters", []):
        for item in collection or []:
            if isinstance(item, dict) and item.get("id"):
                result[str(item["id"])] = item
    return result


def _safe_expression(expression: str, values: dict[str, Any]) -> tuple[float, set[str]]:
    tree = ast.parse(expression, mode="eval")
    symbols: set[str] = set()

    def evaluate(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.Name):
            symbols.add(node.id)
            value = values.get(node.id)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"dependency {node.id} is not numeric")
            return float(value)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
            return _UNARY_OPERATORS[type(node.op)](evaluate(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
            return _BINARY_OPERATORS[type(node.op)](evaluate(node.left), evaluate(node.right))
        raise ValueError("only numeric literals, approved parameter names, and arithmetic are allowed")

    return evaluate(tree), symbols


_MISSING = object()


def _lookup_result(
    row: dict[str, Any],
    variant_result: Any,
    variant: str,
    result_field: str,
) -> Any:
    """Resolve either a field within the selected variant or an explicit table path."""

    if "." not in result_field:
        if isinstance(variant_result, dict):
            return variant_result.get(result_field, _MISSING)
        return _MISSING
    current: Any = row
    for segment in result_field.split("."):
        if not isinstance(current, dict) or segment not in current:
            return _MISSING
        current = current[segment]
    return current


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item]


def _is_explicit(item: dict[str, Any]) -> bool:
    return item.get("source") == "user" or item.get("authority") == "explicit"


def _values_match(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    try:
        return abs(float(left) - float(right)) <= 1e-6
    except (TypeError, ValueError):
        return str(left) == str(right)


def _units_match(left: Any, right: Any) -> bool:
    if left in (None, "") or right in (None, ""):
        return True
    return str(left).strip().lower() == str(right).strip().lower()


def _finding(rule_id: str, message: str, *, expected: Any = None, detected: Any = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "rule_id": rule_id,
        "stage": "design_plan_validation",
        "severity": "critical",
        "is_blocking": True,
        "message": message,
    }
    if expected is not None:
        result["expected"] = expected
    if detected is not None:
        result["detected"] = detected
    return result
