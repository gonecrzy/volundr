"""Bounded policy for one feature-informed revision operation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class FeatureRepairContext:
    feature_id: str
    requirement_ids: list[str]
    source_function_id: str | None
    failed_measurements: dict[str, Any]
    source_statements: list[str]
    final_geometry_summary: dict[str, Any]
    approved_parameters: list[str]
    required_result: str
    prohibited_changes: list[str]
    protected_hashes: dict[str, str] = field(default_factory=dict)
    max_provider_calls: int = 1
    output_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def build_feature_repair_context(
    findings: Iterable[dict[str, Any]],
    *,
    worker_succeeded: bool,
    topology_valid: bool,
) -> FeatureRepairContext:
    """Build context only when exactly one feature is repairable."""

    candidates = [item for item in findings if isinstance(item, dict) and _feature_id(item)]
    feature_ids = sorted({_feature_id(item) for item in candidates})
    if len(feature_ids) != 1:
        raise ValueError("feature repair must target exactly one feature")
    if not worker_succeeded or not topology_valid:
        raise ValueError("feature repair requires a successful or repairable topology result")
    selected = candidates[0]
    metadata = selected.get("metadata") if isinstance(selected.get("metadata"), dict) else {}
    record = metadata.get("record") if isinstance(metadata.get("record"), dict) else metadata
    trace = record.get("source_trace") if isinstance(record.get("source_trace"), dict) else {}
    source_statements = record.get("source_statements") or metadata.get("source_statements") or []
    return FeatureRepairContext(
        feature_id=feature_ids[0],
        requirement_ids=[
            str(value)
            for value in (
                record.get("requirement_ids")
                or ([record.get("requirement_id")] if record.get("requirement_id") else [])
            )
        ],
        source_function_id=(
            str(record.get("source_function_id"))
            if record.get("source_function_id") else None
        ),
        failed_measurements=dict(record.get("measurements") or {}),
        source_statements=[str(value) for value in source_statements if value],
        final_geometry_summary=dict(record.get("final_geometry_summary") or {}),
        approved_parameters=[str(value) for value in record.get("approved_parameters", []) or []],
        required_result=str(record.get("required_result") or "modified_shape"),
        prohibited_changes=[
            "Do not change unrelated feature slots.",
            "Do not add outputs, component IDs, or exposed controls.",
            "Do not replace an integral feature with a disconnected compound.",
            "Do not regenerate or promote an output without final remeasurement.",
        ],
        protected_hashes={
            str(key): str(value)
            for key, value in (record.get("protected_hashes") or {}).items()
            if value
        },
        max_provider_calls=1,
        output_id=(str(record.get("output_id")) if record.get("output_id") else None),
    )


def is_feature_repair_request(reason: str, findings: Iterable[dict[str, Any]]) -> bool:
    """Recognize the frontend geometric-finding path without broadening repairs."""

    if reason == "feature_repair":
        return True
    candidates = [item for item in findings if isinstance(item, dict) and _feature_id(item)]
    return (
        reason == "geometric_finding"
        and len(candidates) == 1
        and str(candidates[0].get("category") or "") == "geometry_feature"
    )


def validate_feature_repair_result(
    context: FeatureRepairContext,
    *,
    before: dict[str, Any],
    after: dict[str, Any],
    provider_calls: int,
) -> dict[str, Any]:
    """Reject unchanged, regressive, unrelated, or multi-call repairs."""

    if provider_calls > context.max_provider_calls:
        return {"accepted": False, "reason": "repair_call_limit_exceeded"}
    if before == after:
        return {"accepted": False, "reason": "repair_unchanged"}
    if before.get("output_ids") != after.get("output_ids"):
        return {"accepted": False, "reason": "repair_created_or_removed_output"}
    for key, expected_hash in context.protected_hashes.items():
        if after.get("hashes", {}).get(key) != expected_hash:
            return {"accepted": False, "reason": "repair_changed_unaffected_feature", "key": key}
    if after.get("detected_solid_count") not in {None, 1}:
        return {"accepted": False, "reason": "repair_disconnected_output"}
    evidence = after.get("feature_evidence")
    if not isinstance(evidence, dict):
        return {"accepted": False, "reason": "repair_feature_evidence_missing"}
    if evidence.get("feature_id") not in {None, context.feature_id}:
        return {"accepted": False, "reason": "repair_feature_evidence_mismatch"}
    if evidence.get("requirement_outcome") not in {"satisfied", "satisfied_with_warning"}:
        return {"accepted": False, "reason": "repair_feature_not_satisfied"}
    if evidence.get("measurement_status") != "measured":
        return {"accepted": False, "reason": "repair_feature_not_measured"}
    measurements = evidence.get("measurements")
    if isinstance(measurements, dict):
        if measurements.get("connected_to_primary_body") is False:
            return {"accepted": False, "reason": "repair_feature_disconnected"}
        overlap = measurements.get("material_overlap_volume_estimate_mm3")
        if overlap is not None:
            try:
                if float(overlap) <= 0:
                    return {"accepted": False, "reason": "repair_material_overlap_missing"}
            except (TypeError, ValueError):
                return {"accepted": False, "reason": "repair_material_overlap_unverifiable"}
    return {
        "accepted": True,
        "reason": "localized_feature_repair",
        "feature_id": context.feature_id,
        "provider_calls": provider_calls,
        "protected_hashes": dict(context.protected_hashes),
    }


def _feature_id(item: dict[str, Any]) -> str | None:
    value = item.get("feature_id")
    if value:
        return str(value)
    metadata = item.get("metadata")
    if isinstance(metadata, dict) and metadata.get("feature_id"):
        return str(metadata["feature_id"])
    return None
