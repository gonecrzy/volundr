from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any


AUTHORITY_RANKS = {
    "explicit": 1,
    "clarification": 2,
    "calculated": 3,
    "user_confirmed_preset": 4,
    "printer_profile": 5,
    "product_default": 6,
    "ai_assumption": 7,
}

AUTHORITY_BY_SOURCE = {
    "user": "explicit",
    "clarification": "clarification",
    "calculated": "calculated",
    "preset": "user_confirmed_preset",
    "user_confirmed_preset": "user_confirmed_preset",
    "printer_profile": "printer_profile",
    "product_default": "product_default",
    "ai_assumption": "ai_assumption",
}

DIMENSION_NAMES = ("width", "depth", "height")
FEATURE_WORDS = ("lid", "label_tabs", "tabs", "label tabs")
ID_ALIASES = {
    "rows": "row_count",
    "row": "row_count",
    "cols": "column_count",
    "columns": "column_count",
    "column": "column_count",
    "cell_size": "cell_size",
    "wall_thickness_mm": "wall_thickness",
}


class RequirementTraceError(ValueError):
    def __init__(self, findings: list[dict[str, Any]]) -> None:
        self.findings = findings
        message = "; ".join(finding["rule_id"] for finding in findings)
        super().__init__(message)


def explicit_item(
    requirement_id: str,
    value: Any,
    *,
    unit: str | None = None,
    label: str | None = None,
    requirement_type: str | None = None,
    evidence: str | None = None,
    kind: str | None = None,
    operator: str | None = None,
    subject: str | None = None,
    object_type: str | None = None,
    target: str | None = None,
    raw_evidence: str | None = None,
) -> dict[str, Any]:
    normalized_id = canonical_requirement_id(requirement_id)
    item = {
        "requirement_id": normalized_id,
        "id": normalized_id,
        "label": label or _human_label(normalized_id),
        "value": value,
        "unit": unit,
        "source": "user",
        "authority": "explicit",
        "authority_rank": AUTHORITY_RANKS["explicit"],
        "protected": True,
        "type": requirement_type or _requirement_type(normalized_id, value, unit),
        "evidence": {"request_excerpt": evidence or requirement_id},
    }
    if kind is not None:
        item["kind"] = kind
    if operator is not None:
        item["operator"] = operator
    if subject is not None:
        item["subject"] = subject
    if object_type is not None:
        item["object_type"] = object_type
    if target is not None:
        item["target"] = target
    if raw_evidence is not None:
        item["raw_evidence"] = raw_evidence
    return normalize_requirement_semantics(item)


def normalize_requirement_semantics(item: dict[str, Any]) -> dict[str, Any]:
    """Preserve requirement meaning in a stable, shared representation.

    The ledger and planning contracts may add fields around this payload, but
    these fields remain the semantic authority for operators and capacities.
    """

    normalized = deepcopy(item)
    requirement_type = str(normalized.get("type") or "qualitative_behavior")
    semantic_text = " ".join(
        str(normalized.get(key) or "")
        for key in ("label", "description", "raw_evidence", "evidence")
    ).lower()
    inferred_kind = _kind_for_requirement_type(requirement_type)
    if not normalized.get("kind") and _capacity_language(semantic_text):
        inferred_kind = "capacity"
    kind = str(normalized.get("kind") or inferred_kind)
    operator = str(normalized.get("operator") or _operator_for_requirement(normalized, kind))
    normalized["kind"] = kind
    normalized["operator"] = operator
    # Capacity is a semantic kind, not merely a numeric dimension.  Preserve
    # that distinction even when an older provider record called it an
    # exact_dimension or explicit_count.
    if kind == "capacity":
        normalized["type"] = "capacity"
    if normalized.get("raw_evidence") is None:
        evidence = normalized.get("evidence")
        if isinstance(evidence, dict):
            raw_evidence = evidence.get("raw_evidence") or evidence.get("request_excerpt")
        else:
            raw_evidence = evidence
        if raw_evidence:
            normalized["raw_evidence"] = str(raw_evidence)
    return normalized


