"""Certified three-operation T5 revision microstudy.

This module is research-only.  It certifies the authoritative prior artifact
and deterministic controls before allowing the final provider microstudy to
start.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import cadquery as cq

from app.services.ai.provider import ModelGenerationRequest
from app.services.research.provider_ir_validation import ProviderStudyTask
from app.services.research.t5_parameter_revision_validation import (
    AUTHORITY_PATH,
    _make_task,
    _parameters,
    load_revision_authority,
)


FINAL_STUDY_ID = "t5-final-revision-microstudy-01"
PROMPT_VERSION = "T5-geometry-exact-slot-contract-v2-parameter-map"
OUTPUT_ID = "mounting_bracket"
RESULT_SYMBOL = "body"
REPO_ROOT = Path(__file__).resolve().parents[3]


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")
    ).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def authority_source_expression() -> str:
    return str(load_revision_authority()["prior_body_expression"])


def _protected_dimensions(authority: dict[str, Any]) -> dict[str, Any]:
    return {
        str(item["id"]): copy.deepcopy(item.get("value"))
        for item in authority.get("protected_parameters", [])
        if isinstance(item, dict) and item.get("id")
    }


def _face_frame() -> dict[str, Any]:
    return {
        "frame_id": "upright_outer_negative_y_face",
        "origin_mm": [0, -5, 6],
        "x_direction": [1, 0, 0],
        "y_direction": [0, 0, 1],
        "normal": [0, -1, 0],
        "depth_direction": [0, 1, 0],
    }


def _slot_spec() -> dict[str, Any]:
    return {
        "profile_type": "rounded_end_capsule",
        "overall_length_mm": 18,
        "width_mm": 5,
        "end_radius_mm": 2.5,
        "end_radius_formula": "width_mm / 2",
        "owning_face": "outer_negative_y_face",
        "local_coordinate_frame": _face_frame(),
        "center_local_mm": [10, 14],
        "center_global_mm": [10, -5, 20],
        "orientation_degrees": 0,
        "depth_mode": "blind",
        "depth_mm": 3,
        "depth_direction": [0, 1, 0],
    }


def _hole_change(authority: dict[str, Any], feature_id: str, parameter_id: str) -> dict[str, Any]:
    prior = next(
        item for item in authority["prior_geometry"]["holes"] if item["feature_id"] == feature_id
    )
    return {
        "changed_feature_id": feature_id,
        "parameter_id": parameter_id,
        "prior_feature_dimensions": {"diameter_mm": prior["diameter_mm"], "depth_mode": prior["depth_mode"]},
        "requested_feature_dimensions": {"diameter_mm": 6, "depth_mode": prior["depth_mode"]},
        "owning_face": prior["owning_face"],
        "local_coordinate_frame": "upright_outer_negative_y_face",
        "feature_center_local_mm": list(prior["location_mm"][:2]),
        "feature_axis": list(prior["axis"]),
        "depth_direction": [0, 1, 0],
        "depth_mode": "through",
        "prior_output_id": OUTPUT_ID,
    }


def _revision_facts(
    authority: dict[str, Any],
    *,
    changed_features: list[dict[str, Any]],
    protected_feature_ids: list[str],
) -> dict[str, Any]:
    return {
        "output_id": OUTPUT_ID,
        "prior_output_id": OUTPUT_ID,
        "prior_authority_id": authority["authority_id"],
        "prior_source_reference": copy.deepcopy(authority["prior_source_reference"]),
        "prior_geometry": copy.deepcopy(authority["prior_geometry"]),
        "protected_feature_ids": protected_feature_ids,
        "protected_dimensions": _protected_dimensions(authority),
        "changed_features": changed_features,
    }


def _slot_change(authority: dict[str, Any]) -> dict[str, Any]:
    spec = _slot_spec()
    return {
        "changed_feature_id": "cable_retention_slot",
        "prior_feature_dimensions": {"count": 0},
        "requested_feature_dimensions": copy.deepcopy(spec),
        "owning_face": spec["owning_face"],
        "local_coordinate_frame": copy.deepcopy(spec["local_coordinate_frame"]),
        "feature_center_local_mm": list(spec["center_local_mm"]),
        "feature_axis": [0, 1, 0],
        "depth_direction": list(spec["depth_direction"]),
        "depth_mode": spec["depth_mode"],
        "prior_output_id": OUTPUT_ID,
    }


def _assert_delta_complete(delta: dict[str, Any]) -> None:
    required = {
        "changed_feature_id",
        "prior_feature_dimensions",
        "requested_feature_dimensions",
        "owning_face",
        "local_coordinate_frame",
        "feature_center_local_mm",
        "feature_axis",
        "depth_direction",
        "depth_mode",
        "prior_output_id",
    }
    missing = sorted(required - set(delta))
    if missing:
        raise ValueError(f"revision delta is incomplete: {missing}")
    if delta["prior_output_id"] != OUTPUT_ID:
        raise ValueError("revision delta output identity is not mounting_bracket")
    requested = delta["requested_feature_dimensions"]
    if requested.get("profile_type") == "rounded_end_capsule":
        slot_required = {"overall_length_mm", "width_mm", "end_radius_mm", "orientation_degrees", "depth_mm"}
        if not slot_required.issubset(requested):
            raise ValueError("capsule slot specification is incomplete")
        if requested["end_radius_mm"] != requested["width_mm"] / 2:
            raise ValueError("capsule end radius is not derived from width")


def build_final_tasks() -> tuple[ProviderStudyTask, ...]:
    authority = load_revision_authority()
    prior = authority_source_expression()
    protected_ids = [str(item["feature_id"]) for item in authority["protected_features"]]
    left_change = _hole_change(authority, "upright_hole_left", "upright_hole_left_diameter_after_mm")
    right_change = _hole_change(authority, "upright_hole_right", "upright_hole_right_diameter_after_mm")
    slot_change = _slot_change(authority)
    task_deltas = [
        {
            "changed_features": [left_change],
            **_revision_facts(authority, changed_features=[left_change], protected_feature_ids=[item for item in protected_ids if item != "upright_hole_left"]),
        },
        {
            "changed_features": [slot_change],
            **_revision_facts(authority, changed_features=[slot_change], protected_feature_ids=protected_ids),
        },
        {
            "changed_features": [right_change, slot_change],
            **_revision_facts(authority, changed_features=[right_change, slot_change], protected_feature_ids=[item for item in protected_ids if item != "upright_hole_right"]),
        },
    ]
    for delta in task_deltas:
        for change in delta["changed_features"]:
            _assert_delta_complete(change)
        if delta["prior_output_id"] != OUTPUT_ID:
            raise ValueError("task delta has stale output identity")
    return (
        _make_task(
            1,
            "Final revision: enlarge left upright hole",
            "Starting from the certified mounting_bracket prior output, change only upright_hole_left from 5 mm to 6 mm and preserve every protected feature and dimension.",
            {"revision_delta": task_deltas[0]},
            _parameters([("upright_hole_left_diameter_after_mm", 6)]),
            ("revision", "raw_cadquery"),
            (),
            body_initializer=f"body = {prior}",
            authority=authority,
            revision_delta=task_deltas[0],
            output_id=OUTPUT_ID,
            study_id=FINAL_STUDY_ID,
        ),
        _make_task(
            2,
            "Final revision: rounded-end blind capsule slot",
            "Starting from the certified mounting_bracket prior output, add only the fully specified rounded-end capsule slot on the upright outer face and preserve every prior feature.",
            {"revision_delta": task_deltas[1]},
            _parameters([
                ("slot_length_mm", 18),
                ("slot_width_mm", 5),
                ("slot_depth_mm", 3),
                ("slot_center_x_mm", 10),
                ("slot_center_local_y_mm", 14),
                ("slot_orientation_degrees", 0),
            ]),
            ("revision", "raw_cadquery"),
            (),
            body_initializer=f"body = {prior}",
            authority=authority,
            revision_delta=task_deltas[1],
            output_id=OUTPUT_ID,
            study_id=FINAL_STUDY_ID,
        ),
        _make_task(
            3,
            "Final revision: right upright hole and capsule slot",
            "Starting from the certified mounting_bracket prior output, change only upright_hole_right from 5 mm to 6 mm and add the same fully specified rounded-end capsule slot.",
            {"revision_delta": task_deltas[2]},
            _parameters([
                ("upright_hole_right_diameter_after_mm", 6),
                ("slot_length_mm", 18),
                ("slot_width_mm", 5),
                ("slot_depth_mm", 3),
                ("slot_center_x_mm", 10),
                ("slot_center_local_y_mm", 14),
                ("slot_orientation_degrees", 0),
            ]),
            ("revision", "raw_cadquery"),
            (),
            body_initializer=f"body = {prior}",
            authority=authority,
            revision_delta=task_deltas[2],
            output_id=OUTPUT_ID,
            study_id=FINAL_STUDY_ID,
        ),
    )


def task_parameter_values(task: ProviderStudyTask) -> dict[str, Any]:
    return {
        str(item["id"]): item.get("value", item.get("default"))
        for item in (task.request.design_plan or {}).get("parameters", []) or []
        if isinstance(item, dict) and item.get("id") is not None
    }


def requested_outputs(task: ProviderStudyTask) -> list[dict[str, Any]]:
    return [{
        "output_id": OUTPUT_ID,
        "required": True,
        "expected_solid_count": 1,
        "allow_disconnected_solids": False,
    }]


def revision_delta_report(task: ProviderStudyTask) -> dict[str, Any]:
    facts = task.semantic_facts
    delta = facts["revision_delta"]
    return {
        "task_id": task.task_id,
        "output_id": task.output_ids[0],
        "prior_output_id": delta["prior_output_id"],
        "prior_authority_id": delta["prior_authority_id"],
        "changed_features": copy.deepcopy(delta["changed_features"]),
        "protected_feature_ids": list(delta["protected_feature_ids"]),
        "protected_dimensions": copy.deepcopy(delta["protected_dimensions"]),
        "prior_source_reference": copy.deepcopy(delta["prior_source_reference"]),
        "complete": all(
            change.get("prior_output_id") == OUTPUT_ID
            and change.get("owning_face")
            and change.get("local_coordinate_frame")
            and change.get("feature_center_local_mm")
            and change.get("feature_axis")
            and change.get("depth_direction")
            and change.get("depth_mode")
            for change in delta["changed_features"]
        ),
    }


def build_product_source(
    task: ProviderStudyTask,
    statements: Iterable[str],
    *,
    body_initializer: str | None = None,
) -> str:
    lines = [
        "import cadquery as cq",
        "from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product",
        "",
        "PARAMETERS = [",
    ]
    for parameter in (task.request.design_plan or {}).get("parameters", []) or []:
        lines.append(
            "    ParameterSpec(" 
            f"id={str(parameter['id'])!r}, label={str(parameter['id'])!r}, type='float', "
            f"default={parameter.get('value', parameter.get('default', 0))!r}, unit='mm'),"
        )
    initializer = body_initializer if body_initializer is not None else task.body_initializer
    lines.extend(["]", "", "def build(params):"])
    lines.extend(f"    {line}" for line in initializer.splitlines())
    lines.extend(f"    {statement}" for statement in statements)
    lines.extend([
        "    return Product(",
        "        parameters=PARAMETERS,",
        "        outputs=[",
        f"            PrintableOutput(output_id={OUTPUT_ID!r}, component_id={OUTPUT_ID!r}, label={task.title!r}, model=body, required=True, expected_solid_count=1, allow_disconnected_solids=False),",
        "        ],",
        "    )",
    ])
    return "\n".join(lines) + "\n"


def known_good_statements(control: str) -> list[str]:
    hole = {
        "left": 'body = body.faces("<Y").workplane().pushPoints([(12, 13)]).hole(params["upright_hole_left_diameter_after_mm"])',
        "right": 'body = body.faces("<Y").workplane().pushPoints([(34, 31)]).hole(params["upright_hole_right_diameter_after_mm"])',
    }
    slot = [
        'body = body.faces("<Y").workplane().center(params["slot_center_x_mm"], params["slot_center_local_y_mm"]).slot2D(params["slot_length_mm"], params["slot_width_mm"], params["slot_orientation_degrees"]).cutBlind(-params["slot_depth_mm"])',
    ]
    if control == "left_hole":
        return []
    if control == "slot":
        return slot
    if control == "right_hole_and_slot":
        return slot
    raise ValueError(f"unknown control: {control}")


def known_good_body_initializer(control: str) -> str:
    """Return a deterministic control initializer with the requested hole size.

    Enlarging a hole after the prior body has already been unioned is not a
    receiver-stable operation: the selected face can be a different
    face-derived workplane and leave the original hole in place.  These
    synthetic controls therefore rebuild only the authoritative feature
    construction with the requested diameter, while the provider fixture
    remains the frozen prior-body initializer plus revision statements.
    """
    left_diameter = 6 if control == "left_hole" else 5
    right_diameter = 6 if control == "right_hole_and_slot" else 5
    return "\n".join([
        'base = cq.Workplane("XY").box(80, 50, 6, centered=(False, False, False))',
        'base = base.faces(">Z").workplane().pushPoints([(15, 15), (65, 35)]).hole(6)',
        'upright = cq.Workplane("XZ").box(50, 45, 6, centered=(False, False, False)).translate((0, 1, 6))',
        f'upright = upright.faces("<Y").workplane().pushPoints([(12, 13)]).hole({left_diameter})',
        f'upright = upright.faces("<Y").workplane().pushPoints([(34, 31)]).hole({right_diameter})',
        'body = base.union(upright)',
        'boss = cq.Workplane("XY").box(10, 8, 2, centered=(True, True, False)).translate((20, 20, 6))',
        'rib = cq.Workplane("YZ").polyline([(0, 0), (10, 0), (0, 10)]).close().extrude(5).translate((20, 0, 0))',
        'body = body.union(boss).union(rib)',
    ])


def expected_shape_for_control(control: str) -> Any:
    namespace: dict[str, Any] = {"cq": cq}
    exec(known_good_body_initializer(control), namespace)
    body = namespace["body"]
    if control == "slot":
        return body.faces("<Y").workplane().center(10, 14).slot2D(18, 5, 0).cutBlind(-3)
    if control == "right_hole_and_slot":
        return body.faces("<Y").workplane().center(10, 14).slot2D(18, 5, 0).cutBlind(-3)
    if control == "left_hole":
        return body
    raise ValueError(f"unknown control: {control}")


def expected_prior_shape() -> Any:
    namespace: dict[str, Any] = {"cq": cq}
    exec("body = " + authority_source_expression(), namespace)
    return namespace["body"]


def _round(value: float, digits: int = 6) -> float:
    return round(float(value), digits)


def _bbox(face_or_shape: Any) -> dict[str, float]:
    box = face_or_shape.BoundingBox()
    return {
        "xmin": _round(box.xmin),
        "xmax": _round(box.xmax),
        "ymin": _round(box.ymin),
        "ymax": _round(box.ymax),
        "zmin": _round(box.zmin),
        "zmax": _round(box.zmax),
        "size_x": _round(box.xlen),
        "size_y": _round(box.ylen),
        "size_z": _round(box.zlen),
    }


def _close(left: float, right: float, tolerance: float = 1e-4) -> bool:
    return abs(float(left) - float(right)) <= tolerance


def _axis_tuple(direction: Any) -> list[float]:
    return [_round(direction.X()), _round(direction.Y()), _round(direction.Z())]


def cylinder_signatures(shape: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for face in shape.faces().vals():
        if face.geomType() != "CYLINDER":
            continue
        cylinder = face._geomAdaptor().Cylinder()
        location = cylinder.Axis().Location()
        result.append({
            "radius_mm": _round(cylinder.Radius()),
            "center_mm": [_round(location.X()), _round(location.Y()), _round(location.Z())],
            "axis": _axis_tuple(cylinder.Axis().Direction()),
            "bbox": _bbox(face),
        })
    return result


def _has_cylinder(
    cylinders: list[dict[str, Any]],
    *,
    radius: float,
    center: list[float],
    axis: list[float],
) -> bool:
    return any(
        _close(item["radius_mm"], radius)
        and all(_close(item["center_mm"][index], center[index]) for index in range(3))
        and all(_close(abs(item["axis"][index]), abs(axis[index])) for index in range(3))
        for item in cylinders
    )


def _has_plane(face_shape: Any, *, size: tuple[float, float, float], anchor: tuple[float, float, float]) -> bool:
    box = _bbox(face_shape)
    return (
        all(_close(box[key], value) for key, value in zip(("size_x", "size_y", "size_z"), size))
        and all(_close(box[key], value) for key, value in zip(("xmin", "ymin", "zmin"), anchor))
    )


def _shape_difference_volume(actual: Any, expected: Any) -> float:
    return abs(float(actual.cut(expected).val().Volume())) + abs(float(expected.cut(actual).val().Volume()))


def verify_shape(
    step_path: Path | None,
    expected: Any,
    *,
    authority: dict[str, Any],
    control: str,
) -> dict[str, Any]:
    if step_path is None or not step_path.is_file():
        return {"passed": False, "failures": ["missing_step_artifact"]}
    actual = cq.importers.importStep(str(step_path))
    actual_shape = actual.val()
    expected_shape = expected.val()
    actual_box = _bbox(actual_shape)
    expected_box = _bbox(expected_shape)
    cylinders = cylinder_signatures(actual)
    failures: list[str] = []
    if len(actual.solids().vals()) != 1:
        failures.append("solid_count_not_one")
    if _shape_difference_volume(actual, expected) > 1e-4:
        failures.append("shape_differs_from_certified_expected_geometry")
    if any(not _close(actual_box[key], expected_box[key]) for key in ("size_x", "size_y", "size_z", "xmin", "xmax", "ymin", "ymax", "zmin", "zmax")):
        failures.append("bounding_box_mismatch")

    faces = actual.faces().vals()
    base_dimensions = any(_has_plane(face, size=(80, 50, 0), anchor=(0, 0, 6)) for face in faces)
    upright_dimensions = any(_has_plane(face, size=(50, 0, 45), anchor=(0, -5, 6)) for face in faces)
    boss_presence = any(_has_plane(face, size=(10, 8, 0), anchor=(15, 16, 8)) for face in faces)
    rib_presence = any(
        _close(_bbox(face)["size_x"], 2.828427, 1e-3)
        and _close(_bbox(face)["size_y"], 2, 1e-3)
        and _close(_bbox(face)["size_z"], 0, 1e-3)
        for face in faces
    )
    if not base_dimensions:
        failures.append("base_dimensions_mismatch")
    if not upright_dimensions:
        failures.append("upright_dimensions_mismatch")
    if not boss_presence:
        failures.append("rear_boss_missing_or_mismatched")
    if not rib_presence:
        failures.append("reinforcement_rib_missing_or_mismatched")

    authority_holes = authority["prior_geometry"]["holes"]
    expected_hole_diameters = {
        "upright_hole_left": 6 if control in {"left_hole"} else 5,
        "upright_hole_right": 6 if control in {"right_hole_and_slot"} else 5,
        "mounting_hole_front": 6,
        "mounting_hole_rear": 6,
    }
    hole_checks: list[dict[str, Any]] = []
    for hole in authority_holes:
        feature_id = str(hole["feature_id"])
        local = hole["location_mm"]
        if feature_id.startswith("upright_"):
            center = [float(local[0]), -5.0, float(local[1])]
            axis = [0, 1, 0]
        else:
            center = [float(local[0]), float(local[1]), 6.0]
            axis = [0, 0, -1]
        passed = _has_cylinder(
            cylinders,
            radius=float(expected_hole_diameters[feature_id]) / 2,
            center=center,
            axis=axis,
        )
        hole_checks.append({
            "feature_id": feature_id,
            "expected_diameter_mm": expected_hole_diameters[feature_id],
            "expected_local_location_mm": list(local),
            "expected_axis": axis,
            "expected_owning_face": hole["owning_face"],
            "passed": passed,
        })
        if not passed:
            failures.append(f"hole_mismatch:{feature_id}")

    slot_check: dict[str, Any] = {"required": control in {"slot", "right_hole_and_slot"}, "passed": True}
    if slot_check["required"]:
        slot_centers = [[3.5, -5, 20], [16.5, -5, 20]]
        slot_check.update({
            "profile_type": "rounded_end_capsule",
            "overall_length_mm": 18,
            "width_mm": 5,
            "end_radius_mm": 2.5,
            "center_global_mm": [10, -5, 20],
            "depth_mm": 3,
            "depth_direction": [0, 1, 0],
            "passed": all(_has_cylinder(cylinders, radius=2.5, center=center, axis=[0, 1, 0]) for center in slot_centers),
        })
        if not slot_check["passed"]:
            failures.append("rounded_capsule_slot_mismatch")

    return {
        "passed": not failures,
        "failures": sorted(set(failures)),
        "output_id": OUTPUT_ID,
        "solid_count": len(actual.solids().vals()),
        "actual_bbox": actual_box,
        "expected_bbox": expected_box,
        "volume_mm3": _round(actual_shape.Volume()),
        "expected_volume_mm3": _round(expected_shape.Volume()),
        "symmetric_difference_volume_mm3": _round(_shape_difference_volume(actual, expected)),
        "base_dimensions": {"length": 80, "width": 50, "height": 6, "passed": base_dimensions},
        "upright_dimensions": {"length": 50, "width": 45, "thickness": 6, "angle_degrees": 90, "passed": upright_dimensions},
        "rear_boss": {"center_mm": [20, 20, 7], "dimensions_mm": {"length": 10, "width": 8, "height": 2}, "passed": boss_presence},
        "reinforcement_rib": {"count": 1, "passed": rib_presence},
        "holes": hole_checks,
        "slot": slot_check,
        "protected_features_preserved": not failures,
    }


def verify_worker_output(result: Any, expected: Any, *, authority: dict[str, Any], control: str) -> dict[str, Any]:
    output = next((item for item in result.outputs if item.output_id == OUTPUT_ID), None)
    if output is None:
        return {"passed": False, "failures": ["output_identity_missing"], "output_id": OUTPUT_ID}
    verification = verify_shape(output.step_path, expected, authority=authority, control=control)
    verification["output_identity"] = output.output_id
    verification["worker_success"] = bool(result.success and output.success)
    verification["passed"] = bool(verification["passed"] and result.success and output.success and output.output_id == OUTPUT_ID)
    return verification


__all__ = [
    "AUTHORITY_PATH",
    "FINAL_STUDY_ID",
    "OUTPUT_ID",
    "PROMPT_VERSION",
    "RESULT_SYMBOL",
    "authority_source_expression",
    "build_final_tasks",
    "build_product_source",
    "canonical_hash",
    "expected_prior_shape",
    "expected_shape_for_control",
    "file_hash",
    "known_good_statements",
    "known_good_body_initializer",
    "requested_outputs",
    "revision_delta_report",
    "task_parameter_values",
    "verify_shape",
    "verify_worker_output",
]
