from pathlib import Path

import numpy as np
import trimesh
from trimesh import Trimesh

from app.schemas.printability import (
    PRINTABILITY_PROFILE_VERSION,
    PrintabilityDetectedValue,
    PrintabilityHighlight,
    PrintabilityProfile,
    PrintabilityReport,
    PrintabilityResult,
    PrintabilitySeverity,
)
from app.services.mesh.inspect import _as_mesh, _connected_component_count
from app.services.printability.config import PRINTABILITY_CONFIG, PrintabilityConfig

EPSILON = 1e-6


def inspect_printability(
    path: Path,
    profile: PrintabilityProfile,
    *,
    config: PrintabilityConfig = PRINTABILITY_CONFIG,
) -> PrintabilityReport:
    loaded = trimesh.load(path, force="mesh")
    mesh = _as_mesh(loaded)
    results: list[PrintabilityResult] = []

    if len(mesh.faces) == 0:
        results.append(
            _result(
                "Critical",
                "mesh.empty_or_zero_volume",
                0,
                "faces",
                "The STL contains no printable triangle faces.",
                "Regenerate or repair the model so it exports a closed 3D mesh.",
                orientation_dependent=False,
            )
        )
        return PrintabilityReport(profile_version=PRINTABILITY_PROFILE_VERSION, profile=profile, results=results)

    bounds = mesh.bounds
    extents = mesh.bounding_box.extents.astype(float)
    min_z = float(bounds[0][2])
    volume = float(abs(mesh.volume)) if np.isfinite(mesh.volume) else 0.0

    results.append(_empty_or_zero_volume_result(mesh, volume))
    results.append(_watertight_result(mesh))
    results.append(_components_result(mesh))
    results.append(_above_build_plate_result(min_z, bounds, config))
    results.append(_below_build_plate_result(min_z, bounds, config))
    results.append(_contact_result(mesh, bounds, config))
    results.append(_minimum_thickness_result(mesh, profile, config))
    results.append(_small_features_result(mesh, profile, config))
    results.append(_overhang_result(mesh, config))
    results.append(_bridge_result(mesh, config))
    results.append(_ceilings_and_cavities_result(mesh, config))
    results.append(_build_volume_result(extents, profile, bounds))

    highlights = [result.highlight for result in results if result.highlight is not None]
    return PrintabilityReport(
        profile_version=config.version,
        profile=profile,
        results=results,
        highlights=highlights,
    )


def _empty_or_zero_volume_result(mesh: Trimesh, volume: float) -> PrintabilityResult:
    if volume <= EPSILON:
        return _result(
            "Critical",
            "mesh.empty_or_zero_volume",
            round(volume, 6),
            "mm3",
            "The mesh has zero or near-zero enclosed volume, so it is not a printable solid.",
            "Repair the source so the exported STL forms a closed solid with positive volume.",
            orientation_dependent=False,
            affected_count=len(mesh.faces),
            highlight=_whole_mesh_highlight("mesh.empty_or_zero_volume", "Critical", mesh),
        )
    return _result(
        "Pass",
        "mesh.empty_or_zero_volume",
        round(volume, 3),
        "mm3",
        "The mesh has positive enclosed volume.",
        "No correction is needed for this check.",
        orientation_dependent=False,
        affected_count=len(mesh.faces),
    )


def _watertight_result(mesh: Trimesh) -> PrintabilityResult:
    if not mesh.is_watertight:
        return _result(
            "Warning",
            "mesh.non_watertight",
            "not watertight",
            "state",
            "Open edges or holes can cause slicing failures or missing toolpaths.",
            "Close holes, remove self-intersections, or regenerate the model as a watertight solid.",
            orientation_dependent=False,
            affected_count=len(mesh.faces),
            highlight=_whole_mesh_highlight("mesh.non_watertight", "Warning", mesh),
        )
    return _result(
        "Pass",
        "mesh.non_watertight",
        "watertight",
        "state",
        "The mesh appears watertight.",
        "No correction is needed for this check.",
        orientation_dependent=False,
        affected_count=0,
    )


