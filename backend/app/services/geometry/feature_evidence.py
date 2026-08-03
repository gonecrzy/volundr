"""Generic source-to-final-geometry evidence orchestration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from trimesh import Trimesh

from app.services.geometry.feature_measurements import (
    compare_dimension,
    measure_compartments,
    measure_opening_count,
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
        for requirement_id in target.get("requirement_ids", []) or []
    }
    traces_by_feature: dict[str, list[dict[str, Any]]] = {}
    for trace in feature_trace:
        if not isinstance(trace, dict):
            continue
        source_id = str(trace.get("source_function_id") or "")
        feature_id = str(trace.get("feature_id") or "")
        candidates = {feature_id, source_id.removeprefix("_ai_feature_")}
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
        feature_requirement_ids = [str(item) for item in feature.get("requirement_ids", []) or []]
        if not feature_requirement_ids:
            feature_requirement_ids = [feature_id]
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
    target: dict[str, Any],
    topology_metadata: dict[str, Any] | None,
    trace: dict[str, Any],
) -> dict[str, Any]:
    feature_id = str(feature.get("feature_id") or feature.get("id"))
    object_type = str(feature.get("object_type") or "").lower()
    measurement = str(target.get("measurement") or "")
    requested = _number(target.get("value"))
    if measurement in {"width", "depth", "height"} and object_type in {"desktop organizer", "body", "base", "walls"}:
        axis = {"width": 0, "depth": 1, "height": 2}[measurement]
        measured = float(mesh.bounds[1][axis] - mesh.bounds[0][axis])
        comparison = compare_dimension(requested, measured, operator="exact", tolerance=0.2)
        return _result_payload(
            comparison.passed,
            "measured",
            "overall_dimension" if comparison.passed else "dimension_mismatch",
            {"measurement": measurement, "requested_mm": requested, "measured_mm": round(measured, 3)},
            "final_mesh_bounds",
            {"requested_mm": requested, "operator": "exact", "applied_tolerance_mm": 0.2},
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
        )
    probe_points = target.get("probe_points") or feature.get("probe_points")
    if isinstance(probe_points, list) and probe_points:
        axis = str(target.get("axis") or feature.get("opening_axis") or "z")
        opening = measure_opening_count(mesh, axis=axis, points=probe_points)
        return _result_payload(
            opening.satisfied,
            "measured",
            opening.reason,
            opening.measurements,
            "final_mesh_opening_probe",
            {"axis": axis, "minimum_opening_mm": 0.1},
        )
    samples = target.get("compartment_samples") or feature.get("compartment_samples")
    if isinstance(samples, list):
        compartments = measure_compartments(
            samples,
            expected_count=int(target.get("expected_count") or feature.get("expected_count") or 1),
            expected_width=_number(target.get("center_width") or feature.get("center_width")),
            tolerance=float(target.get("tolerance_mm") or 0.2),
        )
        return _result_payload(
            compartments.satisfied,
            "measured",
            compartments.reason,
            compartments.measurements,
            "final_mesh_compartment_samples",
            compartments.tolerances,
        )
    return _result_payload(
        False,
        "failed" if target else "unavailable",
        "feature_measurement_failed" if target else "verification_target_missing",
        {"shape_hash": _mesh_hash(mesh), "trace_output_shape_hash": trace.get("output_shape_hash")},
        "final_mesh_feature_probe" if target else "final_mesh_without_feature_target",
        {},
        outcome="measurement_failed" if target else "unverifiable",
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
) -> dict[str, Any]:
    return {
        "geometry_presence": "present" if passed else "absent",
        "measurement_status": measurement_status,
        "measurements": measurements,
        "requirement_outcome": outcome or ("satisfied" if passed else "not_satisfied"),
        "evidence_method": method,
        "measurement_inputs": {"reason": reason},
        "tolerances": tolerances,
    }


def _source_function_id(feature_id: str, traces: list[dict[str, Any]]) -> str | None:
    if traces:
        return str(traces[0].get("source_function_id") or "") or None
    return f"_ai_feature_{feature_id}" if feature_id else None


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


def requirement_id_from_feature(feature: dict[str, Any]) -> str:
    return str((feature.get("requirement_ids") or [feature.get("feature_id") or "feature"])[0])


def _first_tolerance(tolerances: dict[str, Any]) -> float | None:
    for value in tolerances.values():
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None
