from pathlib import Path

import trimesh

from app.schemas.printability import BuildVolumeProfile, PrintabilityProfile
from app.services.printability.inspector import inspect_printability


def test_printability_report_includes_required_result_fields(tmp_path: Path) -> None:
    stl_path = _write_mesh(tmp_path, _box((20.0, 20.0, 10.0), z_min=0.0))

    report = inspect_printability(stl_path, PrintabilityProfile())

    assert report.profile.profile_version == "printability-fdm-v1"
    assert _result(report.results, "orientation.overhangs").severity == "Pass"
    assert report.results
    for result in report.results:
        assert result.severity in {"Pass", "Notice", "Warning", "Critical"}
        assert result.rule_id
        assert result.detected_value.units
        assert result.explanation
        assert result.suggested_correction
        assert isinstance(result.orientation_dependent, bool)
        assert result.dismissed is False


def test_printability_detects_geometry_below_and_above_build_plate(tmp_path: Path) -> None:
    below_path = _write_mesh(tmp_path, _box((10.0, 10.0, 10.0), z_min=-5.0), name="below.stl")
    above_path = _write_mesh(tmp_path, _box((10.0, 10.0, 10.0), z_min=8.0), name="above.stl")

    below_report = inspect_printability(below_path, PrintabilityProfile())
    above_report = inspect_printability(above_path, PrintabilityProfile())

    below = _result(below_report.results, "orientation.below_build_plate")
    above = _result(above_report.results, "orientation.above_build_plate")
    assert below.severity == "Critical"
    assert below.detected_value.value == -5.0
    assert below.orientation_dependent is True
    assert above.severity == "Warning"
    assert above.detected_value.value == 8.0
    assert above.orientation_dependent is True


def test_printability_detects_components_build_volume_and_thin_features(tmp_path: Path) -> None:
    left = _box((0.3, 10.0, 10.0), z_min=0.0)
    left.apply_translation([-10.0, 0.0, 0.0])
    right = _box((0.3, 10.0, 10.0), z_min=0.0)
    right.apply_translation([10.0, 0.0, 0.0])
    mesh = trimesh.util.concatenate([left, right])
    profile = PrintabilityProfile(
        build_volume=BuildVolumeProfile(x_mm=15.0, y_mm=15.0, z_mm=15.0)
    )

    report = inspect_printability(_write_mesh(tmp_path, mesh), profile)

    components = _result(report.results, "mesh.disconnected_components")
    volume = _result(report.results, "profile.build_volume")
    thickness = _result(report.results, "feature.minimum_thickness")
    small_features = _result(report.results, "feature.small_features_gaps_holes")
    assert components.severity == "Warning"
    assert components.affected_count == 2
    assert volume.severity == "Warning"
    assert volume.detected_value.units == "mm"
    assert volume.highlight is not None
    assert volume.highlight.severity == "Warning"
    assert thickness.severity == "Critical"
    assert thickness.detected_value.value == 0.3
    assert small_features.severity == "Critical"


def test_printability_detects_large_horizontal_bridge_span(tmp_path: Path) -> None:
    bridge = _box((60.0, 8.0, 2.0), z_min=20.0)

    report = inspect_printability(_write_mesh(tmp_path, bridge), PrintabilityProfile())

    result = _result(report.results, "orientation.bridge_spans")
    assert result.severity == "Critical"
    assert result.detected_value.value == 60.0
    assert result.orientation_dependent is True
    assert result.highlight is not None


def _box(extents: tuple[float, float, float], *, z_min: float) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation([0.0, 0.0, z_min + extents[2] / 2.0])
    return mesh


def _write_mesh(tmp_path: Path, mesh: trimesh.Trimesh, *, name: str = "model.stl") -> Path:
    path = tmp_path / name
    mesh.export(path)
    return path


def _result(results, rule_id: str):
    for result in results:
        if result.rule_id == rule_id:
            return result
    raise AssertionError(f"missing printability result {rule_id}")
