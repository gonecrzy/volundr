"""Fail-closed source routing for an authoritative rounded capsule slot."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.services.cad.capsule_slot_source import build_capsule_slot_helper_statement
from volundr_cad.capsule_slot import CapsuleSlotContractError


CAPSULE_SLOT_ROUTING_VERSION = "capsule-slot-routing-v1"
_PARAMETER_KEYS = ("length", "width", "center_x", "center_y", "orientation", "depth")
_CANONICAL_PARAMETER_IDS = {
    "length": ("capsule_slot_length", "capsule_length"),
    "width": ("capsule_slot_width", "capsule_width"),
    "center_x": ("capsule_slot_center_x", "capsule_center_x"),
    "center_y": ("capsule_slot_center_y", "capsule_center_y"),
    "orientation": ("capsule_slot_orientation", "capsule_orientation"),
    "depth": ("capsule_slot_depth", "capsule_depth"),
}


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


def _plan_parameter_ids(plan: Mapping[str, Any]) -> set[str]:
    return {
        str(item.get("id"))
        for item in plan.get("parameters", []) or []
        if isinstance(item, Mapping) and item.get("id")
    }


def _parameter_source_requirement_ids(plan: Mapping[str, Any]) -> dict[str, list[str]]:
    by_requirement: dict[str, list[str]] = {}
    for item in plan.get("parameters", []) or []:
        if not isinstance(item, Mapping) or not item.get("id"):
            continue
        parameter_id = str(item["id"])
        source_requirement_id = item.get("source_requirement_id")
        if isinstance(source_requirement_id, str) and source_requirement_id:
            by_requirement.setdefault(source_requirement_id, []).append(parameter_id)
    return by_requirement


def _resolve_parameter_ids(
    plan: Mapping[str, Any],
    capsule_slot: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, str]]:
    parameter_ids = capsule_slot.get("parameter_ids")
    if not isinstance(parameter_ids, Mapping) or not all(parameter_ids.get(key) for key in _PARAMETER_KEYS):
        raise CapsuleSlotContractError("capsule helper routing requires all parameter IDs")

    plan_parameter_ids = _plan_parameter_ids(plan)
    requirement_parameter_ids = _parameter_source_requirement_ids(plan)
    resolved: dict[str, str] = {}
    sources: dict[str, str] = {}
    missing: list[str] = []
    for key in _PARAMETER_KEYS:
        original = str(parameter_ids[key])
        if original in plan_parameter_ids:
            resolved[key] = original
            sources[key] = "authoritative_parameter_id"
            continue
        candidates: list[str] = []
        for candidate in _CANONICAL_PARAMETER_IDS[key]:
            if candidate in plan_parameter_ids:
                candidates.append(candidate)
            candidates.extend(requirement_parameter_ids.get(candidate, []))
        unique_candidates = sorted(set(candidates))
        if len(unique_candidates) == 1:
            resolved[key] = unique_candidates[0]
            sources[key] = "plan_requirement_trace"
            continue
        missing.append(original)
    if missing:
        raise CapsuleSlotContractError("capsule helper parameter IDs are absent from Plan: " + ", ".join(sorted(missing)))
    return resolved, sources


def _resolve_feature(
    plan: Mapping[str, Any],
    *,
    feature_id: str,
    parameter_ids: Mapping[str, str],
) -> tuple[Mapping[str, Any], str]:
    features = [item for item in plan.get("features", []) or [] if isinstance(item, Mapping)]
    feature_matches = [item for item in features if str(item.get("id") or "") == feature_id]
    if len(feature_matches) == 1:
        return feature_matches[0], "authoritative_feature_id"
    if len(feature_matches) > 1:
        raise CapsuleSlotContractError("Plan must contain exactly one capsule feature with the authoritative identity")

    required_parameters = set(parameter_ids.values())
    trace_matches = [
        item
        for item in features
        if required_parameters.issubset({str(value) for value in item.get("parameters", []) or []})
    ]
    if len(trace_matches) == 1:
        return trace_matches[0], "plan_parameter_trace"
    raise CapsuleSlotContractError("Plan must contain exactly one capsule feature traceable to authoritative facts")


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
    requested = capsule_slot.get("requested_feature_dimensions")
    if not isinstance(requested, Mapping) or str(requested.get("profile_type") or "") != "rounded_end_capsule":
        raise CapsuleSlotContractError("authoritative capsule facts must include profile_type rounded_end_capsule")

    resolved_parameter_ids, parameter_id_sources = _resolve_parameter_ids(plan, capsule_slot)
    feature, feature_identity_source = _resolve_feature(
        plan,
        feature_id=feature_id,
        parameter_ids=resolved_parameter_ids,
    )
    resolved_feature_id = str(feature.get("id") or "").strip()
    resolved_component_id = str(feature.get("component_id") or "").strip()
    if not resolved_feature_id or not resolved_component_id:
        raise CapsuleSlotContractError("capsule feature component ownership does not match authoritative facts")
    if feature_identity_source == "authoritative_feature_id" and resolved_component_id != component_id:
        raise CapsuleSlotContractError("capsule feature component ownership does not match authoritative facts")
    plan_profile_type = str(feature.get("profile_type") or "").strip()
    if plan_profile_type and plan_profile_type != "rounded_end_capsule":
        raise CapsuleSlotContractError("Plan capsule feature profile_type conflicts with authoritative facts")

    output_matches = [
        item
        for item in plan.get("printable_outputs", []) or []
        if isinstance(item, Mapping)
        and str(item.get("id") or item.get("output_id") or "") == output_id
        and resolved_component_id in [str(value) for value in item.get("component_ids", []) or []]
    ]
    if len(output_matches) != 1:
        raise CapsuleSlotContractError("capsule feature must map to exactly one authoritative output")

    change = _capsule_change(capsule_slot)
    statement = build_capsule_slot_helper_statement(
        change,
        parameter_ids=resolved_parameter_ids,
    )
    return {
        "routing_version": CAPSULE_SLOT_ROUTING_VERSION,
        "feature_id": resolved_feature_id,
        "component_id": resolved_component_id,
        "authoritative_feature_id": feature_id,
        "authoritative_component_id": component_id,
        "target_output_id": output_id,
        "helper_source": (
            f"def _ai_feature_{resolved_feature_id}(body, params):\n"
            f"    {statement}\n"
            "    return body"
        ),
        "authoritative_change": change,
        "authoritative_profile_type": "rounded_end_capsule",
        "plan_profile_type": plan_profile_type or None,
        "feature_identity_source": feature_identity_source,
        "parameter_id_sources": parameter_id_sources,
        "parameter_ids": resolved_parameter_ids,
        "helper_applied": True,
        "provider_strategy_preserved_for_other_features": True,
    }


__all__ = ["CAPSULE_SLOT_ROUTING_VERSION", "build_capsule_slot_feature_source"]
