import pytest

from app.services.cad.runtime_diagnostics import (
    classify_worker_diagnostic,
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


def test_localized_cadquery_selector_failure_is_repairable() -> None:
    traceback = """Traceback (most recent call last):
  File \"model.py\", line 38, in _ai_component_primary_part
    body = body.edges('>Z and not outer_d').chamfer(chamfer_sz)
pyparsing.exceptions.ParseException: Expected end of text, found 'and'
"""

    finding = classify_worker_diagnostic(
        "pyparsing.exceptions.ParseException: Expected end of text, found 'and'",
        traceback=traceback,
    )

    assert finding is not None
    assert finding["rule_id"] == "geometry_body.cadquery_selector_failure"
    assert finding["function_id"] == "_ai_component_primary_part"
    assert finding["source_statement"].startswith("body = body.edges")
    assert finding["selector"] == ">Z and not outer_d"
    assert runtime_repair_is_eligible(finding)


def test_localized_cadquery_api_attribute_failure_is_repairable() -> None:
    traceback = """Traceback (most recent call last):
  File "model.py", line 38, in _ai_component_primary_part
    r1 = cq.impr.math.radians(a1)
AttributeError: module 'cadquery' has no attribute 'impr'
"""

    finding = classify_worker_diagnostic(
        "AttributeError: module 'cadquery' has no attribute 'impr'",
        traceback=traceback,
    )

    assert finding is not None
    assert finding["rule_id"] == "geometry_body.cadquery_api_failure"
    assert finding["function_id"] == "_ai_component_primary_part"
    assert finding["source_statement"] == "r1 = cq.impr.math.radians(a1)"
    assert runtime_repair_is_eligible(finding)


def test_localized_cadquery_workplane_type_failure_is_repairable() -> None:
    traceback = """Traceback (most recent call last):
  File "model.py", line 40, in _ai_feature_mounting_backplate
    body = body.workplane('XY').rect(width, height).extrude(thickness)
TypeError: Multiplied(): incompatible function arguments
"""

    finding = classify_worker_diagnostic(
        "TypeError: Multiplied(): incompatible function arguments",
        traceback=traceback,
    )

    assert finding is not None
    assert finding["rule_id"] == "geometry_body.cadquery_api_failure"
    assert finding["function_id"] == "_ai_feature_mounting_backplate"
    assert finding["exception_type"] == "CadQuery API type failure"
    assert runtime_repair_is_eligible(finding)


def test_localized_pattern_profile_failure_is_repairable() -> None:
    traceback = """Traceback (most recent call last):
  File "model.py", line 43, in _ai_feature_slots
    cutters = place_pattern_cutters(profile, points, coordinate_space="component_local_3d")
TypeError: pattern cutter profile must be a volumetric Solid or Compound; close and extrude the profile before placing it
"""

    finding = classify_worker_diagnostic(
        "TypeError: pattern cutter profile must be a volumetric Solid or Compound; close and extrude the profile before placing it",
        traceback=traceback,
    )

    assert finding is not None
    assert finding["rule_id"] == "geometry_body.cadquery_api_failure"
    assert finding["function_id"] == "_ai_feature_slots"
    assert "place_pattern_cutters" in finding["source_statement"]
    assert runtime_repair_is_eligible(finding)


def test_solid_count_failure_localizes_one_tangent_additive_feature() -> None:
    source = """
def _ai_component_body(params):
    return cq.Workplane('XY').box(10, 10, 10)

def _ai_feature_handle(body, params):
    handle = cq.Workplane('YZ').circle(2).extrude(2)
    modified_shape = body.union(handle)
    return modified_shape
"""
    finding = classify_worker_diagnostic(
        "output shape is invalid",
        source=source,
        worker_metadata={
            "outputs": [
                {
                    "topology_metadata": {
                        "outcome": "solid_count_mismatch",
                        "expected_solid_count": 1,
                        "detected_solid_count": 2,
                    }
                }
            ]
        },
    )

    assert finding is not None
    assert finding["rule_id"] == "geometry_body.disconnected_integral_feature"
    assert finding["function_id"] == "_ai_feature_handle"
    assert runtime_repair_is_eligible(finding)


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