def _components_result(mesh: Trimesh) -> PrintabilityResult:
    component_count = _connected_component_count(mesh)
    if component_count > 1:
        return _result(
            "Warning",
            "mesh.disconnected_components",
            component_count,
            "components",
            "The STL contains disconnected components that may print as separate loose bodies.",
            "Join the components intentionally, split them into separate parts, or confirm this separation is desired.",
            orientation_dependent=False,
            affected_count=component_count,
            highlight=_whole_mesh_highlight("mesh.disconnected_components", "Warning", mesh),
        )
    return _result(
        "Pass",
        "mesh.disconnected_components",
        component_count,
        "components",
        "The mesh is a single connected component.",
        "No correction is needed for this check.",
        orientation_dependent=False,
        affected_count=component_count,
    )


def _above_build_plate_result(
    min_z: float,
    bounds: np.ndarray,
    config: PrintabilityConfig,
) -> PrintabilityResult:
    if min_z > config.build_plate_tolerance_mm:
        return _result(
            "Warning",
            "orientation.above_build_plate",
            round(min_z, 3),
            "mm",
            "The lowest geometry starts above the build plate, so the part is suspended in the current orientation.",
            "Move the model down until the intended first layer touches Z=0, or choose a different orientation.",
            orientation_dependent=True,
            highlight=_bounds_highlight("orientation.above_build_plate", "Warning", bounds),
        )
    return _result(
        "Pass",
        "orientation.above_build_plate",
        round(max(min_z, 0.0), 3),
        "mm",
        "The lowest geometry is not floating above the build plate.",
        "No correction is needed for this check.",
        orientation_dependent=True,
    )


def _below_build_plate_result(
    min_z: float,
    bounds: np.ndarray,
    config: PrintabilityConfig,
) -> PrintabilityResult:
    if min_z < -config.build_plate_tolerance_mm:
        return _result(
            "Critical",
            "orientation.below_build_plate",
            round(min_z, 3),
            "mm",
            "Some geometry is below Z=0 and would be clipped or positioned outside the printable build area.",
            "Move the model up until all geometry is at or above the build plate.",
            orientation_dependent=True,
            highlight=_bounds_highlight("orientation.below_build_plate", "Critical", bounds),
        )
    return _result(
        "Pass",
        "orientation.below_build_plate",
        round(min_z, 3),
        "mm",
        "No geometry is below the build plate.",
        "No correction is needed for this check.",
        orientation_dependent=True,
    )


def _contact_result(mesh: Trimesh, bounds: np.ndarray, config: PrintabilityConfig) -> PrintabilityResult:
    contact_area = _faces_near_z_area(mesh, 0.0, config.build_plate_tolerance_mm)
    footprint_area = max(float((bounds[1][0] - bounds[0][0]) * (bounds[1][1] - bounds[0][1])), EPSILON)
    ratio = contact_area / footprint_area
    severity: PrintabilitySeverity = "Pass"
    explanation = "The model has a meaningful flat contact estimate at the build plate."
    correction = "No correction is needed for this check."
    if contact_area <= EPSILON or ratio < config.contact_area_ratio_warning_below:
        severity = "Warning"
        explanation = "The estimated build-plate contact is small, increasing first-layer adhesion risk."
        correction = "Rotate the part to a broader flat face, add a brim, or redesign the base for more contact."
    elif ratio < config.contact_area_ratio_notice_below:
        severity = "Notice"
        explanation = "The estimated build-plate contact is limited and may need extra adhesion help."
        correction = "Consider a broader contact face, brim, or a more stable orientation."
    return _result(
        severity,
        "orientation.small_build_plate_contact",
        round(contact_area, 3),
        "mm2",
        explanation,
        correction,
        orientation_dependent=True,
        affected_area_mm2=round(contact_area, 3),
        highlight=_bounds_highlight("orientation.small_build_plate_contact", severity, bounds)
        if severity != "Pass"
        else None,
    )


def _minimum_thickness_result(
    mesh: Trimesh,
    profile: PrintabilityProfile,
    config: PrintabilityConfig,
) -> PrintabilityResult:
    estimate = _minimum_component_extent(mesh)
    severity = _thickness_severity(estimate, profile, config)
    thresholds = config.thickness_for(profile)
    if severity == "Pass":
        explanation = "The smallest local feature estimate is at or above the general pass threshold."
        correction = f"Keep ordinary functional walls near {thresholds.functional_recommendation_mm:.2f} mm or thicker when strength matters."
    else:
        explanation = "A conservative local feature estimate is below the recommended wall thickness range for this nozzle."
        correction = "Thicken narrow walls, pins, tabs, and other local features, or inspect the part in a slicer before printing."
    return _result(
        severity,
        "feature.minimum_thickness",
        round(estimate, 3),
        "mm",
        explanation,
        correction,
        orientation_dependent=False,
        highlight=_whole_mesh_highlight("feature.minimum_thickness", severity, mesh)
        if severity != "Pass"
        else None,
    )


