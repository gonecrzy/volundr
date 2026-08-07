import cadquery as cq
import pytest

from app.services.cad.topology_evidence import (
    collect_topology_evidence,
    compare_topology_evidence,
)


def _box(size: float = 10.0, *, x: float = 0.0) -> cq.Solid:
    return cq.Workplane("XY").box(size, size, size).translate((x, 0, 0)).val()


def _evidence(shape: cq.Shape, *, expected: int = 1, allow: bool = False) -> dict:
    return collect_topology_evidence(
        shape,
        expected_solid_count=expected,
        allow_disconnected_solids=allow,
    )


def test_one_valid_solid_records_neutral_measurements() -> None:
    evidence = _evidence(_box())

    assert evidence["schema_version"] == "topology-evidence-v2"
    assert evidence["overall_shape_valid"] is True
    assert evidence["valid"] is True
    assert evidence["expected_solid_count"] == 1
    assert evidence["detected_solid_count"] == 1
    assert evidence["disconnected_solid_policy"] == {"allow_disconnected_solids": False}
    assert evidence["overall_bounding_box"]["size_x"] == pytest.approx(10.0)
    assert evidence["solids"] == [
        {
            "solid_index": 0,
            "solid_id": "solid-0",
            "valid": True,
            "volume_mm3": pytest.approx(1000.0),
            "bounding_box_mm": {
                "x_min": pytest.approx(-5.0),
                "x_max": pytest.approx(5.0),
                "y_min": pytest.approx(-5.0),
                "y_max": pytest.approx(5.0),
                "z_min": pytest.approx(-5.0),
                "z_max": pytest.approx(5.0),
                "size_x": pytest.approx(10.0),
                "size_y": pytest.approx(10.0),
                "size_z": pytest.approx(10.0),
            },
            "centroid_mm": {
                "x": pytest.approx(0.0),
                "y": pytest.approx(0.0),
                "z": pytest.approx(0.0),
            },
            "shell_count": 1,
            "face_count": 6,
        }
    ]
    assert evidence["solid_pairs"] == []


def test_two_overlapping_solids_record_intersection_and_overlap() -> None:
    first = _box()
    second = _box(x=5.0)

    evidence = _evidence(cq.Compound.makeCompound([first, second]), expected=2)
    pair = evidence["solid_pairs"][0]

    assert evidence["detected_solid_count"] == 2
    assert pair["intersects"] is True
    assert pair["touches"] is False
    assert pair["minimum_separation_mm"] == pytest.approx(0.0)
    assert pair["overlapping_volume_mm3"] == pytest.approx(500.0)


def test_two_touching_solids_record_contact_without_overlap() -> None:
    evidence = _evidence(
        cq.Compound.makeCompound([_box(), _box(x=10.0)]),
        expected=2,
    )
    pair = evidence["solid_pairs"][0]

    assert pair["intersects"] is True
    assert pair["touches"] is True
    assert pair["minimum_separation_mm"] == pytest.approx(0.0)
    assert pair["overlapping_volume_mm3"] == pytest.approx(0.0)


def test_two_separated_solids_record_distance_without_relationship() -> None:
    evidence = _evidence(
        cq.Compound.makeCompound([_box(), _box(x=20.0)]),
        expected=2,
    )
    pair = evidence["solid_pairs"][0]

    assert pair["intersects"] is False
    assert pair["touches"] is False
    assert pair["minimum_separation_mm"] == pytest.approx(10.0)
    assert pair["overlapping_volume_mm3"] == pytest.approx(0.0)


def test_multiple_disconnected_solids_preserve_policy_and_all_pairs() -> None:
    evidence = _evidence(
        cq.Compound.makeCompound([_box(), _box(x=20.0), _box(x=40.0)]),
        expected=1,
        allow=False,
    )

    assert evidence["valid"] is False
    assert evidence["overall_shape_valid"] is True
    assert evidence["outcome"] == "solid_count_mismatch"
    assert evidence["detected_solid_count"] == 3
    assert len(evidence["solids"]) == 3
    assert len(evidence["solid_pairs"]) == 3


def test_invalid_shape_evidence_is_explicit_and_non_throwing() -> None:
    evidence = collect_topology_evidence(
        None,
        expected_solid_count=1,
        allow_disconnected_solids=False,
    )

    assert evidence["schema_version"] == "topology-evidence-v2"
    assert evidence["status"] == "unavailable"
    assert evidence["overall_shape_valid"] is False
    assert evidence["valid"] is False
    assert evidence["detected_solid_count"] == 0
    assert evidence["solids"] == []
    assert evidence["solid_pairs"] == []
    assert evidence["measurement_errors"]


def test_topology_evidence_comparison_identifies_material_new_facts() -> None:
    historical = {
        "valid": False,
        "expected_solid_count": 1,
        "detected_solid_count": 2,
        "shell_count": 2,
        "volume_mm3": 100.0,
        "bounding_box_mm": {"size_x": 10.0},
    }
    current = {
        **historical,
        "schema_version": "topology-evidence-v2",
        "overall_shape_valid": True,
        "overall_bounding_box": {"size_x": 10.0},
        "disconnected_solid_policy": {"allow_disconnected_solids": False},
        "solids": [{"solid_id": "solid-0", "centroid_mm": {"x": 0.0}}],
        "solid_pairs": [],
    }

    comparison = compare_topology_evidence(historical, current)

    assert comparison["material_diagnostic_improvement"] is True
    assert comparison["materially_equivalent"] is False
    assert comparison["new_standardized_fields"] == [
        "disconnected_solid_policy",
        "overall_bounding_box",
        "overall_shape_valid",
        "schema_version",
        "solid_pairs",
        "solids",
    ]


def test_topology_evidence_comparison_allows_equivalent_replay_without_new_call() -> None:
    evidence = _evidence(_box())

    comparison = compare_topology_evidence(evidence, evidence)

    assert comparison["material_diagnostic_improvement"] is False
    assert comparison["materially_equivalent"] is True
    assert comparison["new_standardized_fields"] == []
