from __future__ import annotations

import trimesh

from app.services.geometry.feature_measurements import (
    compare_dimension,
    measure_opening_count,
    measure_opening_profiles,
    measure_slots,
    verify_through_opening,
)


def _box(extents: tuple[float, float, float], translation: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation(translation)
    return mesh


def _rectangular_frame(center_x: float = 0.0) -> trimesh.Trimesh:
    return trimesh.util.concatenate(
        [
            _box((18.0, 3.0, 3.0), (center_x, 0.0, 6.25)),
            _box((18.0, 3.0, 3.0), (center_x, 0.0, -6.25)),
            _box((3.0, 3.0, 16.5), (center_x - 7.5, 0.0, 0.0)),
            _box((3.0, 3.0, 16.5), (center_x + 7.5, 0.0, 0.0)),
        ]
    )


def test_profile_projection_reports_boundary_components_not_an_opening_identity() -> None:
    profiles = measure_opening_profiles(_rectangular_frame(), axis="y")

    assert len(profiles) == 4
    assert {tuple(sorted((profile["size_x"], profile["size_y"]))) for profile in profiles} == {
        (3.0, 16.5),
        (3.0, 18.0),
    }
    assert all("output_id" not in profile and "ambiguous" not in profile for profile in profiles)


def test_opening_count_is_deterministic_only_for_explicit_probe_points() -> None:
    mesh = trimesh.util.concatenate(
        [_rectangular_frame(-30.0), _rectangular_frame(), _rectangular_frame(30.0)]
    )
    probes = [(-30.0, -20.0, 0.0), (0.0, -20.0, 0.0), (30.0, -20.0, 0.0)]

    measured = measure_opening_count(mesh, axis="y", points=probes, expected_count=3)

    assert measured.satisfied is True
    assert measured.measurements["count"] == 3
    assert len(measure_opening_profiles(mesh, axis="y")) == 12
    assert not measure_opening_count(mesh, axis="y", points=probes, expected_count=2).satisfied


def test_through_probe_distinguishes_a_frame_from_a_blind_rectangular_region() -> None:
    through = verify_through_opening(_rectangular_frame(), axis="y", point=(0.0, -20.0, 0.0))
    blind = verify_through_opening(_box((18.0, 3.0, 15.0)), axis="y", point=(0.0, -20.0, 0.0))

    assert through.satisfied is True
    assert through.reason == "through_opening"
    assert blind.satisfied is False
    assert blind.reason == "blind_or_blocked"


def test_sample_group_dimension_matching_requires_every_sample() -> None:
    result = measure_slots(
        [
            {"width": 13.0, "depth": 4.0, "through": True, "region": "north"},
            {"width": 31.0, "depth": 17.0, "through": True, "region": "north"},
        ],
        expected_count=2,
        expected_width=13.0,
        expected_depth=4.0,
        tolerance=0.2,
        required_region="north",
    )

    assert result.satisfied is False
    assert result.measurements["count"] == 2
    assert result.measurements["widths_mm"] == [13.0, 31.0]
    assert result.measurements["depths_mm"] == [4.0, 17.0]
    assert result.measurements["failed_sample_indices"] == [1]


def test_sample_group_count_and_region_are_checked_but_geometry_identity_is_external() -> None:
    result = measure_slots(
        [
            {"width": 13.0, "depth": 4.0, "through": True, "region": "north"},
            {"width": 13.0, "depth": 4.0, "through": True, "region": "south"},
        ],
        expected_count=1,
        expected_width=13.0,
        expected_depth=4.0,
        tolerance=0.2,
        required_region="north",
    )

    assert result.satisfied is True
    assert result.measurements["count"] == 1
    assert result.measurements["regions"] == ["north"]
    assert "output_id" not in result.measurements


def test_mesh_measurements_do_not_assign_output_identity_or_cross_output_scope() -> None:
    first = measure_opening_count(
        _rectangular_frame(-20.0),
        axis="y",
        points=[(-20.0, -20.0, 0.0)],
        expected_count=1,
    )
    second = measure_opening_count(
        _rectangular_frame(20.0),
        axis="y",
        points=[(20.0, -20.0, 0.0)],
        expected_count=1,
    )

    assert first.satisfied is True and second.satisfied is True
    assert "output_id" not in first.measurements
    assert "output_id" not in second.measurements


def test_profile_orientation_must_be_supplied_and_is_not_inferred_from_a_face_name() -> None:
    wrong_axis = measure_opening_count(
        _rectangular_frame(),
        axis="z",
        points=[(0.0, -20.0, 0.0)],
        expected_count=1,
    )

    assert wrong_axis.satisfied is False
    assert wrong_axis.measurements["count"] == 0


def test_no_qualifying_region_and_tolerance_boundary_remain_observable() -> None:
    blind = _box((18.0, 3.0, 15.0))
    absent = measure_opening_count(
        blind,
        axis="y",
        points=[(0.0, -20.0, 0.0)],
        expected_count=1,
    )

    assert absent.satisfied is False
    assert absent.reason == "opening_count_mismatch"
    assert compare_dimension(13.0, 13.2, operator="approximate", tolerance=0.2).passed
    assert not compare_dimension(13.0, 13.21, operator="approximate", tolerance=0.2).passed
