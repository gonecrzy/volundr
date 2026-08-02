from __future__ import annotations

import pytest

from app.services.cad.pattern_coordinates import (
    COMPONENT_LOCAL_3D,
    WORLD_3D,
    WORKPLANE_LOCAL_2D,
    WORKPLANE_LOCAL_3D,
    convert_points_to_workplane,
    validate_push_points,
)


def test_workplane_local_2d_points_are_valid_for_push_points() -> None:
    evidence = validate_push_points(
        [(1, 2), (3, 4)],
        coordinate_space=WORKPLANE_LOCAL_2D,
        workplane_normal_axis="Z",
    )

    assert evidence.valid is True
    assert evidence.local_points == ((1.0, 2.0), (3.0, 4.0))
    assert evidence.finding is None


def test_workplane_local_3d_points_with_zero_normal_are_valid() -> None:
    evidence = validate_push_points(
        [(1, 2, 0), (3, 4, 0)],
        coordinate_space=WORKPLANE_LOCAL_3D,
        workplane_normal_axis="Z",
    )

    assert evidence.valid is True
    assert evidence.local_points == ((1.0, 2.0), (3.0, 4.0))


def test_workplane_local_3d_points_with_varying_normal_are_rejected() -> None:
    evidence = validate_push_points(
        [(1, 2, -1), (3, 4, 1)],
        coordinate_space=WORKPLANE_LOCAL_3D,
        workplane_normal_axis="Z",
    )

    assert evidence.valid is False
    assert evidence.finding["rule_id"] == "geometry_body.push_points_nonplanar"
    assert evidence.finding["blocking"] is True


def test_coplanar_component_points_convert_to_workplane_local_2d() -> None:
    points = [(10, 20, 5), (30, 40, 5)]
    evidence = convert_points_to_workplane(
        points,
        coordinate_space=COMPONENT_LOCAL_3D,
        source_frame={"origin": [0, 0, 0], "normal_axis": "Z"},
        workplane_frame={"origin": [0, 0, 5], "normal_axis": "Z"},
    )

    assert evidence.valid is True
    assert evidence.local_points == ((10.0, 20.0), (30.0, 40.0))
    assert evidence.finding["rule_id"] == "geometry_body.pattern_points_converted_to_local"


def test_non_coplanar_component_points_require_placement_strategy() -> None:
    evidence = convert_points_to_workplane(
        [(0, 0, -100), (0, 0, 0), (0, 0, 100)],
        coordinate_space=COMPONENT_LOCAL_3D,
        source_frame={"origin": [0, 0, 0], "normal_axis": "Z"},
        workplane_frame={"origin": [0, 0, 137.5], "normal_axis": "Z"},
    )

    assert evidence.valid is False
    assert evidence.finding["rule_id"] == "geometry_body.pattern_coordinate_space_mismatch"
    assert evidence.finding["repair_eligibility"] == "placement_or_compatible_plane"


def test_world_points_without_a_frame_are_rejected() -> None:
    evidence = convert_points_to_workplane(
        [(1, 2, 3)],
        coordinate_space=WORLD_3D,
        source_frame=None,
        workplane_frame={"origin": [0, 0, 0], "normal_axis": "Z"},
    )

    assert evidence.valid is False
    assert evidence.finding["rule_id"] == "geometry_body.pattern_transform_missing"


def test_push_points_source_validation_catches_direct_component_points() -> None:
    from app.services.cad.pattern_coordinates import validate_pattern_push_points_source

    source = """
def _ai_feature_tray_slots(body, params):
    pts = params.get("tray_slot_points")
    modified = body.faces(">Z").workplane().pushPoints(pts).rect(190, 188).cutBlind(-265)
    return modified
"""
    findings = validate_pattern_push_points_source(
        source,
        [
            {
                "pattern_id": "tray_slot_pattern",
                "owning_feature_id": "tray_slots",
                "point_parameter_id": "tray_slot_points",
                "coordinate_space": COMPONENT_LOCAL_3D,
                "coordinate_frame_id": "root_frame",
                "arrangement_axis": "Z",
                "resolved_points": [[0, 0, -100], [0, 0, 0], [0, 0, 100]],
            }
        ],
    )

    assert len(findings) == 1
    assert findings[0]["rule_id"] == "geometry_body.pattern_coordinate_space_mismatch"
    assert findings[0]["function_id"] == "_ai_feature_tray_slots"
    assert findings[0]["pattern_id"] == "tray_slot_pattern"


