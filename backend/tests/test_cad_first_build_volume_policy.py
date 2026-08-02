from app.schemas.printability import PrintabilityDetectedValue, PrintabilityResult
from app.services.projects.service import ProjectService


def _result(*, rule_id: str, severity: str) -> PrintabilityResult:
    return PrintabilityResult(
        severity=severity,  # type: ignore[arg-type]
        rule_id=rule_id,
        detected_value=PrintabilityDetectedValue(value=64.0, units="mm"),
        explanation="evidence",
        suggested_correction="review",
        orientation_dependent=True,
    )


def test_build_volume_is_advisory_for_cad_first_promotion() -> None:
    service = ProjectService(db=None, ai_provider=None)  # type: ignore[arg-type]

    assert service._is_blocking_printability_result(
        _result(rule_id="profile.build_volume", severity="Warning")
    ) is False


def test_unrelated_critical_printability_gate_remains_blocking() -> None:
    service = ProjectService(db=None, ai_provider=None)  # type: ignore[arg-type]

    assert service._is_blocking_printability_result(
        _result(rule_id="feature.minimum_thickness", severity="Critical")
    ) is True
