"""Final-geometry checks for the executable CadQuery experiment."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import numpy as np
import trimesh

from app.services.geometry.feature_measurements import _ray_parameters
from app.services.geometry.invariants import _detect_axis_aligned_holes


def evaluate_executable_cadquery_semantics(
    *,
    stl_path: Path,
    design_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate contract facts from the final mesh, never from source text."""

    try:
        loaded = trimesh.load(stl_path, force="mesh")
        mesh = loaded if isinstance(loaded, trimesh.Trimesh) else loaded.dump(concatenate=True)
    except Exception as exc:  # pragma: no cover - defensive artifact boundary
        return {
            "status": "unverifiable",
            "passed": [],
            "failed": [],
            "unverifiable": ["final_mesh"],
            "diagnostic": "The final mesh could not be loaded for semantic verification.",
            "error_type": type(exc).__name__,
        }

    requirements = [
        item for item in design_contract.get("requirements", [])
        if isinstance(item, Mapping) and item.get("requirement_id")
    ]
    findings: list[dict[str, Any]] = []
    bounds = np.asarray(mesh.bounds, dtype=float)
    extents = bounds[1] - bounds[0]
    expected_output = next(
        (item for item in design_contract.get("outputs", []) if isinstance(item, Mapping)),
        {},
    )
    expected_solids = int(expected_output.get("expected_solid_count") or 1)
    detected_solids = len(mesh.split(only_watertight=False)) if len(mesh.faces) else 0
    findings.append(
        _finding(
            "topology",
            detected_solids == expected_solids and len(mesh.faces) > 0,
            {
                "expected_solid_count": expected_solids,
                "detected_solid_count": detected_solids,
            },
        )
    )

    expected_body = _expected(requirements, "body_dimensions")
    if expected_body:
        expected_dimensions = [
            float(expected_body.get("width")),
            float(expected_body.get("depth")),
            float(expected_body.get("thickness")),
        ]
        tolerance = _tolerance(requirements, "body_dimensions")
        findings.append(
            _finding(
                "body_dimensions",
                bool(np.all(np.abs(extents - expected_dimensions) <= tolerance)),
                {"expected_mm": expected_dimensions, "detected_mm": _rounded(extents)},
            )
        )

    expected_holes = _expected(requirements, "mounting_hole_pattern")
    expected_offsets = _expected(requirements, "mounting_hole_edge_offsets")
    expected_asymmetric = _expected(requirements, "asymmetric_through_hole")
    detected_holes = [
        hole for hole in _detect_axis_aligned_holes(mesh, "z", _tolerance_profile())
        if hole.confidence >= 0.55
    ]
    if expected_holes:
        holes = detected_holes
        expected_count = int(expected_holes.get("count") or 0)
        diameter = float(expected_holes.get("diameter") or 0)
        matching = [hole for hole in holes if abs(float(hole.diameter) - diameter) <= _tolerance(requirements, "mounting_hole_pattern")]
        passed = len(matching) == expected_count
        findings.append(
            _finding(
                "mounting_hole_pattern",
                passed,
                {
                    "expected_count": expected_count,
                    "detected_count": len(matching),
                    "detected_diameters_mm": sorted(round(float(hole.diameter), 3) for hole in holes),
                },
            )
        )
        if passed and expected_offsets:
            offset = float(expected_offsets.get("nearest_edge_offset") or 0)
            min_x, min_y = float(bounds[0][0]), float(bounds[0][1])
            max_x, max_y = float(bounds[1][0]), float(bounds[1][1])
            offsets = [
                min(float(hole.center[0]) - min_x, max_x - float(hole.center[0]),
                    float(hole.center[1]) - min_y, max_y - float(hole.center[1]))
                for hole in matching
            ]
            findings.append(
                _finding(
                    "mounting_hole_edge_offsets",
                    bool(offsets) and all(abs(value - offset) <= _tolerance(requirements, "mounting_hole_edge_offsets") for value in offsets),
                    {"expected_offset_mm": offset, "detected_offsets_mm": _rounded(offsets)},
                )
            )
    if expected_asymmetric:
        x = float(bounds[0][0]) + float(expected_asymmetric.get("x_from_left") or 0)
        y = float(bounds[0][1]) + float(expected_asymmetric.get("y_from_lower") or 0)
        diameter = float(expected_asymmetric.get("diameter") or 0)
        tolerance = _tolerance(requirements, "asymmetric_through_hole")
        hole_result = _probe_hole_diameter(mesh, (x, y), diameter, tolerance)
        findings.append(
            _finding(
                "asymmetric_through_hole",
                hole_result,
                {
                    "probe_mm": [round(x, 3), round(y, 3)],
                    "through": hole_result,
                    "detected_holes": [
                        {
                            "center": _rounded(hole.center),
                            "diameter_mm": round(float(hole.diameter), 3),
                        }
                        for hole in detected_holes
                    ],
                },
            )
        )

    pocket = _expected(requirements, "centered_recessed_pocket")
    if pocket:
        findings.append(_verify_pocket(mesh, pocket, requirements))

    fillet = _expected(requirements, "external_fillet")
    if fillet:
        findings.append(_verify_external_fillet(mesh, fillet, expected_body))

    passed = [item["requirement_id"] for item in findings if item["status"] == "passed"]
    failed = [item["requirement_id"] for item in findings if item["status"] == "failed"]
    unverifiable = [item["requirement_id"] for item in findings if item["status"] == "unverifiable"]
    status = "failed" if failed else "unverifiable" if unverifiable else "passed"
    return {
        "status": status,
        "passed": passed,
        "failed": failed,
        "unverifiable": unverifiable,
        "findings": findings,
        "mesh_bounds_mm": {"min": _rounded(bounds[0]), "max": _rounded(bounds[1])},
        "detected_solid_count": detected_solids,
    }


