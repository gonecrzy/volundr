from __future__ import annotations

import inspect
import json
from pathlib import Path

import cadquery as cq
import pytest

from app.services.cad.cadquery_contract import validate_cadquery_source
from app.services.cad.capsule_slot_source import (
    build_capsule_slot_helper_statement,
    validate_capsule_slot_facts,
)
from app.services.cad.capsule_slot_routing import build_capsule_slot_feature_source
from app.services.cad.source_scaffold import render_cadquery_scaffold, validate_scaffold_source
from app.services.research.provider_ir_validation import assemble_t5_source
from app.services.research.t5_final_revision_microstudy import (
    build_final_tasks,
    expected_prior_shape,
    expected_shape_for_control,
)
from volundr_cad.capsule_slot import (
    CAPSULE_SLOT_HELPER_VERSION,
    CapsuleSlotContractError,
    CapsuleSlotFrame,
    cut_capsule_slot_v1,
)


def _upright_frame() -> CapsuleSlotFrame:
    return CapsuleSlotFrame(
        origin_mm=(0, -5, 6),
        x_direction=(1, 0, 0),
        y_direction=(0, 0, 1),
        normal=(0, -1, 0),
        depth_direction=(0, 1, 0),
    )


def _top_frame() -> CapsuleSlotFrame:
    return CapsuleSlotFrame(
        origin_mm=(0, 0, 10),
        x_direction=(1, 0, 0),
        y_direction=(0, 1, 0),
        normal=(0, 0, 1),
        depth_direction=(0, 0, -1),
    )


def _slot_on_certified_prior() -> cq.Workplane:
    task = build_final_tasks()[1]
    facts = task.semantic_facts["revision_delta"]["changed_features"][0]
    requested = facts["requested_feature_dimensions"]
    return cut_capsule_slot_v1(
        expected_prior_shape(),
        frame=_upright_frame(),
        center_local_mm=facts["feature_center_local_mm"],
        overall_length_mm=requested["overall_length_mm"],
        width_mm=requested["width_mm"],
        end_radius_mm=requested["end_radius_mm"],
        orientation_degrees=requested["orientation_degrees"],
        depth_mode=requested["depth_mode"],
        blind_depth_mm=requested["depth_mm"],
        depth_direction=requested["depth_direction"],
    )


def _shape_difference_volume(left: cq.Workplane, right: cq.Workplane) -> float:
    return abs(float(left.cut(right).val().Volume())) + abs(float(right.cut(left).val().Volume()))


def _cylinders(shape: cq.Workplane) -> list[tuple[float, tuple[float, float, float], tuple[float, float, float], tuple[float, float, float, float, float, float]]]:
    result = []
    for face in shape.faces().vals():
        if face.geomType() != "CYLINDER":
            continue
        cylinder = face._geomAdaptor().Cylinder()
        location = cylinder.Axis().Location()
        box = face.BoundingBox()
        result.append((
            float(cylinder.Radius()),
            (float(location.X()), float(location.Y()), float(location.Z())),
            (float(cylinder.Axis().Direction().X()), float(cylinder.Axis().Direction().Y()), float(cylinder.Axis().Direction().Z())),
            (float(box.xmin), float(box.xmax), float(box.ymin), float(box.ymax), float(box.zmin), float(box.zmax)),
        ))
    return result


