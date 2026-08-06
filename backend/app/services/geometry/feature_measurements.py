"""Small generic mesh measurements for deterministic feature evidence.

The functions in this module deliberately consume geometry and semantic
descriptors. They do not know about a particular product family.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

import numpy as np
from trimesh import Trimesh


@dataclass(frozen=True)
class MeasurementResult:
    satisfied: bool
    status: str
    reason: str
    measurements: dict[str, Any] = field(default_factory=dict)
    tolerances: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def count(self) -> int:
        return int(self.measurements.get("count", 0))

    @property
    def open_top(self) -> bool:
        return bool(self.measurements.get("open_top", False))


@dataclass(frozen=True)
class DimensionComparison:
    passed: bool
    requested: float | int | None
    measured: float | int | None
    operator: str
    tolerance: float | None


def compare_dimension(
    requested: float | int | None,
    measured: float | int | None,
    *,
    operator: str = "exact",
    tolerance: float | None = None,
) -> DimensionComparison:
    """Compare a dimension while retaining the semantic operator and tolerance."""

    if requested is None or measured is None:
        return DimensionComparison(False, requested, measured, operator, tolerance)
    requested_float = float(requested)
    measured_float = float(measured)
    if operator in {"minimum", "at_least", ">="}:
        passed = measured_float >= requested_float - float(tolerance or 0)
    elif operator in {"maximum", "at_most", "<="}:
        passed = measured_float <= requested_float + float(tolerance or 0)
    elif operator in {"range", "between"}:
        passed = abs(measured_float - requested_float) <= float(tolerance or 0)
    else:
        passed = abs(measured_float - requested_float) <= float(tolerance or 0)
    return DimensionComparison(passed, requested, measured, operator, tolerance)


def verify_one_connected_output(
    mesh: Trimesh,
    *,
    expected_count: int = 1,
) -> MeasurementResult:
    components = list(mesh.split(only_watertight=False))
    count = len(components)
    passed = count == expected_count and bool(len(mesh.faces))
    return MeasurementResult(
        satisfied=passed,
        status="measured" if passed else "not_satisfied",
        reason="connected" if passed else "solid_count_mismatch",
        measurements={
            "expected_solid_count": expected_count,
            "detected_connected_components": count,
            "face_count": int(len(mesh.faces)),
        },
    )


def verify_integral_feature(
    primary_mesh: Trimesh,
    feature_mesh: Trimesh,
    final_mesh: Trimesh,
    *,
    minimum_overlap_mm: float = 0.10,
) -> MeasurementResult:
    """Require positive-volume bounding overlap and final connectedness.

    The strict positive-volume check rejects face-only and edge-only contact.
    The final mesh topology check rejects a disconnected replacement or a
    compound accepted as an integral feature.
    """

    primary_min, primary_max = _bounds(primary_mesh)
    feature_min, feature_max = _bounds(feature_mesh)
    overlap_extents = np.minimum(primary_max, feature_max) - np.maximum(primary_min, feature_min)
    overlap_volume = float(np.prod(np.maximum(overlap_extents, 0.0)))
    topology = verify_one_connected_output(final_mesh, expected_count=1)
    passed = bool(np.all(overlap_extents > minimum_overlap_mm)) and topology.satisfied
    reason = "connected" if passed else (
        "final_disconnected" if not topology.satisfied else "no_material_overlap"
    )
    return MeasurementResult(
        satisfied=passed,
        status="measured" if passed else "not_satisfied",
        reason=reason,
        measurements={
            "connected_to_primary_body": topology.satisfied,
            "overlap_extents_mm": [round(float(value), 4) for value in overlap_extents],
            "minimum_overlap_mm": minimum_overlap_mm,
            "material_overlap_volume_estimate_mm3": round(overlap_volume, 4),
        },
        tolerances={"minimum_overlap_mm": minimum_overlap_mm},
    )


def verify_through_opening(
    mesh: Trimesh,
    *,
    axis: str,
    point: Iterable[float],
    maximum_intersections: int = 0,
    minimum_opening_mm: float = 0.1,
) -> MeasurementResult:
    """Probe a void along an intended direction using triangle intersections."""

    axis_index = _axis_index(axis)
    point_array = np.asarray(tuple(point), dtype=float)
    bounds_min, bounds_max = _bounds(mesh)
    orthogonal_axes = [index for index in range(3) if index != axis_index]
    if any(
        point_array[index] < bounds_min[index] - minimum_opening_mm
        or point_array[index] > bounds_max[index] + minimum_opening_mm
        for index in orthogonal_axes
    ):
        return MeasurementResult(
            satisfied=False,
            status="feature_absent",
            reason="probe_outside_geometry",
            measurements={
                "axis": axis,
                "point": [round(float(value), 4) for value in point_array],
                "intersection_count": 0,
                "opening_length_mm": 0.0,
            },
            tolerances={"minimum_opening_mm": minimum_opening_mm},
        )
    direction = np.zeros(3, dtype=float)
    direction[axis_index] = 1.0
    margin = max(float(np.ptp(mesh.bounds[:, axis_index])), 1.0) + 10.0
    origin = point_array.copy()
    origin[axis_index] = bounds_min[axis_index] - margin
    intersections = _ray_parameters(mesh, origin, direction)
    count = len(intersections)
    opening_length = _opening_length(mesh, axis_index, intersections)
    passed = count <= maximum_intersections and opening_length >= minimum_opening_mm
    return MeasurementResult(
        satisfied=passed,
        status="measured" if passed else "not_satisfied",
        reason="through_opening" if passed else "blind_or_blocked",
        measurements={
            "axis": axis,
            "point": [round(float(value), 4) for value in point_array],
            "intersection_count": count,
            "opening_length_mm": round(opening_length, 4),
        },
        tolerances={"minimum_opening_mm": minimum_opening_mm},
    )


def measure_opening_count(
    mesh: Trimesh,
    *,
    axis: str,
    points: Iterable[Iterable[float]],
    maximum_intersections: int = 0,
    minimum_opening_mm: float = 0.1,
    expected_count: int | None = None,
) -> MeasurementResult:
    results = [
        verify_through_opening(
            mesh,
            axis=axis,
            point=point,
            maximum_intersections=maximum_intersections,
            minimum_opening_mm=minimum_opening_mm,
        )
        for point in points
    ]
    passed_count = sum(1 for result in results if result.satisfied)
    satisfied = passed_count == expected_count if expected_count is not None else passed_count > 0
    return MeasurementResult(
        satisfied=satisfied,
        status="measured" if satisfied else "feature_absent",
        reason=(
            "opening_count_verified"
            if satisfied and expected_count is not None
            else "openings_detected"
            if satisfied
            else "opening_count_mismatch"
            if expected_count is not None
            else "no_openings_detected"
        ),
        measurements={
            "count": passed_count,
            "probed_count": len(results),
            "expected_count": expected_count,
            "probes": [result.measurements for result in results],
        },
    )


def measure_opening_profiles(
    mesh: Trimesh,
    *,
    axis: str,
) -> list[dict[str, float]]:
    """Return projected profiles of enclosed openings on an orthogonal plane."""

    axis_index = _axis_index(axis)
    if len(mesh.faces) == 0:
        return []
    side_faces = set(
        int(index)
        for index in np.where(np.abs(mesh.face_normals[:, axis_index]) < 0.35)[0]
    )
    adjacency: dict[int, list[int]] = {index: [] for index in side_faces}
    for left, right in mesh.face_adjacency:
        left_index = int(left)
        right_index = int(right)
        if left_index in side_faces and right_index in side_faces:
            adjacency[left_index].append(right_index)
            adjacency[right_index].append(left_index)
    projection = [index for index in range(3) if index != axis_index]
    profiles: list[dict[str, float]] = []
    while side_faces:
        start = side_faces.pop()
        stack = [start]
        component = [start]
        while stack:
            current = stack.pop()
            for neighbor in adjacency[current]:
                if neighbor in side_faces:
                    side_faces.remove(neighbor)
                    stack.append(neighbor)
                    component.append(neighbor)
        points = mesh.vertices[np.unique(mesh.faces[component].reshape(-1))][:, projection]
        if len(points) < 8:
            continue
        minimum = points.min(axis=0)
        maximum = points.max(axis=0)
        center = (minimum + maximum) / 2
        profiles.append(
            {
                "center_x": round(float(center[0]), 3),
                "center_y": round(float(center[1]), 3),
                "size_x": round(float(maximum[0] - minimum[0]), 3),
                "size_y": round(float(maximum[1] - minimum[1]), 3),
            }
        )
    return profiles


def measure_slots(
    samples: Iterable[dict[str, Any]],
    *,
    expected_count: int,
    expected_width: float | None = None,
    expected_depth: float | None = None,
    tolerance: float = 0.2,
    required_region: str | None = None,
) -> MeasurementResult:
    """Measure slot count, dimensions, through state, and optional region."""

    sample_list = [sample for sample in samples if isinstance(sample, dict)]
    valid = [
        sample for sample in sample_list
        if bool(sample.get("through", sample.get("open", False)))
        and (required_region is None or str(sample.get("region")) == required_region)
    ]
    widths = [float(sample["width"]) for sample in valid if _number(sample.get("width")) is not None]
    depths = [float(sample["depth"]) for sample in valid if _number(sample.get("depth")) is not None]
    width_ok = expected_width is None or any(abs(value - expected_width) <= tolerance for value in widths)
    depth_ok = expected_depth is None or any(abs(value - expected_depth) <= tolerance for value in depths)
    passed = len(valid) == expected_count and width_ok and depth_ok
    return MeasurementResult(
        satisfied=passed,
        status="measured" if passed else "not_satisfied",
        reason="slots_verified" if passed else "slot_count_dimension_or_access_failed",
        measurements={
            "count": len(valid),
            "expected_count": expected_count,
            "widths_mm": widths,
            "depths_mm": depths,
            "regions": sorted({str(sample.get("region")) for sample in valid if sample.get("region") is not None}),
            "through_count": len(valid),
        },
        tolerances={"dimension_mm": tolerance},
    )


def measure_compartments(
    samples: Iterable[dict[str, Any]],
    *,
    expected_count: int,
    expected_width: float | None = None,
    expected_depth: float | None = None,
    tolerance: float = 0.2,
    access_direction: str = "top",
) -> MeasurementResult:
    """Evaluate open-top compartment samples supplied by a generic sampler."""

    sample_list = [sample for sample in samples if isinstance(sample, dict)]
    open_samples = [sample for sample in sample_list if bool(sample.get("open_top"))]
    widths = [float(sample["width"]) for sample in open_samples if _number(sample.get("width")) is not None]
    depths = [float(sample["depth"]) for sample in open_samples if _number(sample.get("depth")) is not None]
    width_result = (
        any(abs(width - expected_width) <= tolerance for width in widths)
        if expected_width is not None and widths
        else expected_width is None
    )
    depth_result = (
        any(abs(depth - expected_depth) <= tolerance for depth in depths)
        if expected_depth is not None and depths
        else expected_depth is None
    )
    access_result = all(
        str(sample.get("access_direction") or "top") == access_direction
        for sample in open_samples
    )
    passed = len(open_samples) == expected_count and bool(open_samples) and width_result and depth_result and access_result
    return MeasurementResult(
        satisfied=passed,
        status="measured" if passed else "not_satisfied",
        reason="compartments_verified" if passed else "compartment_count_or_access_failed",
        measurements={
            "count": len(open_samples),
            "expected_count": expected_count,
            "open_top": len(open_samples) == len(sample_list) and bool(open_samples),
            "widths_mm": widths,
            "depths_mm": depths,
            "access_direction": access_direction,
        },
        tolerances={"width_mm": tolerance, "depth_mm": tolerance},
    )


def _bounds(mesh: Trimesh) -> tuple[np.ndarray, np.ndarray]:
    return np.asarray(mesh.bounds[0], dtype=float), np.asarray(mesh.bounds[1], dtype=float)


def _axis_index(axis: str) -> int:
    try:
        return {"x": 0, "y": 1, "z": 2}[str(axis).lower()]
    except KeyError as exc:
        raise ValueError(f"unsupported axis: {axis}") from exc


def _opening_length(mesh: Trimesh, axis_index: int, intersections: list[float]) -> float:
    if len(intersections) < 2:
        return float(np.ptp(mesh.bounds[:, axis_index])) if not intersections else 0.0
    sorted_values = sorted(intersections)
    return max(float(right - left) for left, right in zip(sorted_values, sorted_values[1:]))


def _ray_parameters(mesh: Trimesh, origin: np.ndarray, direction: np.ndarray) -> list[float]:
    triangles = np.asarray(mesh.triangles, dtype=float)
    if triangles.size == 0:
        return []
    vertex = triangles[:, 0]
    edge_one = triangles[:, 1] - vertex
    edge_two = triangles[:, 2] - vertex
    ray_cross = np.cross(direction, edge_two)
    determinant = np.einsum("ij,ij->i", edge_one, ray_cross)
    valid = np.abs(determinant) > 1e-9
    inverse = np.zeros_like(determinant)
    inverse[valid] = 1.0 / determinant[valid]
    offset = origin - vertex
    u = inverse * np.einsum("ij,ij->i", offset, ray_cross)
    cross = np.cross(offset, edge_one)
    v = inverse * np.einsum("j,ij->i", direction, cross)
    distance = inverse * np.einsum("ij,ij->i", edge_two, cross)
    valid &= (u >= -1e-7) & (v >= -1e-7) & (u + v <= 1.0000001) & (distance >= -1e-7)
    values = sorted(float(value) for value in distance[valid])
    unique: list[float] = []
    for value in values:
        if not unique or not math.isclose(value, unique[-1], abs_tol=1e-5):
            unique.append(value)
    return unique


def _number(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None
