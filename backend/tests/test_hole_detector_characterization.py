from __future__ import annotations

import math

import numpy as np
import pytest
import trimesh

from app.services.executable_cadquery.semantic import _verify_opening_requirement
from app.services.geometry.invariants import (
    GeometricToleranceProfile,
    _detect_axis_aligned_hole_candidates,
)


def _wall(points: list[tuple[float, float]], height: float = 11.0) -> trimesh.Trimesh:
    points_array = np.asarray(points, dtype=float)
    count = len(points_array)
    vertices = np.vstack(
        [
            np.column_stack([points_array, np.zeros(count)]),
            np.column_stack([points_array, np.full(count, height)]),
        ]
    )
    faces: list[list[int]] = []
    for index in range(count):
        next_index = (index + 1) % count
        faces.extend(
            [
                [index, next_index + count, next_index],
                [index, index + count, next_index + count],
            ]
        )
    return trimesh.Trimesh(vertices=vertices, faces=np.asarray(faces), process=False)


def _circle(radius: float, segments: int) -> list[tuple[float, float]]:
    return [
        (
            radius * math.cos(2.0 * math.pi * index / segments),
            radius * math.sin(2.0 * math.pi * index / segments),
        )
        for index in range(segments)
    ]


def _ellipse(radius_x: float, radius_y: float, segments: int = 64) -> list[tuple[float, float]]:
    return [
        (
            radius_x * math.cos(2.0 * math.pi * index / segments),
            radius_y * math.sin(2.0 * math.pi * index / segments),
        )
        for index in range(segments)
    ]


def _rounded_rectangle(
    width: float,
    height: float,
    corner_radius: float,
    segments_per_corner: int = 8,
) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    corners = (
        (width / 2.0 - corner_radius, height / 2.0 - corner_radius, 0.0),
        (-width / 2.0 + corner_radius, height / 2.0 - corner_radius, 90.0),
        (-width / 2.0 + corner_radius, -height / 2.0 + corner_radius, 180.0),
        (width / 2.0 - corner_radius, -height / 2.0 + corner_radius, 270.0),
    )
    for center_x, center_y, start_degrees in corners:
        for index in range(segments_per_corner + 1):
            angle = math.radians(start_degrees + 90.0 * index / segments_per_corner)
            points.append(
                (
                    center_x + corner_radius * math.cos(angle),
                    center_y + corner_radius * math.sin(angle),
                )
            )
    return points


def _slot(length: float = 19.0, width: float = 7.0, segments: int = 16) -> list[tuple[float, float]]:
    radius = width / 2.0
    points: list[tuple[float, float]] = []
    for index in range(segments + 1):
        angle = math.pi / 2.0 - math.pi * index / segments
        points.append(
            (
                (length - width) / 2.0 + radius * math.cos(angle),
                radius * math.sin(angle),
            )
        )
    for index in range(segments + 1):
        angle = -math.pi / 2.0 - math.pi * index / segments
        points.append(
            (
                -(length - width) / 2.0 + radius * math.cos(angle),
                radius * math.sin(angle),
            )
        )
    return points


def _irregular_profile() -> list[tuple[float, float]]:
    return [
        (
            8.0 * math.cos(angle) * (1.0 + 0.18 * math.sin(3.0 * angle)),
            5.0 * math.sin(angle),
        )
        for angle in np.linspace(0.0, 2.0 * math.pi, 56, endpoint=False)
    ]


def _cylindrical_band(radius: float, lower: float, upper: float, segments: int = 48) -> trimesh.Trimesh:
    points = _circle(radius, segments)
    points_array = np.asarray(points, dtype=float)
    vertices = np.vstack(
        [
            np.column_stack([points_array, np.full(segments, lower)]),
            np.column_stack([points_array, np.full(segments, upper)]),
        ]
    )
    faces: list[list[int]] = []
    for index in range(segments):
        next_index = (index + 1) % segments
        faces.extend(
            [
                [index, next_index + segments, next_index],
                [index, index + segments, next_index + segments],
            ]
        )
    return trimesh.Trimesh(vertices=vertices, faces=np.asarray(faces), process=False)


def _translated_wall(points: list[tuple[float, float]], offset: tuple[float, float, float]) -> trimesh.Trimesh:
    mesh = _wall(points)
    mesh.apply_translation(offset)
    return mesh


def _candidate_summary(mesh: trimesh.Trimesh) -> dict[str, object]:
    candidates = _detect_axis_aligned_hole_candidates(mesh, "z", GeometricToleranceProfile())
    return {
        "raw_candidate_count": len(candidates),
        "candidate_diameters_mm": [round(float(item.diameter), 3) for item in candidates],
        "candidate_confidence": [round(float(item.confidence), 3) for item in candidates],
    }


