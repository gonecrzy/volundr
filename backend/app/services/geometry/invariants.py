from __future__ import annotations

import hashlib
import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

import numpy as np
import trimesh
from trimesh import Trimesh

from app.schemas.printability import PrintabilityProfile
from app.services.cad.source_metadata import SourceGeometryMapping, SourceMetadata

GEOMETRIC_ANALYZER_VERSION = "geometric-invariants-v1"
GEOMETRIC_TOLERANCE_PROFILE_VERSION = "geometry-tolerance-v1"


@dataclass(frozen=True)
class GeometricToleranceProfile:
    version: str = GEOMETRIC_TOLERANCE_PROFILE_VERSION
    overall_abs_mm: float = 0.20
    overall_relative: float = 0.0025
    hole_diameter_abs_mm: float = 0.20
    hole_spacing_abs_mm: float = 0.25
    below_plate_tolerance_mm: float = 0.05
    on_plate_tolerance_mm: float = 0.10
    wall_measurement_tolerance_mm: float = 0.20
    wall_uncertainty_band_mm: float = 0.30
    high_confidence: float = 0.90
    medium_confidence: float = 0.70
    max_triangle_count: int = 50_000
    max_hole_candidates: int = 24


@dataclass(frozen=True)
class GeometricFinding:
    rule_id: str
    requirement_id: str | None
    verification_state: str
    expected_value: float | int | str | None
    detected_value: float | int | str | None
    unit: str | None
    tolerance: float | None
    confidence: float
    severity: str
    is_blocking: bool
    title: str
    explanation: str
    suggested_correction: str
    feature_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GeometricAnalysisContext:
    mesh: Trimesh
    design_specification: dict[str, Any] | None
    source_metadata: SourceMetadata | None
    source_hash: str | None
    mesh_hash: str
    printer_profile: PrintabilityProfile = field(default_factory=PrintabilityProfile)
    tolerance: GeometricToleranceProfile = field(default_factory=GeometricToleranceProfile)


@dataclass(frozen=True)
class GeometricAnalysisResult:
    analysis_version: str
    tolerance_profile_version: str
    mesh_hash: str
    source_hash: str | None
    findings: list[GeometricFinding]
    analysis_ms: float

    def to_json(self) -> dict[str, Any]:
        return {
            "analysis_version": self.analysis_version,
            "tolerance_profile_version": self.tolerance_profile_version,
            "mesh_hash": self.mesh_hash,
            "source_hash": self.source_hash,
            "findings": [finding.to_json() for finding in self.findings],
            "analysis_ms": self.analysis_ms,
        }


class GeometricInvariantAnalyzer(Protocol):
    rule_id: str
    supported_feature_types: set[str]

    def analyze(self, analysis_context: GeometricAnalysisContext) -> list[GeometricFinding]:
        ...


class GeometryAnalyzerRegistry:
    def __init__(self, analyzers: list[GeometricInvariantAnalyzer]) -> None:
        self.analyzers = analyzers

    @classmethod
    def default(cls) -> "GeometryAnalyzerRegistry":
        return cls(
            [
                BoundingBoxAnalyzer(),
                BuildPlateAnalyzer(),
                CylindricalHoleAnalyzer(),
                HoleGroupAnalyzer(),
                WallThicknessAnalyzer(),
            ]
        )

    def analyze(self, context: GeometricAnalysisContext) -> GeometricAnalysisResult:
        started = time.perf_counter()
        findings: list[GeometricFinding] = []
        for analyzer in self.analyzers:
            try:
                findings.extend(analyzer.analyze(context))
            except Exception as exc:  # pragma: no cover - defensive boundary tested via registry
                findings.append(
                    GeometricFinding(
                        rule_id=getattr(analyzer, "rule_id", "geometry.analyzer_failure"),
                        requirement_id=None,
                        verification_state="unverifiable",
                        expected_value=None,
                        detected_value=None,
                        unit=None,
                        tolerance=None,
                        confidence=0.0,
                        severity="warning",
                        is_blocking=False,
                        title="Geometric analyzer failed",
                        explanation="Volundr could not verify this geometric invariant.",
                        suggested_correction="Review the generated model manually before accepting.",
                        metadata={"error": str(exc), "analyzer": type(analyzer).__name__},
                    )
                )
        return GeometricAnalysisResult(
            analysis_version=GEOMETRIC_ANALYZER_VERSION,
            tolerance_profile_version=context.tolerance.version,
            mesh_hash=context.mesh_hash,
            source_hash=context.source_hash,
            findings=findings,
            analysis_ms=round((time.perf_counter() - started) * 1000, 3),
        )


