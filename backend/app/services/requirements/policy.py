"""Application-owned policy routing for normalized requirements.

Provider extraction may describe semantic roles, but it does not own the
completion policy.  This module is the single application boundary that
turns normalized authority and semantic structure into the policy consumed by
the executable contract and semantic evaluator.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any


REQUIREMENT_POLICY_VERSION = "product-requirement-policy-v1"
REQUIREMENT_POLICIES = frozenset({"machine_required", "review_required", "informational"})

_FLEXIBLE_AUTHORITIES = frozenset({"flexible", "provisional", "proposed", "ai_assumption"})
_MODEL_SOURCES = frozenset({"ai_assumption", "volundr_proposal", "product_default", "calculated"})
_DELEGATED_ROLES = frozenset({"delegated_choice", "model_choice", "design_choice"})
_HARD_ROLES = frozenset({"hard_constraint", "structural_intent"})
_QUALITATIVE_ROLES = frozenset({"qualitative_objective", "review_required"})
_QUALITATIVE_KINDS = frozenset(
    {
        "qualitative",
        "qualitative_behavior",
        "support",
        "retention",
        "access",
        "removal_access",
        "orientation",
        "usability",
        "function",
        "process_constraint",
    }
)
_HARD_KINDS = frozenset(
    {
        "dimension",
        "clearance",
        "count",
        "capacity",
        "fit",
        "compatibility",
        "spacing",
        "position",
        "interface",
        "mechanical_relationship",
    }
)
_HARD_OPERATORS = frozenset(
    {"exact", "minimum", "maximum", "range", "up_to", "at_least", "present", "absent", "approximately"}
)
_NONBLOCKING_POLICIES = frozenset({"informational", "review_required", "review_only", "human_review"})


def resolve_product_requirement_policy(requirement: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy with application-owned policy and authority semantics.

    The resolver is deliberately conservative.  Flexible/model authority is
    nonblocking only when normalized provenance proves it.  Conversely,
    explicit structured facts remain machine-required even when provider
    metadata requests a softer classification.  Ambiguous required records
    use the fail-closed machine-required default.
    """

    result = deepcopy(dict(requirement))
    explicit = _explicit(result)
    authority = _authority(result, explicit)
    role = _role(result)
    flexible = _is_flexible_choice(result, explicit, authority, role)
    hard = _is_hard_structured_requirement(result, explicit, role, flexible)

    if flexible and not hard:
        policy = "informational"
        reason = "normalized_flexible_or_delegated_choice"
        authority = "flexible"
        result["explicit"] = False
        result["protected"] = False
    elif hard:
        policy = "machine_required"
        reason = "explicit_or_structural_hard_floor"
    elif _is_design_context(result, role):
        policy = "informational"
        reason = "pure_design_context"
    elif _is_qualitative_objective(result, role):
        policy = "review_required"
        reason = "explicit_qualitative_objective"
    else:
        policy = "machine_required"
        reason = "fail_closed_default"

    result["authority"] = authority
    result["policy"] = policy
    result["classification"] = policy
    result["policy_version"] = REQUIREMENT_POLICY_VERSION
    result["policy_source"] = "application"
    result["policy_reason"] = reason
    return result


def _explicit(item: Mapping[str, Any]) -> bool:
    if isinstance(item.get("explicit"), bool):
        return bool(item["explicit"])
    source = str(item.get("source") or "").strip().lower()
    authority = str(item.get("authority") or "").strip().lower()
    return source in {"initial_user", "clarification_user", "revision_user", "physical_test_feedback", "user", "clarification"} or authority == "explicit"


def _authority(item: Mapping[str, Any], explicit: bool) -> str:
    value = str(item.get("authority") or "").strip().lower()
    if value:
        return value
    if explicit:
        return "explicit"
    source = str(item.get("source") or "").strip().lower()
    return "flexible" if source in _MODEL_SOURCES else "provisional"


def _role(item: Mapping[str, Any]) -> str:
    return str(item.get("semantic_role") or "").strip().lower()


