import json
from pathlib import Path

import trimesh

from app.services.geometry.feature_evidence import evaluate_feature_evidence
from app.services.geometry.feature_measurements import (
    compare_dimension,
    measure_compartments,
    measure_opening_count,
    verify_integral_feature,
    verify_one_connected_output,
    verify_through_opening,
)
from app.services.geometry.feature_repair import (
    build_feature_repair_context,
    validate_feature_repair_result,
)
from app.services.projects.output_outcomes import resolve_output_outcome


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "feature_verification"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def _box(extents, translation=(0, 0, 0)) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation(translation)
    return mesh


def _frame(axis: str = "y") -> trimesh.Trimesh:
    # A rectangular frame with a real void through its thin wall.
    if axis != "y":
        raise ValueError(axis)
    return trimesh.util.concatenate([
        _box((10, 2, 2), translation=(0, 0, 4)),
        _box((10, 2, 2), translation=(0, 0, -4)),
        _box((2, 2, 6), translation=(-4, 0, 0)),
        _box((2, 2, 6), translation=(4, 0, 0)),
    ])


def _trace(feature_id: str, *, changed: bool = True) -> dict:
    return {
        "feature_id": feature_id,
        "source_function_id": f"_ai_feature_{feature_id}",
        "source_executed": True,
        "shape_changed": changed,
        "input_shape_hash": "before",
        "output_shape_hash": "after" if changed else "before",
        "operation_category": "subtractive" if changed else "no_effect",
    }


def test_frozen_portable_and_organizer_require_final_evidence() -> None:
    portable = _fixture("portable_holder_frozen.json")
    organizer = _fixture("desktop_organizer_frozen.json")
    assert portable["expected_initial_outcome"] == "verification_blocked"
    assert organizer["expected_unresolved_requirements"] == [
        "req_one_piece", "req_phone_slot", "req_pen_compartment",
        "req_accessory_compartments", "req_cable_notch",
    ]
    assert portable["feature_trace"] == organizer["feature_trace"] == []


def test_source_presence_alone_and_missing_feature_remain_blocked() -> None:
    evaluation = evaluate_feature_evidence(
        mesh=_box((10, 10, 10)), output_id="part",
        requirement_trace={"features": [{"feature_id": "handle", "requirement_ids": ["req_handle"]}]},
        feature_trace=[],
    )
    assert evaluation.records[0].requirement_outcome == "unverifiable"
    assert evaluation.trace_findings[0]["rule_id"] == "feature.trace_missing"


def test_executed_no_effect_and_trace_ambiguity_are_not_satisfied() -> None:
    base = {"features": [{"feature_id": "slot", "requirement_ids": ["req_slot"]}]}
    no_effect = evaluate_feature_evidence(
        mesh=_box((10, 10, 10)), output_id="part", requirement_trace=base,
        feature_trace=[_trace("slot", changed=False)],
    )
    ambiguous = evaluate_feature_evidence(
        mesh=_box((10, 10, 10)), output_id="part", requirement_trace=base,
        feature_trace=[_trace("slot"), _trace("slot")],
    )
    assert no_effect.records[0].requirement_outcome == "feature_absent"
    assert ambiguous.records[0].requirement_outcome == "unverifiable"


def test_integral_overlap_and_edge_only_contact() -> None:
    primary = _box((10, 10, 10))
    feature = _box((4, 4, 4), translation=(5, 0, 5))
    assert verify_integral_feature(primary, feature, _box((14, 10, 10), translation=(2, 0, 0))).satisfied
    separate = _box((4, 4, 4), translation=(7, 0, 7))
    assert not verify_integral_feature(primary, separate, trimesh.util.concatenate([primary, separate])).satisfied


def test_drainage_through_opening_and_blind_recess() -> None:
    assert verify_through_opening(_frame(), axis="y", point=(0, -10, 0)).satisfied
    assert not verify_through_opening(_box((10, 2, 10)), axis="y", point=(0, -10, 0)).satisfied


def test_two_strap_slots_are_counted_as_two_actual_openings() -> None:
    slots = trimesh.util.concatenate([
        _box((4, 2, 2), translation=(-6, 0, 4)),
        _box((4, 2, 2), translation=(-6, 0, -4)),
        _box((4, 2, 2), translation=(6, 0, 4)),
        _box((4, 2, 2), translation=(6, 0, -4)),
    ])
    result = measure_opening_count(slots, axis="y", points=[(-6, -10, 0), (6, -10, 0)])
    assert result.count == 2