def _small_features_result(
    mesh: Trimesh,
    profile: PrintabilityProfile,
    config: PrintabilityConfig,
) -> PrintabilityResult:
    estimate = _minimum_component_extent(mesh)
    severity = _thickness_severity(estimate, profile, config)
    if severity == "Pass":
        explanation = "No small positive features, gaps, or holes were detected by the current conservative size estimate."
        correction = "No correction is needed for this check, but slicer preview remains the authority for fine holes and gaps."
    else:
        explanation = "The current conservative size estimate found features that may be too small for the nozzle to reproduce reliably."
        correction = "Increase small features, widen gaps and holes, or use a smaller nozzle if those details are required."
    return _result(
        severity,
        "feature.small_features_gaps_holes",
        round(estimate, 3),
        "mm",
        explanation,
        correction,
        orientation_dependent=False,
        highlight=_whole_mesh_highlight("feature.small_features_gaps_holes", severity, mesh)
        if severity != "Pass"
        else None,
    )


def _overhang_result(mesh: Trimesh, config: PrintabilityConfig) -> PrintabilityResult:
    face_indices, angles, areas = _downward_face_angles(mesh)
    if face_indices.size:
        centroids = mesh.triangles_center[face_indices]
        elevated_mask = centroids[:, 2] > config.build_plate_tolerance_mm
    else:
        elevated_mask = np.array([], dtype=bool)
    risk_mask = elevated_mask & (angles < config.overhang.notice_below_degrees)
    affected_area = float(areas[risk_mask].sum()) if areas.size else 0.0
    severity = _overhang_severity(float(angles[risk_mask].min()), config) if np.any(risk_mask) else "Pass"
    if affected_area < config.overhang_min_area_mm2:
        severity = "Pass"
    if severity == "Pass":
        explanation = "No meaningful downward-facing overhang area exceeded the configured support-risk thresholds."
        correction = "No correction is needed for this check."
    else:
        explanation = "Downward-facing surfaces in this orientation are shallow enough to need support or a different orientation."
        correction = "Rotate the part, add chamfers, split the model, or plan slicer supports for the highlighted overhang regions."
    return _result(
        severity,
        "orientation.overhangs",
        round(float(angles[risk_mask].min()), 3) if np.any(risk_mask) else 90.0,
        "degrees",
        explanation,
        correction,
        orientation_dependent=True,
        affected_count=int(risk_mask.sum()) if angles.size else 0,
        affected_area_mm2=round(affected_area, 3),
        highlight=PrintabilityHighlight(
            rule_id="orientation.overhangs",
            severity=severity,
            type="faces",
            bounds_min_mm=_tuple(mesh.bounds[0]),
            bounds_max_mm=_tuple(mesh.bounds[1]),
            face_indices=[int(face_indices[index]) for index in np.where(risk_mask)[0][:500]],
        )
        if severity != "Pass"
        else None,
    )


def _bridge_result(mesh: Trimesh, config: PrintabilityConfig) -> PrintabilityResult:
    span, area, face_count = _largest_bridge_span(mesh, config)
    severity = _bridge_severity(span, config)
    if severity == "Pass":
        explanation = "No simple horizontal bridge span exceeded the configured limits."
        correction = "No correction is needed for this check."
    elif span > config.bridge.warning_max_mm and span <= config.bridge.strong_warning_max_mm:
        explanation = "A simple horizontal bridge span is in the strong-warning range for unsupported FDM printing."
        correction = "Reduce the unsupported span, add supports, add an arch/chamfer, or reorient the model."
    else:
        explanation = "A simple horizontal bridge span is longer than the configured reliable unsupported distance."
        correction = "Reduce the unsupported span, add supports, add an arch/chamfer, or reorient the model."
    return _result(
        severity,
        "orientation.bridge_spans",
        round(span, 3),
        "mm",
        explanation,
        correction,
        orientation_dependent=True,
        affected_count=face_count,
        affected_area_mm2=round(area, 3),
        highlight=_whole_mesh_highlight("orientation.bridge_spans", severity, mesh)
        if severity != "Pass"
        else None,
    )


