"""Neutral CadQuery/OCP topology measurements for executable-CadQuery recovery."""

from __future__ import annotations

from itertools import combinations
from typing import Any

import cadquery as cq


TOPOLOGY_EVIDENCE_SCHEMA_VERSION = "topology-evidence-v2"
MEASUREMENT_TOLERANCE_MM = 1e-7
_STANDARDIZED_EVIDENCE_FIELDS = (
    "disconnected_solid_policy",
    "measurement_tolerance_mm",
    "overall_bounding_box",
    "overall_shape_valid",
    "schema_version",
    "solid_pairs",
    "solids",
)
_NON_MATERIAL_EVIDENCE_FIELDS = {"measurement_tolerance_mm", "schema_version"}


def compare_topology_evidence(
    historical: Any,
    current: Any,
) -> dict[str, Any]:
    """Compare standardized topology facts without treating source changes as progress."""

    prior = historical if isinstance(historical, dict) else {}
    latest = current if isinstance(current, dict) else {}
    historical_fields = sorted(
        field for field in _STANDARDIZED_EVIDENCE_FIELDS if field in prior
    )
    current_fields = sorted(
        field for field in _STANDARDIZED_EVIDENCE_FIELDS if field in latest
    )
    new_fields = sorted(set(current_fields) - set(historical_fields))
    material_new_fields = [
        field for field in new_fields if field not in _NON_MATERIAL_EVIDENCE_FIELDS
    ]
    return {
        "historical_fields_available": historical_fields,
        "current_fields_available": current_fields,
        "new_standardized_fields": new_fields,
        "material_new_fields": material_new_fields,
        "material_diagnostic_improvement": bool(material_new_fields),
        "materially_equivalent": not bool(material_new_fields),
    }


def collect_topology_evidence(
    model: Any,
    *,
    expected_solid_count: int,
    allow_disconnected_solids: bool,
) -> dict[str, Any]:
    """Measure a model without recommending a geometry operation or strategy."""

    evidence: dict[str, Any] = {
        "schema_version": TOPOLOGY_EVIDENCE_SCHEMA_VERSION,
        "status": "unavailable",
        "measurement_tolerance_mm": MEASUREMENT_TOLERANCE_MM,
        "expected_solid_count": int(expected_solid_count),
        "detected_solid_count": 0,
        "disconnected_solid_policy": {
            "allow_disconnected_solids": bool(allow_disconnected_solids),
        },
        "allow_disconnected_solids": bool(allow_disconnected_solids),
        "overall_shape_valid": False,
        "valid": False,
        "volume_mm3": None,
        "shell_count": None,
        "face_count": None,
        "bounding_box_mm": None,
        "overall_bounding_box": None,
        "solids": [],
        "solid_pairs": [],
        "measurement_errors": [],
    }

    shape = _shape_for(model, evidence["measurement_errors"])
    if shape is None:
        evidence["measurement_errors"].append("model shape is unavailable")
        return evidence

    evidence["status"] = "measured"
    overall_valid = _safe_bool_method(shape, "isValid", evidence["measurement_errors"])
    evidence["overall_shape_valid"] = bool(overall_valid) if overall_valid is not None else False
    evidence["volume_mm3"] = _safe_float_method(shape, "Volume", evidence["measurement_errors"])
    evidence["shell_count"] = _safe_count_method(shape, "Shells", evidence["measurement_errors"])
    evidence["face_count"] = _safe_count_method(shape, "Faces", evidence["measurement_errors"])
    evidence["bounding_box_mm"] = _bounding_box(shape, evidence["measurement_errors"])
    evidence["overall_bounding_box"] = evidence["bounding_box_mm"]

    solids = _solid_list(shape, evidence["measurement_errors"])
    evidence["detected_solid_count"] = len(solids)
    evidence["solids"] = [
        _solid_measurement(index, solid, evidence["measurement_errors"])
        for index, solid in enumerate(solids)
    ]
    evidence["solid_pairs"] = [
        _pair_measurement(left_index, left, right_index, right, evidence["measurement_errors"])
        for (left_index, left), (right_index, right) in combinations(enumerate(solids), 2)
    ]

    outcome = "valid"
    valid = evidence["overall_shape_valid"]
    if evidence["volume_mm3"] is not None and evidence["volume_mm3"] <= 0:
        valid = False
        outcome = "empty"
    if len(solids) != int(expected_solid_count) and not allow_disconnected_solids:
        valid = False
        outcome = "solid_count_mismatch"
    if not valid and outcome == "valid":
        outcome = "invalid"
    if not solids and evidence["volume_mm3"] in {None, 0.0}:
        valid = False
        outcome = "empty"

    evidence["valid"] = bool(valid)
    evidence["outcome"] = outcome
    return evidence


def _shape_for(model: Any, errors: list[str]) -> Any | None:
    if model is None:
        return None
    if hasattr(model, "val"):
        try:
            return model.val()
        except Exception as exc:  # pragma: no cover - defensive worker boundary
            errors.append(f"model.val failed: {type(exc).__name__}")
            return None
    return model


