"""Coordinate-space contracts for repeated CadQuery feature placements.

Pattern helpers produce canonical placements in an explicitly declared space.
Consumers such as ``pushPoints`` are checked against the frame they actually
consume; no coordinate is silently dropped or projected.
"""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


WORKPLANE_LOCAL_2D = "workplane_local_2d"
WORKPLANE_LOCAL_3D = "workplane_local_3d"
COMPONENT_LOCAL_3D = "component_local_3d"
WORLD_3D = "world_3d"
_SPACES = {WORKPLANE_LOCAL_2D, WORKPLANE_LOCAL_3D, COMPONENT_LOCAL_3D, WORLD_3D}
_AXES = {"X": 0, "Y": 1, "Z": 2}
_FACES_RE = re.compile(r"faces\(\s*['\"](?P<selector>[<>]?[XYZ])['\"]\s*\)")
_WORKPLANE_RE = re.compile(r"workplane\(\s*['\"](?P<plane>[XYZ]{2})['\"]\s*\)")


@dataclass(frozen=True)
class PatternPointEvidence:
    valid: bool
    local_points: tuple[tuple[float, float], ...] | None
    finding: dict[str, Any] | None


def validate_push_points(
    points: Iterable[Iterable[float]],
    *,
    coordinate_space: str,
    workplane_normal_axis: str = "Z",
    pattern_id: str | None = None,
    function_id: str | None = None,
    coordinate_frame_id: str | None = None,
) -> PatternPointEvidence:
    normalized = _normalize_points(points)
    space = str(coordinate_space or "")
    normal_axis = _axis(workplane_normal_axis)
    if space == WORKPLANE_LOCAL_2D:
        return PatternPointEvidence(True, tuple(_in_plane(point, normal_axis) for point in normalized), None)
    if space == WORKPLANE_LOCAL_3D:
        normal_values = [point[_AXES[normal_axis]] for point in normalized]
        if all(math.isclose(value, 0.0, abs_tol=1e-6) for value in normal_values):
            return PatternPointEvidence(True, tuple(_in_plane(point, _AXES[normal_axis]) for point in normalized), None)
        return PatternPointEvidence(
            False,
            None,
            _finding(
                "geometry_body.push_points_nonplanar",
                pattern_id=pattern_id,
                function_id=function_id,
                coordinate_space=space,
                coordinate_frame_id=coordinate_frame_id,
                original_points=normalized,
                workplane_normal_axis=normal_axis,
                coplanar=False,
                repair_eligibility="compatible_plane_or_placement",
            ),
        )
    if space in {COMPONENT_LOCAL_3D, WORLD_3D}:
        return PatternPointEvidence(
            False,
            None,
            _finding(
                "geometry_body.pattern_coordinate_space_mismatch",
                pattern_id=pattern_id,
                function_id=function_id,
                coordinate_space=space,
                coordinate_frame_id=coordinate_frame_id,
                original_points=normalized,
                workplane_normal_axis=normal_axis,
                coplanar=None,
                repair_eligibility="placement_or_compatible_plane",
            ),
        )
    return PatternPointEvidence(
        False,
        None,
        _finding(
            "geometry_body.pattern_coordinate_space_mismatch",
            pattern_id=pattern_id,
            function_id=function_id,
            coordinate_space=space,
            coordinate_frame_id=coordinate_frame_id,
            original_points=normalized,
            workplane_normal_axis=normal_axis,
            coplanar=None,
            repair_eligibility="declare_supported_coordinate_space",
        ),
    )


