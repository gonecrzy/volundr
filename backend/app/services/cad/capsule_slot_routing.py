"""Fail-closed source routing for an authoritative rounded capsule slot."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.services.cad.capsule_slot_source import build_capsule_slot_helper_statement
from volundr_cad.capsule_slot import CapsuleSlotContractError, validate_capsule_slot_values


CAPSULE_SLOT_ROUTING_VERSION = "capsule-slot-routing-v1"
_PARAMETER_KEYS = ("length", "width", "center_x", "center_y", "orientation", "depth")


def _capsule_change(spec: Mapping[str, Any]) -> dict[str, Any]:
    requested = spec.get("requested_feature_dimensions")
    if not isinstance(requested, Mapping):
        raise CapsuleSlotContractError("capsule_slot.requested_feature_dimensions is required")
    frame = spec.get("local_coordinate_frame")
    if not isinstance(frame, Mapping):
        raise CapsuleSlotContractError("capsule_slot.local_coordinate_frame is required")
    center = spec.get("feature_center_local_mm")
    if center is None:
        raise CapsuleSlotContractError("capsule_slot.feature_center_local_mm is required")
    return {
        "requested_feature_dimensions": dict(requested),
        "local_coordinate_frame": dict(frame),
        "feature_center_local_mm": list(center),
    }


def build_capsule_slot_feature_source(
    plan: Mapping[str, Any],
    capsule_slot: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a compiler-owned feature body only after Plan traceability passes."""

    if not isinstance(plan, Mapping) or not isinstance(capsule_slot, Mapping):
        raise CapsuleSlotContractError("capsule helper routing requires Plan and capsule facts")
    feature_id = str(capsule_slot.get("feature_id") or "").strip()
    component_id = str(capsule_slot.get("component_id") or "").strip()
    output_id = str(capsule_slot.get("target_output_id") or "").strip()
    if not feature_id or not component_id or not output_id:
        raise CapsuleSlotContractError("capsule helper routing requires feature, component, and output identities")

    feature_matches = [
        item
        for item in plan.get("features", []) or []
        if isinstance(item, Mapping) and str(item.get("id") or "") == feature_id
    ]
    if len(feature_matches) != 1:
        raise CapsuleSlotContractError("Plan must contain exactly one capsule feature with the authoritative identity")
    feature = feature_matches[0]
    if str(feature.get("component_id") or "") != component_id:
        raise CapsuleSlotContractError("capsule feature component ownership does not match authoritative facts")
    if str(feature.get("profile_type") or "") != "rounded_end_capsule":
        raise CapsuleSlotContractError("Plan capsule feature must preserve profile_type rounded_end_capsule")

    output_matches = [
        item
        for item in plan.get("printable_outputs", []) or []
        if isinstance(item, Mapping)
        and str(item.get("id") or item.get("output_id") or "") == output_id
        and component_id in [str(value) for value in item.get("component_ids", []) or []]
    ]
    if len(output_matches) != 1:
        raise CapsuleSlotContractError("capsule feature must map to exactly one authoritative output")

    parameter_ids = capsule_slot.get("parameter_ids")
    if not isinstance(parameter_ids, Mapping) or not all(parameter_ids.get(key) for key in _PARAMETER_KEYS):
        raise CapsuleSlotContractError("capsule helper routing requires all parameter IDs")
    plan_parameter_ids = {
        str(item.get("id"))
        for item in plan.get("parameters", []) or []
        if isinstance(item, Mapping) and item.get("id")
    }
    unknown = sorted({str(parameter_ids[key]) for key in _PARAMETER_KEYS} - plan_parameter_ids)
    if unknown:
        raise CapsuleSlotContractError("capsule helper parameter IDs are absent from Plan: " + ", ".join(unknown))

    change = _capsule_change(capsule_slot)
    statement = build_capsule_slot_helper_statement(
        change,
        parameter_ids={key: str(parameter_ids[key]) for key in _PARAMETER_KEYS},
    )
    return {
        "routing_version": CAPSULE_SLOT_ROUTING_VERSION,
        "feature_id": feature_id,
        "component_id": component_id,
        "target_output_id": output_id,
        "helper_source": (
            f"def _ai_feature_{feature_id}(body, params):\n"
            f"    {statement}\n"
            "    return body"
        ),
        "authoritative_change": change,
        "parameter_ids": {key: str(parameter_ids[key]) for key in _PARAMETER_KEYS},
        "helper_applied": True,
        "provider_strategy_preserved_for_other_features": True,
    }


__all__ = ["CAPSULE_SLOT_ROUTING_VERSION", "build_capsule_slot_feature_source"]