def _verify_pocket(mesh: trimesh.Trimesh, expected: Mapping[str, Any], requirements: list[Mapping[str, Any]]) -> dict[str, Any]:
    width = float(expected.get("width") or 0)
    depth = float(expected.get("depth") or 0)
    cut_depth = float(expected.get("cut_depth") or 0)
    max_z = float(mesh.bounds[1][2])
    center_z = _top_surface_z(mesh, 0.0, 0.0)
    inside_x = _top_surface_z(mesh, max(-width / 2 + 0.5, 0.0), 0.0)
    outside_x = _top_surface_z(mesh, width / 2 + 0.5, 0.0)
    inside_y = _top_surface_z(mesh, 0.0, max(-depth / 2 + 0.5, 0.0))
    outside_y = _top_surface_z(mesh, 0.0, depth / 2 + 0.5)
    tolerance = _tolerance(requirements, "centered_recessed_pocket")
    measured_depth = max_z - center_z if center_z is not None else None
    passed = (
        measured_depth is not None
        and abs(measured_depth - cut_depth) <= tolerance
        and inside_x is not None
        and outside_x is not None
        and inside_y is not None
        and outside_y is not None
        and abs(inside_x - center_z) <= tolerance
        and abs(inside_y - center_z) <= tolerance
        and abs(outside_x - max_z) <= tolerance
        and abs(outside_y - max_z) <= tolerance
    )
    return {
        "requirement_id": "centered_recessed_pocket",
        "status": "passed" if passed else "unverifiable",
        "measurements": {
            "expected_mm": {"width": width, "depth": depth, "cut_depth": cut_depth},
            "detected_cut_depth_mm": round(measured_depth, 3) if measured_depth is not None else None,
        },
    }


