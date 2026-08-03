from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


COMPARISON_FIELDS = (
    "response_structure",
    "requirements",
    "planning",
    "execution",
    "outcome",
)


@dataclass(frozen=True)
class ControlledComparison:
    controlled: bool
    mismatches: list[dict[str, Any]]


def _numeric_equal(left: float, right: float, tolerance: float = 0.001) -> bool:
    return math.isclose(left, right, rel_tol=tolerance, abs_tol=tolerance)


def _ordered(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _ordered(nested) for key, nested in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, list):
        normalized = [_ordered(item) for item in value]
        if all(isinstance(item, dict) and item.get("id") is not None for item in normalized):
            return sorted(normalized, key=lambda item: str(item["id"]))
        return normalized
    return value


def semantic_equal(left: Any, right: Any, *, tolerance: float = 0.001) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return _numeric_equal(float(left), float(right), tolerance)
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        if set(left) != set(right):
            return False
        return all(semantic_equal(left[key], right[key], tolerance=tolerance) for key in left)
    if isinstance(left, list):
        ordered_left = _ordered(left)
        ordered_right = _ordered(right)
        return len(ordered_left) == len(ordered_right) and all(
            semantic_equal(a, b, tolerance=tolerance) for a, b in zip(ordered_left, ordered_right)
        )
    return left == right


def classify_field(
    left: Any,
    right: Any,
    *,
    failure_a: str | None = None,
    failure_b: str | None = None,
) -> str:
    if failure_a and failure_b:
        return "both_failed_same_signature" if failure_a == failure_b else "both_failed_different_signature"
    if (left is None) != (right is None):
        return "one_sided_failure"
    if left == right:
        return "identical"
    if semantic_equal(left, right):
        return "semantically_equivalent"
    if isinstance(left, (int, float)) and isinstance(right, (int, float)) and _numeric_equal(float(left), float(right)):
        return "acceptably_variable"
    return "materially_inconsistent"


def failure_signature(evidence: dict[str, Any]) -> str | None:
    workspace = evidence.get("workspace")
    if isinstance(workspace, dict):
        integrity = workspace.get("artifact_integrity")
        if isinstance(integrity, dict) and integrity.get("missing_count", 0):
            return "missing_artifacts"

    authoritative_failure_values: list[str] = []
    attempts = evidence.get("generation_attempts")
    if isinstance(attempts, list):
        for attempt in attempts:
            if isinstance(attempt, dict):
                for key in ("failure_class", "error_category", "status"):
                    value = attempt.get(key)
                    if value:
                        authoritative_failure_values.append(str(value).casefold())
    responses = evidence.get("chat_responses")
    if isinstance(responses, list):
        for item in responses:
            if not isinstance(item, dict):
                continue
            response = item.get("response")
            if not isinstance(response, dict):
                continue
            blocked_attempt = response.get("blocked_attempt")
            if isinstance(blocked_attempt, dict):
                for key in ("failure_class", "error_category", "status"):
                    value = blocked_attempt.get(key)
                    if value:
                        authoritative_failure_values.append(str(value).casefold())
    for value in authoritative_failure_values:
        if "provider" in value:
            return "provider_failure"
        if "schema" in value:
            return "provider_schema_error"
        if "worker" in value:
            return "worker_failure"

    category = str(evidence.get("outcome_category") or evidence.get("failure_class") or "").casefold()
    message = str(evidence.get("error") or evidence.get("final_outcome") or "").casefold()
    combined = f"{category} {message}"
    for token, signature in (
        ("clarification", "unanswered_essential_clarification"),
        ("worker", "worker_failure"),
        ("timeout", "workflow_timeout"),
        ("schema", "provider_schema_error"),
        ("provider", "provider_failure"),
        ("retry", "retry_exhausted"),
    ):
        if token in combined:
            return signature
    if category in {"failed", "incomplete", "cancelled"}:
        return category
    return None


def controlled_comparison(first: dict[str, Any], second: dict[str, Any]) -> ControlledComparison:
    fields = (
        "git_head",
        "migration_head",
        "provider",
        "model_policy",
        "prompt_versions",
        "configuration_hash",
        "build_identities",
    )
    mismatches = [
        {"field": field, "first": first.get(field), "second": second.get(field)}
        for field in fields
        if first.get(field) != second.get(field)
    ]
    return ControlledComparison(controlled=not mismatches, mismatches=mismatches)


def _dimension_value(evidence: dict[str, Any], dimension: str) -> Any:
    if dimension == "response_structure":
        return evidence.get("chat_responses")
    if dimension == "requirements":
        return evidence.get("requirements") or evidence.get("design_specification")
    if dimension == "planning":
        return evidence.get("planning") or evidence.get("design_plan")
    if dimension == "execution":
        return {"workflow_events": evidence.get("workflow_events"), "generation_attempts": evidence.get("generation_attempts")}
    if dimension == "outcome":
        return {
            "workspace": evidence.get("workspace"),
            "revisions": evidence.get("revisions"),
            "exports": evidence.get("exports"),
        }
    return None


def _score(classification: str) -> float:
    return {
        "identical": 1.0,
        "semantically_equivalent": 1.0,
        "acceptably_variable": 0.75,
        "both_failed_same_signature": 0.5,
        "one_sided_failure": 0.0,
        "both_failed_different_signature": 0.0,
        "materially_inconsistent": 0.0,
    }.get(classification, 0.0)


def compare_evidence(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    first_failure = failure_signature(first)
    second_failure = failure_signature(second)
    fields: dict[str, dict[str, Any]] = {}
    scores: dict[str, dict[str, Any]] = {}
    for dimension in COMPARISON_FIELDS:
        left = _dimension_value(first, dimension)
        right = _dimension_value(second, dimension)
        classification = classify_field(left, right, failure_a=first_failure, failure_b=second_failure)
        fields[dimension] = {"classification": classification}
        scores[dimension] = {"score": _score(classification), "classification": classification}
    return {
        "schema_version": "gemini-consistency-comparison-v1",
        "failure_signatures": {"first": first_failure, "second": second_failure},
        "fields": fields,
        "scores": scores,
        "overall_score": sum(item["score"] for item in scores.values()) / len(scores),
    }