def _ceilings_and_cavities_result(mesh: Trimesh, config: PrintabilityConfig) -> PrintabilityResult:
    _span, area, face_count = _largest_bridge_span(mesh, config)
    if face_count == 0:
        return _result(
            "Pass",
            "orientation.unsupported_ceilings_cavities",
            0,
            "detected faces",
            "No simple unsupported horizontal ceiling was reliably detected. Inaccessible cavities are not inferred unless detection is reliable.",
            "No correction is needed for this check, but inspect complex internal cavities in a slicer.",
            orientation_dependent=True,
            affected_count=0,
            affected_area_mm2=0.0,
        )
    return _result(
        "Warning",
        "orientation.unsupported_ceilings_cavities",
        face_count,
        "detected faces",
        "A simple unsupported horizontal ceiling was reliably detected in the current orientation.",
        "Add support access, reduce the ceiling span, split the part, or reorient the model.",
        orientation_dependent=True,
        affected_count=face_count,
        affected_area_mm2=round(area, 3),
        highlight=_whole_mesh_highlight("orientation.unsupported_ceilings_cavities", "Warning", mesh),
    )


def _build_volume_result(
    extents: np.ndarray,
    profile: PrintabilityProfile,
    bounds: np.ndarray,
) -> PrintabilityResult:
    build_volume = profile.build_volume
    overages = [
        max(0.0, float(extents[0]) - build_volume.x_mm),
        max(0.0, float(extents[1]) - build_volume.y_mm),
        max(0.0, float(extents[2]) - build_volume.z_mm),
    ]
    max_overage = max(overages)
    if max_overage > EPSILON:
        return _result(
            "Warning",
            "profile.build_volume",
            round(max_overage, 3),
            "mm",
            "The model is larger than the configured printer build volume on at least one axis. The CAD remains available for review, but this printer cannot print it as one piece without a different strategy.",
            "Scale the model down, split it into printable sections, reorient it, or select a printer profile with a larger build volume.",
            orientation_dependent=True,
            affected_count=sum(1 for overage in overages if overage > EPSILON),
            highlight=_bounds_highlight("profile.build_volume", "Warning", bounds),
        )
    return _result(
        "Pass",
        "profile.build_volume",
        round(float(max(extents)), 3),
        "mm",
        "The model extents fit within the configured build volume.",
        "No correction is needed for this check.",
        orientation_dependent=True,
        affected_count=0,
    )


def _result(
    severity: PrintabilitySeverity,
    rule_id: str,
    value: float | int | str,
    units: str,
    explanation: str,
    suggested_correction: str,
    *,
    orientation_dependent: bool,
    dismissed: bool = False,
    affected_count: int | None = None,
    affected_area_mm2: float | None = None,
    highlight: PrintabilityHighlight | None = None,
) -> PrintabilityResult:
    return PrintabilityResult(
        severity=severity,
        rule_id=rule_id,
        detected_value=PrintabilityDetectedValue(value=value, units=units),
        explanation=explanation,
        suggested_correction=suggested_correction,
        orientation_dependent=orientation_dependent,
        dismissed=dismissed,
        affected_count=affected_count,
        affected_area_mm2=affected_area_mm2,
        highlight=highlight,
    )


def _minimum_component_extent(mesh: Trimesh) -> float:
    extents: list[float] = []
    for face_indices in _face_component_groups(mesh):
        vertex_indices = np.unique(mesh.faces[face_indices].reshape(-1))
        vertices = mesh.vertices[vertex_indices]
        component_extents = [
            float(value)
            for value in vertices.max(axis=0) - vertices.min(axis=0)
            if np.isfinite(value) and value > EPSILON
        ]
        if component_extents:
            extents.append(min(component_extents))
    if not extents:
        mesh_extents = [float(value) for value in mesh.bounding_box.extents if np.isfinite(value) and value > EPSILON]
        return min(mesh_extents) if mesh_extents else 0.0
    return min(extents)


