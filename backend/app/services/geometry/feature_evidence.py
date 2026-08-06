"""Generic source-to-final-geometry evidence orchestration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from trimesh import Trimesh

from app.services.geometry.feature_measurements import (
    compare_dimension,
    measure_opening_profiles,
    measure_compartments,
    measure_opening_count,
    measure_slots,
    verify_one_connected_output,
)
from app.services.geometry.invariants import GeometricFinding

EVIDENCE_SCHEMA_VERSION = "feature-evidence-v1"
EVIDENCE_OUTCOMES = {
    "satisfied",
    "satisfied_with_warning",
    "not_satisfied",
    "unverifiable",
    "feature_absent",
    "measurement_failed",
}


@dataclass(frozen=True)
class FeatureEvidenceRecord:
    requirement_id: str
    feature_id: str
    output_id: str
    source_function_id: str | None
    source_executed: bool | None
    geometry_presence: str
    measurement_status: str
    measurements: dict[str, Any] = field(default_factory=dict)
    requirement_outcome: str = "unverifiable"
    evidence_method: str = "unavailable"
    measurement_inputs: dict[str, Any] = field(default_factory=dict)
    tolerances: dict[str, Any] = field(default_factory=dict)
    finding_ids: list[str] = field(default_factory=list)
    source_trace: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.requirement_outcome not in EVIDENCE_OUTCOMES:
            raise ValueError(f"unsupported evidence outcome: {self.requirement_outcome}")

    def to_json(self) -> dict[str, Any]:
        return {"schema_version": EVIDENCE_SCHEMA_VERSION, **asdict(self)}


@dataclass(frozen=True)
class FeatureEvidenceEvaluation:
    records: list[FeatureEvidenceRecord]
    trace_findings: list[dict[str, Any]]


def evidence_to_geometric_finding(record: FeatureEvidenceRecord) -> GeometricFinding:
    state = {
        "satisfied": "verified",
        "satisfied_with_warning": "human_review",
        "not_satisfied": "violated",
        "feature_absent": "violated",
        "unverifiable": "unverifiable",
        "measurement_failed": "unverifiable",
    }[record.requirement_outcome]
    blocking = record.requirement_outcome in {"not_satisfied", "feature_absent"}
    return GeometricFinding(
        rule_id=f"feature.evidence.{record.feature_id}.{record.requirement_id}",
        requirement_id=record.requirement_id,
        verification_state=state,
        expected_value=record.measurements.get("requested_mm")
        or record.measurements.get("expected_solid_count"),
        detected_value=record.measurements.get("measured_mm")
        or record.measurements.get("detected_connected_components"),
        unit="mm" if any(key.endswith("_mm") for key in record.measurements) else None,
        tolerance=_first_tolerance(record.tolerances),
        confidence=0.95 if record.measurement_status == "measured" else 0.0,
        severity="critical" if blocking else "warning",
        is_blocking=blocking,
        title=f"Feature evidence: {record.feature_id}",
        explanation=(
            f"Final geometry evidence outcome: {record.requirement_outcome}."
            if record.measurement_status == "measured"
            else "Final geometry evidence is unavailable for this requirement."
        ),
        suggested_correction="Review or repair only the identified feature, then remeasure the final output.",
        feature_id=record.feature_id,
        metadata=record.to_json(),
    )


def evaluate_feature_evidence(
    *,
    mesh: Trimesh,
    output_id: str,
    requirement_trace: dict[str, Any],
    feature_trace: list[dict[str, Any]],
    topology_metadata: dict[str, Any] | None = None,
) -> FeatureEvidenceEvaluation:
    """Evaluate declared features against final mesh evidence.

    The requirement trace supplies semantics and the worker trace supplies
    execution provenance. Neither is accepted as final geometry evidence on
    its own.
    """

    features = [item for item in requirement_trace.get("features", []) if isinstance(item, dict)]
    targets = [item for item in requirement_trace.get("validation_targets", []) if isinstance(item, dict)]
    target_by_requirement = {
        str(requirement_id): target
        for target in targets
        for requirement_id in (
            target.get("requirement_ids", [])
            or ([target.get("requirement_id")] if target.get("requirement_id") else [])
        )
    }
    traces_by_feature: dict[str, list[dict[str, Any]]] = {}
    for trace in feature_trace:
        if not isinstance(trace, dict):
            continue
        if trace.get("output_id") and str(trace.get("output_id")) != output_id:
            continue
        source_id = str(trace.get("source_function_id") or "")
        feature_id = str(trace.get("feature_id") or "")
        candidates = {feature_id, source_id.removeprefix("_ai_feature_")}
        candidates.add(source_id.removeprefix("_ai_component_"))
        for candidate in candidates:
            if candidate:
                traces_by_feature.setdefault(candidate, []).append(trace)

    records: list[FeatureEvidenceRecord] = []
    trace_findings: list[dict[str, Any]] = []
    for feature in features:
        feature_id = str(feature.get("feature_id") or feature.get("id") or "")
        if not feature_id:
            continue
        source_function_id = _source_function_id(feature_id, feature_trace)
        matches = traces_by_feature.get(feature_id, [])
        feature_requirement_ids = [
            str(item) for item in (
                feature.get("requirement_ids", [])
                or ([feature.get("requirement_id")] if feature.get("requirement_id") else [])
            )
        ]
        if not feature_requirement_ids:
            feature_requirement_ids = [feature_id]
        if (
            matches
            and not any(bool(trace.get("shape_changed")) for trace in matches)
            and str(feature.get("operation") or "").lower() in {"extrude", "additive", "create"}
        ):
            component_id = str(feature.get("component_id") or "")
            component_matches = traces_by_feature.get(component_id, [])
            if any(bool(trace.get("shape_changed")) for trace in component_matches):
                matches = [trace for trace in component_matches if trace.get("shape_changed")]
        for requirement_id in feature_requirement_ids:
            target = target_by_requirement.get(requirement_id, {})
            record, findings = _evaluate_one(
                mesh=mesh,
                output_id=output_id,
                feature=feature,
                requirement_id=requirement_id,
                target=target,
                traces=matches,
                topology_metadata=topology_metadata,
            )
            records.append(record)
            trace_findings.extend(findings)
    return FeatureEvidenceEvaluation(records=records, trace_findings=trace_findings)


def _evaluate_one(
    *,
    mesh: Trimesh,
    output_id: str,
    feature: dict[str, Any],
    requirement_id: str,
    target: dict[str, Any],
    traces: list[dict[str, Any]],
    topology_metadata: dict[str, Any] | None,
) -> tuple[FeatureEvidenceRecord, list[dict[str, Any]]]:
    feature_id = str(feature.get("feature_id") or feature.get("id"))
    source_function_id = (
        str(traces[0].get("source_function_id"))
        if traces and traces[0].get("source_function_id")
        else _source_function_id(feature_id, traces)
    )
    base = {
        "requirement_id": requirement_id,
        "feature_id": feature_id,
        "output_id": output_id,
        "source_function_id": source_function_id,
        "source_trace": traces[0] if len(traces) == 1 else {},
    }
    if len(traces) > 1:
        return (
            FeatureEvidenceRecord(
                **base,
                source_executed=None,
                geometry_presence="unknown",
                measurement_status="unavailable",
                requirement_outcome="unverifiable",
                evidence_method="ambiguous_runtime_trace",
                measurement_inputs={"trace_count": len(traces)},
            ),
            [{
                "rule_id": "feature.trace_ambiguous",
                "feature_id": feature_id,
                "requirement_id": requirement_id,
                "is_blocking": True,
                "message": "More than one runtime trace matched the feature; final attribution is ambiguous.",
            }],
        )
    if not traces:
        return (
            FeatureEvidenceRecord(
                **base,
                source_executed=None,
                geometry_presence="unknown",
                measurement_status="unavailable",
                requirement_outcome="unverifiable",
                evidence_method="source_declaration_without_runtime_trace",
            ),
            [{
                "rule_id": "feature.trace_missing",
                "feature_id": feature_id,
                "requirement_id": requirement_id,
                "is_blocking": True,
                "message": "Source declares the feature, but no runtime source-to-result trace is available.",
            }],
        )

    trace = traces[0]
    if not bool(trace.get("source_executed")):
        return (
            FeatureEvidenceRecord(
                **base,
                source_executed=False,
                geometry_presence="absent",
                measurement_status="failed",
                requirement_outcome="feature_absent",
                evidence_method="runtime_execution_trace",
            ),
            [{
                "rule_id": "feature.source_not_executed",
                "feature_id": feature_id,
                "requirement_id": requirement_id,
                "is_blocking": True,
                "message": "The provider-owned feature function did not execute successfully.",
            }],
        )
    if not bool(trace.get("shape_changed")):
        return (
            FeatureEvidenceRecord(
                **base,
                source_executed=True,
                geometry_presence="absent",
                measurement_status="measured",
                requirement_outcome="feature_absent",
                evidence_method="runtime_shape_identity",
                measurements={"shape_changed": False},
            ),
            [{
                "rule_id": "feature.source_no_effect",
                "feature_id": feature_id,
                "requirement_id": requirement_id,
                "is_blocking": True,
                "message": "The feature function executed but returned an unchanged shape.",
            }],
        )

    result = _measure_final_geometry(
        mesh=mesh,
        feature=feature,
        requirement_id=requirement_id,
        target=target,
        topology_metadata=topology_metadata,
        trace=trace,
    )
    findings = [{
        "rule_id": "feature.geometry_changed",
        "feature_id": feature_id,
        "requirement_id": requirement_id,
        "is_blocking": False,
        "message": "The feature function changed the provider shape; final geometry measurement is recorded separately.",
    }]
    if result["requirement_outcome"] in {"not_satisfied", "feature_absent"}:
        findings.append({
            "rule_id": "feature.geometry_removed_later",
            "feature_id": feature_id,
            "requirement_id": requirement_id,
            "is_blocking": True,
            "message": "The feature changed an intermediate shape but the final geometry measurement did not satisfy the requirement.",
        })
    return FeatureEvidenceRecord(**base, source_executed=True, **result), findings


def _measure_final_geometry(
    *,
    mesh: Trimesh,
    feature: dict[str, Any],
    requirement_id: str,
    target: dict[str, Any],
    topology_metadata: dict[str, Any] | None,
    trace: dict[str, Any],
) -> dict[str, Any]:
    feature_id = str(feature.get("feature_id") or feature.get("id"))
    object_type = str(feature.get("object_type") or "").lower()
    layout = feature.get("layout") if isinstance(feature.get("layout"), dict) else {}
    measurement = str(target.get("measurement") or "")
    requested = _number(target.get("value"))
    if (
        measurement in {"width", "depth", "height", "thickness"}
        and (object_type in {"desktop organizer", "body", "base", "walls", "mounting_plate"}
             or feature_id in {"main_body", "base_plate_body"})
    ):
        axis = {"width": 0, "depth": 1, "height": 2, "thickness": 2}[measurement]
        measured = float(mesh.bounds[1][axis] - mesh.bounds[0][axis])
        operator = str(target.get("operator") or "exact")
        tolerance = _number(target.get("tolerance_mm") or target.get("tolerance"))
        if tolerance is None:
            tolerance = 0.2
        comparison = compare_dimension(requested, measured, operator=operator, tolerance=tolerance)
        return _result_payload(
            comparison.passed,
            "measured",
            "overall_dimension" if comparison.passed else "dimension_mismatch",
            {"measurement": measurement, "requested_mm": requested, "measured_mm": round(measured, 3)},
            "final_mesh_bounds",
            {"requested_mm": requested, "operator": operator, "applied_tolerance_mm": tolerance},
            measurement_inputs={"target_id": target.get("target_id") or target.get("id"), "axis": axis},
            geometry_presence="present",
        )
    if object_type == "mounting_hole" and measurement == "diameter":
        tolerance = _number(target.get("tolerance_mm") or target.get("tolerance")) or 0.2
        profiles = measure_opening_profiles(mesh, axis=str(target.get("axis") or "z"))
        candidates = [
            profile for profile in profiles
            if abs(profile["size_x"] - requested) <= tolerance
            and abs(profile["size_y"] - requested) <= tolerance
        ]
        expected_count = _integer(layout.get("required_count"))
        detected = [max(profile["size_x"], profile["size_y"]) for profile in candidates]
        passed = bool(candidates) and (expected_count is None or len(candidates) == expected_count)
        if requested is not None and detected:
            passed = passed and all(abs(value - requested) <= tolerance for value in detected)
        return _result_payload(
            passed,
            "measured",
            "hole_diameter_and_count" if passed else "hole_diameter_or_count_mismatch",
            {
                "expected_diameter_mm": requested,
                "detected_diameters_mm": [round(value, 3) for value in detected],
                "expected_count": expected_count,
                "detected_count": len(candidates),
            },
            "final_mesh_axis_aligned_openings",
            {"diameter_mm": tolerance},
            measurement_inputs={"axis": str(target.get("axis") or "z")},
            geometry_presence="present" if candidates else "absent",
        )
    if feature_id == "base_plate_body" and not target:
        topology = verify_one_connected_output(
            mesh,
            expected_count=int((topology_metadata or {}).get("expected_solid_count") or 1),
        )
        return _result_payload(
            topology.satisfied,
            "measured",
            topology.reason,
            topology.measurements,
            "authoritative_topology_and_final_mesh",
            {},
            geometry_presence="present" if topology.satisfied else "absent",
        )
    if feature_id == "mounting_holes" and not target:
        profiles = measure_opening_profiles(mesh, axis="z")
        expected_count = _integer(layout.get("required_count"))
        expected_positions = layout.get("positions") or []
        hole_profiles = [profile for profile in profiles if profile["size_x"] <= 8 and profile["size_y"] <= 8]
        if requirement_id == "req_asymmetric_pattern" and expected_positions:
            matched_positions = _match_positions(hole_profiles, expected_positions, tolerance=0.25)
            return _result_payload(
                matched_positions,
                "measured",
                "fixed_hole_layout" if matched_positions else "fixed_hole_layout_mismatch",
                {"expected_count": len(expected_positions), "detected_count": len(hole_profiles)},
                "final_mesh_opening_centers",
                {"position_mm": 0.25},
                geometry_presence="present" if hole_profiles else "absent",
            )
        passed = expected_count is not None and len(hole_profiles) == expected_count
        return _result_payload(
            passed,
            "measured",
            "hole_count" if passed else "hole_count_mismatch",
            {"expected_count": expected_count, "detected_count": len(hole_profiles)},
            "final_mesh_opening_profiles",
            {},
            geometry_presence="present" if hole_profiles else "absent",
        )
    if feature_id == "cable_slot" and not target:
        bounds_size = mesh.bounds[1] - mesh.bounds[0]
        profiles = [
            profile for profile in measure_opening_profiles(mesh, axis="z")
            if profile["size_x"] > 8
            and profile["size_y"] > 5
            and profile["size_x"] < float(bounds_size[0]) * 0.9
            and profile["size_y"] < float(bounds_size[1]) * 0.9
        ]
        passed = len(profiles) == 1
        return _result_payload(
            passed,
            "measured",
            "slot_count" if passed else "slot_count_mismatch",
            {"expected_count": 1, "detected_count": len(profiles)},
            "final_mesh_opening_profiles",
            {},
            geometry_presence="present" if profiles else "absent",
        )
    if object_type == "cable_slot" and measurement in {"width", "height"}:
        tolerance = _number(target.get("tolerance_mm") or target.get("tolerance")) or 0.2
        profiles = measure_opening_profiles(mesh, axis=str(target.get("axis") or "z"))
        requested_size = requested
        candidates = [
            profile for profile in profiles
            if abs((max(profile["size_x"], profile["size_y"]) if measurement == "width" else min(profile["size_x"], profile["size_y"])) - requested_size) <= tolerance
        ]
        return _result_payload(
            bool(candidates),
            "measured",
            "slot_dimension" if candidates else "slot_dimension_mismatch",
            {"measurement": measurement, "requested_mm": requested_size, "profiles": candidates},
            "final_mesh_opening_profiles",
            {"dimension_mm": tolerance},
            geometry_presence="present" if candidates else "absent",
        )
    if feature_id == "main_body":
        topology = verify_one_connected_output(mesh, expected_count=int((topology_metadata or {}).get("expected_solid_count") or 1))
        return _result_payload(
            topology.satisfied,
            "measured",
            topology.reason,
            topology.measurements,
            "authoritative_topology_and_final_mesh",
            {},
            measurement_inputs={"expected_solid_count": (topology_metadata or {}).get("expected_solid_count") or 1},
            geometry_presence="present" if topology.measurements.get("face_count", 0) else "absent",
        )
    probe_points = target.get("probe_points") or feature.get("probe_points")
    if isinstance(probe_points, list) and probe_points:
        axis = str(target.get("axis") or feature.get("opening_axis") or "z")
        opening = measure_opening_count(
            mesh,
            axis=axis,
            points=probe_points,
            expected_count=_integer(target.get("expected_count") or feature.get("expected_count")),
        )
        return _result_payload(
            opening.satisfied,
            "measured",
            opening.reason,
            opening.measurements,
            "final_mesh_opening_probe",
            {"axis": axis, "minimum_opening_mm": 0.1, "expected_count": opening.measurements.get("expected_count")},
            measurement_inputs={
                "target_id": target.get("target_id") or target.get("id"),
                "axis": axis,
                "probe_points": probe_points,
            },
            geometry_presence="present" if opening.measurements.get("count", 0) else "absent",
        )
    samples = target.get("compartment_samples") or feature.get("compartment_samples")
    if isinstance(samples, list):
        compartments = measure_compartments(
            samples,
            expected_count=int(target.get("expected_count") or feature.get("expected_count") or 1),
            expected_width=_number(target.get("center_width") or feature.get("center_width")),
            expected_depth=_number(target.get("depth") or feature.get("depth")),
            tolerance=float(target.get("tolerance_mm") or 0.2),
            access_direction=str(target.get("access_direction") or feature.get("access_direction") or "top"),
        )
        return _result_payload(
            compartments.satisfied,
            "measured",
            compartments.reason,
            compartments.measurements,
            "final_mesh_compartment_samples",
            compartments.tolerances,
            measurement_inputs={
                "target_id": target.get("target_id") or target.get("id"),
                "expected_count": target.get("expected_count") or feature.get("expected_count") or 1,
                "compartment_samples": samples,
            },
            geometry_presence="present" if compartments.measurements.get("count", 0) else "absent",
        )
    slot_samples = target.get("slot_samples") or feature.get("slot_samples")
    if isinstance(slot_samples, list):
        slots = measure_slots(
            slot_samples,
            expected_count=int(target.get("expected_count") or feature.get("expected_count") or 1),
            expected_width=_number(target.get("width") or feature.get("width")),
            expected_depth=_number(target.get("depth") or feature.get("depth")),
            tolerance=float(target.get("tolerance_mm") or 0.2),
            required_region=(str(target.get("region")) if target.get("region") else None),
        )
        return _result_payload(
            slots.satisfied,
            "measured",
            slots.reason,
            slots.measurements,
            "final_mesh_slot_samples",
            slots.tolerances,
            measurement_inputs={"slot_samples": slot_samples},
            geometry_presence="present" if slots.measurements.get("count", 0) else "absent",
        )
    return _result_payload(
        False,
        "failed" if target else "unavailable",
        "feature_measurement_failed" if target else "verification_target_missing",
        {"shape_hash": _mesh_hash(mesh), "trace_output_shape_hash": trace.get("output_shape_hash")},
        "final_mesh_feature_probe" if target else "final_mesh_without_feature_target",
        {},
        outcome="measurement_failed" if target else "unverifiable",
        measurement_inputs={"target_id": target.get("target_id") or target.get("id") if target else None},
        geometry_presence="unknown",
    )


def _result_payload(
    passed: bool,
    measurement_status: str,
    reason: str,
    measurements: dict[str, Any],
    method: str,
    tolerances: dict[str, Any],
    *,
    outcome: str | None = None,
    measurement_inputs: dict[str, Any] | None = None,
    geometry_presence: str | None = None,
) -> dict[str, Any]:
    return {
        "geometry_presence": geometry_presence or ("present" if passed else "absent"),
        "measurement_status": measurement_status,
        "measurements": measurements,
        "requirement_outcome": outcome or ("satisfied" if passed else "not_satisfied"),
        "evidence_method": method,
        "measurement_inputs": {"reason": reason, **(measurement_inputs or {})},
        "tolerances": tolerances,
    }


def _source_function_id(feature_id: str, traces: list[dict[str, Any]]) -> str | None:
    if traces:
        return str(traces[0].get("source_function_id") or "") or None
    return f"_ai_feature_{feature_id}" if feature_id else None


def _match_positions(profiles: list[dict[str, Any]], expected_positions: list[Any], *, tolerance: float) -> bool:
    remaining = list(profiles)
    for expected in expected_positions:
        if isinstance(expected, dict):
            target = (_number(expected.get("x")), _number(expected.get("y")))
        elif isinstance(expected, list) and len(expected) >= 2:
            target = (_number(expected[0]), _number(expected[1]))
        else:
            return False
        if any(value is None for value in target):
            return False
        match_index = next(
            (
                index for index, profile in enumerate(remaining)
                if abs(profile["center_x"] - target[0]) <= tolerance
                and abs(profile["center_y"] - target[1]) <= tolerance
            ),
            None,
        )
        if match_index is None:
            return False
        remaining.pop(match_index)
    return not remaining


def _mesh_hash(mesh: Trimesh) -> str:
    digest = hashlib.sha256()
    digest.update(mesh.vertices.astype("<f8", copy=False).tobytes())
    digest.update(mesh.faces.astype("<i8", copy=False).tobytes())
    return digest.hexdigest()


def _number(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def requirement_id_from_feature(feature: dict[str, Any]) -> str:
    return str((feature.get("requirement_ids") or [feature.get("feature_id") or "feature"])[0])


def _first_tolerance(tolerances: dict[str, Any]) -> float | None:
    for value in tolerances.values():
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None
