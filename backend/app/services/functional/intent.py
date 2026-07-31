"""Validation for the small, generic physical-function contract.

This module intentionally validates intent, not a particular product.  The
contract is optional for legacy plans; once present, critical interfaces must
be explicit enough for deterministic verification.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


_CRITERION_TYPES = {
    "mounting_hole_axis",
    "mounting_hole_count",
    "mounting_hole_diameter",
    "mounting_hole_spacing",
    "support_floor_present",
    "minimum_floor_thickness",
    "required_feature_geometry_present",
    "parameter_geometry_effect",
    "output_exists",
    "solid_count",
    "bounds_preserved",
}
_PARAMETER_CRITERIA = {"parameter_geometry_effect"}
_OUTPUT_CRITERIA = {
    "mounting_hole_axis",
    "mounting_hole_count",
    "mounting_hole_diameter",
    "mounting_hole_spacing",
    "support_floor_present",
    "minimum_floor_thickness",
    "required_feature_geometry_present",
    "output_exists",
    "solid_count",
    "bounds_preserved",
}


def _finding(rule_id: str, message: str, **extra: Any) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "category": "functional",
        "severity": extra.pop("severity", "error"),
        "is_blocking": extra.pop("is_blocking", True),
        "message": message,
        **extra,
    }


def _ambiguous(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.lower()
    return " or " in normalized or normalized.startswith("some ")


def _items(contract: dict[str, Any], *names: str) -> Iterable[dict[str, Any]]:
    for name in names:
        values = contract.get(name, [])
        if isinstance(values, list):
            yield from (value for value in values if isinstance(value, dict))


def validate_functional_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Return deterministic findings for an explicit functional contract.

    Plans without ``functional_contract`` are legacy plans and are left to
    the normal design-plan validators.  They are later classified as
    functionally unverified when critical physical intent is present.
    """

    contract = plan.get("functional_contract")
    if not isinstance(contract, dict):
        return []

    findings: list[dict[str, Any]] = []
    frames = {
        str(frame.get("id")): frame
        for frame in contract.get("coordinate_frames", [])
        if isinstance(frame, dict) and frame.get("id")
    }
    for interface in _items(contract, "mounting_interfaces"):
        interface_id = interface.get("id")
        for field, rule_id in (
            ("mounting_plane", "functional.mounting_plane_missing"),
            ("normal_axis", "functional.mounting_plane_normal_missing"),
            ("hole_axis", "functional.hole_axis_missing"),
            ("arrangement_axis", "functional.arrangement_axis_missing"),
        ):
            if not interface.get(field):
                findings.append(
                    _finding(
                        rule_id,
                        f"Mounting interface `{interface_id or 'unnamed'}` is missing {field}.",
                        entity_type="mounting_interface",
                        entity_id=interface_id,
                    )
                )
        ambiguous_axis = any(
            _ambiguous(interface.get(field))
            for field in ("normal_axis", "hole_axis", "arrangement_axis")
        )
        if ambiguous_axis:
            if _ambiguous(interface.get("hole_axis")) and interface.get("hole_axis"):
                findings.append(
                    _finding(
                        "functional.hole_axis_missing",
                        f"Mounting interface `{interface_id or 'unnamed'}` does not resolve its hole axis.",
                        entity_type="mounting_interface",
                        entity_id=interface_id,
                    )
                )
        if any(_ambiguous(interface.get(field)) for field in ("type", "mounting_plane", "normal_axis", "hole_axis", "arrangement_axis", "hole_style")):
            findings.append(
                _finding(
                    "functional.mounting_strategy_ambiguous",
                    f"Mounting interface `{interface_id or 'unnamed'}` contains an unresolved alternative.",
                    entity_type="mounting_interface",
                    entity_id=interface_id,
                )
            )
        if interface.get("coordinate_frame_id") and interface["coordinate_frame_id"] not in frames:
            findings.append(
                _finding(
                    "functional.coordinate_frame_missing",
                    f"Mounting interface `{interface_id or 'unnamed'}` references an unknown coordinate frame.",
                    entity_type="mounting_interface",
                    entity_id=interface_id,
                )
            )
        count = interface.get("fastener_count")
        if count is not None and (not isinstance(count, int) or count < 1):
            findings.append(
                _finding(
                    "functional.fastener_count_invalid",
                    f"Mounting interface `{interface_id or 'unnamed'}` must declare a positive fastener count.",
                    entity_type="mounting_interface",
                    entity_id=interface_id,
                )
            )

    for interface in _items(contract, "support_interfaces", "containment_interfaces"):
        interface_id = interface.get("id")
        if interface.get("bottom_support_required"):
            if not interface.get("minimum_floor_thickness"):
                findings.append(
                    _finding(
                        "functional.support_requirement_missing",
                        f"Support interface `{interface_id or 'unnamed'}` requires a floor thickness.",
                        entity_type="support_interface",
                        entity_id=interface_id,
                    )
                )
            if not interface.get("removal_direction"):
                findings.append(
                    _finding(
                        "functional.removal_direction_missing",
                        f"Support interface `{interface_id or 'unnamed'}` is missing a removal direction.",
                        entity_type="support_interface",
                        entity_id=interface_id,
                    )
                )
        if _ambiguous(interface.get("primary_axis")) or _ambiguous(interface.get("removal_direction")):
            findings.append(
                _finding(
                    "functional.support_strategy_ambiguous",
                    f"Support interface `{interface_id or 'unnamed'}` contains an unresolved alternative.",
                    entity_type="support_interface",
                    entity_id=interface_id,
                )
            )

    for interface in _items(contract, "retention_interfaces"):
        interface_id = interface.get("id")
        if interface.get("required") and not interface.get("strategy"):
            findings.append(
                _finding(
                    "functional.retention_strategy_unresolved",
                    f"Required retention interface `{interface_id or 'unnamed'}` has no strategy.",
                    entity_type="retention_interface",
                    entity_id=interface_id,
                )
            )
        if _ambiguous(interface.get("strategy")) or _ambiguous(interface.get("release_behavior")):
            findings.append(
                _finding(
                    "functional.retention_strategy_unresolved",
                    f"Retention interface `{interface_id or 'unnamed'}` contains an unresolved alternative.",
                    entity_type="retention_interface",
                    entity_id=interface_id,
                )
            )
    return findings