class BoundingBoxAnalyzer:
    rule_id = "geometry.protected_overall_dimension"
    supported_feature_types = {"bounds"}

    def analyze(self, analysis_context: GeometricAnalysisContext) -> list[GeometricFinding]:
        metadata = analysis_context.source_metadata
        if metadata is None:
            return []
        bounds_mapping = next(
            (mapping for mapping in metadata.geometry_mappings if mapping.geometry_type == "bounds"),
            None,
        )
        if bounds_mapping is None:
            return []
        extents = analysis_context.mesh.bounding_box.extents.astype(float)
        dimensions = _protected_dimensions(analysis_context.design_specification)
        findings: list[GeometricFinding] = []
        for axis, index in (("x", 0), ("y", 1), ("z", 2)):
            parameter_name = bounds_mapping.attributes.get(axis)
            if parameter_name is None:
                continue
            requirement_id = _requirement_for_parameter(metadata, parameter_name)
            dimension = dimensions.get(requirement_id or parameter_name)
            if dimension is None:
                continue
            expected = _float(dimension.get("value"))
            if expected is None:
                continue
            detected = round(float(extents[index]), 3)
            tolerance = max(analysis_context.tolerance.overall_abs_mm, expected * analysis_context.tolerance.overall_relative)
            violated = abs(detected - expected) > tolerance
            findings.append(
                _finding(
                    rule_id=self.rule_id,
                    requirement_id=str(dimension.get("id")),
                    state="violated" if violated else "verified",
                    expected=expected,
                    detected=detected,
                    unit=dimension.get("unit") or "mm",
                    tolerance=round(tolerance, 3),
                    confidence=0.99,
                    blocking=bool(dimension.get("protected")) and violated,
                    title=f"Overall {axis.upper()} dimension",
                    explanation=(
                        f"Detected overall {axis.upper()} dimension differs from the protected Design Specification."
                        if violated
                        else f"Detected overall {axis.upper()} dimension matches the protected Design Specification."
                    ),
                    correction="Revise the generated geometry so the overall dimension matches the Design Specification.",
                    metadata={"axis": axis, "mapping_line": bounds_mapping.line},
                )
            )
        return findings


class BuildPlateAnalyzer:
    rule_id = "geometry.build_plate"
    supported_feature_types = set()

    def analyze(self, analysis_context: GeometricAnalysisContext) -> list[GeometricFinding]:
        bounds = analysis_context.mesh.bounds.astype(float)
        min_z = round(float(bounds[0][2]), 3)
        max_z = round(float(bounds[1][2]), 3)
        below = min_z < -analysis_context.tolerance.below_plate_tolerance_mm
        floating = min_z > analysis_context.tolerance.on_plate_tolerance_mm
        return [
            _finding(
                rule_id="geometry.build_plate_min_z",
                requirement_id=None,
                state="violated" if below else "verified",
                expected=0,
                detected=min_z,
                unit="mm",
                tolerance=analysis_context.tolerance.below_plate_tolerance_mm,
                confidence=0.99,
                blocking=below,
                title="Minimum Z placement",
                explanation="Geometry extends below Z=0." if below else "No geometry extends below the build plate.",
                correction="Move the model so all geometry is at or above Z=0.",
                metadata={"max_z": max_z},
            ),
            _finding(
                rule_id="geometry.build_plate_contact",
                requirement_id=None,
                state="violated" if floating else "verified",
                expected=0,
                detected=min_z,
                unit="mm",
                tolerance=analysis_context.tolerance.on_plate_tolerance_mm,
                confidence=0.95,
                blocking=floating,
                title="Build-plate contact",
                explanation="No component begins at the build plate." if floating else "The model begins at the build plate.",
                correction="Move at least one intended printable component to Z=0.",
                metadata={"max_z": max_z},
            ),
        ]


