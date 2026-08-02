"""Design Plan pattern normalization and source-authority manifests."""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any

from volundr_cad.patterns import PatternSpecError, resolve_pattern_points
from volundr_cad.patterns import COMPONENT_LOCAL_3D


PATTERN_SCHEMA_VERSION = "cadquery-patterns-v1"
_EFFECT_MODES = {"configurable_parameter", "derived_parameter"}
_PATTERN_LAYOUT_MODES = {
    "parameterized_positions",
    "uniform_linear",
    "rectangular_grid",
    "circular",
}
_PATTERN_TYPE_ALIASES = {
    "vertical": "linear",
    "horizontal": "linear",
    "line": "linear",
    "row": "linear",
    "linear_pattern": "linear",
    "uniform_linear": "linear",
    "vertical_linear": "linear",
    "horizontal_linear": "linear",
    "grid": "rectangular",
    "rectangular_grid": "rectangular",
    "radial": "circular",
    "circular_pattern": "circular",
}


def _pattern_finding(
    *,
    rule_id: str,
    blocking: bool,
    pattern_index: int,
    pattern_id: str | None,
    original: dict[str, Any],
    normalized: dict[str, Any],
    explanation: str,
    suggested_correction: str,
    decision: str | None = None,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "category": "plan_pattern",
        "severity": "critical" if blocking else "warning",
        "blocking": blocking,
        "title": rule_id.replace(".", " ").replace("_", " ").title(),
        "explanation": explanation,
        "suggested_correction": suggested_correction,
        "pattern_index": pattern_index,
        "pattern_id": pattern_id,
        "original_record": deepcopy(original),
        "normalized_record": deepcopy(normalized),
        "normalization_decision": decision,
    }


def _append_pattern_finding(plan: dict[str, Any], finding: dict[str, Any]) -> None:
    findings = plan.setdefault("normalization_findings", [])
    identity = (
        finding.get("rule_id"),
        finding.get("pattern_index"),
        finding.get("pattern_id"),
    )
    if not any(
        (item.get("rule_id"), item.get("pattern_index"), item.get("pattern_id")) == identity
        for item in findings
        if isinstance(item, dict)
    ):
        findings.append(finding)


def _cardinal_axis(value: Any) -> tuple[str, int] | None:
    if isinstance(value, str) and value.upper() in {"X", "Y", "Z"}:
        return value.upper(), 1
    if isinstance(value, dict):
        value = [value.get("x", 0), value.get("y", 0), value.get("z", 0)]
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        values = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(item) for item in values):
        return None
    non_zero = [index for index, item in enumerate(values) if abs(item) > 1e-9]
    if len(non_zero) != 1 or not math.isclose(abs(values[non_zero[0]]), 1.0, abs_tol=1e-9):
        return None
    return ("X", 1 if values[0] > 0 else -1) if non_zero[0] == 0 else (
        ("Y", 1 if values[1] > 0 else -1) if non_zero[0] == 1 else ("Z", 1 if values[2] > 0 else -1)
    )


def _pattern_has_linear_evidence(pattern: dict[str, Any]) -> bool:
    has_count = pattern.get("count") is not None or pattern.get("count_parameter_id")
    has_spacing = pattern.get("spacing") is not None or pattern.get("spacing_parameter_id")
    has_direction = pattern.get("axis") is not None
    has_other_layout = any(
        pattern.get(key) is not None
        for key in (
            "positions",
            "fixed_positions",
            "rows",
            "columns",
            "row_spacing",
            "column_spacing",
            "plane",
            "radius",
            "radius_parameter_id",
            "start_angle",
        )
    )
    return bool(has_count and has_spacing and has_direction and not has_other_layout)


def exposed_control_ids(plan: dict[str, Any]) -> set[str]:
    """Return only controls explicitly exposed by the active Design Plan."""

    controls = plan.get("exposed_controls")
    if controls is None:
        return set()
    result: set[str] = set()
    for control in controls or []:
        if isinstance(control, str) and control:
            result.add(control)
        elif isinstance(control, dict) and control.get("parameter_id"):
            result.add(str(control["parameter_id"]))
    return result


def parameter_requires_effect(
    parameter: dict[str, Any],
    *,
    exposed_control_ids: set[str] | None = None,
    legacy_default: bool = True,
) -> bool:
    mode = str(parameter.get("constraint_mode") or "")
    if exposed_control_ids is not None:
        return str(parameter.get("id") or "") in exposed_control_ids
    if mode:
        return mode in _EFFECT_MODES or bool(parameter.get("pattern_driving"))
    return legacy_default


