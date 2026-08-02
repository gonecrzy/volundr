"""Provider/Volundr interoperability evidence and bounded repair contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable


SCHEMA_VERSION = "provider-contract-manifest-v1"
REPAIR_CONTEXT_VERSION = "provider-plan-repair-context-v1"


class ProviderContractError(ValueError):
    """A provider repair crossed an authoritative Volundr boundary."""


def _canonical(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)


def _ids(items: Iterable[Any], *keys: str) -> list[str]:
    result: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        value = next((item.get(key) for key in keys if item.get(key)), None)
        if value is not None and str(value) not in result:
            result.append(str(value))
    return result


def _feature_role(feature: dict[str, Any]) -> str:
    role = str(feature.get("role") or "").strip().lower()
    if role:
        return role
    feature_type = str(feature.get("type") or feature.get("feature_type") or "").lower()
    if feature_type in {"hole", "hole_group", "cut", "opening", "vent", "slot"}:
        return "subtractive"
    if feature_type in {"rib", "boss", "reinforcement", "snap_arm", "handle"}:
        return "integral_additive"
    return "integral_feature"


def _layout_manifest(plan: dict[str, Any]) -> list[dict[str, Any]]:
    layouts: list[dict[str, Any]] = []
    for index, raw in enumerate(
        [
            *(plan.get("feature_layouts", []) or []),
            *(plan.get("patterns", []) or []),
        ]
    ):
        if not isinstance(raw, dict):
            continue
        feature_id = raw.get("feature_id") or raw.get("owning_feature_id") or raw.get("owner_feature_id")
        layout_id = raw.get("id") or raw.get("pattern_id") or f"layout_{index + 1}"
        entry = {
            "layout_id": str(layout_id),
            "feature_id": str(feature_id) if feature_id else None,
            "owner_component_id": raw.get("component_id") or raw.get("owner_component_id"),
            "layout_mode": raw.get("layout_mode") or raw.get("layout_type") or raw.get("pattern_type"),
            "required_count": raw.get("required_count") or raw.get("count"),
            "positions": raw.get("positions") or raw.get("points"),
            "count_parameter_id": raw.get("count_parameter_id"),
            "spacing_parameter_id": raw.get("spacing_parameter_id"),
            "arrangement_axis": raw.get("arrangement_axis") or raw.get("axis"),
            "hole_axis": raw.get("hole_axis") or raw.get("cutting_axis"),
            "centered": raw.get("centered"),
        }
        layouts.append({key: value for key, value in entry.items() if value is not None})
    return layouts


def build_provider_contract_manifest(
    plan: dict[str, Any],
    *,
    planning_depth: str | None = None,
    geometry_inventory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create immutable provider-contract evidence from the approved Plan.

    The manifest describes the boundary the provider must follow. It does not
    create or normalize identities and it does not change the execution Plan.
    """

    components = [
        {
            "component_id": str(component["id"]),
            "printable": bool(component.get("printable", component.get("role") != "integral_feature")),
            "role": component.get("role"),
        }
        for component in plan.get("components", []) or []
        if isinstance(component, dict) and component.get("id")
    ]
    component_ids = {item["component_id"] for item in components}
    features = []
    for feature in plan.get("features", []) or []:
        if not isinstance(feature, dict) or not feature.get("id"):
            continue
        owner = feature.get("component_id") or feature.get("owner_component_id")
        features.append(
            {
                "feature_id": str(feature["id"]),
                "owner_component_id": str(owner) if owner else None,
                "feature_type": feature.get("type") or feature.get("feature_type"),
                "role": _feature_role(feature),
                "layout_mode": feature.get("layout_mode") or feature.get("layout_type"),
                "required": bool(feature.get("required", feature.get("protected", False))),
                "owner_is_approved": str(owner) in component_ids if owner else False,
            }
        )
    outputs = []
    for output in plan.get("printable_outputs", []) or plan.get("outputs", []) or []:
        if not isinstance(output, dict) or not (output.get("id") or output.get("output_id")):
            continue
        output_id = output.get("id") or output.get("output_id")
        outputs.append(
            {
                "output_id": str(output_id),
                "component_ids": [str(item) for item in output.get("component_ids", []) or [] if item],
                "required": bool(output.get("required", True)),
            }
        )
    inventory_entries = []
    if geometry_inventory:
        inventory_entries = [
            {
                "function_id": item.get("function_id"),
                "signature": item.get("signature"),
                "owner_component_id": item.get("owner_component_id"),
                "feature_id": item.get("feature_id"),
                "required_parameters": list(item.get("required_parameters", []) or []),
                "allowed_parameters": list(item.get("allowed_parameters", []) or []),
                "required_return": item.get("required_return"),
                "symbol_inventory": item.get("symbol_inventory", {}),
            }
            for item in geometry_inventory.get("functions", []) or []
            if isinstance(item, dict)
        ]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "planning_depth": planning_depth,
        "components": components,
        "features": features,
        "layouts": _layout_manifest(plan),
        "relationships": [dict(item) for item in plan.get("relationships", []) or [] if isinstance(item, dict)],
        "outputs": outputs,
        "exposed_controls": [
            dict(item) if isinstance(item, dict) else {"id": str(item)}
            for item in plan.get("exposed_controls", []) or []
        ],
        "protected_identity_ids": {
            "component_ids": sorted(item["component_id"] for item in components),
            "feature_ids": sorted(item["feature_id"] for item in features),
            "output_ids": sorted(item["output_id"] for item in outputs),
        },
        "function_inventory": inventory_entries,
        "provider_may_create_component_ids": False,
        "provider_may_create_feature_ids": False,
        "provider_may_create_output_ids": False,
        "provider_may_create_local_names": True,
        "repair_boundary": {
            "plan": "affected_feature_or_relationship_only",
            "geometry": "affected_provider_function_only",
            "worker": "one_localized_provider_statement_only",
        },
    }
    manifest["manifest_hash"] = hashlib.sha256(_canonical(manifest).encode("utf-8")).hexdigest()
    return manifest