def _solid_list(shape: Any, errors: list[str]) -> list[Any]:
    solids_method = getattr(shape, "Solids", None)
    if not callable(solids_method):
        errors.append("shape does not expose Solids")
        return []
    try:
        return list(solids_method())
    except Exception as exc:  # pragma: no cover - defensive worker boundary
        errors.append(f"shape.Solids failed: {type(exc).__name__}")
        return []


def _solid_measurement(index: int, solid: Any, errors: list[str]) -> dict[str, Any]:
    return {
        "solid_index": index,
        "solid_id": f"solid-{index}",
        "valid": _safe_bool_method(solid, "isValid", errors),
        "volume_mm3": _safe_float_method(solid, "Volume", errors),
        "bounding_box_mm": _bounding_box(solid, errors),
        "centroid_mm": _centroid(solid, errors),
        "shell_count": _safe_count_method(solid, "Shells", errors),
        "face_count": _safe_count_method(solid, "Faces", errors),
    }


def _pair_measurement(
    left_index: int,
    left: Any,
    right_index: int,
    right: Any,
    errors: list[str],
) -> dict[str, Any]:
    distance: float | None = None
    overlap: float | None = None
    pair_errors: list[str] = []

    try:
        distance = _as_float(left.distance(right))
    except Exception as exc:  # pragma: no cover - defensive worker boundary
        pair_errors.append(f"distance unavailable: {type(exc).__name__}")
    try:
        intersection = left.intersect(right)
        overlap = _as_float(intersection.Volume())
    except Exception as exc:  # pragma: no cover - defensive worker boundary
        pair_errors.append(f"overlapping volume unavailable: {type(exc).__name__}")

    if pair_errors:
        errors.extend(
            f"pair {left_index},{right_index}: {message}" for message in pair_errors
        )
    intersects: bool | None = None
    touches: bool | None = None
    if overlap is not None or distance is not None:
        intersects = bool(
            (overlap is not None and overlap > MEASUREMENT_TOLERANCE_MM)
            or (distance is not None and distance <= MEASUREMENT_TOLERANCE_MM)
        )
    if overlap is not None and distance is not None:
        touches = bool(
            distance <= MEASUREMENT_TOLERANCE_MM
            and overlap <= MEASUREMENT_TOLERANCE_MM
        )

    return {
        "solid_index_a": left_index,
        "solid_id_a": f"solid-{left_index}",
        "solid_index_b": right_index,
        "solid_id_b": f"solid-{right_index}",
        "intersects": intersects,
        "touches": touches,
        "minimum_separation_mm": distance,
        "overlapping_volume_mm3": overlap,
        "measurement_errors": pair_errors,
    }


def _bounding_box(shape: Any, errors: list[str]) -> dict[str, float | None] | None:
    method = getattr(shape, "BoundingBox", None)
    if not callable(method):
        errors.append("shape does not expose BoundingBox")
        return None
    try:
        box = method()
    except Exception as exc:  # pragma: no cover - defensive worker boundary
        errors.append(f"BoundingBox failed: {type(exc).__name__}")
        return None
    return {
        "x_min": _numeric_attr(box, "xmin"),
        "x_max": _numeric_attr(box, "xmax"),
        "y_min": _numeric_attr(box, "ymin"),
        "y_max": _numeric_attr(box, "ymax"),
        "z_min": _numeric_attr(box, "zmin"),
        "z_max": _numeric_attr(box, "zmax"),
        "size_x": _numeric_attr(box, "xlen"),
        "size_y": _numeric_attr(box, "ylen"),
        "size_z": _numeric_attr(box, "zlen"),
    }


def _centroid(solid: Any, errors: list[str]) -> dict[str, float | None] | None:
    try:
        centroid = cq.Shape.centerOfMass(solid)
    except Exception as exc:  # pragma: no cover - defensive worker boundary
        errors.append(f"center of mass unavailable: {type(exc).__name__}")
        return None
    return {
        "x": _numeric_attr(centroid, "x"),
        "y": _numeric_attr(centroid, "y"),
        "z": _numeric_attr(centroid, "z"),
    }


def _safe_bool_method(shape: Any, name: str, errors: list[str]) -> bool | None:
    method = getattr(shape, name, None)
    if not callable(method):
        errors.append(f"shape does not expose {name}")
        return None
    try:
        return bool(method())
    except Exception as exc:  # pragma: no cover - defensive worker boundary
        errors.append(f"{name} failed: {type(exc).__name__}")
        return None


def _safe_float_method(shape: Any, name: str, errors: list[str]) -> float | None:
    method = getattr(shape, name, None)
    if not callable(method):
        errors.append(f"shape does not expose {name}")
        return None
    try:
        return _as_float(method())
    except Exception as exc:  # pragma: no cover - defensive worker boundary
        errors.append(f"{name} failed: {type(exc).__name__}")
        return None


def _safe_count_method(shape: Any, name: str, errors: list[str]) -> int | None:
    method = getattr(shape, name, None)
    if not callable(method):
        errors.append(f"shape does not expose {name}")
        return None
    try:
        return len(method())
    except Exception as exc:  # pragma: no cover - defensive worker boundary
        errors.append(f"{name} failed: {type(exc).__name__}")
        return None


def _numeric_attr(value: Any, name: str) -> float | None:
    attribute = getattr(value, name, None)
    if callable(attribute):
        attribute = attribute()
    if isinstance(attribute, (int, float)):
        return float(attribute)
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None
