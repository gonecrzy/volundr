from __future__ import annotations

from app.services.geometry.invariants import GeometricFinding
from app.services.geometry.requirement_compliance import evaluate_requirement_compliance


def _finding(
    requirement_id: str,
    state: str,
    *,
    expected=None,
    detected=None,
    blocking: bool = False,
) -> GeometricFinding:
    return GeometricFinding(
        rule_id=f"functional.{requirement_id}",
        requirement_id=requirement_id,
        verification_state=state,
        expected_value=expected,
        detected_value=detected,
        unit="mm",
        tolerance=0.2,
        confidence=0.95,
        severity="critical" if blocking else "warning",
        is_blocking=blocking,
        title=requirement_id,
        explanation=requirement_id,
        suggested_correction="revise",
    )


def test_measured_requirement_violation_blocks_promotion() -> None:
    findings = evaluate_requirement_compliance(
        [
            {
                "requirement_id": "mounting_hole_count",
                "type": "count",
                "value": 2,
                "explicit": True,
            }
        ],
        evidence=[_finding("mounting_hole_count", "violated", expected=2, detected=1, blocking=True)],
    )

    result = findings[0]
    assert result.verification_state == "violated"
    assert result.is_blocking is True


def test_qualitative_uncertainty_is_human_review_not_false_failure() -> None:
    findings = evaluate_requirement_compliance(
        [
            {
                "requirement_id": "one_handed_removal",
                "type": "removal_access",
                "value": "accessible with one hand",
                "explicit": True,
            }
        ],
        evidence=[],
    )

    result = findings[0]
    assert result.verification_state == "human_review"
    assert result.is_blocking is False
    assert result.metadata["review_recommendation"] == "test_print_recommended"


def test_missing_required_feature_is_blocking_when_source_evidence_proves_absence() -> None:
    findings = evaluate_requirement_compliance(
        [
            {
                "requirement_id": "retention_feature",
                "type": "feature_presence",
                "value": True,
                "explicit": True,
            }
        ],
        evidence=[],
        present_feature_ids={"holder_body"},
    )

    result = findings[0]
    assert result.verification_state == "violated"
    assert result.is_blocking is True


def test_verified_requirement_is_reported_without_new_blocking_finding() -> None:
    findings = evaluate_requirement_compliance(
        [
            {
                "requirement_id": "bottle_diameter",
                "type": "exact_dimension",
                "value": 81,
                "unit": "mm",
                "explicit": True,
            }
        ],
        evidence=[_finding("bottle_diameter", "verified", expected=81, detected=81)],
    )

    assert findings[0].verification_state == "verified"
    assert findings[0].is_blocking is False

