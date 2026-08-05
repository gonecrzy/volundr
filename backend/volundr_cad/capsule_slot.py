"""Pinned, deterministic rounded-end capsule slot geometry."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import cadquery as cq


CAPSULE_SLOT_HELPER_VERSION = "cut_capsule_slot_v1"
TARGET_CADQUERY_VERSION = "2.8.0"
_VECTOR_TOLERANCE = 1e-7
_CUTTER_OVERLAP_MM = 1e-6


class CapsuleSlotContractError(ValueError):
    """Raised when an authoritative capsule-slot contract is incomplete."""


@dataclass(frozen=True)
class CapsuleSlotFrame:
    origin_mm: tuple[float, float, float]
    x_direction: tuple[float, float, float]
    y_direction: tuple[float, float, float]
    normal: tuple[float, float, float]
    depth_direction: tuple[float, float, float]


def _vector(value: Sequence[float], name: str, *, length: int = 3) -> tuple[float, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != length:
        raise CapsuleSlotContractError(f"{name} must contain exactly {length} numeric values")
    try:
        result = tuple(float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise CapsuleSlotContractError(f"{name} must contain numeric values") from exc
    if not all(math.isfinite(item) for item in result):
        raise CapsuleSlotContractError(f"{name} must contain finite values")
    return result


def _norm(vector: Sequence[float]) -> float:
    return math.sqrt(sum(float(value) ** 2 for value in vector))


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(float(a) * float(b) for a, b in zip(left, right))


def _cross(left: Sequence[float], right: Sequence[float]) -> tuple[float, float, float]:
    return (
        float(left[1]) * float(right[2]) - float(left[2]) * float(right[1]),
        float(left[2]) * float(right[0]) - float(left[0]) * float(right[2]),
        float(left[0]) * float(right[1]) - float(left[1]) * float(right[0]),
    )


def _same_vector(left: Sequence[float], right: Sequence[float], tolerance: float = _VECTOR_TOLERANCE) -> bool:
    return all(abs(float(a) - float(b)) <= tolerance for a, b in zip(left, right))


def _validate_frame(frame: CapsuleSlotFrame) -> CapsuleSlotFrame:
    if not isinstance(frame, CapsuleSlotFrame):
        raise CapsuleSlotContractError("frame must be a CapsuleSlotFrame")
    origin = _vector(frame.origin_mm, "frame.origin_mm")
    x_direction = _vector(frame.x_direction, "frame.x_direction")
    y_direction = _vector(frame.y_direction, "frame.y_direction")
    normal = _vector(frame.normal, "frame.normal")
    depth_direction = _vector(frame.depth_direction, "frame.depth_direction")
    for name, vector in (
        ("frame.x_direction", x_direction),
        ("frame.y_direction", y_direction),
        ("frame.normal", normal),
        ("frame.depth_direction", depth_direction),
    ):
        if abs(_norm(vector) - 1.0) > _VECTOR_TOLERANCE:
            raise CapsuleSlotContractError(f"{name} must be a unit vector")
    if abs(_dot(x_direction, y_direction)) > _VECTOR_TOLERANCE:
        raise CapsuleSlotContractError("frame axes must be orthogonal")
    if abs(_dot(x_direction, normal)) > _VECTOR_TOLERANCE or abs(_dot(y_direction, normal)) > _VECTOR_TOLERANCE:
        raise CapsuleSlotContractError("frame axes must be orthogonal to frame.normal")
    if not _same_vector(_cross(normal, x_direction), y_direction):
        raise CapsuleSlotContractError("frame.y_direction does not match frame.normal cross frame.x_direction")
    if abs(abs(_dot(depth_direction, normal)) - 1.0) > _VECTOR_TOLERANCE:
        raise CapsuleSlotContractError("depth_direction must be parallel or antiparallel to frame.normal")
    return CapsuleSlotFrame(origin, x_direction, y_direction, normal, depth_direction)


def _validate_values(
    *,
    frame: CapsuleSlotFrame,
    center_local_mm: Sequence[float],
    overall_length_mm: float,
    width_mm: float,
    end_radius_mm: float,
    orientation_degrees: float,
    depth_mode: str,
    blind_depth_mm: float,
    depth_direction: Sequence[float],
) -> tuple[CapsuleSlotFrame, tuple[float, float], tuple[float, float, float], tuple[float, float, float, float, float]]:
    checked_frame = _validate_frame(frame)
    center = _vector(center_local_mm, "center_local_mm", length=2)
    direction = _vector(depth_direction, "depth_direction")
    numeric = {
        "overall_length_mm": overall_length_mm,
        "width_mm": width_mm,
        "end_radius_mm": end_radius_mm,
        "orientation_degrees": orientation_degrees,
        "blind_depth_mm": blind_depth_mm,
    }
    converted: dict[str, float] = {}
    for name, value in numeric.items():
        try:
            converted[name] = float(value)
        except (TypeError, ValueError) as exc:
            raise CapsuleSlotContractError(f"{name} must be numeric") from exc
        if not math.isfinite(converted[name]):
            raise CapsuleSlotContractError(f"{name} must be finite")
    if converted["overall_length_mm"] < converted["width_mm"]:
        raise CapsuleSlotContractError("overall_length_mm must be at least width_mm")
    if converted["width_mm"] <= 0 or converted["end_radius_mm"] <= 0:
        raise CapsuleSlotContractError("width_mm and end radius must be positive")
    if abs(converted["end_radius_mm"] - converted["width_mm"] / 2.0) > _VECTOR_TOLERANCE:
        raise CapsuleSlotContractError("end radius must equal width_mm / 2")
    if depth_mode != "blind":
        raise CapsuleSlotContractError("depth_mode must be blind")
    if converted["blind_depth_mm"] <= 0:
        raise CapsuleSlotContractError("blind_depth_mm must be positive")
    if not _same_vector(direction, checked_frame.depth_direction):
        raise CapsuleSlotContractError("depth_direction must match frame.depth_direction")
    return (
        checked_frame,
        (center[0], center[1]),
        (direction[0], direction[1], direction[2]),
        (converted["overall_length_mm"], converted["width_mm"], converted["end_radius_mm"], converted["orientation_degrees"], converted["blind_depth_mm"]),
    )


def cut_capsule_slot_v1(
    target: cq.Workplane,
    *,
    frame: CapsuleSlotFrame,
    center_local_mm: Sequence[float],
    overall_length_mm: float,
    width_mm: float,
    end_radius_mm: float,
    orientation_degrees: float,
    depth_mode: str,
    blind_depth_mm: float,
    depth_direction: Sequence[float],
) -> cq.Workplane:
    """Cut one exact rounded-end capsule slot from a CadQuery Workplane.

    CadQuery 2.8's ``slot2D(length, diameter, angle)`` length is its
    end-to-end length, so the authoritative overall length is passed through
    a compiler-owned conversion point without substituting a straight-segment
    length.  The cutter starts just outside the owning face and ends exactly
    at the authoritative blind depth.
    """

    if not isinstance(target, cq.Workplane):
        raise TypeError("target must be a CadQuery Workplane")
    checked_frame, center, checked_direction, values = _validate_values(
        frame=frame,
        center_local_mm=center_local_mm,
        overall_length_mm=overall_length_mm,
        width_mm=width_mm,
        end_radius_mm=end_radius_mm,
        orientation_degrees=orientation_degrees,
        depth_mode=depth_mode,
        blind_depth_mm=blind_depth_mm,
        depth_direction=depth_direction,
    )
    length, width, radius, orientation, depth = values
    center_world = tuple(
        checked_frame.origin_mm[index]
        + center[0] * checked_frame.x_direction[index]
        + center[1] * checked_frame.y_direction[index]
        for index in range(3)
    )
    cutter_origin = tuple(
        center_world[index] - checked_direction[index] * _CUTTER_OVERLAP_MM
        for index in range(3)
    )
    plane = cq.Plane(
        origin=cq.Vector(*cutter_origin),
        xDir=cq.Vector(*checked_frame.x_direction),
        normal=cq.Vector(*checked_frame.normal),
    )
    workplane = cq.Workplane(plane)
    signed_depth = (depth + _CUTTER_OVERLAP_MM) * _dot(checked_direction, checked_frame.normal)
    cadquery_slot_length = length
    cutter = workplane.slot2D(cadquery_slot_length, width, angle=orientation).extrude(signed_depth)
    result = target.cut(cutter)
    if not isinstance(result, cq.Workplane):
        raise TypeError("capsule slot cut did not return a CadQuery Workplane")
    if not result.solids().vals():
        raise CapsuleSlotContractError("capsule slot cut produced no solid")
    return result


def validate_capsule_slot_values(facts: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a normalized source-assembly capsule contract."""

    required = {
        "frame",
        "center_local_mm",
        "overall_length_mm",
        "width_mm",
        "end_radius_mm",
        "orientation_degrees",
        "depth_mode",
        "blind_depth_mm",
        "depth_direction",
    }
    missing = sorted(required - set(facts))
    if missing:
        raise CapsuleSlotContractError(f"capsule facts missing: {', '.join(missing)}")
    frame_data = facts["frame"]
    if not isinstance(frame_data, CapsuleSlotFrame):
        raise CapsuleSlotContractError("capsule facts frame must be a CapsuleSlotFrame")
    _validate_values(
        frame=frame_data,
        center_local_mm=facts["center_local_mm"],
        overall_length_mm=facts["overall_length_mm"],
        width_mm=facts["width_mm"],
        end_radius_mm=facts["end_radius_mm"],
        orientation_degrees=facts["orientation_degrees"],
        depth_mode=facts["depth_mode"],
        blind_depth_mm=facts["blind_depth_mm"],
        depth_direction=facts["depth_direction"],
    )
    return dict(facts)


__all__ = [
    "CAPSULE_SLOT_HELPER_VERSION",
    "TARGET_CADQUERY_VERSION",
    "CapsuleSlotContractError",
    "CapsuleSlotFrame",
    "cut_capsule_slot_v1",
    "validate_capsule_slot_values",
]
