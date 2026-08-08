"""Non-production characterization tooling for analytic B-Rep interfaces.

This module deliberately stops before semantic verification.  It enumerates
analytic cylindrical evidence, then permits comparison only after a geometric
target descriptor selects exactly one candidate.  Expected diameter is never
used during candidate selection.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot, isclose, sqrt
from pathlib import Path
from typing import Any, Iterable

import cadquery as cq


Vector3 = tuple[float, float, float]


@dataclass(frozen=True)
class CircularBoundary:
    edge_id: str
    center: Vector3 | None
    radius: float | None
    adjacent_face_ids: tuple[str, ...]


@dataclass(frozen=True)
class CylinderCandidate:
    candidate_id: str
    output_id: str
    source_brep_hash: str
    owning_face_identity: str
    radius: float
    diameter: float
    axis_origin: Vector3
    axis_direction: Vector3
    axial_extent: tuple[float, float]
    surface_area: float
    adjacent_edge_ids: tuple[str, ...]
    adjacent_face_ids: tuple[str, ...]
    circular_boundaries: tuple[CircularBoundary, ...]
    boundary_loops: tuple[tuple[str, ...], ...]
    surface_role: str
    opening_state: str

    @property
    def circular_boundary_edge_count(self) -> int:
        return len(self.circular_boundaries)


@dataclass(frozen=True)
class ConnectionTarget:
    """Evaluator-only target descriptor; not a production requirement schema."""

    axis_origin: Vector3
    axis_direction: Vector3
    interface_point: Vector3 | None = None
    diameter_role: str | None = None
    opening_required: bool = True
    axis_tolerance_mm: float = 1e-5
    point_tolerance_mm: float = 1e-4


@dataclass(frozen=True)
class TargetSelection:
    status: str
    reason: str
    candidate_ids: tuple[str, ...]


@dataclass(frozen=True)
class DiameterCheck:
    status: str
    reason: str
    candidate_id: str | None
    measured_diameter: float | None
    expected_diameter: float
    tolerance_mm: float
    selection: TargetSelection


def enumerate_cylindrical_candidates(
    shape: cq.Shape,
    *,
    source_brep_hash: str,
    output_id: str = "synthetic_output",
) -> list[CylinderCandidate]:
    faces = list(shape.Faces())
    edge_records = _edge_records(faces)
    candidates: list[CylinderCandidate] = []
    for face_index, face in enumerate(faces):
        if face.geomType() != "CYLINDER":
            continue
        adaptor = face._geomAdaptor()
        axis = adaptor.Axis()
        axis_origin = _coord(axis.Location())
        axis_direction = _unit(_coord(axis.Direction()))
        candidate_id = f"face-{face_index}"
        face_edges = list(face.Edges())
        edge_ids = tuple(_edge_id(edge, edge_records) for edge in face_edges)
        adjacent_faces = tuple(
            sorted(
                {
                    face_id
                    for edge in face_edges
                    for face_id in _edge_record(edge, edge_records)["face_ids"]
                    if face_id != candidate_id
                }
            )
        )
        circular_boundaries = tuple(
            _circular_boundary(edge, edge_records)
            for edge in face_edges
            if edge.geomType() == "CIRCLE"
        )
        boundary_loops = tuple(
            tuple(_edge_id(edge, edge_records) for edge in wire.Edges())
            for wire in face.Wires()
        )
        axial_extent = _axial_extent(face, axis_origin, axis_direction)
        candidates.append(
            CylinderCandidate(
                candidate_id=candidate_id,
                output_id=output_id,
                source_brep_hash=source_brep_hash,
                owning_face_identity=candidate_id,
                radius=round(float(adaptor.Radius()), 9),
                diameter=round(float(adaptor.Radius() * 2.0), 9),
                axis_origin=_round(axis_origin),
                axis_direction=_round(axis_direction),
                axial_extent=tuple(round(value, 9) for value in axial_extent),
                surface_area=round(float(face.Area()), 9),
                adjacent_edge_ids=tuple(sorted(edge_ids)),
                adjacent_face_ids=adjacent_faces,
                circular_boundaries=circular_boundaries,
                boundary_loops=boundary_loops,
                surface_role=_infer_surface_role(shape, face, axis_origin, axis_direction),
                opening_state=_infer_opening_state(face_index, faces, edge_records),
            )
        )
    return candidates


def select_unique_connection_candidate(
    candidates: Iterable[CylinderCandidate],
    target: ConnectionTarget,
) -> TargetSelection:
    axis_origin = target.axis_origin
    axis_direction = _unit(target.axis_direction)
    matched: list[CylinderCandidate] = []
    for candidate in candidates:
        if not _same_axis_line(
            candidate.axis_origin,
            candidate.axis_direction,
            axis_origin,
            axis_direction,
            target.axis_tolerance_mm,
        ):
            continue
        if target.interface_point is not None and not _point_near_candidate(
            target.interface_point,
            candidate,
            target.point_tolerance_mm,
        ):
            continue
        if target.diameter_role is not None and candidate.surface_role != target.diameter_role:
            continue
        if target.opening_required and candidate.opening_state != "external_opening":
            continue
        matched.append(candidate)
    ids = tuple(candidate.candidate_id for candidate in matched)
    if len(matched) == 1:
        return TargetSelection("resolved", "unique_geometry_target", ids)
    if not matched:
        return TargetSelection("unverifiable", "no_candidate_satisfies_target", ids)
    return TargetSelection("ambiguous", "multiple_candidates_satisfy_target", ids)


def compare_selected_diameter(
    candidates: Iterable[CylinderCandidate],
    *,
    target: ConnectionTarget,
    expected_diameter: float,
    operator: str = "exact",
    tolerance_mm: float = 0.1,
) -> DiameterCheck:
    selection = select_unique_connection_candidate(candidates, target)
    if selection.status != "resolved":
        return DiameterCheck(
            status="UNVERIFIABLE",
            reason=selection.reason,
            candidate_id=None,
            measured_diameter=None,
            expected_diameter=expected_diameter,
            tolerance_mm=tolerance_mm,
            selection=selection,
        )
    candidate_id = selection.candidate_ids[0]
    candidate = next(item for item in candidates if item.candidate_id == candidate_id)
    measured = candidate.diameter
    if operator in {"exact", "approximately"}:
        passed = isclose(measured, expected_diameter, abs_tol=tolerance_mm)
    elif operator in {"minimum", "at_least", ">="}:
        passed = measured >= expected_diameter - tolerance_mm
    elif operator in {"maximum", "at_most", "<="}:
        passed = measured <= expected_diameter + tolerance_mm
    else:
        return DiameterCheck(
            status="UNVERIFIABLE",
            reason="unsupported_operator",
            candidate_id=candidate_id,
            measured_diameter=measured,
            expected_diameter=expected_diameter,
            tolerance_mm=tolerance_mm,
            selection=selection,
        )
    return DiameterCheck(
        status="PASS" if passed else "FAIL",
        reason="measurement_matches_requirement" if passed else "measurement_outside_tolerance",
        candidate_id=candidate_id,
        measured_diameter=measured,
        expected_diameter=expected_diameter,
        tolerance_mm=tolerance_mm,
        selection=selection,
    )


def load_brep_candidates(
    path: Path,
    *,
    source_brep_hash: str,
    output_id: str,
) -> list[CylinderCandidate]:
    shape = cq.importers.importBrep(str(path))
    return enumerate_cylindrical_candidates(
        shape,
        source_brep_hash=source_brep_hash,
        output_id=output_id,
    )


def _edge_records(faces: list[cq.Face]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for face_index, face in enumerate(faces):
        for edge in face.Edges():
            record = next(
                (item for item in records if edge.wrapped.IsSame(item["edge"].wrapped)),
                None,
            )
            if record is None:
                record = {
                    "edge_id": f"edge-{len(records)}",
                    "face_ids": set(),
                    "edge": edge,
                }
                records.append(record)
            record["face_ids"].add(f"face-{face_index}")
    return records


def _edge_record(edge: Any, records: list[dict[str, Any]]) -> dict[str, Any]:
    return next(item for item in records if edge.wrapped.IsSame(item["edge"].wrapped))


def _edge_id(edge: Any, records: list[dict[str, Any]]) -> str:
    return str(_edge_record(edge, records)["edge_id"])


def _circular_boundary(edge: Any, records: list[dict[str, Any]]) -> CircularBoundary:
    center: Vector3 | None = None
    radius: float | None = None
    try:
        center = _round(_coord(edge.arcCenter()))
        radius = round(float(edge.radius()), 9)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    return CircularBoundary(
        edge_id=_edge_id(edge, records),
        center=center,
        radius=radius,
        adjacent_face_ids=tuple(sorted(_edge_record(edge, records)["face_ids"])),
    )


def _axial_extent(face: cq.Face, axis_origin: Vector3, axis_direction: Vector3) -> tuple[float, float]:
    points = [_coord(vertex.Center()) for vertex in face.Vertices()]
    if not points:
        points = [_coord(edge.arcCenter()) for edge in face.Edges() if edge.geomType() == "CIRCLE"]
    if not points:
        return (0.0, 0.0)
    projections = [_dot(_sub(point, axis_origin), axis_direction) for point in points]
    return (min(projections), max(projections))


def _infer_surface_role(
    shape: cq.Shape,
    face: cq.Face,
    axis_origin: Vector3,
    axis_direction: Vector3,
) -> str:
    """Use local material-side probing; return unknown when not decisive."""
    try:
        point = _coord(face.Center())
        axial = _add(axis_origin, _scale(axis_direction, _dot(_sub(point, axis_origin), axis_direction)))
        radial = _sub(point, axial)
        radial_length = _length(radial)
        if radial_length <= 1e-7:
            return "unknown"
        radial = _scale(radial, 1.0 / radial_length)
        epsilon = min(max(float(radial_length) * 0.05, 0.01), 0.2)
        toward_axis = _sub(point, _scale(radial, epsilon))
        away_from_axis = _add(point, _scale(radial, epsilon))
        toward_inside = bool(shape.isInside(cq.Vector(*toward_axis), epsilon * 0.25, True))
        away_inside = bool(shape.isInside(cq.Vector(*away_from_axis), epsilon * 0.25, True))
        if toward_inside and not away_inside:
            return "outer"
        if away_inside and not toward_inside:
            return "inner"
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    return "unknown"


def _infer_opening_state(
    face_index: int,
    faces: list[cq.Face],
    edge_records: list[dict[str, Any]],
) -> str:
    """Conservative planar-boundary signal; caps and non-planar hosts stay unknown."""
    face = faces[face_index]
    circular_edges = [edge for edge in face.Edges() if edge.geomType() == "CIRCLE"]
    if not circular_edges:
        return "unknown"
    has_external_two_wire_boundary = False
    has_internal_cap = False
    for edge in circular_edges:
        adjacent_faces = _edge_record(edge, edge_records)["face_ids"]
        for face_id in adjacent_faces:
            if face_id == f"face-{face_index}":
                continue
            adjacent = faces[int(face_id.split("-")[-1])]
            if adjacent.geomType() != "PLANE":
                continue
            wire_count = len(adjacent.Wires())
            if wire_count >= 2:
                has_external_two_wire_boundary = True
            elif wire_count == 1:
                has_internal_cap = True
    if has_internal_cap:
        return "blind_recess"
    return "external_opening" if has_external_two_wire_boundary else "unknown"


def _point_near_candidate(point: Vector3, candidate: CylinderCandidate, tolerance: float) -> bool:
    axis = _unit(candidate.axis_direction)
    origin_to_point = _sub(point, candidate.axis_origin)
    axial = _add(candidate.axis_origin, _scale(axis, _dot(origin_to_point, axis)))
    radial_distance = _length(_sub(point, axial))
    axial_position = _dot(origin_to_point, axis)
    return (
        abs(radial_distance - candidate.radius) <= tolerance
        and candidate.axial_extent[0] - tolerance <= axial_position <= candidate.axial_extent[1] + tolerance
    )


def _same_axis_line(
    candidate_origin: Vector3,
    candidate_direction: Vector3,
    target_origin: Vector3,
    target_direction: Vector3,
    tolerance: float,
) -> bool:
    candidate_direction = _unit(candidate_direction)
    target_direction = _unit(target_direction)
    if abs(abs(_dot(candidate_direction, target_direction)) - 1.0) > 1e-6:
        return False
    separation = _cross(_sub(candidate_origin, target_origin), target_direction)
    return _length(separation) <= tolerance


def _coord(value: Any) -> Vector3:
    if hasattr(value, "x"):
        return (float(value.x), float(value.y), float(value.z))
    if hasattr(value, "X"):
        return (float(value.X()), float(value.Y()), float(value.Z()))
    if hasattr(value, "Coord"):
        return tuple(float(item) for item in value.Coord())
    return tuple(float(item) for item in value)


def _round(value: Vector3) -> Vector3:
    return tuple(round(float(item), 9) for item in value)


def _unit(value: Vector3) -> Vector3:
    length = _length(value)
    if length <= 1e-12:
        return (0.0, 0.0, 0.0)
    return _scale(value, 1.0 / length)


def _length(value: Vector3) -> float:
    return sqrt(sum(item * item for item in value))


def _dot(left: Vector3, right: Vector3) -> float:
    return sum(a * b for a, b in zip(left, right))


def _cross(left: Vector3, right: Vector3) -> Vector3:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _add(left: Vector3, right: Vector3) -> Vector3:
    return tuple(a + b for a, b in zip(left, right))


def _sub(left: Vector3, right: Vector3) -> Vector3:
    return tuple(a - b for a, b in zip(left, right))


def _scale(value: Vector3, scalar: float) -> Vector3:
    return tuple(item * scalar for item in value)