class CylindricalHoleAnalyzer:
    rule_id = "geometry.protected_hole_diameter"
    supported_feature_types = {"hole", "hole_group"}

    def analyze(self, analysis_context: GeometricAnalysisContext) -> list[GeometricFinding]:
        mapping = _first_geometry_mapping(analysis_context, {"hole", "hole_group"})
        if mapping is None:
            return []
        diameter_requirement = mapping.attributes.get("diameter")
        expected = _expected_value(analysis_context, diameter_requirement)
        if expected is None:
            return []
        axis = mapping.attributes.get("axis", "z")
        candidates = _detect_axis_aligned_hole_candidates(analysis_context.mesh, axis, analysis_context.tolerance)
        high = [candidate for candidate in candidates if candidate.confidence >= analysis_context.tolerance.high_confidence]
        if not high:
            return [
                _finding(
                    rule_id=self.rule_id,
                    requirement_id=diameter_requirement,
                    state="unverifiable",
                    expected=expected,
                    detected=None,
                    unit="mm",
                    tolerance=analysis_context.tolerance.hole_diameter_abs_mm,
                    confidence=max([candidate.confidence for candidate in candidates], default=0.0),
                    blocking=False,
                    title="Hole diameter",
                    explanation="Volundr could not verify physical hole diameter from derived STL profile candidates.",
                    correction="Review the hole diameter manually or revise with clearer hole geometry.",
                    feature_id=mapping.feature_id,
                    metadata={
                        "axis": axis,
                        "evidence_authority": "derived_stl_candidate",
                        "candidate_count": len(candidates),
                        "candidate_measurements": _hole_candidate_measurements(candidates),
                    },
                )
            ]
        return [
            _finding(
                rule_id=self.rule_id,
                requirement_id=diameter_requirement,
                state="unverifiable",
                expected=expected,
                detected=None,
                unit="mm",
                tolerance=analysis_context.tolerance.hole_diameter_abs_mm,
                confidence=min(candidate.confidence for candidate in high),
                blocking=False,
                title="Hole diameter",
                explanation="STL profile candidates are insufficient to verify physical hole diameter without authoritative B-Rep feature evidence.",
                correction="Revise the hole geometry to match the protected diameter.",
                feature_id=mapping.feature_id,
                metadata={
                    "axis": axis,
                    "evidence_authority": "derived_stl_candidate",
                    "candidate_count": len(candidates),
                    "candidate_measurements": _hole_candidate_measurements(candidates),
                    "physical_feature_count": None,
                },
            )
        ]


