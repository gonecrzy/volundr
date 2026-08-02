"""Deterministic, provider-independent point patterns for CadQuery features."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Mapping


class PatternSpecError(ValueError):
    """A pattern cannot be resolved deterministically from its specification."""


WORKPLANE_LOCAL_2D = "workplane_local_2d"
WORKPLANE_LOCAL_3D = "workplane_local_3d"
COMPONENT_LOCAL_3D = "component_local_3d"
WORLD_3D = "world_3d"
_COORDINATE_SPACES = {
    WORKPLANE_LOCAL_2D,
    WORKPLANE_LOCAL_3D,
    COMPONENT_LOCAL_3D,
    WORLD_3D,
}


@dataclass(frozen=True)
class PatternPointSet:
    """Canonical points plus the provenance needed to audit their construction."""

    points: tuple[tuple[float, ...], ...]
    pattern_type: str
    unit: str = "mm"
    provenance: dict[str, Any] = field(default_factory=dict)
    coordinate_space: str = COMPONENT_LOCAL_3D
    coordinate_frame_id: str | None = None
    arrangement_axis: str | None = None
    point_dimensionality: int | None = None
    consumer_operation: str | None = None
    host_plane: str | None = None
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        normalized = tuple(tuple(_finite_number(value, "point coordinate") for value in point) for point in self.points)
        if any(len(point) not in {2, 3} for point in normalized):
            raise PatternSpecError("pattern points must be two- or three-dimensional")
        dimensionality = self.point_dimensionality or (len(normalized[0]) if normalized else 3)
        if dimensionality not in {2, 3} or any(len(point) != dimensionality for point in normalized):
            raise PatternSpecError("pattern points must have one stable dimensionality")
        if self.coordinate_space not in _COORDINATE_SPACES:
            raise PatternSpecError(f"unsupported coordinate space `{self.coordinate_space}`")
        object.__setattr__(self, "points", normalized)
        object.__setattr__(self, "point_dimensionality", dimensionality)
        payload = {
            "pattern_type": self.pattern_type,
            "unit": self.unit,
            "points": normalized,
            "provenance": self.provenance,
            "coordinate_space": self.coordinate_space,
            "coordinate_frame_id": self.coordinate_frame_id,
            "arrangement_axis": self.arrangement_axis,
            "point_dimensionality": dimensionality,
            "consumer_operation": self.consumer_operation,
            "host_plane": self.host_plane,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        object.__setattr__(self, "content_hash", hashlib.sha256(encoded).hexdigest())

    def __iter__(self):
        return iter(self.points)

    def __len__(self) -> int:
        return len(self.points)


def linear_pattern_points(
    count: int,
    spacing: float,
    axis: str,
    centered: bool = True,
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
    *,
    unit: str = "mm",
    provenance: Mapping[str, Any] | None = None,
    coordinate_space: str = COMPONENT_LOCAL_3D,
    coordinate_frame_id: str | None = None,
    arrangement_axis: str | None = None,
    consumer_operation: str | None = None,
    host_plane: str | None = None,
) -> PatternPointSet:
    count = _positive_integer(count, "count")
    spacing = _finite_number(spacing, "spacing")
    axis_index = _axis_index(axis)
    origin = _origin(origin)
    center = (count - 1) / 2 if centered else 0.0
    points = []
    for index in range(count):
        point = list(origin)
        point[axis_index] += (index - center) * spacing
        points.append(tuple(point))
    return PatternPointSet(
        tuple(points),
        "linear",
        unit,
        _provenance(provenance),
        coordinate_space,
        coordinate_frame_id,
        arrangement_axis or str(axis).upper(),
        3,
        consumer_operation,
        host_plane,
    )


def rectangular_pattern_points(
    rows: int,
    columns: int,
    row_spacing: float,
    column_spacing: float,
    plane: str,
    centered: bool = True,
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
    *,
    unit: str = "mm",
    provenance: Mapping[str, Any] | None = None,
    coordinate_space: str = COMPONENT_LOCAL_3D,
    coordinate_frame_id: str | None = None,
    arrangement_axis: str | None = None,
    consumer_operation: str | None = None,
    host_plane: str | None = None,
) -> PatternPointSet:
    rows = _positive_integer(rows, "rows")
    columns = _positive_integer(columns, "columns")
    row_spacing = _finite_number(row_spacing, "row_spacing")
    column_spacing = _finite_number(column_spacing, "column_spacing")
    plane_axes = _plane_axes(plane)
    origin = _origin(origin)
    row_center = (rows - 1) / 2 if centered else 0.0
    column_center = (columns - 1) / 2 if centered else 0.0
    points = []
    for row in range(rows):
        for column in range(columns):
            point = list(origin)
            point[plane_axes[0]] += (column - column_center) * column_spacing
            point[plane_axes[1]] += (row - row_center) * row_spacing
            points.append(tuple(point))
    return PatternPointSet(
        tuple(points),
        "rectangular",
        unit,
        _provenance(provenance),
        coordinate_space,
        coordinate_frame_id,
        arrangement_axis,
        3,
        consumer_operation,
        host_plane,
    )


def circular_pattern_points(
    count: int,
    radius: float,
    start_angle: float = 0.0,
    *,
    unit: str = "mm",
    provenance: Mapping[str, Any] | None = None,
    coordinate_space: str = WORKPLANE_LOCAL_3D,
    coordinate_frame_id: str | None = None,
    arrangement_axis: str | None = None,
    consumer_operation: str | None = None,
    host_plane: str | None = None,
) -> PatternPointSet:
    count = _positive_integer(count, "count")
    radius = _finite_number(radius, "radius")
    if radius < 0:
        raise PatternSpecError("radius must be non-negative")
    start_angle = _finite_number(start_angle, "start_angle")
    points = tuple(
        (
            radius * math.cos(start_angle + (2 * math.pi * index / count)),
            radius * math.sin(start_angle + (2 * math.pi * index / count)),
            0.0,
        )
        for index in range(count)
    )
    return PatternPointSet(
        points,
        "circular",
        unit,
        _provenance(provenance),
        coordinate_space,
        coordinate_frame_id,
        arrangement_axis,
        3,
        consumer_operation,
        host_plane,
    )


def resolve_pattern_points(pattern: Mapping[str, Any], params: Mapping[str, Any]) -> PatternPointSet:
    """Resolve an approved Design Plan pattern from canonical parameter values."""

    pattern_id = str(pattern.get("pattern_id") or "")
    if not pattern_id:
        raise PatternSpecError("pattern_id is required")
    pattern_type = str(pattern.get("pattern_type") or "").lower()
    unit = str(pattern.get("unit") or "mm")
    source_ids = _source_parameter_ids(pattern, pattern_type)
    values = {
        "pattern_id": pattern_id,
        "source_parameter_ids": source_ids,
        "relationship": "pattern_points",
    }
    provenance = dict(pattern.get("provenance") or {})
    provenance.update(values)
    coordinate_space = str(pattern.get("coordinate_space") or COMPONENT_LOCAL_3D)
    coordinate_frame_id = pattern.get("coordinate_frame_id") or pattern.get("frame_id")
    arrangement_axis = pattern.get("arrangement_axis") or pattern.get("axis")
    consumer_operation = pattern.get("consumer_operation")
    host_plane = pattern.get("host_plane") or pattern.get("workplane")
    if pattern_type == "linear":
        return linear_pattern_points(
            _parameter_or_value(params, pattern, "count_parameter_id", "count"),
            _parameter_or_value(params, pattern, "spacing_parameter_id", "spacing"),
            str(pattern.get("axis") or ""),
            bool(pattern.get("centered", True)),
            tuple(pattern.get("origin") or (0.0, 0.0, 0.0)),
            unit=unit,
            provenance=provenance,
            coordinate_space=coordinate_space,
            coordinate_frame_id=str(coordinate_frame_id) if coordinate_frame_id else None,
            arrangement_axis=str(arrangement_axis).upper() if arrangement_axis else None,
            consumer_operation=str(consumer_operation) if consumer_operation else None,
            host_plane=str(host_plane) if host_plane else None,
        )
    if pattern_type == "rectangular":
        return rectangular_pattern_points(
            _parameter_or_value(params, pattern, "rows_parameter_id", "rows"),
            _parameter_or_value(params, pattern, "columns_parameter_id", "columns"),
            _parameter_or_value(params, pattern, "row_spacing_parameter_id", "row_spacing"),
            _parameter_or_value(params, pattern, "column_spacing_parameter_id", "column_spacing"),
            str(pattern.get("plane") or ""),
            bool(pattern.get("centered", True)),
            tuple(pattern.get("origin") or (0.0, 0.0, 0.0)),
            unit=unit,
            provenance=provenance,
            coordinate_space=coordinate_space,
            coordinate_frame_id=str(coordinate_frame_id) if coordinate_frame_id else None,
            arrangement_axis=str(arrangement_axis).upper() if arrangement_axis else None,
            consumer_operation=str(consumer_operation) if consumer_operation else None,
            host_plane=str(host_plane) if host_plane else None,
        )
    if pattern_type == "circular":
        return circular_pattern_points(
            _parameter_or_value(params, pattern, "count_parameter_id", "count"),
            _parameter_or_value(params, pattern, "radius_parameter_id", "radius"),
            float(pattern.get("start_angle") or 0.0),
            unit=unit,
            provenance=provenance,
            coordinate_space=coordinate_space,
            coordinate_frame_id=str(coordinate_frame_id) if coordinate_frame_id else None,
            arrangement_axis=str(arrangement_axis).upper() if arrangement_axis else None,
            consumer_operation=str(consumer_operation) if consumer_operation else None,
            host_plane=str(host_plane) if host_plane else None,
        )
    if pattern_type == "explicit":
        points = []
        for point in pattern.get("positions") or []:
            if isinstance(point, Mapping):
                points.append((point.get("x", 0.0), point.get("y", 0.0), point.get("z", 0.0)))
            else:
                points.append(tuple(point))
        return PatternPointSet(
            tuple(points),
            "explicit",
            unit,
            provenance,
            coordinate_space,
            str(coordinate_frame_id) if coordinate_frame_id else None,
            str(arrangement_axis).upper() if arrangement_axis else None,
            None,
            str(consumer_operation) if consumer_operation else None,
            str(host_plane) if host_plane else None,
        )
    raise PatternSpecError(f"unsupported pattern_type `{pattern_type}`")


def _source_parameter_ids(pattern: Mapping[str, Any], pattern_type: str) -> list[str]:
    keys = {
        "linear": ("count_parameter_id", "spacing_parameter_id"),
        "rectangular": (
            "rows_parameter_id",
            "columns_parameter_id",
            "row_spacing_parameter_id",
            "column_spacing_parameter_id",
        ),
        "circular": ("count_parameter_id", "radius_parameter_id"),
    }.get(pattern_type, ())
    return [str(pattern[key]) for key in keys if pattern.get(key)]


def _parameter(params: Mapping[str, Any], pattern: Mapping[str, Any], key: str) -> Any:
    parameter_id = str(pattern.get(key) or "")
    if not parameter_id:
        raise PatternSpecError(f"{key} is required")
    if parameter_id not in params:
        raise PatternSpecError(f"pattern parameter `{parameter_id}` is not resolved")
    return params[parameter_id]


def _parameter_or_value(
    params: Mapping[str, Any],
    pattern: Mapping[str, Any],
    parameter_key: str,
    numeric_key: str,
) -> Any:
    parameter_id = str(pattern.get(parameter_key) or "")
    if parameter_id:
        if parameter_id not in params:
            raise PatternSpecError(f"pattern parameter `{parameter_id}` is not resolved")
        value = params[parameter_id]
        if numeric_key in {"count", "rows", "columns"} and isinstance(value, float) and value.is_integer():
            return int(value)
        return value
    if numeric_key in pattern and pattern[numeric_key] is not None:
        value = pattern[numeric_key]
        if numeric_key in {"count", "rows", "columns"} and isinstance(value, float) and value.is_integer():
            return int(value)
        return value
    raise PatternSpecError(f"{parameter_key} or {numeric_key} is required")


def _positive_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PatternSpecError(f"{label} must be a positive integer")
    return value


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(float(value)):
        raise PatternSpecError(f"{label} must be finite")
    return float(value)


def _axis_index(axis: str) -> int:
    normalized = str(axis).upper()
    if normalized not in {"X", "Y", "Z"}:
        raise PatternSpecError(f"unsupported axis `{axis}`")
    return {"X": 0, "Y": 1, "Z": 2}[normalized]


def _plane_axes(plane: str) -> tuple[int, int]:
    normalized = str(plane).upper()
    if normalized not in {"XY", "XZ", "YZ"}:
        raise PatternSpecError(f"unsupported plane `{plane}`")
    return {"XY": (0, 1), "XZ": (0, 2), "YZ": (1, 2)}[normalized]


def _origin(origin: Any) -> tuple[float, float, float]:
    if not isinstance(origin, (tuple, list)) or len(origin) != 3:
        raise PatternSpecError("origin must contain three coordinates")
    return tuple(_finite_number(value, "origin coordinate") for value in origin)  # type: ignore[return-value]


def _provenance(provenance: Mapping[str, Any] | None) -> dict[str, Any]:
    result = dict(provenance or {})
    result.setdefault("effect_parameter_ids", [])
    return result