def test_helper_uses_overall_length_and_width_radius_and_matches_certified_capsule() -> None:
    actual = _slot_on_certified_prior()
    expected = expected_shape_for_control("slot")
    second = _slot_on_certified_prior()
    shorter = cut_capsule_slot_v1(
        expected_prior_shape(),
        frame=_upright_frame(),
        center_local_mm=(10, 14),
        overall_length_mm=13,
        width_mm=5,
        end_radius_mm=2.5,
        orientation_degrees=0,
        depth_mode="blind",
        blind_depth_mm=3,
        depth_direction=(0, 1, 0),
    )

    assert _shape_difference_volume(actual, expected) <= 1e-4
    assert _shape_difference_volume(actual, second) <= 1e-4
    actual_endpoints = sorted(round(center[0], 6) for radius, center, _, _ in _cylinders(actual) if abs(radius - 2.5) <= 1e-6 and abs(center[2] - 20) <= 1e-6)
    shorter_endpoints = sorted(round(center[0], 6) for radius, center, _, _ in _cylinders(shorter) if abs(radius - 2.5) <= 1e-6 and abs(center[2] - 20) <= 1e-6)
    assert actual_endpoints == [3.5, 16.5]
    assert shorter_endpoints == [6.0, 14.0]
    assert len(actual.solids().vals()) == 1
    assert any(
        abs(radius - 2.5) <= 1e-6
        and abs(center[0] - endpoint[0]) <= 1e-6
        and abs(center[1] + 5) <= 1e-5
        and abs(center[2] - 20) <= 1e-6
        and abs(abs(axis[1]) - 1) <= 1e-6
        for radius, center, axis, _ in _cylinders(actual)
        for endpoint in ((3.5, -5, 20), (16.5, -5, 20))
    )


def test_helper_preserves_orientation_frame_and_blind_depth() -> None:
    body = cq.Workplane("XY").box(40, 40, 10, centered=(False, False, False))
    result = cut_capsule_slot_v1(
        body,
        frame=_top_frame(),
        center_local_mm=(20, 20),
        overall_length_mm=18,
        width_mm=5,
        end_radius_mm=2.5,
        orientation_degrees=90,
        depth_mode="blind",
        blind_depth_mm=2,
        depth_direction=(0, 0, -1),
    )

    assert len(result.solids().vals()) == 1
    endpoints = [item for item in _cylinders(result) if abs(item[0] - 2.5) <= 1e-6]
    assert len(endpoints) == 2
    assert all(abs(center[0] - 20) <= 1e-6 for _, center, _, _ in endpoints)
    assert sorted(round(center[1], 6) for _, center, _, _ in endpoints) == [13.5, 26.5]
    assert all(abs(box[4] - 8) <= 1e-6 and abs(box[5] - 10) <= 1e-5 for _, _, _, box in endpoints)


def test_helper_fails_closed_for_incomplete_or_ambiguous_facts() -> None:
    with pytest.raises(CapsuleSlotContractError):
        validate_capsule_slot_facts({})
    with pytest.raises(CapsuleSlotContractError, match="overall_length"):
        cut_capsule_slot_v1(
            cq.Workplane("XY").box(20, 20, 5),
            frame=_top_frame(),
            center_local_mm=(10, 10),
            overall_length_mm=4,
            width_mm=5,
            end_radius_mm=2.5,
            orientation_degrees=0,
            depth_mode="blind",
            blind_depth_mm=1,
            depth_direction=(0, 0, -1),
        )
    with pytest.raises(CapsuleSlotContractError, match="end radius"):
        cut_capsule_slot_v1(
            cq.Workplane("XY").box(20, 20, 5),
            frame=_top_frame(),
            center_local_mm=(10, 10),
            overall_length_mm=10,
            width_mm=5,
            end_radius_mm=2,
            orientation_degrees=0,
            depth_mode="blind",
            blind_depth_mm=1,
            depth_direction=(0, 0, -1),
        )
    with pytest.raises(CapsuleSlotContractError, match="depth_mode"):
        cut_capsule_slot_v1(
            cq.Workplane("XY").box(20, 20, 5),
            frame=_top_frame(),
            center_local_mm=(10, 10),
            overall_length_mm=10,
            width_mm=5,
            end_radius_mm=2.5,
            orientation_degrees=0,
            depth_mode="through",
            blind_depth_mm=1,
            depth_direction=(0, 0, -1),
        )


def test_helper_is_pinned_and_does_not_import_ocp() -> None:
    import volundr_cad.capsule_slot as module

    source = inspect.getsource(module)
    assert CAPSULE_SLOT_HELPER_VERSION == "cut_capsule_slot_v1"
    assert cq.__version__ == "2.8.0"
    assert "from OCP" not in source
    assert "import OCP" not in source