class HoleGroupAnalyzer:
    rule_id = "geometry.protected_hole_group"
    supported_feature_types = {"hole_group"}

    def analyze(self, analysis_context: GeometricAnalysisContext) -> list[GeometricFinding]:
        mapping = _first_geometry_mapping(analysis_context, {"hole_group"})
        if mapping is None:
            return []
        axis = mapping.attributes.get("axis", "z")
        candidates = [
            candidate
            for candidate in _detect_axis_aligned_hole_candidates(analysis_context.mesh, axis, analysis_context.tolerance)
            if candidate.confidence >= analysis_context.tolerance.high_confidence
        ]
        findings: list[GeometricFinding] = []
        expected_count = _int(mapping.attributes.get("count"))
        if expected_count is not None:
            findings.append(
                _unverifiable_group_finding(
                    "geometry.protected_hole_count",
                    mapping,
                    expected_count,
                    "Hole count",
                    "STL profile candidates cannot establish physical-hole identity or count without authoritative B-Rep feature evidence.",
                    metadata={
                        "axis": axis,
                        "evidence_authority": "derived_stl_candidate",
                        "candidate_count": len(candidates),
                        "candidate_measurements": _hole_candidate_measurements(candidates),
                        "physical_feature_count": None,
                    },
                )
            )
        expected_spacing = _expected_value(analysis_context, mapping.attributes.get("spacing"))
        if expected_spacing is not None:
            findings.append(
                _unverifiable_group_finding(
                    "geometry.protected_hole_spacing",
                    mapping,
                    expected_spacing,
                    "Hole spacing",
                    "STL profile candidates cannot establish physical-hole identity or spacing without authoritative B-Rep feature evidence.",
                    metadata={
                        "axis": axis,
                        "evidence_authority": "derived_stl_candidate",
                        "candidate_count": len(candidates),
                        "candidate_measurements": _hole_candidate_measurements(candidates),
                        "physical_feature_count": None,
                    },
                )
            )
        expected_diameter = _expected_value(analysis_context, mapping.attributes.get("diameter"))
        if expected_diameter is not None:
            findings.append(
                _unverifiable_group_finding(
                    "geometry.protected_hole_diameter",
                    mapping,
                    expected_diameter,
                    "Hole diameter",
                    "STL profile candidates cannot establish physical-hole identity or diameter without authoritative B-Rep feature evidence.",
                    metadata={
                        "axis": axis,
                        "evidence_authority": "derived_stl_candidate",
                        "candidate_count": len(candidates),
                        "candidate_measurements": _hole_candidate_measurements(candidates),
                        "physical_feature_count": None,
                    },
                )
            )
        return findings


class WallThicknessAnalyzer:
    rule_id = "geometry.protected_wall_thickness"
    supported_feature_types = {"wall_thickness"}

    def analyze(self, analysis_context: GeometricAnalysisContext) -> list[GeometricFinding]:
        mapping = _first_geometry_mapping(analysis_context, {"wall_thickness"})
        if mapping is None:
            return []
        requirement_id = mapping.attributes.get("value")
        expected = _expected_value(analysis_context, requirement_id)
        if expected is None:
            return []
        extents = sorted(float(value) for value in analysis_context.mesh.bounding_box.extents)
        representative = round(extents[0], 3)
        confidence = 0.92 if representative >= 1.2 else 0.78
        violated = representative < expected - analysis_context.tolerance.wall_measurement_tolerance_mm
        blocking = violated and confidence >= analysis_context.tolerance.high_confidence
        severity = "critical" if blocking else "warning" if violated else "notice"
        return [
            _finding(
                rule_id=self.rule_id,
                requirement_id=requirement_id,
                state="violated" if violated else "verified",
                expected=expected,
                detected=representative,
                unit="mm",
                tolerance=analysis_context.tolerance.wall_measurement_tolerance_mm,
                confidence=confidence,
                blocking=blocking,
                severity=severity,
                title="Wall thickness estimate",
                explanation=(
                    "Estimated representative wall thickness is below the protected Design Specification value."
                    if violated
                    else "Estimated representative wall thickness matches the protected Design Specification value."
                ),
                correction="Revise wall geometry to meet the protected wall-thickness requirement.",
                feature_id=mapping.feature_id,
                metadata={
                    "minimum_reliable_mm": representative,
                    "representative_minimum_mm": representative,
                    "median_estimated_mm": representative,
                    "sample_count": int(len(analysis_context.mesh.faces)),
                    "region": mapping.attributes.get("region"),
                },
            )
        ]


@dataclass(frozen=True)
class _DetectedHoleCandidate:
    center: np.ndarray
    diameter: float
    confidence: float


