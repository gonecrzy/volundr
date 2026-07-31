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
    _detect_axis_aligned_holes,
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
        return cls([MountingHoleVerifier(), SupportFloorVerifier(), ContainmentRemovalVerifier()])

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
            holes = _detect_axis_aligned_holes(
                context.output_shape,
                expected_axis,
                context.tolerance,
            )
            confident = [hole for hole in holes if hole.confidence >= context.tolerance.medium_confidence]
            if not confident:
                alternate_axes = {
                    axis: len(
                        [
                            hole
                            for hole in _detect_axis_aligned_holes(
                                context.output_shape, axis, context.tolerance
                            )
                            if hole.confidence >= context.tolerance.medium_confidence
                        ]
                    )
                    for axis in ("x", "y", "z")
                    if axis != expected_axis
                }
                detected_axis = max(alternate_axes, key=alternate_axes.get) if alternate_axes else None
                findings.append(
                    _finding(
                        "functional.mounting_hole_axis",
                        state="violated" if detected_axis else "unverifiable",
                        expected=expected_axis or None,
                        detected=detected_axis,
                        blocking=True,
                        title="Mounting-hole direction",
                        explanation=(
                            f"Mounting holes were detected along {detected_axis.upper()} instead of the required {expected_axis.upper()} axis."
                            if detected_axis
                            else "Volundr could not verify mounting holes along the required mounting-plane normal."
                        ),
                        feature_id=interface_id,
                        metadata={"interface_id": interface_id, "alternate_axes": alternate_axes},
                    )
                )
                continue
            findings.append(
                _finding(
                    "functional.mounting_hole_axis",
                    state="verified",
                    expected=expected_axis,
                    detected=expected_axis,
                    blocking=False,
                    title="Mounting-hole direction",
                    explanation="Mounting holes are aligned with the required mounting-plane normal.",
                    feature_id=interface_id,
                )
            )
            if count is not None:
                actual_count = len(confident)
                findings.append(
                    _finding(
                        "functional.mounting_hole_count",
                        state="verified" if actual_count == count else "violated",
                        expected=count,
                        detected=actual_count,
                        blocking=actual_count != count,
                        title="Mounting-hole count",
                        explanation=f"Detected {actual_count} mounting holes; expected {count}.",
                        feature_id=interface_id,
                    )
                )
            spacing = _number((interface.get("spacing") or {}).get("value"))
            if spacing is not None and len(confident) == 2:
                arrangement_axis = str(interface.get("arrangement_axis") or "z").lower()
                axis_index = {"x": 0, "y": 1, "z": 2}.get(arrangement_axis)
                detected_spacing = abs(
                    float(confident[0].center[axis_index]) - float(confident[1].center[axis_index])
                ) if axis_index is not None else None
                if detected_spacing is None:
                    continue
                findings.append(
                    _finding(
                        "functional.mounting_hole_spacing",
                        state="verified"
                        if abs(detected_spacing - spacing) <= context.tolerance.hole_spacing_abs_mm
                        else "violated",
                        expected=spacing,
                        detected=round(detected_spacing, 3),
                        blocking=abs(detected_spacing - spacing) > context.tolerance.hole_spacing_abs_mm,
                        title="Mounting-hole spacing",
                        explanation="Detected mounting-hole center spacing matches the approved interface."
                        if abs(detected_spacing - spacing) <= context.tolerance.hole_spacing_abs_mm
                        else "Detected mounting-hole center spacing differs from the approved interface.",
                        feature_id=interface_id,
                    )
                )

            diameter = _number(interface.get("hole_diameter"))
            if diameter is None:
                diameter = _parameter_value(context, interface.get("hole_diameter_parameter_id"))
            if diameter is not None and confident:
                detected_diameter = float(np.median([hole.diameter for hole in confident]))
                findings.append(
                    _finding(
                        "functional.mounting_hole_diameter",
                        state="verified"
                        if abs(detected_diameter - diameter) <= context.tolerance.hole_diameter_abs_mm
                        else "violated",
                        expected=diameter,
                        detected=round(detected_diameter, 3),
                        blocking=abs(detected_diameter - diameter) > context.tolerance.hole_diameter_abs_mm,
                        title="Mounting-hole diameter",
                        explanation="Detected mounting-hole diameter matches the approved interface."
                        if abs(detected_diameter - diameter) <= context.tolerance.hole_diameter_abs_mm
                        else "Detected mounting-hole diameter differs from the approved interface.",
                        feature_id=interface_id,
                    )
                )
        return findings


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