def test_capsule_source_assembly_is_deterministic_and_raw_t5_remains_default() -> None:
    task = build_final_tasks()[1]
    change = task.semantic_facts["revision_delta"]["changed_features"][0]
    parameter_ids = {
        "length": "slot_length_mm",
        "width": "slot_width_mm",
        "center_x": "slot_center_x_mm",
        "center_y": "slot_center_local_y_mm",
        "orientation": "slot_orientation_degrees",
        "depth": "slot_depth_mm",
    }
    statement_a = build_capsule_slot_helper_statement(change, parameter_ids=parameter_ids)
    statement_b = build_capsule_slot_helper_statement(change, parameter_ids=parameter_ids)
    assert statement_a == statement_b
    assert "cut_capsule_slot_v1" in statement_a
    assert "slot2D" not in statement_a

    raw_payload = {"slots": [{"slot_id": 0, "result_symbol": "body", "statements": [
        'body = body.faces(">Z").workplane().slot2D(18, 5, 0).cutBlind(-3)',
    ]}]}
    raw_source = assemble_t5_source(task, raw_payload)
    assert "cut_capsule_slot_v1" not in raw_source
    assert "slot2D(18, 5, 0)" in raw_source
    helper_source = assemble_t5_source(task, raw_payload, deterministic_capsule_slot=True, preserved_statements=[])
    assert helper_source == assemble_t5_source(task, raw_payload, deterministic_capsule_slot=True, preserved_statements=[])
    assert "from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product, CapsuleSlotFrame, cut_capsule_slot_v1" in helper_source
    validate_cadquery_source(helper_source)
    assert "body = cut_capsule_slot_v1(body" in helper_source


def test_wave_capsule_routing_requires_plan_traceability_and_preserves_other_provider_functions() -> None:
    plan = {
        "parameters": [
            {"id": "capsule_length_mm", "type": "float", "value": 34},
            {"id": "capsule_width_mm", "type": "float", "value": 8},
            {"id": "capsule_center_x_mm", "type": "float", "value": 35},
            {"id": "capsule_center_y_mm", "type": "float", "value": 12},
            {"id": "capsule_orientation_degrees", "type": "float", "value": 20},
            {"id": "capsule_depth_mm", "type": "float", "value": 4},
        ],
        "components": [{"id": "guide_body"}],
        "features": [{"id": "capsule_retention_slot", "component_id": "guide_body", "profile_type": "rounded_end_capsule"}],
        "printable_outputs": [{"id": "swept_cable_guide", "component_ids": ["guide_body"], "expected_solid_count": 1}],
    }
    capsule_facts = {
        "feature_id": "capsule_retention_slot",
        "component_id": "guide_body",
        "target_output_id": "swept_cable_guide",
        "requested_feature_dimensions": {
            "profile_type": "rounded_end_capsule",
            "overall_length_mm": 34,
            "width_mm": 8,
            "end_radius_mm": 4,
            "orientation_degrees": 20,
            "depth_mode": "blind",
            "depth_mm": 4,
            "depth_direction": [0, 0, -1],
        },
        "feature_center_local_mm": [35, 12],
        "local_coordinate_frame": {
            "origin_mm": [0, 0, 18],
            "x_direction": [1, 0, 0],
            "y_direction": [0, 1, 0],
            "normal": [0, 0, 1],
            "depth_direction": [0, 0, -1],
        },
        "parameter_ids": {
            "length": "capsule_length_mm",
            "width": "capsule_width_mm",
            "center_x": "capsule_center_x_mm",
            "center_y": "capsule_center_y_mm",
            "orientation": "capsule_orientation_degrees",
            "depth": "capsule_depth_mm",
        },
    }
    routed = build_capsule_slot_feature_source(plan, capsule_facts)
    source = render_cadquery_scaffold(
        plan,
        {
            "_ai_component_guide_body": "def _ai_component_guide_body(params):\n    return cq.Workplane('XY').box(80, 40, 18)",
            "_ai_feature_capsule_retention_slot": "def _ai_feature_capsule_retention_slot(body, params):\n    return body",
        },
        deterministic_feature_sources={"capsule_retention_slot": routed["helper_source"]},
    ).source
    assert "cut_capsule_slot_v1" in source
    assert "return body" in source
    assert "return cq.Workplane('XY').box(80, 40, 18)" in source
    assert validate_scaffold_source(source) == []

    missing_plan_profile = {**plan, "features": [{"id": "capsule_retention_slot", "component_id": "guide_body"}]}
    routed_without_plan_profile = build_capsule_slot_feature_source(missing_plan_profile, capsule_facts)
    assert "cut_capsule_slot_v1" in routed_without_plan_profile["helper_source"]

    missing_authoritative_profile = {
        **capsule_facts,
        "requested_feature_dimensions": {
            key: value
            for key, value in capsule_facts["requested_feature_dimensions"].items()
            if key != "profile_type"
        },
    }
    with pytest.raises(CapsuleSlotContractError, match="profile_type"):
        build_capsule_slot_feature_source(missing_plan_profile, missing_authoritative_profile)


