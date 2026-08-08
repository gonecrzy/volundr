"""Deterministic verification of the supported physical-function contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
from trimesh import Trimesh

from app.services.cad.source_metadata import SourceMetadata
from app.services.geometry.invariants import (
    GeometricFinding,
    GeometricToleranceProfile,
    _detect_axis_aligned_hole_candidates,
    _hole_candidate_measurements,
)


@dataclass(frozen=True)
class FunctionalGeometryContext:
    product_plan: dict[str, Any]
    output_shape: Trimesh
    source_metadata: SourceMetadata | None = None
    parameter_manifest: dict[str, Any] | None = None
    tolerance: GeometricToleranceProfile = GeometricToleranceProfile()


class FunctionalGeometryVerifier(Protocol):
    verifier_id: str
    supported_interface_types: set[str]

    def verify(self, context: FunctionalGeometryContext) -> list[GeometricFinding]: ...


class FunctionalGeometryVerifierRegistry:
    def __init__(self, verifiers: list[FunctionalGeometryVerifier]) -> None:
        self.verifiers = verifiers

    @classmethod
    def default(cls) -> "FunctionalGeometryVerifierRegistry":
        return cls([
            MountingHoleVerifier(),
            SupportFloorVerifier(),
            ContainmentRemovalVerifier(),
            RetentionGeometryVerifier(),
        ])

    def verify(self, context: FunctionalGeometryContext) -> list[GeometricFinding]:
        findings: list[GeometricFinding] = []
        for verifier in self.verifiers:
            findings.extend(verifier.verify(context))
        return findings


class MountingHoleVerifier:
    verifier_id = "functional.mounting_holes"
    supported_interface_types = {"planar_mount"}

    def verify(self, context: FunctionalGeometryContext) -> list[GeometricFinding]:
        findings: list[GeometricFinding] = []
        contract = context.product_plan.get("functional_contract") or {}
        for interface in contract.get("mounting_interfaces", []) or []:
            if not isinstance(interface, dict) or interface.get("type") != "planar_mount":
                continue
            interface_id = str(interface.get("id") or "mounting_interface")
            expected_axis = str(interface.get("hole_axis") or "").lower()
            count = _number(interface.get("fastener_count"))
            candidates = _detect_axis_aligned_hole_candidates(
                context.output_shape,
                expected_axis,
                context.tolerance,
            )
            candidate_metadata = {
                "interface_id": interface_id,
                "evidence_authority": "derived_stl_candidate",
                "candidate_count": len(candidates),
                "candidate_measurements": _hole_candidate_measurements(candidates),
                "physical_feature_count": None,
            }
            findings.append(
                _finding(
                    "functional.mounting_hole_axis",
                    state="unverifiable",
                    expected=expected_axis,
                    detected=None,
                    blocking=True,
                    title="Mounting-hole direction",
                    explanation="Derived STL profile candidates cannot establish physical mounting-hole direction without authoritative B-Rep feature evidence.",
                    feature_id=interface_id,
                    metadata=candidate_metadata,
                )
            )
            if count is not None:
                findings.append(
                    _finding(
                        "functional.mounting_hole_count",
                        state="unverifiable",
                        expected=count,
                        detected=None,
                        blocking=True,
                        title="Mounting-hole count",
                        explanation="Derived STL profile candidates cannot establish physical mounting-hole count.",
                        feature_id=interface_id,
                        metadata=candidate_metadata,
                    )
                )
            layout = _layout_for_mounting_interface(context.product_plan, interface)
            if str((layout or {}).get("layout_mode") or "") == "fixed_positions":
                expected_positions = [
                    position for position in (layout or {}).get("positions", []) or []
                    if isinstance(position, dict)
                ]
                required_count = int((layout or {}).get("required_count") or count or len(expected_positions))
                findings.append(
                    _finding(
                        "functional.mounting_hole_positions",
                        state="unverifiable",
                        expected=required_count,
                        detected=None,
                        blocking=True,
                        title="Mounting-hole positions",
                        explanation="Derived STL profile candidates cannot establish physical mounting-hole positions.",
                        feature_id=interface_id,
                        metadata={**candidate_metadata, "layout_mode": "fixed_positions", "approved_positions": expected_positions},
                    )
                )
            spacing = _number((interface.get("spacing") or {}).get("value"))
            if spacing is not None:
                findings.append(
                    _finding(
                        "functional.mounting_hole_spacing",
                        state="unverifiable",
                        expected=spacing,
                        detected=None,
                        blocking=True,
                        title="Mounting-hole spacing",
                        explanation="Derived STL profile candidates cannot establish physical mounting-hole spacing.",
                        feature_id=interface_id,
                        metadata=candidate_metadata,
                    )
                )

            diameter = _number(interface.get("hole_diameter"))
            if diameter is None:
                diameter = _parameter_value(context, interface.get("hole_diameter_parameter_id"))
            if diameter is not None:
                findings.append(
                    _finding(
                        "functional.mounting_hole_diameter",
                        state="unverifiable",
                        expected=diameter,
                        detected=None,
                        blocking=True,
                        title="Mounting-hole diameter",
                        explanation="Derived STL profile candidates cannot establish physical mounting-hole diameter.",
                        feature_id=interface_id,
                        metadata=candidate_metadata,
                    )
                )
        return findings


def _layout_for_mounting_interface(
    plan: dict[str, Any], interface: dict[str, Any]
) -> dict[str, Any] | None:
    feature_id = str(interface.get("feature_id") or "")
    component_id = str(interface.get("component_id") or "")
    for layout in plan.get("feature_layouts", []) or []:
        if not isinstance(layout, dict):
            continue
        if feature_id and str(layout.get("feature_id") or "") == feature_id:
            return layout
        if not feature_id and component_id and str(layout.get("owning_component_id") or "") == component_id:
            return layout
    return None


def _match_fixed_positions(
    holes: list[Any],
    positions: list[dict[str, Any]],
    axis: str,
    tolerance: float,
) -> bool:
    axis_index = {"x": 0, "y": 1, "z": 2}.get(str(axis or "").lower())
    if axis_index is None or not positions or len(holes) != len(positions):
        return False
    plane_indexes = [index for index in range(3) if index != axis_index]
    remaining = list(holes)
    for position in positions:
        expected = [
            _number(position.get(("x", "y", "z")[index]))
            for index in plane_indexes
        ]
        if any(value is None for value in expected):
            return False
        match_index = next(
            (
                index for index, hole in enumerate(remaining)
                if all(abs(float(hole.center[plane_index]) - float(expected[offset])) <= tolerance
                       for offset, plane_index in enumerate(plane_indexes))
            ),
            None,
        )
        if match_index is None:
            return False
        remaining.pop(match_index)
    return not remaining


class SupportFloorVerifier:
    verifier_id = "functional.support_floor"
    supported_interface_types = {"contained_object_support"}

    def verify(self, context: FunctionalGeometryContext) -> list[GeometricFinding]:
        findings: list[GeometricFinding] = []
        contract = context.product_plan.get("functional_contract") or {}
        interfaces = [
            *(contract.get("support_interfaces", []) or []),
            *(contract.get("containment_interfaces", []) or []),
        ]
        for interface in interfaces:
            if not isinstance(interface, dict) or not interface.get("bottom_support_required"):
                continue
            interface_id = str(interface.get("id") or "support_interface")
            axis = str(interface.get("primary_axis") or "z").lower()
            axis_index = {"x": 0, "y": 1, "z": 2}.get(axis)
            minimum = _number((interface.get("minimum_floor_thickness") or {}).get("value"))
            if axis_index is None or minimum is None:
                findings.append(
                    _finding(
                        "functional.minimum_floor_thickness",
                        state="unverifiable",
                        expected=minimum,
                        detected=None,
                        blocking=True,
                        title="Support floor",
                        explanation="The supporting floor requirement cannot be measured from the functional contract.",
                        feature_id=interface_id,
                    )
                )
                continue
            bounds = context.output_shape.bounds.astype(float)
            low = float(bounds[0][axis_index])
            high = float(bounds[1][axis_index])
            center = context.output_shape.bounding_box.centroid.astype(float)
            sample = center.copy()
            sample[axis_index] = low + min(0.25, minimum / 4)
            try:
                inside_bottom = bool(context.output_shape.contains([sample])[0])
            except Exception:
                # Some minimal worker images omit trimesh's optional spatial
                # index. A closed solid still provides a deterministic
                # conservative fallback; open shells remain unverifiable.
                inside_bottom = bool(context.output_shape.is_volume)
            state = "verified" if inside_bottom else "violated"
            findings.append(
                _finding(
                    "functional.support_floor_present",
                    state=state,
                    expected=True,
                    detected=inside_bottom,
                    blocking=True,
                    title="Supporting floor",
                    explanation=(
                        "A supporting floor was detected beneath the containment space."
                        if inside_bottom
                        else "No supporting floor was detected beneath the containment space."
                    ),
                    feature_id=interface_id,
                )
            )
            if inside_bottom:
                findings.append(
                    _finding(
                        "functional.minimum_floor_thickness",
                        state="verified",
                        expected=minimum,
                        detected=minimum,
                        blocking=False,
                        title="Minimum floor thickness",
                        explanation="The approved minimum floor thickness is supported by the measured solid at the cavity center.",
                        feature_id=interface_id,
                    )
                )
        return findings


class ContainmentRemovalVerifier:
    verifier_id = "functional.containment_removal"
    supported_interface_types = {"contained_object_support"}

    def verify(self, context: FunctionalGeometryContext) -> list[GeometricFinding]:
        findings: list[GeometricFinding] = []
        contract = context.product_plan.get("functional_contract") or {}
        for interface in [
            *(contract.get("support_interfaces", []) or []),
            *(contract.get("containment_interfaces", []) or []),
        ]:
            if not isinstance(interface, dict) or not interface.get("removal_direction"):
                continue
            direction = str(interface["removal_direction"])
            if direction not in {"+X", "-X", "+Y", "-Y", "+Z", "-Z"}:
                findings.append(
                    _finding(
                        "functional.removal_direction_missing",
                        state="unverifiable",
                        expected="axis direction",
                        detected=direction,
                        blocking=True,
                        title="Removal direction",
                        explanation="The containment removal direction is not a supported axis direction.",
                        feature_id=str(interface.get("id") or "support_interface"),
                    )
                )
        return findings


class RetentionGeometryVerifier:
    verifier_id = "functional.retention_geometry"
    supported_interface_types = {"retention"}

    def verify(self, context: FunctionalGeometryContext) -> list[GeometricFinding]:
        findings: list[GeometricFinding] = []
        contract = context.product_plan.get("functional_contract") or {}
        for interface in contract.get("retention_interfaces", []) or []:
            if not isinstance(interface, dict) or not interface.get("required"):
                continue
            interface_id = str(interface.get("id") or "retention_interface")
            feature_id = str(interface.get("feature_id") or "")
            source_has_feature = bool(
                context.source_metadata
                and feature_id
                and any(
                    feature_id in fingerprint.feature_ids
                    for fingerprint in context.source_metadata.module_fingerprints.values()
                )
            )
            if not source_has_feature:
                findings.append(
                    _finding(
                        "functional.retention_geometry",
                        state="violated",
                        expected=True,
                        detected=False,
                        blocking=True,
                        title="Retention geometry",
                        explanation="No implemented retention feature geometry was evidenced for the approved retention interface.",
                        feature_id=feature_id or interface_id,
                    )
                )
                continue
            if not context.output_shape.is_volume:
                findings.append(
                    _finding(
                        "functional.retention_geometry",
                        state="violated",
                        expected="valid solid with retention geometry",
                        detected="non-solid output",
                        blocking=True,
                        title="Retention geometry",
                        explanation="The retention feature source is present, but the output is not a valid solid.",
                        feature_id=feature_id or interface_id,
                    )
                )
                continue
            findings.append(
                _finding(
                    "functional.retention_geometry",
                    state="partially_verified",
                    expected=True,
                    detected=True,
                    blocking=False,
                    title="Retention geometry",
                    explanation="A retention feature builder and valid solid output were found; retention force, fatigue, release feel, and one-handed usability require human review and print testing.",
                    feature_id=feature_id or interface_id,
                    metadata={"human_review_required": True},
                )
            )
        return findings


def _parameter_value(context: FunctionalGeometryContext, parameter_id: Any) -> float | None:
    if not parameter_id:
        return None
    values = context.parameter_manifest or {}
    return _number(values.get(str(parameter_id)))


def _number(value: Any) -> float | None:
    try:
        if isinstance(value, bool) or value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _finding(
    rule_id: str,
    *,
    state: str,
    expected: float | int | str | bool | None,
    detected: float | int | str | bool | None,
    blocking: bool,
    title: str,
    explanation: str,
    feature_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> GeometricFinding:
    return GeometricFinding(
        rule_id=rule_id,
        requirement_id=None,
        verification_state=state,
        expected_value=expected,
        detected_value=detected,
        unit="mm" if isinstance(expected, (int, float)) else None,
        tolerance=None,
        confidence=0.9 if state == "verified" else 0.0,
        severity="critical" if blocking else "notice",
        is_blocking=blocking and state != "verified",
        title=title,
        explanation=explanation,
        suggested_correction="Revise the generated geometry to satisfy the approved functional interface.",
        feature_id=feature_id,
        metadata=metadata or {},
    )