def convert_points_to_workplane(
    points: Iterable[Iterable[float]],
    *,
    coordinate_space: str,
    source_frame: Mapping[str, Any] | None,
    workplane_frame: Mapping[str, Any] | None,
    pattern_id: str | None = None,
    function_id: str | None = None,
) -> PatternPointEvidence:
    normalized = _normalize_points(points)
    if coordinate_space in {WORKPLANE_LOCAL_2D, WORKPLANE_LOCAL_3D}:
        return validate_push_points(
            normalized,
            coordinate_space=coordinate_space,
            workplane_normal_axis=_frame_normal(workplane_frame),
            pattern_id=pattern_id,
            function_id=function_id,
        )
    if coordinate_space not in {COMPONENT_LOCAL_3D, WORLD_3D} or source_frame is None or workplane_frame is None:
        return PatternPointEvidence(
            False,
            None,
            _finding(
                "geometry_body.pattern_transform_missing",
                pattern_id=pattern_id,
                function_id=function_id,
                coordinate_space=coordinate_space,
                original_points=normalized,
                coplanar=None,
                repair_eligibility="placement_or_compatible_plane",
            ),
        )
    world_points = tuple(_to_world(point, source_frame, coordinate_space) for point in normalized)
    local_points_3d = tuple(_from_world(point, workplane_frame) for point in world_points)
    normal_axis = _frame_normal(workplane_frame)
    normal_values = [point[_AXES[normal_axis]] for point in local_points_3d]
    if not all(math.isclose(value, 0.0, abs_tol=1e-6) for value in normal_values):
        return PatternPointEvidence(
            False,
            None,
            _finding(
                "geometry_body.pattern_coordinate_space_mismatch",
                pattern_id=pattern_id,
                function_id=function_id,
                coordinate_space=coordinate_space,
                original_points=normalized,
                transformed_local_points=local_points_3d,
                workplane_normal_axis=normal_axis,
                coplanar=False,
                repair_eligibility="placement_or_compatible_plane",
            ),
        )
    local_points = tuple(_in_plane(point, _AXES[normal_axis]) for point in local_points_3d)
    return PatternPointEvidence(
        True,
        local_points,
        _finding(
            "geometry_body.pattern_points_converted_to_local",
            pattern_id=pattern_id,
            function_id=function_id,
            coordinate_space=coordinate_space,
            original_points=normalized,
            transformed_local_points=local_points_3d,
            local_points=local_points,
            workplane_normal_axis=normal_axis,
            coplanar=True,
            blocking=False,
            repair_eligibility="none",
        ),
    )


def validate_pattern_push_points_source(
    source: str,
    pattern_manifest: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Audit direct ``pushPoints`` use against the canonical pattern manifest."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    manifests = {
        str(item.get("point_parameter_id")): item
        for item in pattern_manifest
        if item.get("point_parameter_id")
    }
    findings: list[dict[str, Any]] = []
    for function in (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)):
        aliases = _point_aliases(function)
        for call in (node for node in ast.walk(function) if isinstance(node, ast.Call)):
            if not isinstance(call.func, ast.Attribute) or call.func.attr != "pushPoints" or not call.args:
                continue
            parameter_ids = _point_parameter_ids(call.args[0], aliases)
            if len(parameter_ids) != 1:
                continue
            parameter_id = next(iter(parameter_ids))
            manifest = manifests.get(parameter_id)
            if manifest is None:
                continue
            workplane_axis = _workplane_normal_axis(call)
            coordinate_space = str(manifest.get("coordinate_space") or COMPONENT_LOCAL_3D)
            points = manifest.get("resolved_points")
            if _is_explicit_conversion(call.args[0]):
                continue
            evidence = validate_push_points(
                points or [],
                coordinate_space=coordinate_space,
                workplane_normal_axis=workplane_axis,
                pattern_id=str(manifest.get("pattern_id") or "") or None,
                function_id=function.name,
                coordinate_frame_id=str(manifest.get("coordinate_frame_id") or "") or None,
            )
            if evidence.finding is None:
                continue
            finding = dict(evidence.finding)
            finding.update(
                {
                    "source_statement": ast.unparse(call),
                    "workplane_frame": {
                        "normal_axis": workplane_axis,
                        "consumer": "pushPoints",
                    },
                    "point_parameter_id": parameter_id,
                    "arrangement_axis": manifest.get("arrangement_axis"),
                    "owner_component_id": manifest.get("owning_component_id"),
                    "owner_feature_id": manifest.get("owning_feature_id"),
                    "canonical_points": points,
                }
            )
            findings.append(finding)
    return findings


def _normalize_points(points: Iterable[Iterable[float]]) -> tuple[tuple[float, ...], ...]:
    result: list[tuple[float, ...]] = []
    for point in points:
        values = tuple(_finite(value) for value in point)
        if len(values) not in {2, 3}:
            raise ValueError("pattern points must be two- or three-dimensional")
        result.append(values)
    return tuple(result)


