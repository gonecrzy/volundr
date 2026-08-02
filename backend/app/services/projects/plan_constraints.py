"""Deterministic constraint-mode and feature-layout normalization.

The mode is a statement about design intent, not a property inferred from a
parameter's numeric type.  This module deliberately contains no product
names or product-specific branches.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

CONSTRAINT_MODE_VERSION = "design-plan-constraint-modes-v1"
CONSTRAINT_MODES = {
    "fixed_constraint",
    "configurable_parameter",
    "derived_parameter",
    "explicit_layout",
    "proposed_value",
    "cosmetic_freedom",
}
LAYOUT_MODES = {
    "fixed_positions",
    "proposed_positions",
    "parameterized_positions",
    "uniform_linear",
    "rectangular_grid",
    "circular",
    "distributed_within_region",
    "derived_custom",
}
EFFECT_MODES = {"configurable_parameter", "derived_parameter"}
PATTERN_LAYOUT_MODES = {
    "parameterized_positions",
    "uniform_linear",
    "rectangular_grid",
    "circular",
}

_INTEGRAL_FEATURE_TERMS = re.compile(
    r"\b(?:rib|reinforc(?:e|ement)|hole|vent(?:ilation)?|slot|boss|opening|"
    r"floor|ledge|fillet|chamfer|snap|retention|drain|support|guide|clip)s?\b",
    re.IGNORECASE,
)
_PATTERN_TYPE_ALIASES = {
    "vertical": "linear",
    "horizontal": "linear",
    "line": "linear",
    "row": "linear",
    "linear_pattern": "linear",
    "grid": "rectangular",
    "rectangular_grid": "rectangular",
    "radial": "circular",
    "circular_pattern": "circular",
}

_CONFIGURATION_CUES = re.compile(
    r"\b(?:adjustable|configurable|parametric|parameterized|user[- ]selectable|"
    r"let\s+me\s+(?:change|adjust|set|choose)|change\s+(?:the\s+)?|"
    r"vary|variable|any\s+number|different\s+number|from\s+\d+\s+to\s+\d+)\b",
    re.IGNORECASE,
)
_COUNT_LAYOUT_CUES = re.compile(
    r"\b(?:count|number|quantity|screws?|fasteners?|holes?|cells?|ribs?|clips?)\b",
    re.IGNORECASE,
)
_CONTROL_REQUEST_CUES = re.compile(
    r"\b(?:expose|adjustable|configurable|parametric|parameterized|reusable\s+template|"
    r"let\s+me\s+(?:change|adjust|set|choose))\b",
    re.IGNORECASE,
)


def normalize_plan_constraints(
    plan: dict[str, Any],
    *,
    request_context: str | None = None,
) -> dict[str, Any]:
    """Add explicit modes and generic feature layouts to a Design Plan."""

    normalized = deepcopy(plan)
    context = str(request_context or "")
    parameter_by_id = {
        str(item.get("id")): item
        for collection in (normalized.get("parameters", []), normalized.get("derived_parameters", []))
        for item in collection or []
        if isinstance(item, dict) and item.get("id")
    }
    derived_ids = {
        str(item.get("id"))
        for item in normalized.get("derived_parameters", []) or []
        if isinstance(item, dict) and item.get("id")
    }
    for parameter in normalized.get("parameters", []) or []:
        if not isinstance(parameter, dict) or not parameter.get("id"):
            continue
        mode = str(parameter.get("constraint_mode") or "")
        if mode not in CONSTRAINT_MODES:
            mode = _infer_parameter_mode(parameter, context)
            parameter["constraint_mode"] = mode
        elif context:
            parameter["constraint_mode"] = mode = _canonicalize_declared_mode(parameter, mode, context)
        if mode in {"fixed_constraint", "derived_parameter", "explicit_layout", "cosmetic_freedom"}:
            parameter["editable"] = False
        elif mode == "configurable_parameter":
            parameter["editable"] = True
    for parameter in normalized.get("derived_parameters", []) or []:
        if not isinstance(parameter, dict) or not parameter.get("id"):
            continue
        parameter["constraint_mode"] = "derived_parameter"
        parameter.setdefault("editable", False)

    normalized["constraint_mode_version"] = CONSTRAINT_MODE_VERSION
    normalized["exposed_controls"] = _normalize_exposed_controls(
        normalized,
        context,
        parameter_by_id,
    )
    normalized = _normalize_feature_layouts(normalized, parameter_by_id, derived_ids)
    _validate_layouts(normalized)
    return normalized


def normalize_compact_component_feature_semantics(
    plan: dict[str, Any],
    *,
    compact: bool = False,
) -> dict[str, Any]:
    """Normalize the semantic boundary between printable parts and features.

    This is intentionally conservative.  Only an unambiguous compact,
    single-part plan may fold a provider-labelled integral feature component
    into the sole printable component.  Detailed/multipart plans retain the
    component identity and are validated by the existing assembly gates.
    """

    normalized = deepcopy(plan)
    components = [dict(item) for item in normalized.get("components", []) or [] if isinstance(item, dict)]
    features = [dict(item) for item in normalized.get("features", []) or [] if isinstance(item, dict)]
    outputs = [dict(item) for item in normalized.get("printable_outputs", []) or [] if isinstance(item, dict)]
    relationships = [item for item in normalized.get("relationships", []) or [] if isinstance(item, dict)]
    findings: list[dict[str, Any]] = list(normalized.get("normalization_findings", []) or [])

    for index, component in enumerate(components):
        component.setdefault("id", component.get("component_id") or ("primary_part" if index == 0 else f"component_{index + 1}"))
        component.setdefault("label", component.get("name") or str(component["id"]).replace("_", " ").title())
        component.setdefault("role", "printable_part")
        component.setdefault("required", True)
        component.setdefault("features", [])
        component.setdefault("parameters", [])

    for feature in features:
        feature.setdefault("id", feature.get("feature_id"))
        feature.setdefault("type", feature.get("feature_type") or "feature")
    for output_index, output in enumerate(outputs):
        output.setdefault("id", output.get("output_id"))
        if not output.get("component_ids") and output.get("component_id"):
            output["component_ids"] = [output["component_id"]]
        if not output.get("id"):
            owners = [str(value) for value in output.get("component_ids", []) or [] if value]
            output["id"] = f"{owners[0]}_output" if len(owners) == 1 else f"output_{output_index + 1}"
            findings.append({
                "rule_id": "plan.stable_id_defaulted",
                "severity": "warning",
                "blocking": False,
                "kind": "output",
                "id": output["id"],
                "reason": "provider output omitted an identifier and ownership supplied a deterministic fallback",
            })

    component_ids = {str(item["id"]) for item in components if item.get("id")}
    sole_component_id = str(components[0]["id"]) if len(components) == 1 else None
    explicit_output_components = {
        str(component_id)
        for output in outputs
        for component_id in output.get("component_ids", []) or []
        if component_id
    }
    assembly_like = bool(relationships) or len(outputs) > 1
    if len(components) > 1 and not assembly_like:
        primary_candidate = next(
            (item for item in components if str(item.get("role") or "").lower() == "printable_part"),
            components[0],
        )
        primary_candidate_id = str(primary_candidate["id"])
        assembly_like = any(
            str(item.get("id") or "") != primary_candidate_id
            and str(item.get("role") or "").lower() not in {"integral_feature", "feature", "fused_feature"}
            and not _INTEGRAL_FEATURE_TERMS.search(
                " ".join(str(item.get(key) or "") for key in ("id", "label", "description"))
            )
            for item in components
        )

    if compact and components and not assembly_like and (len(outputs) <= 1):
        primary_id = sole_component_id
        if primary_id is None:
            primary = next(
                (item for item in components if str(item.get("role") or "").lower() == "printable_part"),
                components[0],
            )
            primary_id = str(primary["id"])
        retained: list[dict[str, Any]] = []
        reclassified: set[str] = set()
        for component in components:
            component_id = str(component["id"])
            if component_id == primary_id:
                retained.append(component)
                continue
            descriptor = " ".join(
                str(component.get(key) or "")
                for key in ("id", "label", "description", "role")
            )
            role = str(component.get("role") or "").lower()
            integral = role in {"integral_feature", "feature", "fused_feature"} or bool(
                _INTEGRAL_FEATURE_TERMS.search(descriptor)
            )
            if integral and component_id not in explicit_output_components:
                feature_id = component_id
                feature = {
                    "id": feature_id,
                    "component_id": primary_id,
                    "type": role if role not in {"integral_feature", "feature", "fused_feature"} else "integral_feature",
                    "description": str(component.get("description") or component.get("label") or feature_id),
                    "parameters": list(component.get("parameters", []) or []),
                    "protected": bool(component.get("protected", False)),
                    "source_component_id": component_id,
                }
                if not any(str(item.get("id") or "") == feature_id for item in features):
                    features.append(feature)
                primary = retained[0] if retained else next(item for item in components if str(item["id"]) == primary_id)
                primary.setdefault("features", [])
                if feature_id not in primary["features"]:
                    primary["features"].append(feature_id)
                reclassified.add(component_id)
                findings.append({
                    "rule_id": "plan.component_reclassified_as_feature",
                    "severity": "warning",
                    "blocking": False,
                    "component_id": component_id,
                    "feature_id": feature_id,
                    "owner_component_id": primary_id,
                    "reason": "compact single-part integral feature normalization",
                })
            else:
                retained.append(component)
        components = retained
        if outputs:
            for output in outputs:
                component_list = [
                    str(value) for value in output.get("component_ids", []) or []
                    if str(value) not in reclassified
                ]
                output["component_ids"] = component_list or [primary_id]

    remaining_component_ids = {str(item["id"]) for item in components if item.get("id")}
    if len(remaining_component_ids) == 1:
        only_component_id = next(iter(remaining_component_ids))
        for feature in features:
            component_id = str(feature.get("component_id") or "")
            if not component_id:
                feature["component_id"] = only_component_id
                findings.append({
                    "rule_id": "plan.feature_owner_defaulted",
                    "severity": "warning",
                    "blocking": False,
                    "feature_id": str(feature.get("id") or ""),
                    "owner_component_id": only_component_id,
                    "reason": "single unambiguous compact printable component",
                })
            elif component_id not in remaining_component_ids:
                if compact:
                    feature["component_id"] = only_component_id
                    findings.append({
                        "rule_id": "plan.feature_owner_defaulted",
                        "severity": "warning",
                        "blocking": False,
                        "feature_id": str(feature.get("id") or ""),
                        "previous_owner_component_id": component_id,
                        "owner_component_id": only_component_id,
                        "reason": "single compact printable component is the only unambiguous feature owner",
                    })
                else:
                    raise ValueError(
                        f"feature {feature.get('id')!r} references unknown component {component_id!r}"
                    )
    else:
        unknown = {
            str(feature.get("component_id"))
            for feature in features
            if feature.get("component_id") and str(feature["component_id"]) not in remaining_component_ids
        }
        if unknown:
            raise ValueError(
                "feature references unknown components: " + ", ".join(sorted(unknown))
            )

    for feature in features:
        layout = feature.get("layout")
        if isinstance(layout, dict) and layout.get("layout_mode"):
            feature["layout_mode"] = layout["layout_mode"]

    normalized["components"] = components
    normalized["features"] = features
    normalized["printable_outputs"] = outputs
    normalized["normalization_findings"] = findings
    normalized["normalization_version"] = "plan-component-feature-semantics-v1"
    return normalized


def _normalize_exposed_controls(
    plan: dict[str, Any],
    context: str,
    parameter_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    controls: list[dict[str, Any]] = []
    known_ids = set(parameter_by_id)
    for item in plan.get("exposed_controls", []) or []:
        if isinstance(item, str):
            parameter_id = item
            normalized = {"parameter_id": parameter_id}
        elif isinstance(item, dict):
            parameter_id = str(item.get("parameter_id") or item.get("id") or "")
            normalized = dict(item)
            normalized["parameter_id"] = parameter_id
        else:
            continue
        if parameter_id not in known_ids:
            raise ValueError(f"Exposed control references unknown parameter {parameter_id!r}")
        normalized.setdefault("label", parameter_by_id[parameter_id].get("label") or parameter_id)
        normalized.setdefault("source", "explicit_user_request")
        controls.append(normalized)

    controls.extend(explicit_control_requests(plan, context))
    return _dedupe_controls(controls)


def explicit_control_requests(
    plan: dict[str, Any],
    context: str | None,
) -> list[dict[str, Any]]:
    """Return controls named by an explicit user request.

    Numeric values and ordinary revision language are intentionally ignored.
    Only control language such as ``expose`` or ``adjustable`` activates this
    deterministic interpretation.
    """

    if not context or not _CONTROL_REQUEST_CUES.search(context):
        return []
    parameter_by_id = {
        str(item.get("id")): item
        for collection in (plan.get("parameters", []), plan.get("derived_parameters", []))
        for item in collection or []
        if isinstance(item, dict) and item.get("id")
    }
    lowered = context.lower()
    controls: list[dict[str, Any]] = []
    for parameter_id, parameter in parameter_by_id.items():
        label = str(parameter.get("label") or "")
        terms = (parameter_id.replace("_", " ").lower(), label.lower())
        if any(term and term in lowered for term in terms):
            controls.append(
                {
                    "parameter_id": parameter_id,
                    "label": label or parameter_id,
                    "unit": parameter.get("unit"),
                    "source": "explicit_user_request",
                }
            )
    return controls


def _dedupe_controls(controls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in controls:
        parameter_id = str(item.get("parameter_id") or "")
        if not parameter_id or parameter_id in seen:
            continue
        seen.add(parameter_id)
        result.append(item)
    return result


def exposed_control_ids(plan: dict[str, Any]) -> set[str]:
    """Return only controls explicitly exposed by the active Design Plan."""

    controls = plan.get("exposed_controls")
    if controls is None:
        return set()
    return {
        str(control if isinstance(control, str) else control.get("parameter_id"))
        for control in controls or []
        if (isinstance(control, str) and control) or (isinstance(control, dict) and control.get("parameter_id"))
    }


def parameter_requires_effect(
    parameter: dict[str, Any],
    *,
    exposed_control_ids: set[str] | None = None,
    legacy_default: bool = True,
) -> bool:
    """Whether source sensitivity is required for an explicitly exposed value."""

    if exposed_control_ids is not None:
        return str(parameter.get("id") or "") in exposed_control_ids
    mode = str(parameter.get("constraint_mode") or "")
    if mode:
        return mode in EFFECT_MODES or bool(parameter.get("pattern_driving"))
    # Older raw fixtures predate explicit controls. Preserve their contract
    # until they are normalized by the Design Plan lifecycle.
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
    return mode in PATTERN_LAYOUT_MODES or bool(layout.get("pattern_driving"))


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


def _infer_parameter_mode(parameter: dict[str, Any], context: str) -> str:
    provenance = parameter.get("provenance") if isinstance(parameter.get("provenance"), dict) else {}
    relationship = str(provenance.get("relationship") or "")
    source = str(parameter.get("source") or "")
    if relationship in {"derived_formula", "calculated"} or source == "calculated":
        return "derived_parameter"
    if relationship in {"product_default", "printer_default", "ai_proposal"} or source in {"product_default", "printer_profile", "ai_assumption"}:
        return "proposed_value"
    if relationship == "direct" or parameter.get("source_requirement_id"):
        return "configurable_parameter" if _is_config_requested(parameter, context) else "fixed_constraint"
    if str(parameter.get("unit") or "").lower() == "cosmetic":
        return "cosmetic_freedom"
    return "proposed_value"


def _canonicalize_declared_mode(parameter: dict[str, Any], mode: str, context: str) -> str:
    if mode not in CONSTRAINT_MODES:
        return _infer_parameter_mode(parameter, context)
    if mode == "derived_parameter":
        return mode
    relationship = str((parameter.get("provenance") or {}).get("relationship") or "")
    is_direct = relationship == "direct" or bool(parameter.get("source_requirement_id"))
    config_requested = _is_config_requested(parameter, context)
    if config_requested or parameter.get("pattern_driving"):
        return "configurable_parameter" if mode in {"configurable_parameter", "proposed_value", "fixed_constraint"} else mode
    if is_direct:
        if mode == "configurable_parameter" and not parameter.get("protected"):
            # An already explicit Plan decision remains authoritative for an
            # unprotected configuration control. Protected direct values
            # still default to fixed unless the request opts into adjustment.
            return mode
        return "fixed_constraint"
    if mode == "configurable_parameter" and relationship in {"ai_proposal", "product_default", "printer_default", ""}:
        return "proposed_value"
    return mode


def _is_config_requested(parameter: dict[str, Any], context: str) -> bool:
    if not context or not _CONFIGURATION_CUES.search(context):
        return False
    if re.search(r"\b(?:configurable|parametric|parameterized)\b", context, re.IGNORECASE) and (
        parameter.get("editable") or parameter.get("source_requirement_id")
    ):
        return True
    parameter_id = str(parameter.get("id") or "")
    label = str(parameter.get("label") or "")
    parameter_text = f"{parameter_id} {label}"
    if _COUNT_LAYOUT_CUES.search(parameter_text) and _COUNT_LAYOUT_CUES.search(context):
        return True
    tokens = [token for token in re.split(r"[_\s-]+", parameter_id.lower()) if len(token) > 2]
    lowered = context.lower()
    return bool(tokens) and any(token in lowered for token in tokens)


def _normalize_feature_layouts(
    plan: dict[str, Any],
    parameter_by_id: dict[str, dict[str, Any]],
    derived_ids: set[str],
) -> dict[str, Any]:
    layouts = [dict(item) for item in plan.get("feature_layouts", []) or [] if isinstance(item, dict)]
    normalization_findings = plan.setdefault("normalization_findings", [])
    patterns = [item for item in plan.get("patterns", []) or [] if isinstance(item, dict)]
    pattern_by_feature = {
        str(item.get("owning_feature_id") or item.get("feature_id")): item
        for item in patterns
        if item.get("owning_feature_id") or item.get("feature_id")
    }
    for layout in layouts:
        legacy_mode = layout.get("layout_type") or layout.get("strategy")
        mode = str(layout.get("layout_mode") or legacy_mode or "").strip()
        linked_pattern = pattern_by_feature.get(str(layout.get("feature_id") or ""))
        if (
            linked_pattern
            and mode in PATTERN_LAYOUT_MODES
            and not layout.get("pattern_id")
            and not layout.get("count_parameter_id")
        ):
            pattern_id = linked_pattern.get("pattern_id") or linked_pattern.get("id")
            if pattern_id:
                layout["pattern_id"] = str(pattern_id)
                normalization_findings.append({
                    "rule_id": "plan.layout_pattern_linked",
                    "severity": "warning",
                    "blocking": False,
                    "feature_id": layout.get("feature_id"),
                    "pattern_id": str(pattern_id),
                    "reason": "linked a layout to the existing pattern for the same feature",
                })
        if "positions" not in layout and isinstance(layout.get("fixed_positions"), list):
            layout["positions"] = list(layout["fixed_positions"])
        if (
            layout.get("positions")
            and mode in PATTERN_LAYOUT_MODES
            and not layout.get("count_parameter_id")
            and not layout.get("spacing_parameter_id")
            and not layout.get("pattern_id")
        ):
            mode = "fixed_positions"
            normalization_findings.append({
                "rule_id": "plan.layout_normalized",
                "severity": "warning",
                "blocking": False,
                "feature_id": layout.get("feature_id"),
                "reason": "explicit coordinates take precedence over an unbacked uniform or grid label",
            })
        if mode == "fixed_positions" and layout.get("positions") and not layout.get("required_count"):
            layout["required_count"] = len(layout["positions"])
        if mode in {"fixed", "explicit", "explicit_positions", "irregular"}:
            mode = "fixed_positions"
        elif mode in {"proposed", "proposed_layout"}:
            mode = "proposed_positions"
        elif mode in {"distributed", "distributed_region"}:
            mode = "distributed_within_region"
        if mode:
            layout["layout_mode"] = mode
        if mode == "fixed_positions" and not (layout.get("positions", []) or []):
            required_count = layout.get("required_count")
            if isinstance(required_count, int) and required_count > 0:
                layout["layout_mode"] = "proposed_positions"
                normalization_findings.append({
                    "rule_id": "plan.layout_semantics_missing",
                    "severity": "warning",
                    "blocking": False,
                    "feature_id": layout.get("feature_id"),
                    "reason": "fixed layout supplied a count without fixed positions; treating locations as proposals",
                })
            continue
        if mode:
            continue
        required_count = layout.get("required_count")
        positions = layout.get("positions", []) or []
        if isinstance(required_count, int) and required_count > 0 and len(positions) == required_count:
            layout["layout_mode"] = "fixed_positions"
            reason = "positions match the declared fixed count"
        elif isinstance(required_count, int) and required_count > 0:
            layout["layout_mode"] = "proposed_positions"
            reason = "count is known but positions were not supplied as a fixed layout"
        else:
            layout["layout_mode"] = "proposed_positions"
            layout["required_count"] = len(positions) if positions else 1
            reason = "layout mode was omitted and no stronger layout semantics were supplied"
        normalization_findings.append({
            "rule_id": "plan.layout_semantics_missing",
            "severity": "warning",
            "blocking": False,
            "feature_id": layout.get("feature_id"),
            "reason": reason,
        })
    layout_by_feature = {str(item.get("feature_id")): item for item in layouts if item.get("feature_id")}
    features = [item for item in plan.get("features", []) or [] if isinstance(item, dict) and item.get("id")]
    contract = plan.get("functional_contract") if isinstance(plan.get("functional_contract"), dict) else {}
    mounting_interfaces = [item for item in contract.get("mounting_interfaces", []) or [] if isinstance(item, dict)]
    patterns = [item for item in plan.get("patterns", []) or [] if isinstance(item, dict)]
    values = {key: item.get("value") for key, item in parameter_by_id.items()}
    for feature in features:
        feature_id = str(feature["id"])
        if feature_id in layout_by_feature:
            layout = layout_by_feature[feature_id]
            count_id = str(layout.get("count_parameter_id") or "")
            count_mode = str(parameter_by_id.get(count_id, {}).get("constraint_mode") or "")
            if count_mode == "fixed_constraint" and str(layout.get("layout_mode") or "") in PATTERN_LAYOUT_MODES:
                # A fixed requirement cannot silently become a future
                # sensitivity obligation because the provider called it a
                # uniform pattern. Preserve its approved positions and make
                # the geometric constraint explicit.
                layout["layout_mode"] = "fixed_positions"
            feature["layout_mode"] = layout.get("layout_mode")
            feature["layout"] = dict(layout)
            continue
        feature_text = " ".join(str(feature.get(key) or "") for key in ("id", "type", "description")).lower()
        if not any(token in feature_text for token in ("hole", "fastener", "screw", "pattern", "array")):
            continue
        interface = next(
            (item for item in mounting_interfaces if str(item.get("component_id") or "") == str(feature.get("component_id") or "")),
            None,
        )
        pattern = next(
            (item for item in patterns if str(item.get("owning_feature_id") or "") == feature_id),
            None,
        )
        if not isinstance(interface, dict):
            continue
        layout = _layout_from_pattern(feature, interface, pattern, parameter_by_id, values)
        if layout is None:
            continue
        layout_by_feature[feature_id] = layout
        layouts.append(layout)
        feature["layout_mode"] = layout["layout_mode"]
        feature["layout"] = dict(layout)
        interface.setdefault("feature_id", feature_id)
        interface.setdefault("layout_mode", layout["layout_mode"])
        interface.setdefault("count_constraint_mode", _interface_count_mode(interface, feature, parameter_by_id))
        if not interface.get("hole_diameter_parameter_id"):
            diameter_id = next(
                (str(value) for value in feature.get("parameters", []) or [] if "diameter" in str(value).lower()),
                None,
            )
            if diameter_id:
                interface["hole_diameter_parameter_id"] = diameter_id
    plan["features"] = features
    plan["feature_layouts"] = layouts
    for interface in mounting_interfaces:
        if not interface.get("feature_id"):
            candidate = next(
                (
                    item for item in layouts
                    if str(item.get("owning_component_id") or "") == str(interface.get("component_id") or "")
                ),
                None,
            )
            if candidate:
                interface["feature_id"] = candidate.get("feature_id")
        feature = next(
            (
                item for item in features
                if str(item.get("id") or "") == str(interface.get("feature_id") or "")
            ),
            None,
        )
        interface.setdefault(
            "count_constraint_mode",
            _interface_count_mode(interface, feature or {}, parameter_by_id),
        )
        layout = next(
            (item for item in layouts if str(item.get("feature_id") or "") == str(interface.get("feature_id") or "")),
            None,
        )
        if layout:
            interface.setdefault("layout_mode", layout.get("layout_mode"))
        if not interface.get("hole_diameter_parameter_id") and isinstance(feature, dict):
            diameter_id = next(
                (str(value) for value in feature.get("parameters", []) or [] if "diameter" in str(value).lower()),
                None,
            )
            if diameter_id:
                interface["hole_diameter_parameter_id"] = diameter_id
    return plan


def _layout_from_pattern(
    feature: dict[str, Any],
    interface: dict[str, Any],
    pattern: dict[str, Any] | None,
    parameter_by_id: dict[str, dict[str, Any]],
    values: dict[str, Any],
) -> dict[str, Any] | None:
    count_id = str((pattern or {}).get("count_parameter_id") or "")
    spacing_id = str((pattern or {}).get("spacing_parameter_id") or "")
    count = _number((pattern or {}).get("count"))
    if count is None and count_id:
        count = _number(values.get(count_id))
    if count is None:
        count = _number(interface.get("fastener_count"))
    spacing = _number((pattern or {}).get("spacing"))
    if spacing is None and spacing_id:
        spacing = _number(values.get(spacing_id))
    if spacing is None:
        spacing = _number((interface.get("spacing") or {}).get("value"))
    mode = str(parameter_by_id.get(count_id, {}).get("constraint_mode") or "")
    pattern_mode = str((pattern or {}).get("layout_mode") or "")
    layout_mode = pattern_mode or ("uniform_linear" if mode in {"configurable_parameter", "derived_parameter"} else "fixed_positions")
    if layout_mode == "fixed_positions" and count is not None and spacing is not None:
        points = _linear_points(int(count), spacing, str((pattern or {}).get("axis") or interface.get("arrangement_axis") or "Z"), (pattern or {}).get("origin") or (0.0, 0.0, 0.0))
    else:
        points = []
    if layout_mode == "fixed_positions" and not points:
        # A fixed count without approved coordinates is a proposal, not a
        # claim that Volundr knows the final positions.  Keep the count and
        # let the downstream plan/geometry stages disclose or choose the
        # locations without inventing a fixed layout.
        layout_mode = "proposed_positions"
    layout: dict[str, Any] = {
        "feature_id": str(feature["id"]),
        "owning_component_id": feature.get("component_id"),
        "layout_mode": layout_mode,
        "required_count": int(count) if count is not None else None,
        "positions": [{"x": point[0], "y": point[1], "z": point[2]} for point in points],
        "hole_axis": str(interface.get("hole_axis") or interface.get("normal_axis") or "").upper() or None,
        "arrangement_axis": str((pattern or {}).get("axis") or interface.get("arrangement_axis") or "").upper() or None,
        "mounting_plane": interface.get("mounting_plane"),
        "count_parameter_id": count_id or None,
        "spacing_parameter_id": spacing_id or None,
        "source": "volundr_proposal" if points else "design_plan",
    }
    if layout_mode in PATTERN_LAYOUT_MODES:
        layout["pattern_id"] = (pattern or {}).get("pattern_id")
    return layout


def _interface_count_mode(interface: dict[str, Any], feature: dict[str, Any], parameter_by_id: dict[str, dict[str, Any]]) -> str:
    for parameter_id in feature.get("parameters", []) or []:
        parameter = parameter_by_id.get(str(parameter_id), {})
        if str(parameter_id).lower().endswith("_count") or str(parameter.get("unit") or "").lower() == "count":
            return str(parameter.get("constraint_mode") or "fixed_constraint")
    return "fixed_constraint"


def _linear_points(count: int, spacing: float, axis: str, origin: Any) -> list[tuple[float, float, float]]:
    axis = str(axis or "").upper()
    axis_index = {"X": 0, "Y": 1, "Z": 2}.get(axis)
    if axis_index is None or count < 1:
        return []
    origin_values = tuple(float(value) for value in origin)
    start = -((count - 1) * float(spacing)) / 2.0
    points: list[tuple[float, float, float]] = []
    for index in range(count):
        values = list(origin_values)
        values[axis_index] += start + index * float(spacing)
        points.append((values[0], values[1], values[2]))
    return points


def _number(value: Any) -> float | None:
    try:
        if isinstance(value, bool) or value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _validate_layouts(plan: dict[str, Any]) -> None:
    feature_ids = {str(item.get("id")) for item in plan.get("features", []) or [] if isinstance(item, dict) and item.get("id")}
    parameter_modes = {
        str(item.get("id")): str(item.get("constraint_mode") or "")
        for collection in (plan.get("parameters", []), plan.get("derived_parameters", []))
        for item in collection or []
        if isinstance(item, dict) and item.get("id")
    }
    for layout in plan.get("feature_layouts", []) or []:
        if not isinstance(layout, dict):
            raise ValueError("feature layout must be an object")
        feature_id = str(layout.get("feature_id") or "")
        mode = str(layout.get("layout_mode") or "")
        if feature_id not in feature_ids:
            raise ValueError(f"feature layout references unknown feature {feature_id!r}")
        if mode not in LAYOUT_MODES:
            raise ValueError(f"unsupported feature layout mode {mode!r}")
        positions = layout.get("positions", []) or []
        if mode in {"fixed_positions", "proposed_positions"}:
            required_count = layout.get("required_count")
            if not isinstance(required_count, int) or required_count < 1:
                raise ValueError(f"{mode} layout {feature_id!r} must declare a positive required_count")
            if mode == "fixed_positions" and len(positions) != required_count:
                raise ValueError(f"fixed layout {feature_id!r} must declare positions matching required_count")
            count_id = str(layout.get("count_parameter_id") or "")
            if count_id and parameter_modes.get(count_id) in {"configurable_parameter", "derived_parameter"}:
                raise ValueError(f"{mode} layout {feature_id!r} cannot be driven by configurable count {count_id!r}")
        if mode in PATTERN_LAYOUT_MODES and not layout.get("pattern_id") and not layout.get("count_parameter_id"):
            raise ValueError(f"parameterized layout {feature_id!r} must identify its pattern or count source")