def test_slot_width_and_approximate_compartment_dimension() -> None:
    assert compare_dimension(180, 179.5, operator="approximate", tolerance=1).passed
    assert not compare_dimension(180, 176, operator="approximate", tolerance=1).passed
    compartments = measure_compartments(
        [{"open_top": True, "width": 55, "depth": 45}, {"open_top": True, "width": 70, "depth": 45}],
        expected_count=2, expected_width=55, tolerance=2,
    )
    assert compartments.satisfied


def test_one_piece_topology_and_cable_wall_not_base() -> None:
    body = _box((10, 10, 10))
    assert verify_one_connected_output(body).satisfied
    assert not verify_one_connected_output(
        trimesh.util.concatenate([body, _box((2, 2, 2), translation=(20, 0, 0))])
    ).satisfied
    assert verify_through_opening(_frame(), axis="y", point=(0, -10, 0)).satisfied
    assert not verify_through_opening(_box((10, 2, 10)), axis="z", point=(0, 0, -10)).satisfied


def test_present_measurable_feature_resolves_and_repaired_geometry_is_remeasured() -> None:
    evaluation = evaluate_feature_evidence(
        mesh=_box((220, 140, 65)), output_id="organizer",
        requirement_trace={
            "features": [{"feature_id": "main_body", "requirement_ids": ["req_body"], "object_type": "desktop organizer"}],
            "validation_targets": [{"feature_id": "main_body", "measurement": "width", "requirement_ids": ["req_body"], "value": 220}],
        },
        feature_trace=[_trace("main_body")],
        topology_metadata={"expected_solid_count": 1},
    )
    assert evaluation.records[0].requirement_outcome == "satisfied"
    repaired = evaluate_feature_evidence(
        mesh=_box((220, 140, 65)), output_id="organizer",
        requirement_trace={
            "features": [{"feature_id": "handle", "requirement_ids": ["req_handle"]}],
            "validation_targets": [{"feature_id": "handle", "requirement_ids": ["req_handle"], "probe_points": [[0, -90, 0]], "axis": "y"}],
        },
        feature_trace=[_trace("handle")],
        topology_metadata={"expected_solid_count": 1},
    )
    assert repaired.records[0].measurement_status == "measured"
    assert repaired.records[0].requirement_outcome == "not_satisfied"


def test_feature_repair_preserves_slots_and_candidate_consumes_final_evidence() -> None:
    context = build_feature_repair_context(
        [{"feature_id": "handle", "metadata": {"feature_id": "handle", "requirement_id": "req_handle", "protected_hashes": {"slot_2": "h"}}}],
        worker_succeeded=True, topology_valid=True,
    )
    result = validate_feature_repair_result(
        context,
        before={"output_ids": ["part"], "hashes": {"slot_2": "h"}},
        after={
            "output_ids": ["part"],
            "hashes": {"slot_2": "h"},
            "detected_solid_count": 1,
            "feature_evidence": {
                "feature_id": "handle",
                "requirement_outcome": "satisfied",
                "measurement_status": "measured",
                "measurements": {
                    "connected_to_primary_body": True,
                    "material_overlap_volume_estimate_mm3": 2,
                },
            },
        },
        provider_calls=1,
    )
    assert result["accepted"]
    outcome = resolve_output_outcome(
        expected_outputs=[{"output_id": "part", "required": True, "expected_solid_count": 1}],
        worker_status="succeeded",
        registered_artifacts=[{"output_id": "part", "required": True, "stl_path": "a", "stl_hash": "a", "step_path": "b", "step_hash": "b", "brep_path": "c", "brep_hash": "c", "topology_metadata": {"valid": True, "detected_solid_count": 1}}],
        verification_findings=[{"rule_id": "feature.evidence.handle.req_handle", "is_blocking": False}],
    )
    assert outcome.state == "candidate_ready_with_warnings"


def test_physical_review_warning_remains_independent_of_geometry_success() -> None:
    outcome = resolve_output_outcome(
        expected_outputs=[{"output_id": "part", "required": True, "expected_solid_count": 1}],
        worker_status="succeeded",
        registered_artifacts=[{"output_id": "part", "required": True, "stl_path": "a", "stl_hash": "a", "step_path": "b", "step_hash": "b", "brep_path": "c", "brep_hash": "c", "topology_metadata": {"valid": True, "detected_solid_count": 1}}],
        verification_findings=[{"rule_id": "feature.evidence.handle.req_handle", "is_blocking": False}],
        candidate_findings=[{"rule_id": "physical.load_testing_required", "is_blocking": False}],
    )
    assert outcome.state == "candidate_ready_with_warnings"