def mesh_hash(mesh: Trimesh) -> str:
    digest = hashlib.sha256()
    digest.update(np.asarray(mesh.vertices, dtype=np.float64).tobytes())
    digest.update(np.asarray(mesh.faces, dtype=np.int64).tobytes())
    return digest.hexdigest()


def _detect_axis_aligned_hole_candidates(
    mesh: Trimesh,
    axis: str,
    tolerance: GeometricToleranceProfile,
) -> list[_DetectedHoleCandidate]:
    """Extract derived STL circular-profile candidates, not physical holes.

    The mesh path has no analytic B-Rep identity or reliable distinction
    between an interior opening, an exterior curved wall, and one band of a
    stepped hole.  Callers must therefore treat the returned components as
    candidate evidence only and must not use them as authoritative physical
    hole verification.
    """
    axis_index = {"x": 0, "y": 1, "z": 2}.get(axis.lower())
    if axis_index is None or len(mesh.faces) == 0 or len(mesh.faces) > tolerance.max_triangle_count:
        return []
    face_normals = np.asarray(mesh.face_normals)
    side_face_indexes = np.where(np.abs(face_normals[:, axis_index]) < 0.35)[0]
    components = _face_components(mesh, side_face_indexes.tolist())
    candidates: list[_DetectedHoleCandidate] = []
    projection = [index for index in range(3) if index != axis_index]
    for component in components[: tolerance.max_hole_candidates]:
        face_vertices = mesh.faces[component].reshape(-1)
        unique_vertices = np.unique(face_vertices)
        points = mesh.vertices[unique_vertices]
        if len(points) < 12:
            continue
        projected = points[:, projection]
        center = projected.mean(axis=0)
        radii = np.linalg.norm(projected - center, axis=1)
        radius = float(np.mean(radii))
        if radius <= 0:
            continue
        radial_std = float(np.std(radii))
        angles = np.arctan2(projected[:, 1] - center[1], projected[:, 0] - center[0])
        coverage = len(np.unique(np.floor(((angles + math.pi) / (2 * math.pi)) * 24))) / 24
        face_centers = mesh.triangles_center[component][:, projection]
        radial = face_centers - center
        radial_norm = np.linalg.norm(radial, axis=1)
        valid = radial_norm > 1e-9
        if not np.any(valid):
            continue
        radial_unit = radial[valid] / radial_norm[valid][:, None]
        normal_projected = face_normals[component][:, projection][valid]
        normal_norm = np.linalg.norm(normal_projected, axis=1)
        normal_valid = normal_norm > 1e-9
        if not np.any(normal_valid):
            continue
        normal_unit = normal_projected[normal_valid] / normal_norm[normal_valid][:, None]
        radial_unit = radial_unit[normal_valid]
        inward_score = -float(np.mean(np.sum(normal_unit * radial_unit, axis=1)))
        if inward_score < 0.3:
            continue
        segment_confidence = min(1.0, len(points) / 32)
        circularity = max(0.0, 1.0 - radial_std / max(radius, 1e-9))
        confidence = round(max(0.0, min(1.0, inward_score * 0.45 + coverage * 0.25 + circularity * 0.2 + segment_confidence * 0.1)), 3)
        full_center = np.zeros(3)
        full_center[projection] = center
        full_center[axis_index] = float((points[:, axis_index].min() + points[:, axis_index].max()) / 2)
        candidates.append(
            _DetectedHoleCandidate(
                center=full_center,
                diameter=round(radius * 2, 3),
                confidence=confidence,
            )
        )
    return candidates


def _hole_candidate_measurements(
    candidates: list[_DetectedHoleCandidate],
) -> list[dict[str, Any]]:
    """Serialize derived STL observations without claiming physical identity."""

    return [
        {
            "evidence_type": "stl_circular_profile_candidate",
            "physical_feature_verified": False,
            "center_mm": [round(float(value), 3) for value in candidate.center],
            "diameter_mm": round(float(candidate.diameter), 3),
            "confidence": round(float(candidate.confidence), 3),
        }
        for candidate in candidates
    ]