def _finite(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("pattern coordinates must be finite")
    return number


def _axis(value: str) -> str:
    normalized = str(value or "Z").upper()
    if normalized not in _AXES:
        raise ValueError(f"unsupported workplane axis `{value}`")
    return normalized


def _frame_normal(frame: Mapping[str, Any] | None) -> str:
    return _axis(str((frame or {}).get("normal_axis") or "Z"))


def _in_plane(point: tuple[float, ...], normal_index: int) -> tuple[float, float]:
    if len(point) == 2:
        return point  # type: ignore[return-value]
    values = point if len(point) == 3 else (*point, 0.0)
    return tuple(values[index] for index in range(3) if index != normal_index)  # type: ignore[return-value]


def _frame_axes(frame: Mapping[str, Any]) -> tuple[tuple[float, float, float], ...]:
    axes = frame.get("axes")
    if isinstance(axes, list) and len(axes) == 3:
        return tuple(tuple(_finite(value) for value in axis) for axis in axes)  # type: ignore[return-value]
    normal = _frame_normal(frame)
    if normal == "X":
        return ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0))
    if normal == "Y":
        return ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0))
    return ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def _origin(frame: Mapping[str, Any]) -> tuple[float, float, float]:
    values = frame.get("origin") or (0.0, 0.0, 0.0)
    return tuple(_finite(value) for value in values)  # type: ignore[return-value]


def _to_world(point: tuple[float, ...], frame: Mapping[str, Any], space: str) -> tuple[float, float, float]:
    values = (*point, 0.0) if len(point) == 2 else point
    axes = _frame_axes(frame)
    origin = _origin(frame)
    return tuple(origin[index] + sum(values[axis] * axes[axis][index] for axis in range(3)) for index in range(3))


def _from_world(point: tuple[float, float, float], frame: Mapping[str, Any]) -> tuple[float, float, float]:
    delta = tuple(point[index] - _origin(frame)[index] for index in range(3))
    axes = _frame_axes(frame)
    return tuple(sum(delta[index] * axes[axis][index] for index in range(3)) for axis in range(3))


def _finding(rule_id: str, **details: Any) -> dict[str, Any]:
    blocking = bool(details.pop("blocking", True))
    return {
        "rule_id": rule_id,
        "category": "geometry_body",
        "severity": "critical" if blocking else "warning",
        "blocking": blocking,
        "is_blocking": blocking,
        **details,
    }


def _point_aliases(function: ast.FunctionDef) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(function):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        parameter_id = _parameter_id(node.value)
        if parameter_id is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                aliases[target.id] = parameter_id
    return aliases


def _parameter_id(node: ast.AST) -> str | None:
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "params":
        return _string(node.slice)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if isinstance(node.func.value, ast.Name) and node.func.value.id == "params" and node.func.attr == "get" and node.args:
            return _string(node.args[0])
    return None


def _point_parameter_id(node: ast.AST, aliases: Mapping[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return aliases.get(node.id)
    return _parameter_id(node)


def _point_parameter_ids(node: ast.AST, aliases: Mapping[str, str]) -> set[str]:
    direct = _point_parameter_id(node, aliases)
    if direct is not None:
        return {direct}
    return {
        aliases[item.id]
        for item in ast.walk(node)
        if isinstance(item, ast.Name) and item.id in aliases
    }


def _string(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _workplane_normal_axis(call: ast.Call) -> str:
    expression = ast.unparse(call.func.value)
    face_match = _FACES_RE.search(expression)
    if face_match:
        return _axis(face_match.group("selector")[-1])
    plane_match = _WORKPLANE_RE.search(expression)
    if plane_match:
        plane = plane_match.group("plane")
        return next(axis for axis in _AXES if axis not in plane)
    return "Z"


def _is_explicit_conversion(node: ast.AST) -> bool:
    return any(
        isinstance(item, ast.Name)
        and item.id in {"convert_points_to_workplane", "to_workplane_local_2d", "pattern_points_to_workplane"}
        for item in ast.walk(node)
    )