def test_capsule_routing_uses_plan_association_when_frozen_identity_is_stale() -> None:
    plan = {
        "parameters": [
            {"id": "capsule_slot_length", "source_requirement_id": "capsule_slot_length"},
            {"id": "capsule_slot_width", "source_requirement_id": "capsule_slot_width"},
            {"id": "capsule_slot_center_x", "source_requirement_id": "capsule_slot_center_x"},
            {"id": "capsule_slot_center_y", "source_requirement_id": "capsule_slot_center_y"},
            {"id": "capsule_slot_orientation", "source_requirement_id": "capsule_slot_orientation"},
            {"id": "capsule_slot_depth", "source_requirement_id": "capsule_slot_depth"},
        ],
        "features": [
            {
                "id": "capsule_slot_feature",
                "component_id": "swept_cable_guide_body",
                "parameters": [
                    "capsule_slot_length",
                    "capsule_slot_width",
                    "capsule_slot_center_x",
                    "capsule_slot_center_y",
                    "capsule_slot_orientation",
                    "capsule_slot_depth",
                ],
                "requirement_ids": [
                    "capsule_slot_feature",
                    "capsule_slot_length",
                    "capsule_slot_width",
                    "capsule_slot_center_x",
                    "capsule_slot_center_y",
                    "capsule_slot_orientation",
                    "capsule_slot_depth",
                ],
            }
        ],
        "printable_outputs": [
            {"id": "swept_cable_guide", "component_ids": ["swept_cable_guide_body"], "expected_solid_count": 1}
        ],
    }
    stale_frozen_capsule_facts = {
        "feature_id": "capsule_retention_slot",
        "component_id": "guide_body",
        "target_output_id": "swept_cable_guide",
        "requested_feature_dimensions": {
            "profile_type": "rounded_end_capsule",
            "overall_length_mm": 34,
            "width_mm": 8,
            "end_radius_mm": 4,
            "orientation_degrees": 20,
            "depth_mode": "blind",
            "depth_mm": 4,
            "depth_direction": [0, 0, -1],
        },
        "feature_center_local_mm": [35, 12],
        "local_coordinate_frame": {
            "origin_mm": [0, 0, 18],
            "x_direction": [1, 0, 0],
            "y_direction": [0, 1, 0],
            "normal": [0, 0, 1],
            "depth_direction": [0, 0, -1],
        },
        "parameter_ids": {
            "length": "capsule_length_mm",
            "width": "capsule_width_mm",
            "center_x": "capsule_center_x_mm",
            "center_y": "capsule_center_y_mm",
            "orientation": "capsule_orientation_degrees",
            "depth": "capsule_depth_mm",
        },
    }

    routed = build_capsule_slot_feature_source(plan, stale_frozen_capsule_facts)

    assert routed["feature_id"] == "capsule_slot_feature"
    assert routed["component_id"] == "swept_cable_guide_body"
    assert routed["authoritative_feature_id"] == "capsule_retention_slot"
    assert routed["authoritative_component_id"] == "guide_body"
    assert routed["parameter_ids"] == {
        "length": "capsule_slot_length",
        "width": "capsule_slot_width",
        "center_x": "capsule_slot_center_x",
        "center_y": "capsule_slot_center_y",
        "orientation": "capsule_slot_orientation",
        "depth": "capsule_slot_depth",
    }
    assert "cut_capsule_slot_v1" in routed["helper_source"]
