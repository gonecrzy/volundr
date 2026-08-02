import math

import pytest

from volundr_cad.patterns import (
    PatternSpecError,
    circular_pattern_points,
    linear_pattern_points,
    rectangular_pattern_points,
    resolve_pattern_points,
)
from app.services.cad.patterns import normalize_pattern_specs


def test_linear_pattern_count_one_is_origin() -> None:
    result = linear_pattern_points(count=1, spacing=50.0, axis="Z", centered=True)

    assert result.points == ((0.0, 0.0, 0.0),)
    assert result.provenance["effect_parameter_ids"] == []
    assert result.content_hash == linear_pattern_points(count=1, spacing=50.0, axis="Z", centered=True).content_hash


def test_linear_pattern_centers_even_and_odd_counts() -> None:
    even = linear_pattern_points(count=4, spacing=10.0, axis="Z", centered=True)
    odd = linear_pattern_points(count=3, spacing=10.0, axis="X", centered=True)

    assert even.points == ((0.0, 0.0, -15.0), (0.0, 0.0, -5.0), (0.0, 0.0, 5.0), (0.0, 0.0, 15.0))
    assert odd.points == ((-10.0, 0.0, 0.0), (0.0, 0.0, 0.0), (10.0, 0.0, 0.0))


def test_linear_pattern_supports_origin_and_spacing_changes() -> None:
    result = linear_pattern_points(count=2, spacing=12.5, axis="Y", centered=True, origin=(1.0, 2.0, 3.0))

    assert result.points == ((1.0, -4.25, 3.0), (1.0, 8.25, 3.0))
    assert result.content_hash != linear_pattern_points(count=2, spacing=10.0, axis="Y", centered=True, origin=(1.0, 2.0, 3.0)).content_hash


def test_rectangular_and_circular_patterns_have_canonical_order() -> None:
    grid = rectangular_pattern_points(rows=2, columns=3, row_spacing=4.0, column_spacing=10.0, plane="XZ")
    circle = circular_pattern_points(count=4, radius=5.0, start_angle=math.pi / 2)

    assert grid.points == (
        (-10.0, 0.0, -2.0),
        (0.0, 0.0, -2.0),
        (10.0, 0.0, -2.0),
        (-10.0, 0.0, 2.0),
        (0.0, 0.0, 2.0),
        (10.0, 0.0, 2.0),
    )
    assert circle.points[0] == pytest.approx((0.0, 5.0, 0.0))
    assert len(circle.points) == 4


def test_patterns_reject_invalid_counts_axes_planes_and_nonfinite_values() -> None:
    with pytest.raises(PatternSpecError, match="positive integer"):
        linear_pattern_points(count=0, spacing=10.0, axis="Z")
    with pytest.raises(PatternSpecError, match="finite"):
        linear_pattern_points(count=2, spacing=float("nan"), axis="Z")
    with pytest.raises(PatternSpecError, match="axis"):
        linear_pattern_points(count=2, spacing=10.0, axis="Q")
    with pytest.raises(PatternSpecError, match="plane"):
        rectangular_pattern_points(rows=2, columns=2, row_spacing=1.0, column_spacing=1.0, plane="Q")


def test_design_plan_pattern_resolves_count_and_spacing_provenance() -> None:
    result = resolve_pattern_points(
        {
            "pattern_id": "mounting_hole_pattern",
            "pattern_type": "linear",
            "count_parameter_id": "mounting_screw_count",
            "spacing_parameter_id": "screw_spacing_vertical",
            "axis": "Z",
            "centered": True,
        },
        {
            "mounting_screw_count": 2,
            "screw_spacing_vertical": 81.0,
        },
    )

    assert result.points == ((0.0, 0.0, -40.5), (0.0, 0.0, 40.5))
    assert result.provenance["pattern_id"] == "mounting_hole_pattern"
    assert result.provenance["source_parameter_ids"] == ["mounting_screw_count", "screw_spacing_vertical"]


def test_repeated_mounting_feature_receives_generic_pattern_spec_when_plan_omits_one() -> None:
    plan = {
        "units": "mm",
        "parameters": [
            {"id": "mounting_screw_count", "value": 2, "unit": "count"},
            {"id": "screw_spacing_vertical", "value": 50.0, "unit": "mm"},
        ],
        "components": [{"id": "body"}],
        "features": [{
            "id": "rear_mounting_flange",
            "component_id": "body",
            "type": "wall",
            "description": "Vertical mounting screw holes",
            "parameters": ["mounting_screw_count", "screw_spacing_vertical"],
        }],
        "functional_contract": {"mounting_interfaces": [{"component_id": "body", "arrangement_axis": "Z"}]},
    }

    normalized = normalize_pattern_specs(plan)

    assert normalized["patterns"] == [{
        "pattern_id": "rear_mounting_flange_pattern",
        "owning_feature_id": "rear_mounting_flange",
        "owning_component_id": "body",
        "pattern_type": "linear",
        "point_parameter_id": "rear_mounting_flange_points",
        "count_parameter_id": "mounting_screw_count",
        "spacing_parameter_id": "screw_spacing_vertical",
        "axis": "Z",
        "centered": True,
        "origin": [0.0, 0.0, 0.0],
        "unit": "mm",
    }]


def test_pattern_point_id_collision_is_replaced_by_stable_scaffold_id() -> None:
    normalized = normalize_pattern_specs({
        "parameters": [{"id": "screw_spacing_vertical", "value": 50.0}],
        "patterns": [{
            "pattern_id": "mounting_screw_pattern",
            "owning_feature_id": "holes",
            "point_parameter_id": "screw_spacing_vertical",
            "pattern_type": "linear",
            "count_parameter_id": "count",
            "spacing_parameter_id": "screw_spacing_vertical",
            "axis": "Z",
        }],
    })

    assert normalized["patterns"][0]["point_parameter_id"] == "mounting_screw_pattern_points"