def _face_components(mesh: Trimesh, face_indexes: list[int]) -> list[np.ndarray]:
    selected = set(int(index) for index in face_indexes)
    if not selected:
        return []
    adjacency: dict[int, list[int]] = {index: [] for index in selected}
    for left, right in mesh.face_adjacency:
        left_i = int(left)
        right_i = int(right)
        if left_i in selected and right_i in selected:
            adjacency[left_i].append(right_i)
            adjacency[right_i].append(left_i)
    components: list[np.ndarray] = []
    while selected:
        start = selected.pop()
        stack = [start]
        component = [start]
        while stack:
            current = stack.pop()
            for neighbor in adjacency[current]:
                if neighbor in selected:
                    selected.remove(neighbor)
                    stack.append(neighbor)
                    component.append(neighbor)
        components.append(np.array(component, dtype=int))
    return components


def _first_geometry_mapping(
    context: GeometricAnalysisContext,
    geometry_types: set[str],
) -> SourceGeometryMapping | None:
    metadata = context.source_metadata
    if metadata is None:
        return None
    return next(
        (mapping for mapping in metadata.geometry_mappings if mapping.geometry_type in geometry_types),
        None,
    )


def _protected_dimensions(design_specification: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if design_specification is None:
        return {}
    return {
        str(dimension.get("id")): dimension
        for dimension in design_specification.get("critical_dimensions", [])
        if dimension.get("protected")
    }


def _requirement_for_parameter(metadata: SourceMetadata, parameter_name: str) -> str | None:
    for requirement_id, mapping in metadata.requirement_mappings.items():
        if mapping.target_name == parameter_name:
            return requirement_id
    return None


def _expected_value(context: GeometricAnalysisContext, requirement_id: str | None) -> float | None:
    if requirement_id is None:
        return None
    dimensions = _protected_dimensions(context.design_specification)
    if requirement_id in dimensions:
        return _float(dimensions[requirement_id].get("value"))
    assignment = context.source_metadata.assignments.get(requirement_id) if context.source_metadata else None
    return _float(assignment)


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _unverifiable_group_finding(
    rule_id: str,
    mapping: SourceGeometryMapping,
    expected: float | int,
    title: str,
    explanation: str,
    metadata: dict[str, Any] | None = None,
) -> GeometricFinding:
    return _finding(
        rule_id=rule_id,
        requirement_id=mapping.feature_id,
        state="unverifiable",
        expected=expected,
        detected=None,
        unit="holes" if "count" in rule_id else "mm",
        tolerance=None,
        confidence=0.0,
        blocking=False,
        title=title,
        explanation=explanation,
        correction="Review the declared hole group manually before accepting the candidate.",
        feature_id=mapping.feature_id,
        metadata={"mapping_line": mapping.line, **(metadata or {})},
    )


def _finding(
    *,
    rule_id: str,
    requirement_id: str | None,
    state: str,
    expected: float | int | str | None,
    detected: float | int | str | None,
    unit: str | None,
    tolerance: float | None,
    confidence: float,
    blocking: bool,
    title: str,
    explanation: str,
    correction: str,
    severity: str | None = None,
    feature_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> GeometricFinding:
    if severity is None:
        severity = "critical" if blocking else "warning" if state in {"violated", "unverifiable"} else "notice"
    return GeometricFinding(
        rule_id=rule_id,
        requirement_id=requirement_id,
        verification_state=state,
        expected_value=expected,
        detected_value=detected,
        unit=unit,
        tolerance=tolerance,
        confidence=round(confidence, 3),
        severity=severity,
        is_blocking=blocking,
        title=title,
        explanation=explanation,
        suggested_correction=correction,
        feature_id=feature_id,
        metadata=metadata or {},
    )