def _affected_feature_ids(findings: Iterable[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        for key in ("feature_id", "affected_feature_id", "target_id", "entity_id"):
            value = finding.get(key)
            if value and str(value) not in result:
                result.append(str(value))
    return sorted(result)


def build_focused_plan_repair_context(
    rejected_plan: dict[str, Any],
    *,
    findings: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Describe the smallest safe repair boundary for a rejected Plan."""

    finding_list = [dict(item) for item in findings if isinstance(item, dict)]
    feature_ids = _ids(rejected_plan.get("features", []) or [], "id", "feature_id")
    component_ids = _ids(rejected_plan.get("components", []) or [], "id", "component_id")
    output_ids = _ids(rejected_plan.get("printable_outputs", []) or [], "id", "output_id")
    affected_feature_ids = set(_affected_feature_ids(finding_list))
    affected_layout_ids: list[str] = []
    valid_layout_ids: list[str] = []
    for collection in ("feature_layouts", "patterns"):
        for index, layout in enumerate(rejected_plan.get(collection, []) or []):
            if not isinstance(layout, dict):
                continue
            layout_id = str(
                layout.get("id")
                or layout.get("pattern_id")
                or layout.get("feature_id")
                or f"{collection}_{index + 1}"
            )
            layout_feature_id = str(
                layout.get("feature_id")
                or layout.get("owning_feature_id")
                or layout.get("owner_feature_id")
                or ""
            )
            has_positions = bool(layout.get("positions") or layout.get("points"))
            has_required_count = layout.get("required_count") is not None or layout.get("count") is not None
            malformed = not layout_feature_id or (has_required_count and not has_positions)
            if malformed:
                affected_layout_ids.append(layout_id)
                if layout_feature_id:
                    affected_feature_ids.add(layout_feature_id)
            else:
                valid_layout_ids.append(layout_id)
    return {
        "schema_version": REPAIR_CONTEXT_VERSION,
        "valid_component_ids": sorted(component_ids),
        "valid_feature_ids": sorted(feature_ids),
        "valid_output_ids": sorted(output_ids),
        "affected_feature_ids": sorted(affected_feature_ids),
        "affected_layout_ids": sorted(affected_layout_ids),
        "valid_layout_ids": sorted(set(valid_layout_ids)),
        "findings": finding_list,
        "allowed_schema_alternatives": {
            "feature_ownership": "Use an existing printable component; integral ribs, holes, vents, bosses, and reinforcements are not new printable parts.",
            "fixed_layout": "Use explicit positions or numeric fixed spacing and required_count; do not require a spacing_parameter_id without an exposed control.",
            "irregular_layout": "Use explicit positions or numeric radius/angles when the requirement gives irregular locations.",
            "proposed_layout": "Use a disclosed proposed position/spacing/radius value without inventing a reusable control.",
        },
        "prohibited_changes": {
            "create_printable_component": True,
            "create_feature_id": True,
            "create_output_id": True,
            "add_exposed_control": True,
            "change_unaffected_requirements": True,
            "change_unaffected_layouts": True,
        },
    }


def _flatten_ids(payload: dict[str, Any], collection: str, key: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for index, item in enumerate(payload.get(collection, []) or []):
        if not isinstance(item, dict):
            continue
        item_id = (
            item.get(key)
            or item.get("id")
            or item.get("output_id")
            or item.get("pattern_id")
            or item.get("feature_id")
        )
        if item_id:
            result[str(item_id)] = item
        else:
            result[f"#{index}"] = item
    return result


def _canonical_plan_item(collection: str, item: Any) -> Any:
    """Compare harmless provider layout aliases by their execution meaning."""

    if collection not in {"feature_layouts", "patterns"} or not isinstance(item, dict):
        return item
    normalized = dict(item)
    if "positions" not in normalized and isinstance(normalized.get("fixed_positions"), list):
        normalized["positions"] = normalized["fixed_positions"]
    mode = str(normalized.get("layout_mode") or normalized.get("layout_type") or "")
    if mode in {"vertical_linear", "horizontal_linear", "linear_positions"} and normalized.get("positions"):
        normalized["layout_mode"] = "fixed_positions"
    elif mode in {"fixed", "explicit", "explicit_positions", "irregular"}:
        normalized["layout_mode"] = "fixed_positions"
    if normalized.get("layout_mode") == "fixed_positions" and not normalized.get("positions"):
        if normalized.get("required_count") is not None:
            normalized["layout_mode"] = "proposed_positions"
    normalized.pop("layout_type", None)
    normalized.pop("fixed_positions", None)
    return normalized


def compare_plan_repair(
    original: dict[str, Any],
    repaired: dict[str, Any],
    *,
    affected_feature_ids: set[str] | None = None,
) -> dict[str, Any]:
    affected = {str(item) for item in (affected_feature_ids or set())}
    fields_changed: list[str] = []
    tracked_collections = (
        ("components", "id"),
        ("features", "id"),
        ("printable_outputs", "id"),
        ("feature_layouts", "id"),
        ("patterns", "pattern_id"),
        ("relationships", "id"),
    )
    for collection, key in tracked_collections:
        original_items = _flatten_ids(original, collection, key)
        repaired_items = _flatten_ids(repaired, collection, key)
        for item_id in sorted(set(original_items) | set(repaired_items)):
            before = _canonical_plan_item(collection, original_items.get(item_id))
            after = _canonical_plan_item(collection, repaired_items.get(item_id))
            if before == after:
                continue
            if before is None:
                fields_changed.append(f"{collection}.{item_id}.__added__")
                continue
            if after is None:
                fields_changed.append(f"{collection}.{item_id}.__removed__")
                continue
            for field in sorted(set(before) | set(after)):
                if before.get(field) != after.get(field):
                    fields_changed.append(f"{collection}.{item_id}.{field}")
    original_ids = {collection: sorted(_flatten_ids(original, collection, key)) for collection, key in tracked_collections}
    repaired_ids = {collection: sorted(_flatten_ids(repaired, collection, key)) for collection, key in tracked_collections}
    identity_collections = ("components", "features", "printable_outputs")
    return {
        "schema_version": "provider-plan-repair-comparison-v1",
        "fields_preserved": sorted(set(
            f"{collection}.{item_id}"
            for collection, ids in original_ids.items()
            for item_id in ids
            if item_id in repaired_ids[collection] and not any(
                field.startswith(f"{collection}.{item_id}.") for field in fields_changed
            )
        )),
        "fields_changed": fields_changed,
        "fields_removed": [field for field in fields_changed if field.endswith(".__removed__")],
        "identities_added": [
            f"{collection}.{item_id}"
            for collection in identity_collections
            for item_id in repaired_ids[collection]
            if item_id not in original_ids[collection]
        ],
        "identities_removed": [
            f"{collection}.{item_id}"
            for collection in identity_collections
            for item_id in original_ids[collection]
            if item_id not in repaired_ids[collection]
        ],
        "affected_feature_ids": sorted(affected),
        "findings_resolved": [],
        "findings_repeated": [],
    }


def validate_plan_repair_preservation(
    original: dict[str, Any],
    repaired: dict[str, Any],
    *,
    affected_feature_ids: set[str] | None = None,
    affected_layout_ids: set[str] | None = None,
) -> dict[str, Any]:
    comparison = compare_plan_repair(original, repaired, affected_feature_ids=affected_feature_ids)
    if _canonical(original) == _canonical(repaired):
        raise ProviderContractError("Plan repair returned an identical response")
    if comparison["identities_added"] or comparison["identities_removed"]:
        raise ProviderContractError("Plan repair changed protected component, feature, or output identities")
    affected = {str(item) for item in (affected_feature_ids or set())}
    affected_layouts = {str(item) for item in (affected_layout_ids or set())}
    for field in comparison["fields_changed"]:
        if field.startswith("features."):
            feature_id = field.split(".", 2)[1]
            if feature_id not in affected:
                raise ProviderContractError("Plan repair changed an unaffected feature")
        elif field.startswith(("feature_layouts.", "patterns.")):
            collection, item_id, _field = field.split(".", 2)
            source = original.get(collection, []) or []
            item = next(
                (
                    candidate
                    for candidate in source
                    if isinstance(candidate, dict)
                    and str(
                        candidate.get("id")
                        or candidate.get("pattern_id")
                        or candidate.get("feature_id")
                    ) == item_id
                ),
                None,
            )
            owner = str((item or {}).get("feature_id") or (item or {}).get("owning_feature_id") or "")
            if item_id not in affected_layouts and owner not in affected:
                raise ProviderContractError("Plan repair changed an unaffected layout")
        else:
            raise ProviderContractError("Plan repair changed an unaffected authoritative field")
    return comparison