def _is_flexible_choice(
    item: Mapping[str, Any],
    explicit: bool,
    authority: str,
    role: str,
) -> bool:
    provenance = item.get("provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}
    authority_semantics = str(provenance.get("authority_semantics") or "").strip().lower()
    delegated = role in _DELEGATED_ROLES or bool(item.get("delegated")) or authority_semantics == "user_delegated_choice"
    model_origin = str(item.get("source") or "").strip().lower() in _MODEL_SOURCES
    if explicit:
        return (delegated or authority in _FLEXIBLE_AUTHORITIES) and not _has_explicit_fixed_value(item)
    return delegated or authority in _FLEXIBLE_AUTHORITIES or model_origin


def _has_explicit_fixed_value(item: Mapping[str, Any]) -> bool:
    if item.get("explicit") is not True:
        return False
    kind = _kind(item)
    operator = _operator(item)
    value = _value(item)
    return (
        operator in _HARD_OPERATORS
        and (kind in _HARD_KINDS or _is_numeric(value) or _is_bounds(value))
    )


def _is_hard_structured_requirement(
    item: Mapping[str, Any],
    explicit: bool,
    role: str,
    flexible: bool,
) -> bool:
    if not explicit:
        return False
    if role in _HARD_ROLES:
        return True
    if item.get("verification_policy") and not flexible and str(item.get("verification_policy")) not in _NONBLOCKING_POLICIES:
        return True

    kind = _kind(item)
    operator = _operator(item)
    value = _value(item)
    if operator in _HARD_OPERATORS and (kind in _HARD_KINDS or _is_numeric(value) or _is_bounds(value)):
        return True
    if kind in _HARD_KINDS and (operator != "qualitative" or kind in {"fit", "compatibility", "interface"}):
        return True
    if kind in {"feature", "feature_presence", "feature_absence"} and operator in {"present", "absent"}:
        return True
    if _is_required_output_structure(item):
        return True
    if _is_structural_feature_claim(item):
        return True
    return False


def _is_qualitative_objective(item: Mapping[str, Any], role: str) -> bool:
    if role in _QUALITATIVE_ROLES:
        return True
    kind = _kind(item)
    operator = _operator(item)
    return kind in _QUALITATIVE_KINDS or (kind == "feature" and operator == "qualitative") or (
        kind == "relationship" and operator == "qualitative"
    )


def _is_design_context(item: Mapping[str, Any], role: str) -> bool:
    if role in {"design_context", "context", "descriptive_context"}:
        return True
    kind = _kind(item)
    return kind in {"design_context", "context", "object_type", "purpose"}


def _is_required_output_structure(item: Mapping[str, Any]) -> bool:
    kind = _kind(item)
    text = _text(item)
    output_signal = kind in {"output", "printable_output", "output_count", "component_count", "part_count"}
    output_signal = output_signal or any(token in text for token in ("output count", "printable output", "separately printable", "required output"))
    return output_signal and (item.get("required", True) is not False or item.get("explicit") is True)


def _is_structural_feature_claim(item: Mapping[str, Any]) -> bool:
    if _role(item) in _HARD_ROLES:
        return True
    if _kind(item) != "feature" or _operator(item) != "qualitative":
        return False
    text = _text(item)
    # These are generic structural nouns, not project-specific feature rules.
    return any(token in text for token in ("path", "opening", "channel", "passage", "airflow", "vent", "cavity", "contain", "enclose"))


def _kind(item: Mapping[str, Any]) -> str:
    return str(item.get("kind") or item.get("type") or "").strip().lower()


def _operator(item: Mapping[str, Any]) -> str:
    return str(item.get("operator") or "").strip().lower()


def _value(item: Mapping[str, Any]) -> Any:
    if "expected" in item:
        expected = item.get("expected")
        if isinstance(expected, Mapping) and set(expected) == {"value"}:
            return expected.get("value")
        return expected
    return item.get("value")


def _is_bounds(value: Any) -> bool:
    return isinstance(value, Mapping) and {"width", "depth", "height"}.issubset(value)


def _is_numeric(value: Any) -> bool:
    if isinstance(value, bool) or isinstance(value, Mapping) or isinstance(value, (list, tuple, set)):
        return False
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return value is not None


def _text(item: Mapping[str, Any]) -> str:
    return " ".join(
        str(item.get(key) or "").strip().lower()
        for key in ("requirement_id", "id", "label", "description", "subject", "object_type", "raw_evidence", "value")
    )
