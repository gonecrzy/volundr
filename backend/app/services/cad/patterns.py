"""Design Plan pattern normalization and source-authority manifests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from volundr_cad.patterns import PatternSpecError, resolve_pattern_points


PATTERN_SCHEMA_VERSION = "cadquery-patterns-v1"


def normalize_pattern_specs(plan: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(plan)
    patterns: list[dict[str, Any]] = []
    for raw in normalized.get("patterns", []) or []:
        if not isinstance(raw, dict):
            continue
        pattern = dict(raw)
        pattern_id = str(pattern.get("pattern_id") or "")
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
        required_keys = {
            "linear": ("count_parameter_id", "spacing_parameter_id", "axis"),
            "rectangular": (
                "rows_parameter_id",
                "columns_parameter_id",
                "row_spacing_parameter_id",
                "column_spacing_parameter_id",
                "plane",
            ),
            "circular": ("count_parameter_id", "radius_parameter_id"),
        }.get(pattern_type)
        if required_keys is None:
            errors.append(f"pattern `{pattern_id}` uses unsupported pattern_type `{pattern_type}`")
            continue
        for key in required_keys:
            value = pattern.get(key)
            if not value:
                errors.append(f"pattern `{pattern_id}` requires {key}")
            elif key.endswith("parameter_id") and str(value) not in parameter_ids:
                errors.append(f"pattern `{pattern_id}` references unknown parameter `{value}`")
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
        effects = [
            {
                "parameter_id": str(pattern[field]),
                "allowed_via": [str(pattern["point_parameter_id"])],
                "effect_type": effect_type,
            }
            for field, effect_type in effect_fields
            if pattern.get(field)
        ]
        manifest.append({
            "pattern_id": str(pattern["pattern_id"]),
            "owning_feature_id": str(pattern["owning_feature_id"]),
            "owning_component_id": pattern.get("owning_component_id"),
            "pattern_type": str(pattern["pattern_type"]),
            "point_parameter_id": str(pattern["point_parameter_id"]),
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
