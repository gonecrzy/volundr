"""Requirement-led post-worker compliance aggregation.

This module interprets existing geometric and functional evidence.  It does
not infer a source representation or create a second geometry validator.
"""

from __future__ import annotations

from typing import Any, Iterable

from app.services.geometry.invariants import GeometricFinding


def evaluate_requirement_compliance(
    requirements: list[dict[str, Any]],
    *,
    evidence: Iterable[GeometricFinding] = (),
    present_feature_ids: set[str] | None = None,
) -> list[GeometricFinding]:
    evidence_by_requirement: dict[str, list[GeometricFinding]] = {}
    for finding in evidence:
        for key in _evidence_keys(finding):
            evidence_by_requirement.setdefault(key, []).append(finding)
    results: list[GeometricFinding] = []
    for requirement in requirements:
        if not isinstance(requirement, dict) or not requirement.get("requirement_id"):
            continue
        requirement_id = str(requirement["requirement_id"])
        requirement_type = str(requirement.get("type") or "qualitative_behavior")
        matches = evidence_by_requirement.get(requirement_id, [])
        if matches:
            result = _from_evidence(requirement, matches)
        elif requirement_type == "feature_presence" and present_feature_ids is not None:
            present = requirement_id in {str(item) for item in present_feature_ids}
            result = _finding(
                requirement,
                state="verified" if present else "violated",
                detected=present,
                blocking=not present,
                explanation=(
                    "The required feature is present in the generated geometry."
                    if present
                    else "The required feature is absent from source or worker evidence."
                ),
            )
        else:
            result = _finding(
                requirement,
                state="human_review",
                detected=None,
                blocking=False,
                explanation="The generated artifact does not provide reliable automatic evidence for this requirement.",
                metadata={"review_recommendation": "test_print_recommended"},
            )
        results.append(result)
    return results


def _from_evidence(
    requirement: dict[str, Any],
    evidence: list[GeometricFinding],
) -> GeometricFinding:
    blocking = any(item.is_blocking or item.verification_state == "violated" for item in evidence)
    if blocking:
        selected = next((item for item in evidence if item.verification_state == "violated"), evidence[0])
        return _finding(
            requirement,
            state="violated",
            expected=selected.expected_value,
            detected=selected.detected_value,
            unit=selected.unit,
            tolerance=selected.tolerance,
            confidence=selected.confidence,
            blocking=True,
            explanation=selected.explanation,
            metadata={"evidence_rule_ids": [item.rule_id for item in evidence]},
        )
    selected = next((item for item in evidence if item.verification_state == "verified"), evidence[0])
    if selected.verification_state in {"unverifiable", "human_review"}:
        return _finding(
            requirement,
            state="human_review",
            expected=selected.expected_value,
            detected=selected.detected_value,
            unit=selected.unit,
            tolerance=selected.tolerance,
            confidence=selected.confidence,
            blocking=False,
            explanation=selected.explanation,
            metadata={
                "evidence_rule_ids": [item.rule_id for item in evidence],
                "review_recommendation": "test_print_recommended",
            },
        )
    return _finding(
        requirement,
        state="verified",
        expected=selected.expected_value,
        detected=selected.detected_value,
        unit=selected.unit,
        tolerance=selected.tolerance,
        confidence=selected.confidence,
        blocking=False,
        explanation=selected.explanation,
        metadata={"evidence_rule_ids": [item.rule_id for item in evidence]},
    )


def _finding(
    requirement: dict[str, Any],
    *,
    state: str,
    detected: Any,
    blocking: bool,
    explanation: str,
    expected: Any = None,
    unit: str | None = None,
    tolerance: float | None = None,
    confidence: float = 0.0,
    metadata: dict[str, Any] | None = None,
) -> GeometricFinding:
    requirement_id = str(requirement["requirement_id"])
    return GeometricFinding(
        rule_id=f"requirement.{requirement_id}",
        requirement_id=requirement_id,
        verification_state=state,
        expected_value=expected if expected is not None else requirement.get("value"),
        detected_value=detected,
        unit=unit or requirement.get("unit"),
        tolerance=tolerance if tolerance is not None else _number(requirement.get("tolerance")),
        confidence=confidence,
        severity="critical" if blocking else "warning",
        is_blocking=blocking,
        title="Active requirement compliance",
        explanation=explanation,
        suggested_correction="Create a new version that satisfies the active requirement.",
        metadata=metadata or {},
    )


def _number(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _evidence_keys(finding: GeometricFinding) -> set[str]:
    keys: set[str] = set()
    if finding.requirement_id:
        keys.add(str(finding.requirement_id))
    if finding.feature_id:
        keys.add(str(finding.feature_id))
    rule_leaf = str(finding.rule_id or "").rsplit(".", 1)[-1]
    if rule_leaf:
        keys.add(rule_leaf)
    return keys