def _face_component_groups(mesh: Trimesh) -> list[list[int]]:
    face_count = len(mesh.faces)
    if face_count == 0:
        return []

    parents = list(range(face_count))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for left, right in mesh.face_adjacency:
        union(int(left), int(right))

    groups: dict[int, list[int]] = {}
    for index in range(face_count):
        groups.setdefault(find(index), []).append(index)
    return list(groups.values())


def _thickness_severity(
    thickness_mm: float,
    profile: PrintabilityProfile,
    config: PrintabilityConfig,
) -> PrintabilitySeverity:
    thresholds = config.thickness_for(profile)
    if thickness_mm < thresholds.critical_below_mm:
        return "Critical"
    if thickness_mm < thresholds.warning_below_mm:
        return "Warning"
    if thickness_mm < thresholds.notice_below_mm:
        return "Notice"
    return "Pass"


def _downward_face_angles(mesh: Trimesh) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    normals = mesh.face_normals
    downward_mask = normals[:, 2] < -EPSILON if normals.size else np.array([], dtype=bool)
    face_indices = np.where(downward_mask)[0]
    if face_indices.size == 0:
        return face_indices, np.array([], dtype=float), np.array([], dtype=float)
    downward_normals = normals[downward_mask]
    angles = np.degrees(np.arccos(np.clip(np.abs(downward_normals[:, 2]), 0.0, 1.0)))
    return face_indices, angles, mesh.area_faces[downward_mask]


def _overhang_severity(angle_degrees: float, config: PrintabilityConfig) -> PrintabilitySeverity:
    if angle_degrees < config.overhang.critical_below_degrees:
        return "Critical"
    if angle_degrees < config.overhang.warning_below_degrees:
        return "Warning"
    if angle_degrees < config.overhang.notice_below_degrees:
        return "Notice"
    return "Pass"


def _largest_bridge_span(
    mesh: Trimesh,
    config: PrintabilityConfig,
) -> tuple[float, float, int]:
    face_indices, angles, areas = _downward_face_angles(mesh)
    if face_indices.size == 0:
        return 0.0, 0.0, 0
    centroids = mesh.triangles_center[face_indices]
    elevated_mask = centroids[:, 2] > config.build_plate_tolerance_mm
    horizontal_mask = angles <= config.horizontal_face_angle_degrees
    candidate_indices = face_indices[elevated_mask & horizontal_mask]
    if candidate_indices.size == 0:
        return 0.0, 0.0, 0
    vertices = mesh.vertices[mesh.faces[candidate_indices].reshape(-1)]
    span_x = float(vertices[:, 0].max() - vertices[:, 0].min())
    span_y = float(vertices[:, 1].max() - vertices[:, 1].min())
    return max(span_x, span_y), float(areas[elevated_mask & horizontal_mask].sum()), int(candidate_indices.size)


def _bridge_severity(span_mm: float, config: PrintabilityConfig) -> PrintabilitySeverity:
    if span_mm <= config.bridge.pass_max_mm:
        return "Pass"
    if span_mm <= config.bridge.notice_max_mm:
        return "Notice"
    if span_mm <= config.bridge.strong_warning_max_mm:
        return "Warning"
    return "Critical"


def _faces_near_z_area(mesh: Trimesh, z: float, tolerance: float) -> float:
    vertices = mesh.vertices[mesh.faces]
    face_on_plane = np.all(np.abs(vertices[:, :, 2] - z) <= tolerance, axis=1)
    if not np.any(face_on_plane):
        return 0.0
    return float(mesh.area_faces[face_on_plane].sum())


def _whole_mesh_highlight(
    rule_id: str,
    severity: PrintabilitySeverity,
    mesh: Trimesh,
) -> PrintabilityHighlight:
    return PrintabilityHighlight(
        rule_id=rule_id,
        severity=severity,
        type="whole_mesh",
        bounds_min_mm=_tuple(mesh.bounds[0]),
        bounds_max_mm=_tuple(mesh.bounds[1]),
    )


def _bounds_highlight(
    rule_id: str,
    severity: PrintabilitySeverity,
    bounds: np.ndarray,
) -> PrintabilityHighlight:
    return PrintabilityHighlight(
        rule_id=rule_id,
        severity=severity,
        type="bounds",
        bounds_min_mm=_tuple(bounds[0]),
        bounds_max_mm=_tuple(bounds[1]),
    )


def _tuple(values: np.ndarray) -> tuple[float, float, float]:
    return (float(values[0]), float(values[1]), float(values[2]))