@pytest.mark.parametrize(
    ("case", "mesh_factory", "expected_count"),
    [
        ("single_true_circle", lambda: _wall(_circle(5.5, 48)), 1),
        ("multiple_true_circles", lambda: trimesh.util.concatenate([_wall(_circle(4.5, 48)), _translated_wall(_circle(4.5, 48), (25.0, 0.0, 0.0))]), 2),
        ("different_true_circle_diameter", lambda: _wall(_circle(7.25, 64)), 1),
        ("coarse_true_circle", lambda: _wall(_circle(5.5, 12)), 1),
        ("fine_true_circle", lambda: _wall(_circle(5.5, 96)), 1),
        ("square_negative_control", lambda: _wall([(-7.0, -7.0), (7.0, -7.0), (7.0, 7.0), (-7.0, 7.0)]), 0),
        ("near_square_false_positive", lambda: _wall(_rounded_rectangle(14.0, 14.0, 0.5)), 1),
        ("rounded_rectangle", lambda: _wall(_rounded_rectangle(16.0, 10.0, 2.5)), 1),
        ("elongated_slot", lambda: _wall(_slot()), 0),
        ("ellipse", lambda: _wall(_ellipse(8.0, 5.0)), 1),
        ("regular_polygon", lambda: _wall(_circle(6.0, 8)), 1),
        ("irregular_curved_profile", lambda: _wall(_irregular_profile()), 1),
        ("counterbored_physical_hole", lambda: trimesh.util.concatenate([_cylindrical_band(6.0, 0.0, 2.0), _cylindrical_band(3.0, 2.0, 11.0)]), 2),
        ("countersunk_physical_hole", lambda: trimesh.util.concatenate([_cylindrical_band(6.0, 0.0, 1.0), _cylindrical_band(5.0, 1.0, 2.0), _cylindrical_band(3.0, 2.0, 11.0)]), 3),
        ("stepped_cylindrical_opening", lambda: trimesh.util.concatenate([_cylindrical_band(6.0, 0.0, 3.0), _cylindrical_band(3.0, 3.0, 11.0)]), 2),
        ("multiple_surface_bands_one_feature", lambda: trimesh.util.concatenate([_cylindrical_band(6.0, 0.0, 2.0), _cylindrical_band(5.0, 2.0, 4.0), _cylindrical_band(3.0, 4.0, 11.0)]), 3),
        ("indistinguishable_rounded_exterior_profile", lambda: _wall(_rounded_rectangle(14.0, 14.0, 0.5)), 1),
        ("nearby_curved_features", lambda: trimesh.util.concatenate([_wall(_rounded_rectangle(14.0, 14.0, 0.5)), _translated_wall(_rounded_rectangle(14.0, 14.0, 0.5), (24.0, 0.0, 0.0))]), 2),
        ("circular_feature_without_region_scope", lambda: _wall(_circle(5.5, 48)), 1),
    ],
)
def test_stl_candidate_shape_matrix_records_current_behavior(case, mesh_factory, expected_count) -> None:
    mesh = mesh_factory()
    summary = _candidate_summary(mesh)

    assert summary["raw_candidate_count"] == expected_count, case
    assert len(summary["candidate_diameters_mm"]) == expected_count
    assert len(summary["candidate_confidence"]) == expected_count


def test_known_near_square_false_positive_is_reproduced_before_recovery() -> None:
    summary = _candidate_summary(_wall(_rounded_rectangle(14.0, 14.0, 0.5)))

    assert summary["raw_candidate_count"] == 1
    assert summary["candidate_diameters_mm"][0] != 14.0


@pytest.mark.parametrize(
    "mesh_factory, expected_diameter",
    [
        (lambda: _wall(_circle(5.5, 48)), 11.0),
        (lambda: _wall(_rounded_rectangle(14.0, 14.0, 0.5)), 16.0),
    ],
)
def test_stl_candidate_alone_cannot_authoritatively_verify_a_circular_hole(mesh_factory, expected_diameter) -> None:
    finding = _verify_opening_requirement(
        "synthetic_hole_requirement",
        mesh_factory(),
        {"hole_count": 1, "hole_diameter": expected_diameter},
        tolerance=0.25,
    )

    assert finding["status"] == "unverifiable"
    assert finding["measurement_available"] is False
    assert finding["measurements"]["evidence_authority"] == "derived_stl_candidate"