def layout_requires_pattern_effect(
    layout: dict[str, Any] | None,
    *,
    effect_parameter_ids: set[str] | None = None,
) -> bool:
    if not isinstance(layout, dict):
        return True
    if effect_parameter_ids is not None:
        sources = {
            str(layout.get(key))
            for key in (
                "count_parameter_id",
                "spacing_parameter_id",
                "rows_parameter_id",
                "columns_parameter_id",
                "row_spacing_parameter_id",
                "column_spacing_parameter_id",
                "radius_parameter_id",
            )
            if layout.get(key)
        }
        return bool(sources & effect_parameter_ids)
    mode = str(layout.get("layout_mode") or "")
    if not mode:
        return True
    return mode in _PATTERN_LAYOUT_MODES or bool(layout.get("pattern_driving"))


def layout_for_feature(plan: dict[str, Any], feature_id: str) -> dict[str, Any] | None:
    for layout in plan.get("feature_layouts", []) or []:
        if isinstance(layout, dict) and str(layout.get("feature_id") or "") == str(feature_id):
            return layout
    feature = next(
        (item for item in plan.get("features", []) or []
         if isinstance(item, dict) and str(item.get("id") or "") == str(feature_id)),
        None,
    )
    if isinstance(feature, dict) and isinstance(feature.get("layout"), dict) and feature["layout"].get("layout_mode"):
        return feature["layout"]
    return None


