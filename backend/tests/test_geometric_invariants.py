import numpy as np
import trimesh

from app.services.cad.source_metadata import SourceGeometryMapping, SourceMetadata
from app.services.geometry.invariants import (
    GEOMETRIC_ANALYZER_VERSION,
    GEOMETRIC_TOLERANCE_PROFILE_VERSION,
    BoundingBoxAnalyzer,
    BuildPlateAnalyzer,
    CylindricalHoleAnalyzer,
    GeometricAnalysisContext,
    GeometryAnalyzerRegistry,
    HoleGroupAnalyzer,
    WallThicknessAnalyzer,
)


DESIGN_SPEC = {
    "schema_version": "1.0",
    "critical_dimensions": [
        {
            "id": "part_width",
            "label": "Overall width",
            "value": 80,
            "unit": "mm",
            "source": "user",
            "importance": "critical",
            "protected": True,
        },
        {
            "id": "part_depth",
            "label": "Overall depth",
            "value": 35,
            "unit": "mm",
            "source": "user",
            "importance": "critical",
            "protected": True,
        },
        {
            "id": "part_height",
            "label": "Overall height",
            "value": 6,
            "unit": "mm",
            "source": "user",
            "importance": "critical",
            "protected": True,
        },
        {
            "id": "mount_hole_diameter",
            "label": "Mounting hole diameter",
            "value": 5,
            "unit": "mm",
            "source": "user",
            "importance": "critical",
            "protected": True,
        },
        {
            "id": "mount_hole_spacing",
            "label": "Mounting hole spacing",
            "value": 50,
            "unit": "mm",
            "source": "user",
            "importance": "critical",
            "protected": True,
        },
        {
            "id": "wall_thickness",
            "label": "Wall thickness",
            "value": 3,
            "unit": "mm",
            "source": "user",
            "importance": "critical",
            "protected": True,
        },
    ],
    "functional_requirements": [
        {
            "id": "mounting_holes",
            "description": "Two mounting holes",
            "source": "user",
            "importance": "critical",
            "protected": True,
        }
    ],
}


def fixture_source_metadata() -> SourceMetadata:
    return SourceMetadata(
        source_hash="source-hash",
        source_size_bytes=0,
        line_count=1,
        geometry_mappings=[
            SourceGeometryMapping(
                geometry_type="bounds",
                attributes={"x": "part_width", "y": "part_depth", "z": "part_height"},
                line=1,
            ),
            SourceGeometryMapping(
                geometry_type="hole_group",
                attributes={
                    "count": "2",
                    "diameter": "mount_hole_diameter",
                    "spacing": "mount_hole_spacing",
                    "axis": "z",
                },
                line=1,
                feature_id="mounting_holes",
            ),
            SourceGeometryMapping(
                geometry_type="wall_thickness",
                attributes={"value": "wall_thickness", "region": "main_body"},
                line=1,
            ),
        ],
        assignments={
            "part_width": "80",
            "part_depth": "35",
            "part_height": "6",
            "mount_hole_diameter": "5",
            "mount_hole_spacing": "50",
            "wall_thickness": "3",
        },
    )


def context(mesh: trimesh.Trimesh) -> GeometricAnalysisContext:
    metadata = fixture_source_metadata()
    return GeometricAnalysisContext(
        mesh=mesh,
        design_specification=DESIGN_SPEC,
        source_metadata=metadata,
        source_hash=metadata.source_hash,
        mesh_hash="mesh-hash",
    )


def test_fixture_metadata_contains_geometry_mappings() -> None:
    metadata = fixture_source_metadata()

    assert metadata.geometry_mappings[0].geometry_type == "bounds"
    assert metadata.geometry_mappings[0].attributes["x"] == "part_width"
    hole_group = next(mapping for mapping in metadata.geometry_mappings if mapping.geometry_type == "hole_group")
    assert hole_group.feature_id == "mounting_holes"
    assert hole_group.attributes["diameter"] == "mount_hole_diameter"


def test_bounding_box_exact_dimensions_verify() -> None:
    result = BoundingBoxAnalyzer().analyze(context(box_mesh((80, 35, 6), z_min=0)))

    states = {finding.requirement_id: finding.verification_state for finding in result}
    assert states["part_width"] == "verified"
    assert states["part_depth"] == "verified"
    assert states["part_height"] == "verified"
    assert all(not finding.is_blocking for finding in result)


def test_bounding_box_protected_violation_blocks() -> None:
    result = BoundingBoxAnalyzer().analyze(context(box_mesh((90, 35, 6), z_min=0)))

    width = next(finding for finding in result if finding.requirement_id == "part_width")
    assert width.verification_state == "violated"
    assert width.is_blocking is True
    assert width.detected_value == 90
    assert width.tolerance == 0.2


def test_bounding_box_tolerance_uses_larger_absolute_or_relative() -> None:
    result = BoundingBoxAnalyzer().analyze(context(box_mesh((80.19, 35, 6), z_min=0)))

    width = next(finding for finding in result if finding.requirement_id == "part_width")
    assert width.verification_state == "verified"