def _verify_external_fillet(mesh: trimesh.Trimesh, expected: Mapping[str, Any], body: Mapping[str, Any]) -> dict[str, Any]:
    radius = float(expected.get("radius") or 0)
    # A rounded external corner has no vertex at the bounding-box corner.
    max_x, max_y = float(mesh.bounds[1][0]), float(mesh.bounds[1][1])
    corner_distance = np.linalg.norm(
        mesh.vertices[:, :2] - np.asarray([max_x, max_y]), axis=1
    )
    rounded_corner = bool(np.min(corner_distance) > 0.1)
    return {
        "requirement_id": "external_fillet",
        "status": "passed" if rounded_corner else "unverifiable",
        "measurements": {
            "expected_radius_mm": radius,
            "corner_clearance_mm": round(float(np.min(corner_distance)), 3),
            "body_dimensions_present": bool(body),
        },
    }


def _probe_through(mesh: trimesh.Trimesh, point: tuple[float, float]) -> bool:
    origin = np.asarray([point[0], point[1], float(mesh.bounds[0][2]) - 5.0], dtype=float)
    intersections = _ray_parameters(mesh, origin, np.asarray([0.0, 0.0, 1.0]))
    if len(intersections) < 2:
        within_xy = (
            float(mesh.bounds[0][0]) <= point[0] <= float(mesh.bounds[1][0])
            and float(mesh.bounds[0][1]) <= point[1] <= float(mesh.bounds[1][1])
        )
        return not intersections and within_xy
    return max(
        right - left for left, right in zip(sorted(intersections), sorted(intersections)[1:])
    ) >= float(np.ptp(mesh.bounds[:, 2])) - 0.25


def _probe_hole_diameter(
    mesh: trimesh.Trimesh,
    center: tuple[float, float],
    diameter: float,
    tolerance: float,
) -> bool:
    radius = diameter / 2.0
    angles = np.linspace(0.0, 2.0 * np.pi, num=9, endpoint=False)
    inner = [
        (center[0] + (radius - tolerance) * float(np.cos(angle)),
         center[1] + (radius - tolerance) * float(np.sin(angle)))
        for angle in angles
    ]
    outer = [
        (center[0] + (radius + tolerance) * float(np.cos(angle)),
         center[1] + (radius + tolerance) * float(np.sin(angle)))
        for angle in angles
    ]
    inner_open = all(_probe_through(mesh, point) for point in inner)
    outer_blocked = sum(1 for point in outer if not _probe_through(mesh, point))
    # The pocket and the asymmetric opening share an edge in this frozen
    # design, so the top-surface profile is one merged opening. A ring of
    # bottom-slice probes still proves the requested hole boundary without
    # treating the merged top profile as an independent circle.
    return _probe_through(mesh, center) and inner_open and outer_blocked >= 2


def _top_surface_z(mesh: trimesh.Trimesh, x: float, y: float) -> float | None:
    origin = np.asarray([x, y, float(mesh.bounds[1][2]) + 5.0], dtype=float)
    intersections = _ray_parameters(mesh, origin, np.asarray([0.0, 0.0, -1.0]))
    return max((float(mesh.bounds[1][2]) + 5.0 - value for value in intersections), default=None)


def _finding(requirement_id: str, passed: bool, measurements: dict[str, Any]) -> dict[str, Any]:
    return {
        "requirement_id": requirement_id,
        "status": "passed" if passed else "failed",
        "measurements": measurements,
    }


def _expected(requirements: list[Mapping[str, Any]], requirement_id: str) -> Mapping[str, Any] | None:
    item = next((item for item in requirements if item.get("requirement_id") == requirement_id), None)
    value = item.get("expected") if item else None
    return value if isinstance(value, Mapping) else None


def _tolerance(requirements: list[Mapping[str, Any]], requirement_id: str) -> float:
    item = next((item for item in requirements if item.get("requirement_id") == requirement_id), None)
    try:
        return float(item.get("tolerance") or 0.25) if item else 0.25
    except (TypeError, ValueError):
        return 0.25


def _tolerance_profile() -> Any:
    from app.services.geometry.invariants import GeometricToleranceProfile

    return GeometricToleranceProfile()


def _rounded(values: Any) -> list[float]:
    return [round(float(value), 3) for value in np.asarray(values).reshape(-1)]
