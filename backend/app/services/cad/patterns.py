"""Design Plan pattern normalization and source-authority manifests."""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any

from volundr_cad.patterns import PatternSpecError, resolve_pattern_points


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
    for raw in normalized.get("patterns", []) or []:
        if not isinstance(raw, dict):
            continue
        pattern = dict(raw)
        pattern_id = str(pattern.get("pattern_id") or pattern.get("id") or "")
        if pattern_id:
            pattern["pattern_id"] = pattern_id
        feature_id = str(pattern.get("owning_feature_id") or pattern.get("feature_id") or "")
        if feature_id:
            pattern["owning_feature_id"] = feature_id
        pattern_type = str(pattern.get("pattern_type") or pattern.get("type") or "").lower()
        if not pattern_type:
            pattern_type = str(pattern.get("layout_type") or "").lower()
        if pattern_type in {"fixed_positions", "proposed_positions", "distributed_within_region"}:
            pattern_type = ""
        if not pattern_type and pattern.get("positions"):
            # Explicit positions are evidence of a repeated feature, not a
            # request for a reusable pattern. Keep that distinction in the
            # pattern manifest so irregular coordinates do not acquire a
            # false linear-axis contract.
            pattern_type = "explicit"
        if pattern_type in _PATTERN_TYPE_ALIASES:
            pattern["pattern_type"] = _PATTERN_TYPE_ALIASES[pattern_type]
        elif pattern_type:
            pattern["pattern_type"] = pattern_type
        if isinstance(pattern.get("axis"), dict):
            vector = pattern["axis"]
            components = {axis: float(vector.get(axis.lower(), 0.0) or 0.0) for axis in ("X", "Y", "Z")}
            dominant = max(components, key=lambda axis: abs(components[axis]))
            if components[dominant] != 0.0 and sum(1 for value in components.values() if value != 0.0) == 1:
                pattern["axis"] = dominant
        if feature_id and not pattern_id:
            pattern_id = f"{feature_id}_pattern"
            pattern["pattern_id"] = pattern_id
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
        if pattern_type in {"fixed_positions", "proposed_positions", "distributed_within_region"}:
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
    for pattern in patterns:
        pattern_id = str(pattern.get("pattern_id") or "")
        if not pattern_id:
            errors.append("pattern_id is required")
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
            errors.append(f"pattern `{pattern_id}` references unknown owning feature `{feature_id}`")
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
        }.get(pattern_type)
        if required_keys is None:
            errors.append(f"pattern `{pattern_id}` uses unsupported pattern_type `{pattern_type}`")
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
        raise PatternSpecError("; ".join(errors))


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
        resolved = resolve_pattern_points(pattern, values) if resolved_values is not None else None
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
