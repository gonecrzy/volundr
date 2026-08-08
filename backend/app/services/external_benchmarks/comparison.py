"""Independent requirement-compliance and reference-similarity metrics."""

from __future__ import annotations

from typing import Any, Mapping


def compare_reference_geometry(
    *,
    reference: Mapping[str, Any],
    generated: Mapping[str, Any],
    requirement_compliance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    reference_geometry = _geometry(reference)
    generated_geometry = _geometry(generated)
    metrics = {
        "bounding_box_error_by_axis_mm": _bounding_box_error(reference_geometry, generated_geometry),
        "volume_difference_mm3": _absolute_difference(reference_geometry.get("volume_mm3"), generated_geometry.get("volume_mm3")),
        "volume_difference_ratio": _relative_difference(reference_geometry.get("volume_mm3"), generated_geometry.get("volume_mm3")),
        "surface_area_difference_mm2": _absolute_difference(reference_geometry.get("surface_area_mm2"), generated_geometry.get("surface_area_mm2")),
        "surface_area_difference_ratio": _relative_difference(reference_geometry.get("surface_area_mm2"), generated_geometry.get("surface_area_mm2")),
        "solid_count_agreement": _agreement(reference_geometry.get("solid_count"), generated_geometry.get("solid_count")),
    }
    measured = any(value is not None for value in metrics.values())
    return {
        "schema_version": "external-cad-comparison-v1",
        "requirement_compliance": dict(requirement_compliance or {"status": "not_run"}),
        "reference_similarity": {
            "status": "measured" if measured else "unavailable",
            "metrics": metrics,
        },
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