def default_item(
    requirement_id: str,
    value: float | int | str | bool,
    *,
    unit: str | None = None,
    source: str = "product_default",
    label: str | None = None,
) -> dict[str, Any]:
    normalized_id = canonical_requirement_id(requirement_id)
    authority = AUTHORITY_BY_SOURCE.get(source, source)
    return {
        "requirement_id": normalized_id,
        "id": normalized_id,
        "label": label or _human_label(normalized_id),
        "value": value,
        "unit": unit,
        "source": source,
        "authority": authority,
        "authority_rank": AUTHORITY_RANKS.get(authority, 99),
        "protected": False,
        "type": _requirement_type(normalized_id, value, unit),
        "evidence": {},
    }


def build_explicit_requirement_inventory(
    user_instruction: str,
    *,
    supplemental_requirements: list[str] | tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for text in [*supplemental_requirements, user_instruction]:
        items.extend(_parse_requirement_text(str(text)))
    return merge_resolved_requirements(items)


def merge_resolved_requirements(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    resolved: dict[str, dict[str, Any]] = {}
    for raw_item in items:
        if not isinstance(raw_item, dict):
            continue
        item = _normalize_item(raw_item)
        item_id = item["requirement_id"]
        existing = resolved.get(item_id)
        if existing is None or _rank(item) < _rank(existing):
            resolved[item_id] = item
    return [resolved[key] for key in sorted(resolved)]


def validate_requirement_extraction_trace(
    payload: dict[str, Any],
    inventory: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized = deepcopy(payload)
    findings: list[dict[str, Any]] = []
    questions = [
        question for question in normalized.get("clarification_questions", []) if isinstance(question, dict)
    ]
    redundant = [
        question for question in questions if _question_restates_inventory(question, inventory)
    ]
    if redundant:
        findings.append(
            _finding(
                "clarification_redundant",
                "requirements",
                "Clarification asked for an explicit requirement already supplied.",
                detected_value=[question.get("id") for question in redundant],
            )
        )
        remaining = [question for question in questions if question not in redundant]
        normalized["clarification_questions"] = remaining
        if not remaining:
            normalized["clarification_required"] = False
            normalized["generation_ready"] = True
            normalized["outcome"] = "generation_ready"
            normalized["missing_requirements"] = []
    return normalized, _stage_trace("requirements", "repaired" if findings else "passed", findings)


def validate_design_specification_trace(
    payload: dict[str, Any],
    inventory: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized = deepcopy(payload)
    findings: list[dict[str, Any]] = []
    normalized["explicit_requirements"] = [deepcopy(item) for item in inventory]
    critical = {
        canonical_requirement_id(str(entry.get("id") or entry.get("requirement_id"))): deepcopy(entry)
        for entry in normalized.get("critical_dimensions", [])
        if isinstance(entry, dict)
    }
    functional = {
        canonical_requirement_id(str(entry.get("id") or entry.get("requirement_id"))): deepcopy(entry)
        for entry in normalized.get("functional_requirements", [])
        if isinstance(entry, dict)
    }
    for item in inventory:
        if item.get("type") == "explicit_feature":
            existing = functional.get(item["requirement_id"])
            if existing is None:
                findings.append(
                    _finding(
                        "design_spec.explicit_feature_missing",
                        "design_specification",
                        f"Explicit feature {item['requirement_id']} was missing from the Design Specification.",
                    )
                )
            functional[item["requirement_id"]] = _functional_requirement_from_item(item)
            continue
        existing = critical.get(item["requirement_id"])
        if existing is None:
            findings.append(
                _finding(
                    "design_spec.explicit_requirement_missing",
                    "design_specification",
                    f"Explicit requirement {item['requirement_id']} was missing from the Design Specification.",
                )
            )
        elif not values_match(existing.get("value"), item.get("value")):
            findings.append(
                _finding(
                    "design_spec.explicit_value_mismatch",
                    "design_specification",
                    f"Explicit requirement {item['requirement_id']} was replaced or changed.",
                    expected_value=item.get("value"),
                    detected_value=existing.get("value"),
                )
            )
        critical[item["requirement_id"]] = _dimension_from_item(item)
    normalized["critical_dimensions"] = [critical[key] for key in sorted(critical)]
    normalized["functional_requirements"] = [functional[key] for key in sorted(functional)]
    return normalized, _stage_trace(
        "design_specification",
        "repaired" if findings else "passed",
        findings,
    )


def validate_design_plan_trace(
    payload: dict[str, Any],
    inventory: list[dict[str, Any]],
) -> dict[str, Any]:
    if payload.get("outcome") not in {None, "plan_ready"}:
        return _stage_trace("design_plan", "passed", [])
    findings: list[dict[str, Any]] = []
    parameters = [entry for entry in payload.get("parameters", []) if isinstance(entry, dict)]
    derived = [entry for entry in payload.get("derived_parameters", []) if isinstance(entry, dict)]
    for item in inventory:
        if item.get("type") == "explicit_feature":
            continue
        matching = _matching_parameter(parameters, item["requirement_id"])
        if matching is None:
            findings.append(
                _finding(
                    "design_plan.explicit_requirement_missing",
                    "design_plan",
                    f"Protected requirement {item['requirement_id']} is not represented in the Design Plan.",
                )
            )
            continue
        if canonical_requirement_id(str(matching.get("source_requirement_id") or "")) != item["requirement_id"]:
            findings.append(
                _finding(
                    "design_plan.requirement_source_lost",
                    "design_plan",
                    f"Design Plan parameter {matching.get('id')} lost source requirement {item['requirement_id']}.",
                )
            )
        if not values_match(matching.get("value"), item.get("value")):
            matching_source = matching.get("source")
            rule_id = (
                "design_plan.default_overrode_user_value"
                if matching_source is not None
                and _rank_from_source(matching_source) > AUTHORITY_RANKS["explicit"]
                else "design_plan.explicit_value_mismatch"
            )
            findings.append(
                _finding(
                    rule_id,
                    "design_plan",
                    f"Design Plan parameter {matching.get('id')} does not match explicit requirement {item['requirement_id']}.",
                    expected_value=item.get("value"),
                    detected_value=matching.get("value"),
                )
            )
        if item.get("unit") and matching.get("unit") and matching.get("unit") != item.get("unit"):
            findings.append(
                _finding(
                    "design_plan.explicit_value_mismatch",
                    "design_plan",
                    f"Design Plan parameter {matching.get('id')} unit does not match explicit requirement {item['requirement_id']}.",
                    expected_value=item.get("unit"),
                    detected_value=matching.get("unit"),
                )
            )
    if findings:
        raise RequirementTraceError(findings)
    return _stage_trace("design_plan", "passed", [])


def validate_source_parameter_trace(
    source_metadata: dict[str, Any],
    inventory: list[dict[str, Any]],
) -> dict[str, Any]:
    parameter_ids = {
        canonical_requirement_id(str(parameter_id))
        for parameter_id in source_metadata.get("parameter_ids", [])
    }
    raw_defaults = source_metadata.get("parameter_defaults", {}) or {}
    defaults = {canonical_requirement_id(str(key)): value for key, value in raw_defaults.items()}
    findings: list[dict[str, Any]] = []
    for item in inventory:
        if item.get("type") == "explicit_feature":
            continue
        item_id = item["requirement_id"]
        if item_id not in parameter_ids:
            findings.append(
                _finding(
                    "source_parameter.protected_parameter_missing",
                    "source_parameter",
                    f"Generated source is missing protected parameter {item_id}.",
                )
            )
            continue
        if item_id in defaults and not values_match(defaults[item_id], item.get("value")):
            findings.append(
                _finding(
                    "source_parameter.explicit_value_mismatch",
                    "source_parameter",
                    f"Generated source default for {item_id} does not match the approved value.",
                    expected_value=item.get("value"),
                    detected_value=defaults[item_id],
                )
            )
    if findings:
        raise RequirementTraceError(findings)
    return _stage_trace("source_parameter", "passed", [])


def validate_execution_parameters(
    parameter_values: dict[str, Any],
    inventory: list[dict[str, Any]],
) -> dict[str, Any]:
    values = {canonical_requirement_id(str(key)): value for key, value in parameter_values.items()}
    findings: list[dict[str, Any]] = []
    for item in inventory:
        if item.get("type") == "explicit_feature":
            continue
        item_id = item["requirement_id"]
        if item_id not in values:
            findings.append(
                _finding(
                    "execution_parameter.protected_parameter_missing",
                    "execution_parameter",
                    f"Execution manifest is missing protected parameter {item_id}.",
                )
            )
            continue
        if not values_match(values[item_id], item.get("value")):
            findings.append(
                _finding(
                    "execution_parameter.explicit_value_mismatch",
                    "execution_parameter",
                    f"Execution parameter {item_id} does not match approved value.",
                    expected_value=item.get("value"),
                    detected_value=values[item_id],
                )
            )
    if findings:
        raise RequirementTraceError(findings)
    return _stage_trace("execution_parameter", "passed", [])


def requirement_trace_payload(
    *,
    inventory: list[dict[str, Any]],
    resolved_requirements: list[dict[str, Any]],
    stages: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = {
        "schema_version": "requirement-trace-v1",
        "explicit_requirements": sorted(
            (deepcopy(item) for item in inventory),
            key=lambda item: item["requirement_id"],
        ),
        "resolved_requirements": sorted(
            (deepcopy(item) for item in resolved_requirements),
            key=lambda item: item["requirement_id"],
        ),
        "stages": stages,
    }
    payload["content_hash"] = hashlib.sha256(
        json.dumps(
            {
                "explicit_requirements": payload["explicit_requirements"],
                "resolved_requirements": payload["resolved_requirements"],
                "stages": payload["stages"],
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return payload


def inventory_from_design_specification(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not payload:
        return []
    explicit = payload.get("explicit_requirements")
    if isinstance(explicit, list) and explicit:
        return merge_resolved_requirements([item for item in explicit if isinstance(item, dict)])
    items: list[dict[str, Any]] = []
    for collection_name in ("critical_dimensions", "parameters"):
        for entry in payload.get(collection_name, []) or []:
            if not isinstance(entry, dict) or not entry.get("protected"):
                continue
            if entry.get("source") not in {"user", "clarification"}:
                continue
            source = str(entry.get("source"))
            item = explicit_item(
                str(entry.get("id") or entry.get("requirement_id")),
                entry.get("value"),
                unit=entry.get("unit"),
                label=entry.get("label"),
                requirement_type=entry.get("type"),
                evidence=entry.get("raw_evidence") or entry.get("evidence"),
                kind=entry.get("kind"),
                operator=entry.get("operator"),
                subject=entry.get("subject"),
                object_type=entry.get("object_type"),
                target=entry.get("target"),
            )
            if source == "clarification":
                item["source"] = "clarification"
                item["authority"] = "clarification"
                item["authority_rank"] = AUTHORITY_RANKS["clarification"]
            items.append(item)
    for entry in payload.get("functional_requirements", []) or []:
        if not isinstance(entry, dict) or not entry.get("protected"):
            continue
        if entry.get("source") not in {"user", "clarification"}:
            continue
        items.append(
            explicit_item(
                str(entry.get("id") or entry.get("requirement_id")),
                True,
                label=str(entry.get("description") or entry.get("label") or ""),
                requirement_type=entry.get("type") or "explicit_feature",
                evidence=entry.get("raw_evidence") or entry.get("description"),
                kind=entry.get("kind"),
                operator=entry.get("operator"),
                subject=entry.get("subject"),
                object_type=entry.get("object_type"),
                target=entry.get("target"),
            )
        )
    return merge_resolved_requirements(items)


def values_match(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    try:
        return abs(float(left) - float(right)) <= 1e-6
    except (TypeError, ValueError):
        return str(left) == str(right)


def canonical_requirement_id(value: str) -> str:
    identifier = re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")
    identifier = re.sub(r"_mm$", "", identifier)
    return ID_ALIASES.get(identifier, identifier)


def _parse_requirement_text(text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    number_words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    for count_word, designation in re.findall(
        r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\s+#([0-9]+)\s+(?:mounting\s+)?(?:screws?|fasteners?)\b",
        text,
        flags=re.IGNORECASE,
    ):
        items.append(
            explicit_item(
                "mounting_screw_count",
                number_words[count_word.lower()],
                unit="count",
                evidence=f"{count_word} #{designation} mounting screws",
            )
        )
        items.append(
            explicit_item(
                "mounting_screw_designation",
                f"#{designation}",
                requirement_type="explicit_enum",
                evidence=f"#{designation} mounting screws",
            )
        )
    for raw_key, dimensions, unit in re.findall(
        r"\b([a-zA-Z][a-zA-Z0-9_]*)\s*=\s*([0-9]+(?:\.[0-9]+)?(?:\s*x\s*[0-9]+(?:\.[0-9]+)?){1,2})\s*(mm|cm|in)?\b",
        text,
        flags=re.IGNORECASE,
    ):
        numbers = [float(value) for value in re.findall(r"[0-9]+(?:\.[0-9]+)?", dimensions)]
        key = canonical_requirement_id(raw_key)
        names = _dimension_component_names(key, len(numbers))
        for name, number in zip(names, numbers, strict=False):
            items.append(explicit_item(name, _clean_number(number), unit=unit or "mm", evidence=f"{raw_key}={dimensions} {unit}".strip()))

    for raw_key, op, raw_value, unit in re.findall(
        r"\b([a-zA-Z][a-zA-Z0-9_]*)\s*(<=|>=|=)\s*([0-9]+(?:\.[0-9]+)?)\s*(mm|cm|in)?\b",
        text,
        flags=re.IGNORECASE,
    ):
        key = canonical_requirement_id(raw_key)
        if key == "cell":
            continue
        value = _clean_number(float(raw_value))
        req_type = "explicit_maximum" if op == "<=" else "explicit_minimum" if op == ">=" else None
        items.append(explicit_item(key, value, unit=unit or _default_unit_for_id(key), requirement_type=req_type, evidence=f"{raw_key}{op}{raw_value} {unit}".strip()))

    for raw_key, raw_value in re.findall(
        r"\b([a-zA-Z][a-zA-Z0-9_]*)\s*=\s*([a-zA-Z][a-zA-Z0-9_.+-]*)\b",
        text,
    ):
        key = canonical_requirement_id(raw_key)
        if any(item["requirement_id"] == key for item in items):
            continue
        items.append(explicit_item(key, raw_value, requirement_type="explicit_enum", evidence=f"{raw_key}={raw_value}"))

    for raw_name, raw_value in re.findall(
        r"\b([a-zA-Z][a-zA-Z0-9_-]*)\s+(?:width|wide)\s*(?:=|is|of)?\s*([0-9]+(?:\.[0-9]+)?)\s*mm\b",
        text,
        flags=re.IGNORECASE,
    ):
        items.append(explicit_item(f"{raw_name}_width", float(raw_value), unit="mm", evidence=f"{raw_name} width {raw_value} mm"))

    for raw_value, raw_name in re.findall(
        r"\b([0-9]+(?:\.[0-9]+)?)\s*mm\s+(?:wide|width)\s+([a-zA-Z][a-zA-Z0-9_-]*s)\b",
        text,
        flags=re.IGNORECASE,
    ):
        items.append(explicit_item(f"{raw_name.rstrip('s')}_width", float(raw_value), unit="mm", evidence=f"{raw_value} mm wide {raw_name}"))

    for raw_value, raw_name in re.findall(
        r"\b([0-9]+(?:\.[0-9]+)?)\s*mm\s+([a-zA-Z][a-zA-Z0-9_\s-]{0,40}?\s*spacing)\b",
        text,
        flags=re.IGNORECASE,
    ):
        name = canonical_requirement_id(raw_name)
        if name == "mounting_hole_spacing":
            name = "mount_hole_spacing"
        items.append(
            explicit_item(
                name,
                _clean_number(float(raw_value)),
                unit="mm",
                evidence=f"{raw_value} mm {raw_name}",
            )
        )

    lowered = text.lower()
    items.extend(_parse_capacity_phrases(text))
    items.extend(_parse_feature_semantics(text))
    if "label tabs" in lowered or "label_tabs" in lowered:
        items.append(explicit_item("label_tabs", True, requirement_type="explicit_feature", evidence="label tabs"))
    for feature in FEATURE_WORDS:
        normalized = canonical_requirement_id(feature)
        if re.search(rf"\b(no|without)\s+{re.escape(feature).replace('\\ ', r'\\s+')}\b", lowered):
            items.append(explicit_item(normalized, False, requirement_type="explicit_feature", evidence=f"no {feature}"))
    return items


def _dimension_component_names(key: str, count: int) -> list[str]:
    if key == "cell":
        return ["cell_width", "cell_depth"][:count]
    suffixes = list(DIMENSION_NAMES[:count])
    if key == "plate" and count >= 3:
        suffixes[2] = "thickness"
    return [f"{key}_{suffix}" for suffix in suffixes]


def _dimension_from_item(item: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_requirement_semantics(item)
    return {
        "id": item["requirement_id"],
        "requirement_id": item["requirement_id"],
        "label": item["label"],
        "value": item["value"],
        "unit": item.get("unit"),
        "tolerance": None,
        "source": item["source"],
        "importance": "critical",
        "protected": True,
        "authority": item["authority"],
        "authority_rank": item["authority_rank"],
        "kind": normalized["kind"],
        "operator": normalized["operator"],
        "subject": normalized.get("subject"),
        "object_type": normalized.get("object_type"),
        "target": normalized.get("target"),
        "raw_evidence": normalized.get("raw_evidence"),
    }


def _functional_requirement_from_item(item: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_requirement_semantics(item)
    return {
        "id": item["requirement_id"],
        "requirement_id": item["requirement_id"],
        "description": item.get("label") or f"{item['label']} {'enabled' if item.get('value') else 'disabled'}",
        "source": item["source"],
        "importance": "critical",
        "protected": True,
        "authority": item["authority"],
        "authority_rank": item["authority_rank"],
        "type": normalized.get("type"),
        "kind": normalized["kind"],
        "operator": normalized["operator"],
        "value": normalized.get("value"),
        "unit": normalized.get("unit"),
        "subject": normalized.get("subject"),
        "object_type": normalized.get("object_type"),
        "target": normalized.get("target"),
        "raw_evidence": normalized.get("raw_evidence"),
    }


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(item)
    item_id = canonical_requirement_id(str(normalized.get("requirement_id") or normalized.get("id") or ""))
    normalized["requirement_id"] = item_id
    normalized["id"] = item_id
    source = str(normalized.get("source") or "ai_assumption")
    authority = str(normalized.get("authority") or AUTHORITY_BY_SOURCE.get(source, "ai_assumption"))
    normalized["source"] = source
    normalized["authority"] = authority
    normalized["authority_rank"] = AUTHORITY_RANKS.get(authority, 99)
    normalized.setdefault("label", _human_label(item_id))
    normalized.setdefault("protected", authority == "explicit")
    normalized.setdefault("type", _requirement_type(item_id, normalized.get("value"), normalized.get("unit")))
    normalized.setdefault("evidence", {})
    return normalize_requirement_semantics(normalized)


def _matching_parameter(parameters: list[dict[str, Any]], requirement_id: str) -> dict[str, Any] | None:
    for parameter in parameters:
        if canonical_requirement_id(str(parameter.get("id") or "")) == requirement_id:
            return parameter
        provenance = parameter.get("provenance")
        relationship = provenance.get("relationship") if isinstance(provenance, dict) else None
        if relationship in {"derived_formula", "calculated", "standard_lookup"}:
            continue
        if canonical_requirement_id(str(parameter.get("source_requirement_id") or "")) == requirement_id:
            return parameter
    return None


def _derived_depends_on_requirement(derived: list[dict[str, Any]], requirement_id: str) -> bool:
    for parameter in derived:
        dependencies = parameter.get("source_requirement_ids") or parameter.get("depends_on") or []
        if requirement_id in {canonical_requirement_id(str(value)) for value in dependencies}:
            return True
    return False


def _question_restates_inventory(question: dict[str, Any], inventory: list[dict[str, Any]]) -> bool:
    text = " ".join(
        str(question.get(key) or "")
        for key in ("id", "question", "reason", "related_requirement_id")
    ).lower()
    for item in inventory:
        item_id = item["requirement_id"]
        words = item_id.replace("_", " ")
        if words in text or item_id in text:
            return True
        if item_id in {"cell_width", "cell_depth"} and "cell" in text and ("size" in text or "dimension" in text):
            return True
        if item_id.endswith("_count") and item_id.removesuffix("_count") in text and "count" in text:
            return True
        if item_id == "mount_hole_spacing" and "hole spacing" in text and (
            "mount" in text or "mounting" in text
        ):
            return True
    return False


def _stage_trace(stage: str, status: str, findings: list[dict[str, Any]]) -> dict[str, Any]:
    return {"stage": stage, "status": status, "findings": findings}


def _finding(
    rule_id: str,
    stage: str,
    message: str,
    *,
    expected_value: Any = None,
    detected_value: Any = None,
) -> dict[str, Any]:
    payload = {
        "rule_id": rule_id,
        "stage": stage,
        "severity": "critical",
        "is_blocking": True,
        "message": message,
    }
    if expected_value is not None:
        payload["expected_value"] = expected_value
    if detected_value is not None:
        payload["detected_value"] = detected_value
    return payload


def _rank(item: dict[str, Any]) -> int:
    return int(item.get("authority_rank") or AUTHORITY_RANKS.get(str(item.get("authority")), 99))


def _rank_from_source(source: Any) -> int:
    return AUTHORITY_RANKS.get(AUTHORITY_BY_SOURCE.get(str(source or ""), "ai_assumption"), 99)


def _requirement_type(requirement_id: str, value: Any, unit: str | None) -> str:
    if isinstance(value, bool):
        return "explicit_feature"
    if requirement_id.endswith("_count") or unit == "count":
        return "explicit_count"
    if isinstance(value, int | float):
        return "explicit_numeric"
    if isinstance(value, str):
        return "explicit_enum"
    return "missing_information"


def _kind_for_requirement_type(requirement_type: str) -> str:
    normalized = requirement_type.lower()
    if normalized in {"capacity", "minimum_capacity", "maximum_capacity"}:
        return "capacity"
    if normalized in {"count", "explicit_count", "exact_count", "minimum_count", "maximum_count"}:
        return "count"
    if "dimension" in normalized or normalized in {"numeric", "explicit_numeric", "clearance", "fit", "spacing", "position"}:
        return "dimension" if normalized not in {"clearance", "fit", "spacing", "position"} else normalized
    if normalized in {"feature_presence", "feature_absence", "explicit_feature"}:
        return "feature"
    if normalized in {
        "orientation",
        "containment",
        "support",
        "retention",
        "access",
        "removal_access",
        "relationship",
        "process_constraint",
        "qualitative_behavior",
    }:
        return normalized
    return normalized


def _operator_for_requirement(item: dict[str, Any], kind: str) -> str:
    requirement_type = str(item.get("type") or "").lower()
    value = item.get("value")
    semantic_text = " ".join(
        str(item.get(key) or "")
        for key in ("label", "description", "raw_evidence", "evidence")
    ).lower()
    if re.search(r"\bup\s+to\b", semantic_text):
        return "up_to"
    if re.search(r"\bat\s+least\b", semantic_text):
        return "at_least"
    if re.search(r"\bbetween\b", semantic_text) and isinstance(value, dict) and {"min", "max"} <= set(value):
        return "range"
    if re.search(r"\b(?:about|approximately|approx)\b", semantic_text):
        return "approximately"
    if re.search(r"\bexactly\b", semantic_text):
        return "exact"
    if requirement_type in {"explicit_maximum", "maximum", "maximum_dimension", "maximum_count", "maximum_capacity"}:
        return "maximum"
    if requirement_type in {"explicit_minimum", "minimum", "minimum_dimension", "minimum_count", "minimum_capacity"}:
        return "minimum"
    if requirement_type in {"range", "numeric_range"} or isinstance(value, dict) and {"min", "max"} <= set(value):
        return "range"
    if requirement_type in {"approximate", "approximately"}:
        return "approximately"
    if requirement_type in {"feature_presence"} or kind == "feature" and value is True:
        return "present"
    if requirement_type in {"feature_absence"} or kind == "feature" and value is False:
        return "absent"
    if requirement_type in {"qualitative_behavior"}:
        return "qualitative"
    return "exact"


def _capacity_language(text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:can|must|should|able\s+to)\b.{0,50}\b(?:hold|accommodate|fit)\b",
            text,
            flags=re.IGNORECASE,
        )
    )


def _parse_capacity_phrases(text: str) -> list[dict[str, Any]]:
    """Parse generic capacity language without product vocabulary."""

    number_words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    pattern = re.compile(
        r"\b(?:can|must|should|able\s+to)\s+(?:hold|accommodate|fit|support)\s+"
        r"(?:(?P<operator>up\s+to|at\s+least|exactly)\s+)?"
        r"(?P<value>\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
        r"(?P<object>[a-z0-9][a-z0-9 _-]*?)(?=\s*(?:[,.;]|$|\b(?:with|that|which|and|needs|suitable)\b))",
        flags=re.IGNORECASE,
    )
    range_pattern = re.compile(
        r"\b(?:can|must|should|able\s+to)\s+(?:hold|accommodate|fit|support)\s+"
        r"between\s+(?P<minimum>\d+)\s+and\s+(?P<maximum>\d+)\s+"
        r"(?P<object>[a-z0-9][a-z0-9 _-]*?)(?=\s*(?:[,.;]|$|\b(?:with|that|which|and|needs|suitable)\b))",
        flags=re.IGNORECASE,
    )
    items: list[dict[str, Any]] = []
    matches = list(pattern.finditer(text)) + list(range_pattern.finditer(text))
    for match in sorted(matches, key=lambda item: item.start()):
        object_phrase = str(match.group("object") or "").strip()
        object_type, unit = _object_semantics(object_phrase)
        if not object_type or not unit:
            continue
        if "minimum" in match.groupdict():
            value: Any = {
                "min": int(match.group("minimum")),
                "max": int(match.group("maximum")),
            }
            operator = "range"
        else:
            raw_value = str(match.group("value"))
            value = number_words.get(raw_value.lower())
            if value is None:
                value = int(raw_value)
            operator = str(match.group("operator") or "exact").replace(" ", "_").lower()
            if operator == "exactly":
                operator = "exact"
        requirement_id = f"{unit}_capacity"
        subject = _subject_before_capacity(text, match.start())
        items.append(
            explicit_item(
                requirement_id,
                value,
                unit=unit,
                label=f"{unit.replace('_', ' ').title()} capacity",
                requirement_type="capacity",
                evidence=match.group(0).strip(),
                kind="capacity",
                operator=operator,
                subject=subject,
                object_type=object_type,
                target=f"{unit}_storage",
            )
        )
    return items


def _parse_feature_semantics(text: str) -> list[dict[str, Any]]:
    """Preserve generic feature presence/absence without a product vocabulary."""

    items: list[dict[str, Any]] = []
    patterns = (
        ("absent", False, r"\b(?:without|no longer needs?|does not need|doesn't need)\s+(?:a|an|the)?\s*(?P<feature>[a-z][a-z0-9 _-]*?)(?=\s*(?:[,.;]|$|\band\b))"),
        ("present", True, r"\b(?:with|has|have|includes?|including)\s+(?:a|an|the)\s+(?P<feature>[a-z][a-z0-9_-]*)(?=\s*(?:[,.;]|$|\band\b))"),
    )
    for operator, value, pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            phrase = str(match.group("feature") or "").strip()
            object_type, unit = _object_semantics(phrase)
            if not object_type:
                continue
            requirement_id = canonical_requirement_id(object_type)
            items.append(
                explicit_item(
                    requirement_id,
                    value,
                    label=phrase.replace("_", " ").title(),
                    requirement_type="feature_absence" if not value else "feature_presence",
                    evidence=match.group(0).strip(),
                    kind="feature",
                    operator=operator,
                    object_type=object_type,
                    target=object_type,
                )
            )
    return items


def _object_semantics(phrase: str) -> tuple[str, str | None]:
    words = [
        token
        for token in re.findall(r"[a-z0-9]+", phrase.lower())
        if token not in {"a", "an", "the", "of", "sized", "type"}
    ]
    if not words:
        return "", None
    words[-1] = _singularize(words[-1])
    return canonical_requirement_id("_".join(words)), words[-1]


def _singularize(word: str) -> str:
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("ses") and len(word) > 4:
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def _subject_before_capacity(text: str, start: int) -> str | None:
    prefix = text[:start]
    match = re.search(
        r"\b(?:create|make|build|design)\s+(?:a|an|the)\s+([a-z0-9][a-z0-9 _-]*?)(?=\s*(?:,|\bthat\b|\bwhich\b|\bcan\b))",
        prefix,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return canonical_requirement_id(match.group(1).strip())


def _default_unit_for_id(requirement_id: str) -> str | None:
    if requirement_id.endswith("_count"):
        return "count"
    return None


def _clean_number(value: float) -> float | int:
    return int(value) if value.is_integer() else value


def _human_label(value: str) -> str:
    return value.replace("_", " ").title()