def test_push_points_source_validation_catches_provider_rebuilt_3d_points() -> None:
    from app.services.cad.pattern_coordinates import validate_pattern_push_points_source

    source = """
def _ai_feature_slots(body, params):
    pts = params.get("slot_points")
    modified = cq.Workplane("XY").pushPoints([(p[0], p[1] + 90, p[2]) for p in pts]).box(10, 10, 10)
    return modified
"""
    findings = validate_pattern_push_points_source(
        source,
        [{
            "pattern_id": "slot_pattern",
            "point_parameter_id": "slot_points",
            "coordinate_space": COMPONENT_LOCAL_3D,
            "arrangement_axis": "Z",
            "resolved_points": [[0, 0, -1], [0, 0, 1]],
        }],
    )

    assert findings[0]["rule_id"] == "geometry_body.pattern_coordinate_space_mismatch"


def test_runtime_nonplanar_worker_error_is_localizable() -> None:
    from app.services.cad.runtime_diagnostics import classify_worker_diagnostic

    finding = classify_worker_diagnostic(
        "ValueError: Cannot build face(s): wires not planar",
        traceback=(
            "Traceback (most recent call last):\n"
            "  File \"source.py\", line 9, in _ai_feature_tray_slots\n"
            "    modified = body.faces(\">Z\").workplane().pushPoints(pts).rect(190, 188)\n"
            "ValueError: Cannot build face(s): wires not planar\n"
        ),
    )

    assert finding is not None
    assert finding["rule_id"] == "worker.pattern_points_not_planar_for_workplane"
    assert finding["function_id"] == "_ai_feature_tray_slots"
    assert finding["repair_available"] is True


def test_runtime_nonplanar_finding_carries_the_canonical_pattern_contract() -> None:
    from app.services.cad.runtime_diagnostics import classify_worker_diagnostic

    finding = classify_worker_diagnostic(
        "ValueError: Cannot build face(s): wires not planar",
        traceback="File \"source.py\", line 9, in _ai_feature_tray_slots\n    modified = body.pushPoints(pts)",
        pattern_manifest=[
            {
                "pattern_id": "slot_pattern",
                "owning_component_id": "body",
                "owning_feature_id": "slots",
                "coordinate_space": COMPONENT_LOCAL_3D,
                "coordinate_frame_id": "root_frame",
                "point_dimensionality": 3,
                "arrangement_axis": "Z",
                "resolved_points": [[0, 0, -1], [0, 0, 1]],
            }
        ],
    )

    assert finding["pattern_id"] == "slot_pattern"
    assert finding["pattern_coordinate_evidence"]["coordinate_space"] == COMPONENT_LOCAL_3D


def test_runtime_cadquery_api_finding_carries_worker_version() -> None:
    from app.services.cad.runtime_diagnostics import classify_worker_diagnostic

    finding = classify_worker_diagnostic(
        "AttributeError: 'Workplane' object has no attribute 'assembly'",
        traceback=(
            "Traceback (most recent call last):\n"
            "  File \"source.py\", line 9, in _ai_feature_slots\n"
            "    tool = cq.Workplane(\"XY\").assembly()\n"
            "AttributeError: 'Workplane' object has no attribute 'assembly'\n"
        ),
        worker_metadata={"cadquery_version": "2.8.0", "worker_version": "cadquery-cli-runner-v1"},
    )

    assert finding is not None
    assert finding["rule_id"] == "geometry_body.cadquery_api_failure"
    assert finding["worker_runtime"] == {
        "cadquery_version": "2.8.0",
        "worker_version": "cadquery-cli-runner-v1",
    }


def test_runtime_metadata_can_be_read_from_worker_result_diagnostics() -> None:
    from app.services.cad.runtime_diagnostics import classify_worker_diagnostic

    finding = classify_worker_diagnostic(
        "AttributeError: 'Workplane' object has no attribute 'assembly'",
        traceback=(
            "  File \"source.py\", line 9, in _ai_feature_slots\n"
            "    tool = cq.Workplane(\"XY\").assembly()\n"
            "AttributeError: 'Workplane' object has no attribute 'assembly'\n"
        ),
        worker_metadata={
            "diagnostics": {
                "cadquery_version": "2.8.0",
                "cadquery_worker_version": "cadquery-cli-runner-v1",
            }
        },
    )

    assert finding is not None
    assert finding["worker_runtime"] == {
        "cadquery_version": "2.8.0",
        "worker_version": "cadquery-cli-runner-v1",
    }
