import pytest

from app.services.cad.runtime_diagnostics import (
    classify_worker_name_failure,
    runtime_repair_is_eligible,
)
from app.services.cad.python_symbols import analyze_scaffold_source


@pytest.mark.parametrize(
    ("message", "rule_id", "symbol"),
    [
        (
            "NameError: name 'plate_width' is not defined",
            "geometry_body.unbound_name",
            "plate_width",
        ),
        (
            "UnboundLocalError: cannot access local variable 'width' where it is not associated with a value",
            "geometry_body.conditionally_bound_name",
            "width",
        ),
    ],
)
def test_runtime_name_failures_are_classified_without_geometry_claims(
    message: str, rule_id: str, symbol: str
) -> None:
    finding = classify_worker_name_failure(
        message,
        traceback='  File "model.py", line 19, in _ai_component_primary_part\n'
        + message,
    )

    assert finding is not None
    assert finding["rule_id"] == rule_id
    assert finding["symbol"] == symbol
    assert finding["function_id"] == "_ai_component_primary_part"
    assert finding["category"] == "source_runtime"
    assert runtime_repair_is_eligible(finding)


def test_runtime_failure_without_safe_function_identification_is_not_guessed() -> None:
    finding = classify_worker_name_failure("NameError: name 'width' is not defined")

    assert finding is not None
    assert finding["function_id"] is None
    assert not runtime_repair_is_eligible(finding)


def test_non_name_worker_failure_is_not_misclassified() -> None:
    assert classify_worker_name_failure("ValueError: invalid CadQuery shape") is None


def test_deterministic_scaffold_names_are_checked_separately_from_provider_bodies() -> None:
    assert analyze_scaffold_source(
        "import cadquery as cq\n"
        "def build(params):\n"
        "    body = cq.Workplane('XY')\n"
        "    return body\n"
    ) == []

    findings = analyze_scaffold_source(
        "import cadquery as cq\n"
        "def build(params):\n"
        "    body = cq.Workplane('XY').box(missing_width, 1, 1)\n"
        "    return body\n"
    )

    assert findings[0]["rule_id"] == "geometry_body.unbound_name"
    assert findings[0]["function_id"] == "build"
