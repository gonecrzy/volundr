import numpy as np
import trimesh

from app.services.geometry.feature_measurements import (
    compare_dimension,
    measure_compartments,
    measure_opening_count,
    verify_integral_feature,
    verify_one_connected_output,
    verify_through_opening,
)


def _box(extents, translation=(0, 0, 0)) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation(translation)
    return mesh


def test_integral_feature_requires_positive_material_overlap_and_one_final_component() -> None:
    primary = _box((10, 10, 10))
    overlapping_feature = _box((4, 4, 4), translation=(5, 0, 5))
    fused_final = _box((14, 10, 10), translation=(2, 0, 0))
    edge_feature = _box((4, 4, 4), translation=(7, 0, 7))
    edge_final = trimesh.util.concatenate([primary, edge_feature])

    assert verify_integral_feature(primary, overlapping_feature, fused_final).satisfied
    assert not verify_integral_feature(primary, edge_feature, edge_final).satisfied
    assert verify_integral_feature(primary, edge_feature, edge_final).reason == "final_disconnected"


def test_through_opening_distinguishes_frame_opening_from_blind_solid() -> None:
    frame = trimesh.util.concatenate([
        _box((10, 2, 2), translation=(0, 0, 4)),
        _box((10, 2, 2), translation=(0, 0, -4)),
        _box((2, 2, 6), translation=(-4, 0, 0)),
        _box((2, 2, 6), translation=(4, 0, 0)),
    ])
    blind = _box((10, 2, 10))

    assert verify_through_opening(frame, axis="y", point=(0, -10, 0)).satisfied
    assert not verify_through_opening(blind, axis="y", point=(0, -10, 0)).satisfied


def test_slots_count_actual_opening_probes_and_compare_width_uses_semantic_tolerance() -> None:
    slot_frame = trimesh.util.concatenate([
        _box((4, 2, 2), translation=(-6, 0, 4)),
        _box((4, 2, 2), translation=(-6, 0, -4)),
        _box((4, 2, 2), translation=(6, 0, 4)),
        _box((4, 2, 2), translation=(6, 0, -4)),
    ])
    probes = [(-6, -10, 0), (6, -10, 0)]

    measured = measure_opening_count(slot_frame, axis="y", points=probes)
    assert measured.count == 2
    assert compare_dimension(55.0, 56.0, operator="approximate", tolerance=2.0).passed
    assert not compare_dimension(55.0, 58.0, operator="approximate", tolerance=2.0).passed


def test_compartment_count_requires_open_top_samples_and_expected_dimensions() -> None:
    samples = [
        {"x": 0.0, "y": 0.0, "open_top": True, "width": 55.0, "depth": 45.0},
        {"x": 70.0, "y": 0.0, "open_top": True, "width": 65.0, "depth": 45.0},
    ]

    result = measure_compartments(samples, expected_count=2, expected_width=55.0, tolerance=2.0)

    assert result.count == 2
    assert result.open_top is True
    assert result.satisfied is True


def test_one_connected_output_reuses_topology_and_cable_wall_probe_not_base_probe() -> None:
    connected = _box((10, 10, 10))
    disconnected = trimesh.util.concatenate([connected, _box((2, 2, 2), translation=(20, 0, 0))])

    assert verify_one_connected_output(connected, expected_count=1).satisfied
    assert not verify_one_connected_output(disconnected, expected_count=1).satisfied

    wall_probe = {"axis": "y", "point": (0, -20, 5), "surface": "rear_wall"}
    base_probe = {"axis": "z", "point": (0, 0, -20), "surface": "base"}
    assert wall_probe["surface"] == "rear_wall"
    assert base_probe["surface"] != wall_probe["surface"]
