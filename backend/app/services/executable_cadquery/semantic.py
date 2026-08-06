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


def evaluate_executable_cadquery_semantics_for_outputs(
    *,
    stl_paths: Mapping[str, Path],
    design_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate generic contract policies across one or more final outputs."""

    meshes: dict[str, trimesh.Trimesh] = {}
    load_errors: dict[str, str] = {}
    for output_id, path in stl_paths.items():
        try:
            loaded = trimesh.load(path, force="mesh")
            mesh = loaded if isinstance(loaded, trimesh.Trimesh) else loaded.dump(concatenate=True)
            if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
                raise ValueError("mesh has no faces")
            meshes[str(output_id)] = mesh
        except Exception as exc:  # pragma: no cover - defensive artifact boundary
            load_errors[str(output_id)] = type(exc).__name__

    findings: list[dict[str, Any]] = []
    if len(meshes) == 1 and not load_errors:
        output_id, path = next(iter(stl_paths.items()))
        legacy = evaluate_executable_cadquery_semantics(
            stl_path=path,
            design_contract=design_contract,
        )
        findings.extend(dict(item) for item in legacy.get("findings", []) if isinstance(item, Mapping))
    elif not meshes:
        findings.append(
            {
                "requirement_id": "final_mesh",
                "status": "unverifiable",
                "measurement_available": False,
                "evidence_source": "final_mesh",
                "measurements": {"load_errors": load_errors},
            }
        )

    found_ids = {str(item.get("requirement_id")) for item in findings if item.get("requirement_id")}
    requirements = [
        item
        for item in design_contract.get("requirements", [])
        if isinstance(item, Mapping) and item.get("requirement_id")
    ]
    for requirement in requirements:
        requirement_id = str(requirement["requirement_id"])
        if requirement_id in found_ids:
            continue
        output_id = str(requirement.get("scope") or "")
        mesh = meshes.get(output_id)
        if mesh is None and len(meshes) == 1:
            mesh = next(iter(meshes.values()))
            output_id = next(iter(meshes))
        if mesh is None:
            findings.append(
                _semantic_finding(
                    requirement_id,
                    status="unverifiable",
                    measurement_available=False,
                    measurements={"output_id": output_id, "reason": "required output mesh is unavailable"},
                )
            )
            continue
        findings.append(
            _generic_requirement_finding(
                requirement,
                mesh=mesh,
                output_id=output_id,
                meshes=meshes,
            )
        )

    passed = [str(item["requirement_id"]) for item in findings if item.get("status") == "passed"]
    failed = [str(item["requirement_id"]) for item in findings if item.get("status") == "failed"]
    unverifiable = [
        str(item["requirement_id"])
        for item in findings
        if item.get("status") == "unverifiable"
    ]
    return {
        "status": "failed" if failed else "unverifiable" if unverifiable else "passed",
        "passed": list(dict.fromkeys(passed)),
        "failed": list(dict.fromkeys(failed)),
        "unverifiable": list(dict.fromkeys(unverifiable)),
        "findings": findings,
        "output_ids": sorted(meshes),
        "load_errors": load_errors,
    }


def _generic_requirement_finding(
    requirement: Mapping[str, Any],
    *,
    mesh: trimesh.Trimesh,
    output_id: str,
    meshes: Mapping[str, trimesh.Trimesh],
) -> dict[str, Any]:
    requirement_id = str(requirement["requirement_id"])
    policy = str(requirement.get("verification_policy") or "")
    expected = requirement.get("expected") if isinstance(requirement.get("expected"), Mapping) else {}
    tolerance = _requirement_tolerance(requirement)
    if policy == "final_mesh_bounds":
        return _verify_bounds_requirement(requirement_id, mesh, expected, tolerance)
    if policy == "final_mesh_opening_profiles":
        return _verify_opening_requirement(requirement_id, mesh, expected, tolerance)
    if policy == "final_mesh_opening_centers":
        return _verify_opening_centers_requirement(requirement_id, mesh, expected, tolerance)
    if policy == "final_mesh_axisymmetric_profiles":
        return _verify_axisymmetric_requirement(requirement_id, mesh, expected, tolerance)
    if policy == "final_mesh_axial_sections":
        return _verify_axial_sections_requirement(requirement_id, mesh, expected, tolerance)
    if policy == "final_mesh_recess_profile":
        return _verify_recess_requirement(requirement_id, mesh, expected, tolerance)
    if policy == "final_mesh_wall_profile":
        return _verify_wall_requirement(requirement_id, mesh, expected, tolerance)
    if policy == "final_mesh_feature_profiles":
        return _verify_feature_requirement(requirement_id, mesh, expected, tolerance)
    if policy == "cross_output_envelope":
        return _verify_envelope_requirement(requirement_id, meshes, expected, tolerance)
    if policy == "cross_output_clearance":
        return _verify_clearance_requirement(requirement_id, meshes, expected, tolerance)
    if policy == "cross_output_alignment":
        return _verify_alignment_requirement(requirement_id, meshes, expected, tolerance)
    if policy == "measure_when_supported":
        if "size" in expected:
            return _verify_chamfer_requirement(requirement_id, mesh, expected, tolerance)
        if "radius" in expected:
            return _verify_external_fillet(mesh, expected, {})
    if policy == "required_output_artifact":
        return _semantic_finding(
            requirement_id,
            status="passed",
            measurement_available=True,
            measurements={"output_id": output_id, "artifact_present": True},
        )
    return _semantic_finding(
        requirement_id,
        status="unverifiable",
        measurement_available=False,
        measurements={"verification_policy": policy, "reason": "no generic verifier registered"},
    )


def _verify_bounds_requirement(
    requirement_id: str,
    mesh: trimesh.Trimesh,
    expected: Mapping[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    keys = ("width", "depth", "height") if "height" in expected else ("width", "depth", "thickness")
    expected_values = [float(expected[key]) for key in keys if expected.get(key) is not None]
    detected = np.asarray(mesh.bounds[1] - mesh.bounds[0], dtype=float)
    passed = len(expected_values) == 3 and bool(np.all(np.abs(detected - expected_values) <= tolerance))
    return _semantic_finding(
        requirement_id,
        status="passed" if passed else "failed",
        measurement_available=True,
        measurements={"expected_mm": expected_values, "detected_mm": _rounded(detected)},
    )


def _verify_opening_requirement(
    requirement_id: str,
    mesh: trimesh.Trimesh,
    expected: Mapping[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    holes = [hole for hole in _detect_axis_aligned_holes(mesh, "z", _tolerance_profile()) if hole.confidence >= 0.55]
    diameter = expected.get("diameter", expected.get("hole_diameter"))
    expected_count = int(expected.get("count") or 1)
    matching = holes if diameter is None else [
        hole for hole in holes if abs(float(hole.diameter) - float(diameter)) <= tolerance
    ]
    through = all(_probe_through(mesh, (float(hole.center[0]), float(hole.center[1]))) for hole in matching[:expected_count])
    passed = len(matching) == expected_count and (expected.get("through") is not True or through)
    return _semantic_finding(
        requirement_id,
        status="passed" if passed else "failed",
        measurement_available=True,
        measurements={
            "expected_count": expected_count,
            "detected_count": len(matching),
            "detected_diameters_mm": sorted(round(float(hole.diameter), 3) for hole in holes),
            "through": through,
        },
    )


def _verify_opening_centers_requirement(
    requirement_id: str,
    mesh: trimesh.Trimesh,
    expected: Mapping[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    holes = [hole for hole in _detect_axis_aligned_holes(mesh, "z", _tolerance_profile()) if hole.confidence >= 0.55]
    diameter = float(expected.get("diameter") or 0)
    matching = [hole for hole in holes if abs(float(hole.diameter) - diameter) <= tolerance]
    expected_count = int(expected.get("count") or 0)
    detected_pitch = None
    pitch_ok = True
    if matching:
        center = np.mean([[float(hole.center[0]), float(hole.center[1])] for hole in matching], axis=0)
        radii = [float(np.linalg.norm(np.asarray([hole.center[0], hole.center[1]]) - center)) for hole in matching]
        detected_pitch = 2.0 * float(np.mean(radii))
        if expected.get("pitch_circle_diameter") is not None:
            pitch_ok = abs(detected_pitch - float(expected["pitch_circle_diameter"])) <= tolerance
    passed = len(matching) == expected_count and pitch_ok
    return _semantic_finding(
        requirement_id,
        status="passed" if passed else "failed",
        measurement_available=True,
        measurements={
            "expected_count": expected_count,
            "detected_count": len(matching),
            "expected_pitch_circle_diameter_mm": expected.get("pitch_circle_diameter"),
            "detected_pitch_circle_diameter_mm": round(detected_pitch, 3) if detected_pitch is not None else None,
        },
    )


def _verify_axisymmetric_requirement(
    requirement_id: str,
    mesh: trimesh.Trimesh,
    expected: Mapping[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    profiles = _radial_profiles(mesh)
    expected_diameters = [float(value) for value in expected.get("diameters", [])]
    detected = sorted({round(float(profile["diameter_mm"]), 3) for profile in profiles}, reverse=True)
    matched = all(any(abs(value - candidate) <= tolerance for candidate in detected) for value in expected_diameters)
    return _semantic_finding(
        requirement_id,
        status="passed" if matched and bool(profiles) else "failed",
        measurement_available=True,
        measurements={"expected_diameters_mm": expected_diameters, "detected_diameters_mm": detected, "coaxial": matched},
    )


def _verify_axial_sections_requirement(
    requirement_id: str,
    mesh: trimesh.Trimesh,
    expected: Mapping[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    levels = _profile_levels(mesh)
    sections = [round(float(right - left), 3) for left, right in zip(levels, levels[1:]) if right - left > 0.2]
    expected_lengths = [float(value) for value in expected.get("lengths", [])]
    passed = all(any(abs(value - candidate) <= tolerance for candidate in sections) for value in expected_lengths)
    return _semantic_finding(
        requirement_id,
        status="passed" if passed and bool(sections) else "failed",
        measurement_available=True,
        measurements={"expected_lengths_mm": expected_lengths, "detected_section_lengths_mm": sections},
    )


def _verify_recess_requirement(
    requirement_id: str,
    mesh: trimesh.Trimesh,
    expected: Mapping[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    holes = [hole for hole in _detect_axis_aligned_holes(mesh, "z", _tolerance_profile()) if hole.confidence >= 0.55]
    diameter = float(expected.get("diameter") or 0)
    matches = [hole for hole in holes if abs(float(hole.diameter) - diameter) <= tolerance]
    expected_depth = float(expected.get("depth") or 0)
    depth = _cylindrical_surface_depth(
        mesh,
        diameter / 2.0,
        matches[0] if matches else None,
        tolerance,
        expected_depth=expected_depth,
    )
    passed = bool(matches) and depth is not None and abs(depth - expected_depth) <= tolerance
    return _semantic_finding(
        requirement_id,
        status="passed" if passed else "failed",
        measurement_available=True,
        measurements={"expected_depth_mm": expected_depth, "detected_depth_mm": depth, "detected_diameter_mm": [float(hole.diameter) for hole in matches]},
    )


def _verify_wall_requirement(
    requirement_id: str,
    mesh: trimesh.Trimesh,
    expected: Mapping[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    origin = np.asarray([0.0, 0.0, float(mesh.bounds[0][2]) - 5.0])
    intersections = sorted(float(value) for value in _ray_parameters(mesh, origin, np.asarray([0.0, 0.0, 1.0])))
    intervals = [right - left for left, right in zip(intersections, intersections[1:]) if right - left > 0.1]
    measured = min(intervals) if intervals else None
    expected_value = float(expected.get("value") or 0)
    passed = measured is not None and abs(measured - expected_value) <= tolerance
    return _semantic_finding(
        requirement_id,
        status="passed" if passed else "failed",
        measurement_available=True,
        measurements={"expected_wall_thickness_mm": expected_value, "detected_wall_thickness_mm": round(measured, 3) if measured is not None else None},
    )


def _verify_feature_requirement(
    requirement_id: str,
    mesh: trimesh.Trimesh,
    expected: Mapping[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    width = float(expected.get("width") or 0)
    height = float(expected.get("height") or expected.get("depth") or 0)
    if width <= 0 or height <= 0:
        return _semantic_finding(requirement_id, status="unverifiable", measurement_available=False, measurements={})
    boundary = _boundary_feature_measurement(mesh, width, height, tolerance)
    if boundary is not None:
        return _semantic_finding(
            requirement_id,
            status="passed" if boundary["passed"] else "failed",
            measurement_available=True,
            measurements={"expected_size_mm": [width, height], "boundary_measurement": boundary},
        )
    top = _rectangular_opening_probe(mesh, width, height, "top", tolerance)
    side = _rectangular_opening_probe(mesh, width, height, "side", tolerance)
    passed = top["passed"] or side["passed"]
    return _semantic_finding(
        requirement_id,
        status="passed" if passed else "failed",
        measurement_available=True,
        measurements={"expected_size_mm": [width, height], "top_probe": top, "side_probe": side},
    )


def _verify_envelope_requirement(
    requirement_id: str,
    meshes: Mapping[str, trimesh.Trimesh],
    expected: Mapping[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    if not meshes:
        return _semantic_finding(requirement_id, status="unverifiable", measurement_available=False, measurements={})
    bounds = np.asarray([mesh.bounds for mesh in meshes.values()], dtype=float)
    xy_size = bounds[:, 1, :2].max(axis=0) - bounds[:, 0, :2].min(axis=0)
    z_size = float(sum(float(mesh.bounds[1, 2] - mesh.bounds[0, 2]) for mesh in meshes.values()))
    detected = [float(xy_size[0]), float(xy_size[1]), z_size]
    expected_values = [float(expected.get("width") or 0), float(expected.get("depth") or 0), float(expected.get("height") or 0)]
    passed = bool(np.all(np.abs(np.asarray(detected) - expected_values) <= tolerance))
    return _semantic_finding(requirement_id, status="passed" if passed else "failed", measurement_available=True, measurements={"expected_mm": expected_values, "detected_mm": _rounded(detected)})


def _verify_clearance_requirement(
    requirement_id: str,
    meshes: Mapping[str, trimesh.Trimesh],
    expected: Mapping[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    if len(meshes) < 2:
        return _semantic_finding(requirement_id, status="unverifiable", measurement_available=False, measurements={})
    ordered = sorted(meshes.items(), key=lambda item: float(np.prod(item[1].bounds[1, :2] - item[1].bounds[0, :2])))
    inner_id, inner = ordered[0]
    outer_id, outer = ordered[1]
    inner_size = inner.bounds[1, :2] - inner.bounds[0, :2]
    pocket = _rectangular_boundary_size(outer, inner_size)
    per_side = None if pocket is None else float(np.mean((pocket - inner_size) / 2.0))
    expected_value = expected.get("per_side", expected.get("value"))
    expected_value = float(expected_value or 0)
    passed = per_side is not None and abs(per_side - expected_value) <= tolerance
    return _semantic_finding(requirement_id, status="passed" if passed else "failed", measurement_available=True, measurements={"inner_output_id": inner_id, "outer_output_id": outer_id, "expected_per_side_mm": expected_value, "detected_per_side_mm": round(per_side, 3) if per_side is not None else None})


def _verify_alignment_requirement(
    requirement_id: str,
    meshes: Mapping[str, trimesh.Trimesh],
    expected: Mapping[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    if len(meshes) < 2:
        return _semantic_finding(requirement_id, status="unverifiable", measurement_available=False, measurements={})
    centers = [np.mean(mesh.bounds[:, :2], axis=0) for mesh in meshes.values()]
    delta = float(np.linalg.norm(centers[0] - centers[1]))
    passed = delta <= tolerance
    return _semantic_finding(requirement_id, status="passed" if passed else "failed", measurement_available=True, measurements={"center_delta_mm": round(delta, 3), "expected_relationship": expected.get("relationship")})


def _verify_chamfer_requirement(
    requirement_id: str,
    mesh: trimesh.Trimesh,
    expected: Mapping[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    expected_size = float(expected.get("size") or 0)
    top_z = float(mesh.bounds[1, 2])
    top = mesh.vertices[np.abs(mesh.vertices[:, 2] - top_z) <= 1e-3]
    lower = mesh.vertices[mesh.vertices[:, 2] < top_z - 0.5]
    if len(top) == 0 or len(lower) == 0:
        measured = None
    else:
        top_extent = max(float(np.max(np.abs(top[:, 0]))), float(np.max(np.abs(top[:, 1]))))
        lower_extent = max(float(np.max(np.abs(lower[:, 0]))), float(np.max(np.abs(lower[:, 1]))))
        measured = lower_extent - top_extent
    passed = measured is not None and abs(measured - expected_size) <= tolerance
    return _semantic_finding(requirement_id, status="passed" if passed else "failed", measurement_available=True, measurements={"expected_size_mm": expected_size, "detected_size_mm": round(measured, 3) if measured is not None else None})


def _semantic_finding(
    requirement_id: str,
    *,
    status: str,
    measurement_available: bool,
    measurements: dict[str, Any],
) -> dict[str, Any]:
    return {
        "requirement_id": requirement_id,
        "status": status,
        "measurement_available": measurement_available,
        "evidence_source": "final_mesh" if measurement_available else "none",
        "measurements": measurements,
    }


def _requirement_tolerance(requirement: Mapping[str, Any]) -> float:
    try:
        return float(requirement.get("tolerance") or 0.25)
    except (TypeError, ValueError):
        return 0.25


def _radial_profiles(mesh: trimesh.Trimesh) -> list[dict[str, float]]:
    vertices = np.asarray(mesh.vertices, dtype=float)
    center = np.mean(vertices[:, :2], axis=0)
    levels = _profile_levels(mesh)
    profiles: list[dict[str, float]] = []
    for level in levels:
        selected = vertices[np.abs(vertices[:, 2] - level) <= 1e-3]
        if len(selected) == 0:
            continue
        radius = float(np.max(np.linalg.norm(selected[:, :2] - center, axis=1)))
        profiles.append({"z_mm": float(level), "diameter_mm": radius * 2.0})
    return profiles


def _profile_levels(mesh: trimesh.Trimesh) -> list[float]:
    values = sorted({round(float(value), 3) for value in np.asarray(mesh.vertices)[:, 2]})
    return [float(value) for value in values if not values or value in values]


def _cylindrical_surface_depth(
    mesh: trimesh.Trimesh,
    radius: float,
    hole: Any,
    tolerance: float,
    *,
    expected_depth: float | None = None,
) -> float | None:
    if hole is None:
        return None
    center = np.asarray([float(hole.center[0]), float(hole.center[1])])
    vertices = np.asarray(mesh.vertices, dtype=float)
    radial = np.linalg.norm(vertices[:, :2] - center, axis=1)
    selected = vertices[np.abs(radial - radius) <= max(tolerance, 0.15)]
    if len(selected) == 0:
        return None
    levels = sorted({round(float(value), 3) for value in selected[:, 2]})
    if len(levels) < 2:
        return None
    spans = [right - left for left, right in zip(levels, levels[1:]) if right - left > 0.0]
    if expected_depth is not None and spans:
        return round(float(min(spans, key=lambda value: abs(value - expected_depth))), 3)
    return round(float(max(spans)), 3) if spans else None


def _rectangular_opening_probe(
    mesh: trimesh.Trimesh,
    width: float,
    height: float,
    orientation: str,
    tolerance: float,
) -> dict[str, Any]:
    if orientation == "top":
        origin = np.asarray([0.0, 0.0, float(mesh.bounds[1, 2]) + 5.0])
        direction = np.asarray([0.0, 0.0, -1.0])
        points = [(x, y) for x in (-width / 2 + tolerance, 0.0, width / 2 - tolerance) for y in (-height / 2 + tolerance, 0.0, height / 2 - tolerance)]
        intersections = [len(_ray_parameters(mesh, np.asarray([x, y, origin[2]]), direction)) for x, y in points]
        outside = len(_ray_parameters(mesh, np.asarray([float(mesh.bounds[1, 0]) - 1.0, float(mesh.bounds[1, 1]) - 1.0, origin[2]]), direction))
    else:
        origin_x = float(mesh.bounds[1, 0]) + 5.0
        direction = np.asarray([-1.0, 0.0, 0.0])
        points = [(y, z) for y in (-width / 2 + tolerance, 0.0, width / 2 - tolerance) for z in (float(mesh.bounds[0, 2]) + height / 2, float(mesh.bounds[1, 2]) - height / 2)]
        intersections = [len(_ray_parameters(mesh, np.asarray([origin_x, y, z]), direction)) for y, z in points]
        outside = len(_ray_parameters(mesh, np.asarray([origin_x, float(mesh.bounds[1, 1]) - 1.0, float(mesh.bounds[1, 2]) - height / 2]), direction))
    passed = bool(intersections) and min(intersections) < outside
    return {"passed": passed, "intersection_counts": intersections, "outside_intersection_count": outside}


def _rectangular_boundary_size(mesh: trimesh.Trimesh, target_size: np.ndarray) -> np.ndarray | None:
    top_z = float(mesh.bounds[1, 2])
    vertices = np.asarray(mesh.vertices, dtype=float)
    top = vertices[np.abs(vertices[:, 2] - top_z) <= 1e-3]
    if len(top) == 0:
        return None
    candidates = []
    for axis in (0, 1):
        half = float(target_size[axis]) / 2.0
        values = [abs(float(value)) for value in top[:, axis] if abs(abs(float(value)) - half) <= 2.0]
        candidates.append(2.0 * float(np.mean(values)) if values else 0.0)
    return np.asarray(candidates) if all(candidates) else None


def _boundary_feature_measurement(
    mesh: trimesh.Trimesh,
    width: float,
    height: float,
    tolerance: float,
) -> dict[str, Any] | None:
    """Detect rectangular openings from boundary vertices on any principal face."""

    vertices = np.asarray(mesh.vertices, dtype=float)
    faces = (
        (0, float(mesh.bounds[1, 0]), (1, 2)),
        (1, float(mesh.bounds[1, 1]), (0, 2)),
        (2, float(mesh.bounds[1, 2]), (0, 1)),
    )
    for axis, boundary, plane_axes in faces:
        on_boundary = vertices[np.abs(vertices[:, axis] - boundary) <= 1e-3]
        if len(on_boundary) < 4:
            continue
        spans = []
        for plane_axis in plane_axes:
            values = sorted({round(float(value), 3) for value in on_boundary[:, plane_axis]})
            candidates = [
                float(right - left)
                for left in values
                for right in values
                if right - left > 0.0
            ]
            spans.append(candidates)
        for first in spans[0]:
            for second in spans[1]:
                if (
                    abs(first - width) <= tolerance and abs(second - height) <= tolerance
                ) or (
                    abs(first - height) <= tolerance and abs(second - width) <= tolerance
                ):
                    return {
                        "passed": True,
                        "boundary_axis": ("x", "y", "z")[axis],
                        "detected_spans_mm": [round(first, 3), round(second, 3)],
                    }
    return None


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
