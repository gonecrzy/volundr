"""Source-assembly contract for the narrow capsule-slot helper."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from volundr_cad.capsule_slot import (
    CapsuleSlotContractError,
    CapsuleSlotFrame,
    validate_capsule_slot_values,
)


CAPSULE_SLOT_SOURCE_VERSION = "capsule-slot-source-v1"


def _frame_from_facts(value: Any) -> CapsuleSlotFrame:
    if not isinstance(value, Mapping):
        raise CapsuleSlotContractError("local_coordinate_frame must be an object")
    required = {"origin_mm", "x_direction", "y_direction", "normal", "depth_direction"}
    missing = sorted(required - set(value))
    if missing:
        raise CapsuleSlotContractError(f"local_coordinate_frame missing: {', '.join(missing)}")
    return CapsuleSlotFrame(
        origin_mm=tuple(value["origin_mm"]),
        x_direction=tuple(value["x_direction"]),
        y_direction=tuple(value["y_direction"]),
        normal=tuple(value["normal"]),
        depth_direction=tuple(value["depth_direction"]),
    )


def normalize_capsule_slot_facts(change: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(change, Mapping):
        raise CapsuleSlotContractError("capsule slot change must be an object")
    requested = change.get("requested_feature_dimensions")
    if not isinstance(requested, Mapping):
        raise CapsuleSlotContractError("requested_feature_dimensions is required")
    if requested.get("profile_type") != "rounded_end_capsule":
        raise CapsuleSlotContractError("profile_type must be rounded_end_capsule")
    frame = _frame_from_facts(change.get("local_coordinate_frame"))
    required_requested = {
        "overall_length_mm",
        "width_mm",
        "end_radius_mm",
        "orientation_degrees",
        "depth_mode",
        "depth_mm",
        "depth_direction",
    }
    missing = sorted(required_requested - set(requested))
    if missing:
        raise CapsuleSlotContractError(f"requested capsule dimensions missing: {', '.join(missing)}")
    center = change.get("feature_center_local_mm")
    if center is None:
        raise CapsuleSlotContractError("feature_center_local_mm is required")
    facts = {
        "frame": frame,
        "center_local_mm": tuple(center),
        "overall_length_mm": requested["overall_length_mm"],
        "width_mm": requested["width_mm"],
        "end_radius_mm": requested["end_radius_mm"],
        "orientation_degrees": requested["orientation_degrees"],
        "depth_mode": requested["depth_mode"],
        "blind_depth_mm": requested["depth_mm"],
        "depth_direction": tuple(requested["depth_direction"]),
    }
    validate_capsule_slot_values(facts)
    return facts


def validate_capsule_slot_facts(change: Mapping[str, Any]) -> dict[str, Any]:
    return normalize_capsule_slot_facts(change)


def build_capsule_slot_helper_statement(
    change: Mapping[str, Any],
    *,
    parameter_ids: Mapping[str, str],
    target_symbol: str = "body",
) -> str:
    facts = normalize_capsule_slot_facts(change)
    expected_parameter_names = {"length", "width", "center_x", "center_y", "orientation", "depth"}
    missing = sorted(expected_parameter_names - set(parameter_ids))
    if missing:
        raise CapsuleSlotContractError(f"capsule source parameter mapping missing: {', '.join(missing)}")
    if target_symbol != "body":
        raise CapsuleSlotContractError("capsule helper currently requires the canonical body target")
    frame = facts["frame"]
    frame_text = (
        "CapsuleSlotFrame("
        f"origin_mm={tuple(frame.origin_mm)!r}, "
        f"x_direction={tuple(frame.x_direction)!r}, "
        f"y_direction={tuple(frame.y_direction)!r}, "
        f"normal={tuple(frame.normal)!r}, "
        f"depth_direction={tuple(frame.depth_direction)!r})"
    )
    return (
        f"body = cut_capsule_slot_v1(body, frame={frame_text}, "
        f"center_local_mm=(params[{parameter_ids['center_x']!r}], params[{parameter_ids['center_y']!r}]), "
        f"overall_length_mm=params[{parameter_ids['length']!r}], "
        f"width_mm=params[{parameter_ids['width']!r}], "
        f"end_radius_mm=params[{parameter_ids['width']!r}] / 2, "
        f"orientation_degrees=params[{parameter_ids['orientation']!r}], "
        f"depth_mode={facts['depth_mode']!r}, "
        f"blind_depth_mm=params[{parameter_ids['depth']!r}], "
        f"depth_direction={tuple(facts['depth_direction'])!r})"
    )


__all__ = [
    "CAPSULE_SLOT_SOURCE_VERSION",
    "build_capsule_slot_helper_statement",
    "normalize_capsule_slot_facts",
    "validate_capsule_slot_facts",
]
