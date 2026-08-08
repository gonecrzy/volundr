"""Independent requirement-compliance and reference-similarity metrics."""

from __future__ import annotations

from typing import Any, Mapping


def compare_reference_geometry(
    *,
    reference: Mapping[str, Any],
    generated: Mapping[str, Any],
    requirement_compliance: Mapping[str, Any] | None = None,
    reference_output_mapping: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    reference_parts = _reference_parts(reference)
    if len(reference_parts) > 1:
        return _compare_multi_part_reference(
            reference=reference,
            generated=generated,
            reference_parts=reference_parts,
            requirement_compliance=requirement_compliance,
            reference_output_mapping=reference_output_mapping,
        )
    reference_geometry = _geometry(reference)
    generated_geometry = _geometry(generated)
    metrics = _geometry_metrics(reference_geometry, generated_geometry)
    measured = any(value is not None for value in metrics.values())
    return {
        "schema_version": "external-cad-comparison-v1",
        "requirement_compliance": dict(requirement_compliance or {"status": "not_run"}),
        "reference_similarity": {
            "status": "measured" if measured else "unavailable",
            "metrics": metrics,
        },
    }


def _compare_multi_part_reference(
    *,
    reference: Mapping[str, Any],
    generated: Mapping[str, Any],
    reference_parts: Mapping[str, Mapping[str, Any]],
    requirement_compliance: Mapping[str, Any] | None,
    reference_output_mapping: Mapping[str, str] | None,
) -> dict[str, Any]:
    generated_parts = _generated_parts(generated)
    mapping = reference_output_mapping or reference.get("reference_output_mapping")
    mapping = mapping if isinstance(mapping, Mapping) else None
    required_ids = set(reference_parts)
    mapped_ids = set(mapping or {})
    valid_mapping = (
        mapping is not None
        and mapped_ids == required_ids
        and len(set(mapping.values())) == len(mapping)
        and set(mapping.values()).issubset(generated_parts)
    )
    per_part: dict[str, Any] = {}
    if valid_mapping:
        for part_id, generated_id in mapping.items():
            per_part[part_id] = _geometry_metrics(
                _geometry(reference_parts[part_id]),
                _geometry(generated_parts[generated_id]),
            )
    aggregate_metrics = _geometry_metrics(
        _geometry(reference.get("aggregate_geometry", {})),
        _geometry(generated.get("aggregate_geometry", {})),
    )
    part_count_agreement = (
        len(reference_parts) == len(generated_parts)
        if generated_parts
        else None
    )
    metrics = {
        "project_part_count_agreement": part_count_agreement,
        "per_part": per_part,
        "aggregate": aggregate_metrics,
    }
    if not valid_mapping:
        metrics["mapping_status"] = "explicit_reference_output_mapping_required"
    measured = valid_mapping and any(
        value is not None
        for part_metrics in per_part.values()
        for value in part_metrics.values()
    )
    return {
        "schema_version": "external-cad-comparison-v1",
        "requirement_compliance": dict(requirement_compliance or {"status": "not_run"}),
        "reference_similarity": {
            "status": "measured" if measured else "unavailable",
            "metrics": metrics,
        },
    }


def _reference_parts(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    parts = payload.get("canonical_parts")
    if not isinstance(parts, list):
        return {}
    result: dict[str, Mapping[str, Any]] = {}
    for part in parts:
        if not isinstance(part, Mapping):
            continue
        part_id = part.get("part_id")
        if isinstance(part_id, str) and part_id.strip():
            result[part_id] = part.get("derived", part)
    return result


def _generated_parts(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    parts = payload.get("parts", payload.get("outputs", {}))
    if not isinstance(parts, Mapping):
        return {}
    return {
        str(output_id): value
        for output_id, value in parts.items()
        if isinstance(value, Mapping)
    }


def _geometry_metrics(
    reference: Mapping[str, Any],
    generated: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "bounding_box_error_by_axis_mm": _bounding_box_error(reference, generated),
        "volume_difference_mm3": _absolute_difference(reference.get("volume_mm3"), generated.get("volume_mm3")),
        "volume_difference_ratio": _relative_difference(reference.get("volume_mm3"), generated.get("volume_mm3")),
        "surface_area_difference_mm2": _absolute_difference(reference.get("surface_area_mm2"), generated.get("surface_area_mm2")),
        "surface_area_difference_ratio": _relative_difference(reference.get("surface_area_mm2"), generated.get("surface_area_mm2")),
        "solid_count_agreement": _agreement(reference.get("solid_count"), generated.get("solid_count")),
    }


def _geometry(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    geometry = payload.get("geometry")
    return geometry if isinstance(geometry, Mapping) else payload


def _bounding_box_error(reference: Mapping[str, Any], generated: Mapping[str, Any]) -> dict[str, float | None]:
    reference_box = reference.get("bounding_box_mm")
    generated_box = generated.get("bounding_box_mm")
    if not isinstance(reference_box, Mapping) or not isinstance(generated_box, Mapping):
        return {"x": None, "y": None, "z": None}
    return {
        axis: _absolute_difference(reference_box.get(f"size_{axis}"), generated_box.get(f"size_{axis}"))
        for axis in ("x", "y", "z")
    }


def _absolute_difference(left: Any, right: Any) -> float | None:
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        return None
    return abs(float(left) - float(right))


def _relative_difference(reference: Any, generated: Any) -> float | None:
    difference = _absolute_difference(reference, generated)
    if difference is None or not isinstance(reference, (int, float)) or float(reference) == 0:
        return None
    return difference / abs(float(reference))


def _agreement(left: Any, right: Any) -> bool | None:
    if not isinstance(left, int) or isinstance(left, bool) or not isinstance(right, int) or isinstance(right, bool):
        return None
    return left == right
