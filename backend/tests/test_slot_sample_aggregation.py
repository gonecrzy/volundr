from __future__ import annotations

from app.services.geometry.feature_measurements import measure_slots


def _sample(
    *,
    width: float | None = 21.0,
    depth: float | None = 6.0,
    through: bool = True,
    region: str = "north",
) -> dict[str, object]:
    sample: dict[str, object] = {
        "through": through,
        "region": region,
    }
    if width is not None:
        sample["width"] = width
    if depth is not None:
        sample["depth"] = depth
    return sample


def _measure(samples: list[dict[str, object]], *, expected_count: int = 2, region: str | None = "north"):
    return measure_slots(
        samples,
        expected_count=expected_count,
        expected_width=21.0,
        expected_depth=6.0,
        tolerance=0.2,
        required_region=region,
    )


def test_all_qualifying_samples_matching_dimensions_pass() -> None:
    result = _measure([_sample(), _sample()])

    assert result.satisfied is True
    assert result.measurements["count"] == 2
    assert result.measurements["through_count"] == 2


def test_one_sample_with_wrong_width_fails_the_group() -> None:
    result = _measure([_sample(), _sample(width=22.0)])

    assert result.satisfied is False


def test_one_sample_with_wrong_depth_fails_the_group() -> None:
    result = _measure([_sample(), _sample(depth=7.0)])

    assert result.satisfied is False


def test_one_sample_with_both_dimensions_wrong_fails_the_group() -> None:
    result = _measure([_sample(), _sample(width=22.0, depth=7.0)])

    assert result.satisfied is False


def test_matching_dimensions_must_be_true_for_every_sample_not_just_the_subset() -> None:
    result = _measure([_sample(width=21.0, depth=6.0), _sample(width=31.0, depth=16.0)])

    assert result.satisfied is False


def test_count_mismatch_fails_even_when_dimensions_match() -> None:
    too_few = _measure([_sample()], expected_count=2)
    too_many = _measure([_sample(), _sample(), _sample()], expected_count=2)

    assert too_few.satisfied is False
    assert too_many.satisfied is False


def test_required_region_selects_the_qualifying_group_before_verification() -> None:
    result = _measure(
        [_sample(), _sample(), _sample(width=31.0, depth=16.0, region="south")],
        expected_count=2,
    )

    assert result.satisfied is True
    assert result.measurements["count"] == 2
    assert result.measurements["regions"] == ["north"]


def test_wrong_region_samples_do_not_contaminate_a_selected_group() -> None:
    result = _measure(
        [_sample(), _sample(width=31.0, depth=16.0, region="south")],
        expected_count=1,
    )

    assert result.satisfied is True
    assert result.measurements["count"] == 1


def test_mixed_through_and_blind_samples_fail_when_through_is_required() -> None:
    result = _measure([_sample(), _sample(through=False)])

    assert result.satisfied is False
    assert result.measurements["through_count"] == 1


def test_dimension_exactly_at_tolerance_boundary_passes() -> None:
    result = _measure([_sample(width=21.2, depth=6.2), _sample(width=20.8, depth=5.8)])

    assert result.satisfied is True


def test_dimension_outside_tolerance_fails() -> None:
    result = _measure([_sample(), _sample(width=21.21)])

    assert result.satisfied is False


def test_missing_required_dimension_fails_closed() -> None:
    result = _measure([_sample(), _sample(width=None)])

    assert result.satisfied is False


def test_empty_qualifying_group_does_not_pass_zero_count_requirement() -> None:
    result = measure_slots(
        [],
        expected_count=0,
        expected_width=None,
        expected_depth=None,
        tolerance=0.2,
    )

    assert result.satisfied is False
    assert result.measurements["count"] == 0


def test_diagnostics_identify_failed_samples_and_constraints() -> None:
    result = _measure([_sample(), _sample(width=31.0, depth=16.0, through=False)])

    assert result.satisfied is False
    assert result.measurements["failed_sample_indices"] == [1]
    assert set(result.measurements["sample_diagnostics"][1]["failed_constraints"]) == {
        "through",
        "width",
        "depth",
    }