def normalize_pattern_specs(plan: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(plan)
    patterns: list[dict[str, Any]] = []
    for pattern_index, raw in enumerate(normalized.get("patterns", []) or []):
        if not isinstance(raw, dict):
            continue
        original = deepcopy(raw)
        pattern = dict(raw)
        pattern_id = str(pattern.get("pattern_id") or pattern.get("id") or "")
        if pattern_id and not pattern.get("pattern_id"):
            pattern["pattern_id"] = pattern_id
            _append_pattern_finding(
                normalized,
                _pattern_finding(
                    rule_id="plan.pattern_alias_normalized",
                    blocking=False,
                    pattern_index=pattern_index,
                    pattern_id=pattern_id,
                    original=original,
                    normalized=pattern,
                    explanation="The provider used the legacy id field for a pattern identifier.",
                    suggested_correction="Use pattern_id in future Design Plan responses.",
                    decision="id mapped to pattern_id",
                ),
            )
        elif not pattern_id:
            _append_pattern_finding(
                normalized,
                _pattern_finding(
                    rule_id="plan.pattern_id_missing",
                    blocking=True,
                    pattern_index=pattern_index,
                    pattern_id=None,
                    original=original,
                    normalized=pattern,
                    explanation="The repeated feature does not have a stable pattern identifier.",
                    suggested_correction="Provide a unique pattern_id.",
                ),
            )
        if "positions" not in pattern and isinstance(pattern.get("fixed_positions"), list):
            # Providers sometimes use the descriptive fixed_positions alias
            # for the same one-off explicit layout contract. Normalize that
            # harmless representation before validating pattern semantics.
            pattern["positions"] = deepcopy(pattern["fixed_positions"])
        canonical_feature_id = str(pattern.get("owning_feature_id") or "")
        alias_feature_id = str(pattern.get("feature_id") or pattern.get("owner_feature_id") or "")
        if canonical_feature_id and alias_feature_id and canonical_feature_id != alias_feature_id:
            _append_pattern_finding(
                normalized,
                _pattern_finding(
                    rule_id="plan.pattern_semantics_conflicting",
                    blocking=True,
                    pattern_index=pattern_index,
                    pattern_id=pattern_id or None,
                    original=original,
                    normalized=pattern,
                    explanation="The canonical and aliased pattern owners disagree.",
                    suggested_correction="Provide one owner_feature_id that matches the feature identity.",
                ),
            )
        feature_id = canonical_feature_id or alias_feature_id
        if feature_id:
            pattern["owning_feature_id"] = feature_id
            if not canonical_feature_id:
                _append_pattern_finding(
                    normalized,
                    _pattern_finding(
                        rule_id="plan.pattern_alias_normalized",
                        blocking=False,
                        pattern_index=pattern_index,
                        pattern_id=pattern_id or None,
                        original=original,
                        normalized=pattern,
                        explanation="The provider used feature_id as the pattern owner field.",
                        suggested_correction="Use owning_feature_id in future Design Plan responses.",
                        decision="feature_id mapped to owning_feature_id",
                    ),
                )
        pattern_type = str(pattern.get("pattern_type") or pattern.get("type") or "").lower()
        if not pattern_type:
            pattern_type = str(pattern.get("layout_type") or "").lower()
        if pattern_type in {"fixed_positions", "proposed_positions"}:
            pattern_type = ""
        if not pattern_type and pattern.get("positions"):
            # Explicit positions are evidence of a repeated feature, not a
            # request for a reusable pattern. Keep that distinction in the
            # pattern manifest so irregular coordinates do not acquire a
            # false linear-axis contract.
            pattern_type = "explicit"
        if pattern_type in _PATTERN_TYPE_ALIASES:
            pattern["pattern_type"] = _PATTERN_TYPE_ALIASES[pattern_type]
            if pattern_type != pattern["pattern_type"]:
                _append_pattern_finding(
                    normalized,
                    _pattern_finding(
                        rule_id="plan.pattern_alias_normalized",
                        blocking=False,
                        pattern_index=pattern_index,
                        pattern_id=pattern_id or None,
                        original=original,
                        normalized=pattern,
                        explanation="The provider used a recognized pattern type alias.",
                        suggested_correction="Use the canonical pattern_type value.",
                        decision=f"{pattern_type} mapped to {pattern['pattern_type']}",
                    ),
                )
        elif pattern_type:
            pattern["pattern_type"] = pattern_type
        direction = pattern.get("direction")
        if pattern.get("axis") is None and direction is not None:
            pattern["axis"] = deepcopy(direction)
        if direction is not None and not _cardinal_axis(direction):
            pattern["axis"] = None
            _append_pattern_finding(
                normalized,
                _pattern_finding(
                    rule_id="plan.pattern_direction_invalid",
                    blocking=True,
                    pattern_index=pattern_index,
                    pattern_id=pattern_id or None,
                    original=original,
                    normalized=pattern,
                    explanation="The pattern direction is not a supported cardinal axis vector.",
                    suggested_correction="Use [±1,0,0], [0,±1,0], or [0,0,±1], or provide axis X, Y, or Z.",
                ),
            )
        axis_value = pattern.get("axis")
        axis_result = _cardinal_axis(axis_value) if axis_value is not None else None
        if axis_value is not None and axis_result is None:
            _append_pattern_finding(
                normalized,
                _pattern_finding(
                    rule_id="plan.pattern_direction_invalid",
                    blocking=True,
                    pattern_index=pattern_index,
                    pattern_id=pattern_id or None,
                    original=original,
                    normalized=pattern,
                    explanation="The pattern axis is not a supported cardinal axis.",
                    suggested_correction="Use axis X, Y, or Z, or a cardinal direction vector.",
                ),
            )
        elif axis_result is not None:
            pattern["axis"] = axis_result[0]
            if axis_result[1] != 1:
                pattern["axis_sign"] = axis_result[1]
        # The deterministic pattern runtime emits three-dimensional
        # component placements unless a Plan explicitly declares a local
        # workplane representation.  Keep that space visible to geometry
        # consumers instead of allowing an implicit 2D interpretation.
        pattern.setdefault("coordinate_space", COMPONENT_LOCAL_3D)
        pattern.setdefault("point_dimensionality", 3)
        if pattern.get("coordinate_frame_id") is None and pattern.get("frame_id") is not None:
            pattern["coordinate_frame_id"] = pattern["frame_id"]
        if pattern.get("coordinate_frame_id") is None:
            frames = [
                item for item in normalized.get("coordinate_frames", []) or []
                if isinstance(item, dict) and item.get("frame_id")
            ]
            if len(frames) == 1:
                pattern["coordinate_frame_id"] = str(frames[0]["frame_id"])
                _append_pattern_finding(
                    normalized,
                    _pattern_finding(
                        rule_id="plan.pattern_alias_normalized",
                        blocking=False,
                        pattern_index=pattern_index,
                        pattern_id=pattern_id or None,
                        original=original,
                        normalized=pattern,
                        explanation="The pattern inherited the sole approved coordinate frame from the Plan.",
                        suggested_correction="Declare coordinate_frame_id explicitly in future Design Plan responses.",
                        decision="sole coordinate frame mapped to coordinate_frame_id",
                    ),
                )
        if pattern.get("arrangement_axis") is None and pattern.get("axis") is not None:
            pattern["arrangement_axis"] = pattern["axis"]
        if "spacing_mm" in pattern:
            spacing_mm = pattern.get("spacing_mm")
            if pattern.get("spacing") is not None and pattern.get("spacing") != spacing_mm:
                _append_pattern_finding(
                    normalized,
                    _pattern_finding(
                        rule_id="plan.pattern_semantics_conflicting",
                        blocking=True,
                        pattern_index=pattern_index,
                        pattern_id=pattern_id or None,
                        original=original,
                        normalized=pattern,
                        explanation="The canonical spacing and spacing_mm aliases disagree.",
                        suggested_correction="Provide one fixed spacing value.",
                    ),
                )
            else:
                pattern["spacing"] = spacing_mm
                pattern.setdefault("unit", "mm")
                _append_pattern_finding(
                    normalized,
                    _pattern_finding(
                        rule_id="plan.pattern_alias_normalized",
                        blocking=False,
                        pattern_index=pattern_index,
                        pattern_id=pattern_id or None,
                        original=original,
                        normalized=pattern,
                        explanation="The provider used spacing_mm for fixed millimeter spacing.",
                        suggested_correction="Use spacing with unit mm in future Design Plan responses.",
                        decision="spacing_mm mapped to spacing",
                    ),
                )
        if not pattern_type:
            if _pattern_has_linear_evidence(pattern):
                pattern["pattern_type"] = "linear"
                _append_pattern_finding(
                    normalized,
                    _pattern_finding(
                        rule_id="plan.pattern_alias_normalized",
                        blocking=False,
                        pattern_index=pattern_index,
                        pattern_id=pattern_id or None,
                        original=original,
                        normalized=pattern,
                        explanation="Count, fixed spacing, and one cardinal axis unambiguously describe a linear pattern.",
                        suggested_correction="Use pattern_type=linear in future Design Plan responses.",
                        decision="pattern_type inferred as linear",
                    ),
                )
            else:
                _append_pattern_finding(
                    normalized,
                    _pattern_finding(
                        rule_id="plan.pattern_type_missing",
                        blocking=True,
                        pattern_index=pattern_index,
                        pattern_id=pattern_id or None,
                        original=original,
                        normalized=pattern,
                        explanation="The pattern type cannot be inferred from unambiguous fixed-layout evidence.",
                        suggested_correction="Provide a supported pattern_type.",
                    ),
                )
        elif pattern.get("pattern_type") != "linear" and pattern.get("direction") is not None and pattern.get("spacing") is not None:
            _append_pattern_finding(
                normalized,
                _pattern_finding(
                    rule_id="plan.pattern_semantics_conflicting",
                    blocking=True,
                    pattern_index=pattern_index,
                    pattern_id=pattern_id or None,
                    original=original,
                    normalized=pattern,
                    explanation="Linear direction and spacing evidence conflicts with the declared pattern type.",
                    suggested_correction="Use a linear pattern type or remove the conflicting linear fields.",
                ),
            )
        if pattern_id and not pattern.get("point_parameter_id"):
            pattern["point_parameter_id"] = (
                pattern_id[:-8] + "_points" if pattern_id.endswith("_pattern") else pattern_id + "_points"
            )
        patterns.append(pattern)
    existing_features = {
        str(pattern.get("owning_feature_id"))
        for pattern in patterns
        if pattern.get("owning_feature_id")
    }
    mounting_interfaces = [
        interface
        for interface in (normalized.get("functional_contract") or {}).get("mounting_interfaces", []) or []
        if isinstance(interface, dict)
    ]
    component_by_feature = {
        str(feature.get("id")): str(feature.get("component_id") or "")
        for feature in normalized.get("features", []) or []
        if isinstance(feature, dict) and feature.get("id")
    }
    parameter_by_id = {
        str(parameter.get("id")): parameter
        for collection in (normalized.get("parameters", []), normalized.get("derived_parameters", []))
        for parameter in collection or []
        if isinstance(parameter, dict) and parameter.get("id")
    }
    layout_by_pattern_id = {
        str(layout.get("pattern_id")): layout
        for layout in normalized.get("feature_layouts", []) or []
        if isinstance(layout, dict) and layout.get("pattern_id")
    }
    for pattern in patterns:
        feature_id = str(pattern.get("owning_feature_id") or "")
        if not feature_id:
            referenced_layout = layout_by_pattern_id.get(str(pattern.get("pattern_id") or ""))
            if referenced_layout:
                feature_id = str(referenced_layout.get("feature_id") or "")
                if feature_id:
                    pattern["owning_feature_id"] = feature_id
        if not pattern.get("owning_component_id") and feature_id in component_by_feature:
            pattern["owning_component_id"] = component_by_feature[feature_id]
        elif pattern.get("owning_component_id") and feature_id in component_by_feature:
            # The feature owner is authoritative for integral repeated
            # features; retain the provider value only when it agrees.
            if str(pattern["owning_component_id"]) != component_by_feature[feature_id]:
                raise PatternSpecError(
                    f"pattern `{pattern.get('pattern_id')}` does not match its feature component"
                )
        layout = layout_for_feature(normalized, feature_id)
        layout_positions = (layout or {}).get("positions") if isinstance(layout, dict) else None
        if not pattern.get("positions") and isinstance(layout_positions, list) and layout_positions:
            pattern["positions"] = deepcopy(layout_positions)
        pattern_type = str(pattern.get("pattern_type") or "").lower()
        if pattern_type in {"fixed_positions", "proposed_positions"}:
            pattern_type = "explicit" if pattern.get("positions") else ""
            if pattern_type:
                pattern["pattern_type"] = pattern_type
        if not pattern_type and pattern.get("positions"):
            pattern_type = "explicit"
            pattern["pattern_type"] = pattern_type
        if pattern_type == "explicit":
            pattern["positions"] = [_canonical_explicit_point(point) for point in pattern.get("positions") or []]
        layout_mode = str((layout or {}).get("layout_mode") or pattern.get("layout_mode") or "")
        if layout_mode in {"fixed_positions", "proposed_positions", "distributed_within_region"}:
            for parameter_key, numeric_key in (
                ("count_parameter_id", "count"),
                ("spacing_parameter_id", "spacing"),
                ("rows_parameter_id", "rows"),
                ("columns_parameter_id", "columns"),
                ("row_spacing_parameter_id", "row_spacing"),
                ("column_spacing_parameter_id", "column_spacing"),
                ("radius_parameter_id", "radius"),
            ):
                if pattern.get(parameter_key) and str(pattern[parameter_key]) not in parameter_by_id and pattern.get(numeric_key) is None:
                    pattern[parameter_key] = None
                    normalized.setdefault("normalization_findings", []).append({
                        "rule_id": "plan.layout_normalized",
                        "severity": "warning",
                        "blocking": False,
                        "pattern_id": pattern.get("pattern_id"),
                        "field": parameter_key,
                        "reason": "non-parametric layout does not require an unresolved control identity",
                    })
        pattern_type = str(pattern.get("pattern_type") or "").lower()
        if (
            pattern_type == "linear"
            and not pattern.get("spacing_parameter_id")
            and pattern.get("spacing") is None
            and layout_mode not in _PATTERN_LAYOUT_MODES
        ):
            pattern["layout_mode"] = "proposed_positions"
            normalized.setdefault("normalization_findings", []).append({
                "rule_id": "plan.layout_semantics_missing",
                "severity": "warning",
                "blocking": False,
                "pattern_id": pattern.get("pattern_id"),
                "reason": "fixed-count repeated feature may use proposed positions without a spacing control",
            })
    for pattern in patterns:
        if pattern.get("point_parameter_id") in parameter_by_id:
            pattern_id = str(pattern.get("pattern_id") or "pattern")
            pattern["point_parameter_id"] = f"{pattern_id}_points"
    for feature in normalized.get("features", []) or []:
        if not mounting_interfaces:
            break
        if not isinstance(feature, dict) or not feature.get("id"):
            continue
        feature_id = str(feature["id"])
        if feature_id in existing_features:
            continue
        feature_text = " ".join(
            str(feature.get(key) or "") for key in ("id", "type", "description")
        ).lower()
        if not any(token in feature_text for token in ("mount", "hole", "fastener", "screw", "pattern", "array")):
            continue
        feature_parameter_ids = [str(value) for value in feature.get("parameters", []) or [] if value]
        count_id = next(
            (value for value in feature_parameter_ids if value.lower().endswith("_count") or value.lower() in {"count", "quantity"}),
            None,
        )
        spacing_id = next(
            (value for value in feature_parameter_ids if "spacing" in value.lower() or "pitch" in value.lower()),
            None,
        )
        if not count_id or not spacing_id:
            continue
        interface = next(
            (
                item for item in mounting_interfaces
                if str(item.get("component_id") or "") == component_by_feature.get(feature_id)
            ),
            {},
        )
        patterns.append({
            "pattern_id": f"{feature_id}_pattern",
            "owning_feature_id": feature_id,
            "owning_component_id": component_by_feature.get(feature_id),
            "pattern_type": "linear",
            "point_parameter_id": f"{feature_id}_points",
            "count_parameter_id": count_id,
            "spacing_parameter_id": spacing_id,
            "axis": str(interface.get("arrangement_axis") or "Z").upper(),
            "centered": True,
            "origin": [0.0, 0.0, 0.0],
            "unit": str(parameter_by_id.get(spacing_id, {}).get("unit") or normalized.get("units") or "mm"),
        })
    normalized["patterns"] = patterns
    return normalized


def _canonical_explicit_point(point: Any) -> Any:
    if not isinstance(point, dict) or "radius" not in point or "angle" not in point:
        return point
    radius = float(point["radius"])
    angle = math.radians(float(point["angle"]))
    return {
        "x": radius * math.cos(angle),
        "y": radius * math.sin(angle),
        "z": float(point.get("z", 0.0) or 0.0),
    }


def validate_pattern_specs(plan: dict[str, Any]) -> None:
    patterns = [item for item in plan.get("patterns", []) or [] if isinstance(item, dict)]
    parameter_ids = {
        str(item.get("id"))
        for collection in (plan.get("parameters", []), plan.get("derived_parameters", []))
        for item in collection or []
        if isinstance(item, dict) and item.get("id")
    }
    feature_components = {
        str(item.get("id")): str(item.get("component_id") or "")
        for item in plan.get("features", []) or []
        if isinstance(item, dict) and item.get("id")
    }
    component_ids = {
        str(item.get("id"))
        for item in plan.get("components", []) or []
        if isinstance(item, dict) and item.get("id")
    }
    seen_ids: set[str] = set()
    seen_points: set[str] = set()
    errors: list[str] = []
    findings: list[dict[str, Any]] = [
        dict(item) for item in plan.get("normalization_findings", []) or [] if isinstance(item, dict)
    ]

    def add_finding(
        *,
        rule_id: str,
        blocking: bool,
        pattern_index: int,
        pattern: dict[str, Any],
        explanation: str,
        suggested_correction: str,
    ) -> None:
        pattern_id = str(pattern.get("pattern_id") or "") or None
        finding = _pattern_finding(
            rule_id=rule_id,
            blocking=blocking,
            pattern_index=pattern_index,
            pattern_id=pattern_id,
            original=pattern,
            normalized=pattern,
            explanation=explanation,
            suggested_correction=suggested_correction,
        )
        identity = (rule_id, pattern_index, pattern_id)
        if not any(
            (item.get("rule_id"), item.get("pattern_index"), item.get("pattern_id")) == identity
            for item in findings
        ):
            findings.append(finding)

    for pattern_index, pattern in enumerate(patterns):
        pattern_id = str(pattern.get("pattern_id") or "")
        if not pattern_id:
            errors.append("pattern_id is required")
            add_finding(
                rule_id="plan.pattern_id_missing",
                blocking=True,
                pattern_index=pattern_index,
                pattern=pattern,
                explanation="The repeated feature does not have a stable pattern identifier.",
                suggested_correction="Provide a unique pattern_id.",
            )
            continue
        if pattern_id in seen_ids:
            errors.append(f"duplicate pattern_id `{pattern_id}`")
        seen_ids.add(pattern_id)
        point_id = str(pattern.get("point_parameter_id") or "")
        if not point_id:
            errors.append(f"pattern `{pattern_id}` requires point_parameter_id")
        elif point_id in seen_points:
            errors.append(f"duplicate point_parameter_id `{point_id}`")
        seen_points.add(point_id)
        feature_id = str(pattern.get("owning_feature_id") or "")
        if feature_id not in feature_components:
            if feature_id:
                errors.append(f"pattern `{pattern_id}` references unknown owning feature `{feature_id}`")
                add_finding(
                    rule_id="plan.pattern_owner_unknown",
                    blocking=True,
                    pattern_index=pattern_index,
                    pattern=pattern,
                    explanation=f"Pattern owner `{feature_id}` is not a declared feature.",
                    suggested_correction="Reference an existing feature without inventing a new owner.",
                )
            else:
                errors.append(f"pattern `{pattern_id}` references unknown owning feature `{feature_id}`")
                add_finding(
                    rule_id="plan.pattern_owner_missing",
                    blocking=True,
                    pattern_index=pattern_index,
                    pattern=pattern,
                    explanation="The pattern does not identify the feature it repeats.",
                    suggested_correction="Provide feature_id or owning_feature_id for an existing feature.",
                )
        component_id = str(pattern.get("owning_component_id") or "")
        if component_id and component_id not in component_ids:
            errors.append(f"pattern `{pattern_id}` references unknown owning component `{component_id}`")
        if component_id and feature_components.get(feature_id) not in {None, component_id}:
            errors.append(f"pattern `{pattern_id}` does not match its feature component")
        pattern_type = str(pattern.get("pattern_type") or "").lower()
        layout = layout_for_feature(plan, feature_id)
        layout_mode = str((layout or {}).get("layout_mode") or pattern.get("layout_mode") or "")
        effect_required = layout_requires_pattern_effect(
            layout or pattern,
            effect_parameter_ids=(exposed_control_ids(plan) if "exposed_controls" in plan else None),
        )
        required_keys = {
            "linear": ("axis",),
            "rectangular": ("plane",),
            "circular": (),
            "explicit": (),
            "distributed_within_region": (),
        }.get(pattern_type)
        if required_keys is None:
            if pattern_type:
                errors.append(f"pattern `{pattern_id}` uses unsupported pattern_type `{pattern_type}`")
                add_finding(
                    rule_id="plan.pattern_type_unsupported",
                    blocking=True,
                    pattern_index=pattern_index,
                    pattern=pattern,
                    explanation=f"Pattern type `{pattern_type}` is not supported by the canonical pattern contract.",
                    suggested_correction="Use linear, rectangular, circular, explicit, or distributed_within_region.",
                )
            else:
                errors.append(f"pattern `{pattern_id}` uses unsupported pattern_type `{pattern_type}`")
                add_finding(
                    rule_id="plan.pattern_type_missing",
                    blocking=True,
                    pattern_index=pattern_index,
                    pattern=pattern,
                    explanation="The pattern type is missing after deterministic normalization.",
                    suggested_correction="Provide a supported pattern_type or sufficient unambiguous fixed-layout evidence.",
                )
            continue
        numeric_sources = {
            "linear": (("count_parameter_id", "count"), ("spacing_parameter_id", "spacing")),
            "rectangular": (
                ("rows_parameter_id", "rows"),
                ("columns_parameter_id", "columns"),
                ("row_spacing_parameter_id", "row_spacing"),
                ("column_spacing_parameter_id", "column_spacing"),
            ),
            "circular": (("count_parameter_id", "count"), ("radius_parameter_id", "radius")),
            "explicit": (),
            "distributed_within_region": (("count_parameter_id", "count"),),
        }[pattern_type]
        for key in required_keys:
            value = pattern.get(key)
            if not value:
                errors.append(f"pattern `{pattern_id}` requires {key}")
            elif key.endswith("parameter_id") and str(value) not in parameter_ids:
                errors.append(f"pattern `{pattern_id}` references unknown parameter `{value}`")
        for parameter_key, numeric_key in numeric_sources:
            value = pattern.get(parameter_key)
            numeric_value = pattern.get(numeric_key)
            if value and str(value) not in parameter_ids:
                errors.append(f"pattern `{pattern_id}` references unknown parameter `{value}`")
            if effect_required and not value:
                errors.append(
                    f"pattern `{pattern_id}` requires {parameter_key} for a configurable layout"
                )
            elif not effect_required and value is None and numeric_value is None:
                if layout_mode not in {"fixed_positions", "proposed_positions", "distributed_within_region"}:
                    errors.append(
                        f"pattern `{pattern_id}` requires numeric {numeric_key} or {parameter_key}"
                    )
    if errors:
        error = PatternSpecError("; ".join(errors))
        setattr(error, "findings", findings)
        setattr(error, "normalized_plan", deepcopy(plan))
        raise error


def pattern_parameter_ids(plan: dict[str, Any]) -> set[str]:
    plan = normalize_pattern_specs(plan)
    return {
        str(pattern.get("point_parameter_id"))
        for pattern in plan.get("patterns", []) or []
        if isinstance(pattern, dict) and pattern.get("point_parameter_id")
    }


def build_pattern_manifest(
    plan: dict[str, Any],
    *,
    resolved_values: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    normalized = normalize_pattern_specs(plan)
    validate_pattern_specs(normalized)
    values = dict(resolved_values or {})
    manifest: list[dict[str, Any]] = []
    for pattern in normalized.get("patterns", []) or []:
        if not isinstance(pattern, dict):
            continue
        resolved = None
        try:
            # Fixed/proposed layouts can be resolved without a parameter map;
            # configurable layouts are resolved only when their approved
            # values are supplied.
            resolved = resolve_pattern_points(pattern, values)
        except PatternSpecError:
            if resolved_values is not None:
                raise
        effect_fields = {
            "linear": (
                ("count_parameter_id", "pattern_count"),
                ("spacing_parameter_id", "pattern_spacing"),
            ),
            "rectangular": (
                ("rows_parameter_id", "pattern_count"),
                ("columns_parameter_id", "pattern_count"),
                ("row_spacing_parameter_id", "pattern_spacing"),
                ("column_spacing_parameter_id", "pattern_spacing"),
            ),
            "circular": (("count_parameter_id", "pattern_count"), ("radius_parameter_id", "radius_or_diameter")),
        }.get(str(pattern.get("pattern_type") or "").lower(), ())
        layout = layout_for_feature(normalized, str(pattern.get("owning_feature_id") or ""))
        modern_control_contract = "exposed_controls" in normalized
        control_ids = exposed_control_ids(normalized) if modern_control_contract else None
        effect_parameter_ids = None
        if control_ids is not None:
            effect_parameter_ids = set(control_ids)
            derived_parameters = [
                item for item in normalized.get("derived_parameters", []) or []
                if isinstance(item, dict) and item.get("id")
            ]
            changed = True
            while changed:
                changed = False
                for derived in derived_parameters:
                    derived_id = str(derived["id"])
                    dependencies = {
                        str(item) for item in derived.get("depends_on", []) or []
                    }
                    if derived_id not in effect_parameter_ids and dependencies & effect_parameter_ids:
                        effect_parameter_ids.add(derived_id)
                        changed = True
        effect_required = layout_requires_pattern_effect(
            layout or pattern,
            effect_parameter_ids=effect_parameter_ids,
        )
        effects = [
            {
                "parameter_id": str(pattern[field]),
                "allowed_via": [str(pattern["point_parameter_id"])],
                "effect_type": effect_type,
            }
            for field, effect_type in effect_fields
            if effect_required
            if pattern.get(field)
        ]
        manifest.append({
            "pattern_id": str(pattern["pattern_id"]),
            "owning_feature_id": str(pattern["owning_feature_id"]),
            "owning_component_id": pattern.get("owning_component_id"),
            "pattern_type": str(pattern["pattern_type"]),
            "point_parameter_id": str(pattern["point_parameter_id"]),
            "layout_mode": layout.get("layout_mode") if layout else pattern.get("layout_mode"),
            "coordinate_space": resolved.coordinate_space if resolved else pattern.get("coordinate_space", COMPONENT_LOCAL_3D),
            "coordinate_frame_id": resolved.coordinate_frame_id if resolved else pattern.get("coordinate_frame_id"),
            "arrangement_axis": resolved.arrangement_axis if resolved else pattern.get("arrangement_axis") or pattern.get("axis"),
            "point_dimensionality": resolved.point_dimensionality if resolved else pattern.get("point_dimensionality", 3),
            "consumer_operation": resolved.consumer_operation if resolved else pattern.get("consumer_operation"),
            "host_plane": resolved.host_plane if resolved else pattern.get("host_plane") or pattern.get("workplane"),
            "effect_required": effect_required,
            "specification": pattern,
            "required_parameter_effects": effects,
            "resolved_points": [list(point) for point in resolved.points] if resolved else None,
            "resolved_point_hash": resolved.content_hash if resolved else None,
            "provenance": resolved.provenance if resolved else {
                "pattern_id": pattern["pattern_id"],
                "relationship": "pattern_points",
                "source_parameter_ids": [str(value) for value in (
                    pattern.get("count_parameter_id"), pattern.get("spacing_parameter_id")
                ) if value],
            },
        })
    return manifest