def validate_revision_success_criteria(
    payload: dict[str, Any], plan: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Validate typed, measurable revision criteria against plan identities."""

    if not str(payload.get("schema_version", "")).startswith("revision-plan-v2"):
        return []
    plan = plan or {}
    parameters = {
        str(item.get("id"))
        for item in plan.get("parameters", [])
        if isinstance(item, dict) and item.get("id")
    }
    outputs = {
        str(item.get("id"))
        for item in plan.get("printable_outputs", plan.get("outputs", []))
        if isinstance(item, dict) and item.get("id")
    }
    features = {
        str(item.get("id"))
        for item in plan.get("features", [])
        if isinstance(item, dict) and item.get("id")
    }
    findings: list[dict[str, Any]] = []
    for index, criterion in enumerate(payload.get("success_criteria", [])):
        if not isinstance(criterion, dict):
            continue
        criterion_type = criterion.get("type")
        target_id = str(criterion.get("target_id") or "")
        if criterion_type not in _CRITERION_TYPES:
            findings.append(
                _finding(
                    "functional.revision_criterion_type_unknown",
                    f"Revision success criterion {index + 1} uses unsupported type `{criterion_type}`.",
                    entity_type="revision_success_criterion",
                    entity_id=target_id or None,
                )
            )
            if target_id in outputs or target_id in features:
                findings.append(
                    _finding(
                        "functional.revision_criterion_target_invalid",
                        f"Unknown revision criterion type cannot target output or feature `{target_id}`.",
                        entity_type="revision_success_criterion",
                        entity_id=target_id or None,
                    )
                )
            continue
        if criterion_type in _PARAMETER_CRITERIA and target_id not in parameters:
            findings.append(
                _finding(
                    "functional.revision_criterion_target_invalid",
                    f"Revision criterion `{criterion_type}` targets unknown parameter `{target_id}`.",
                    entity_type="revision_success_criterion",
                    entity_id=target_id or None,
                )
            )
        elif criterion_type in _OUTPUT_CRITERIA and target_id not in outputs and target_id not in features:
            findings.append(
                _finding(
                    "functional.revision_criterion_target_invalid",
                    f"Revision criterion `{criterion_type}` targets unknown output or feature `{target_id}`.",
                    entity_type="revision_success_criterion",
                    entity_id=target_id or None,
                )
            )
    return findings