def test_build_plate_below_violation_blocks_and_above_is_unprintable() -> None:
    below = BuildPlateAnalyzer().analyze(context(box_mesh((10, 10, 10), z_min=-0.2)))
    above = BuildPlateAnalyzer().analyze(context(box_mesh((10, 10, 10), z_min=0.5)))

    assert next(f for f in below if f.rule_id == "geometry.build_plate_min_z").is_blocking is True
    assert next(f for f in above if f.rule_id == "geometry.build_plate_contact").is_blocking is True


def test_hole_group_count_spacing_and_diameter_verify() -> None:
    mesh = two_hole_wall_mesh(spacing=50, diameter=5, height=6, segments=48)

    result = GeometryAnalyzerRegistry.default().analyze(context(mesh))

    assert state(result, "geometry.protected_hole_count") == "verified"
    assert state(result, "geometry.protected_hole_spacing") == "verified"
    assert state(result, "geometry.protected_hole_diameter") == "verified"


def test_high_confidence_hole_spacing_violation_blocks() -> None:
    mesh = two_hole_wall_mesh(spacing=60, diameter=5, height=6, segments=48)

    result = HoleGroupAnalyzer().analyze(context(mesh))

    spacing = next(finding for finding in result if finding.rule_id == "geometry.protected_hole_spacing")
    assert spacing.verification_state == "violated"
    assert spacing.is_blocking is True
    assert spacing.detected_value == 60


def test_low_confidence_hole_diameter_mismatch_is_unverifiable_not_blocking() -> None:
    mesh = two_hole_wall_mesh(spacing=50, diameter=7, height=6, segments=6)

    result = CylindricalHoleAnalyzer().analyze(context(mesh))

    diameter = next(finding for finding in result if finding.rule_id == "geometry.protected_hole_diameter")
    assert diameter.verification_state == "unverifiable"
    assert diameter.is_blocking is False


def test_external_cylinders_are_not_classified_as_holes() -> None:
    mesh = trimesh.util.concatenate(
        [
            trimesh.creation.cylinder(radius=2.5, height=6, sections=48),
            translated(trimesh.creation.cylinder(radius=2.5, height=6, sections=48), [50, 0, 0]),
        ]
    )

    result = HoleGroupAnalyzer().analyze(context(mesh))

    count = next(finding for finding in result if finding.rule_id == "geometry.protected_hole_count")
    assert count.verification_state == "unverifiable"
    assert count.is_blocking is False


def test_wall_thickness_percentile_warns_for_thin_wall() -> None:
    result = WallThicknessAnalyzer().analyze(context(box_mesh((80, 35, 0.6), z_min=0)))

    finding = next(finding for finding in result if finding.rule_id == "geometry.protected_wall_thickness")
    assert finding.verification_state == "violated"
    assert finding.severity == "warning"
    assert finding.is_blocking is False
    assert finding.metadata["representative_minimum_mm"] == 0.6


def test_wall_thickness_high_confidence_material_violation_blocks() -> None:
    result = WallThicknessAnalyzer().analyze(context(box_mesh((80, 35, 1.5), z_min=0)))

    finding = next(finding for finding in result if finding.rule_id == "geometry.protected_wall_thickness")
    assert finding.verification_state == "violated"
    assert finding.is_blocking is True


def test_analyzer_registry_preserves_versions_and_continues_on_failure() -> None:
    class FailingAnalyzer:
        rule_id = "geometry.failing"
        supported_feature_types = set()

        def analyze(self, analysis_context):
            raise RuntimeError("boom")

    result = GeometryAnalyzerRegistry([FailingAnalyzer()]).analyze(context(box_mesh((80, 35, 6), z_min=0)))

    assert result.analysis_version == GEOMETRIC_ANALYZER_VERSION
    assert result.tolerance_profile_version == GEOMETRIC_TOLERANCE_PROFILE_VERSION
    assert result.findings[0].verification_state == "unverifiable"
    assert result.findings[0].is_blocking is False


def state(findings, rule_id: str) -> str:
    return next(finding for finding in findings.findings if finding.rule_id == rule_id).verification_state


def box_mesh(extents: tuple[float, float, float], *, z_min: float) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation([0, 0, z_min + extents[2] / 2])
    return mesh


def translated(mesh: trimesh.Trimesh, offset: list[float]) -> trimesh.Trimesh:
    copy = mesh.copy()
    copy.apply_translation(offset)
    return copy


def two_hole_wall_mesh(
    *,
    spacing: float,
    diameter: float,
    height: float,
    segments: int,
) -> trimesh.Trimesh:
    radius = diameter / 2
    meshes = [
        inward_cylinder_wall(center=(-spacing / 2, 0), radius=radius, height=height, segments=segments),
        inward_cylinder_wall(center=(spacing / 2, 0), radius=radius, height=height, segments=segments),
    ]
    return trimesh.util.concatenate(meshes)


def inward_cylinder_wall(
    *,
    center: tuple[float, float],
    radius: float,
    height: float,
    segments: int,
) -> trimesh.Trimesh:
    vertices: list[list[float]] = []
    faces: list[list[int]] = []
    for index in range(segments):
        angle = 2 * np.pi * index / segments
        x = center[0] + radius * np.cos(angle)
        y = center[1] + radius * np.sin(angle)
        vertices.append([x, y, 0])
        vertices.append([x, y, height])
    for index in range(segments):
        next_index = (index + 1) % segments
        a = 2 * index
        b = 2 * next_index
        faces.append([a, b + 1, b])
        faces.append([a, a + 1, b + 1])
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
