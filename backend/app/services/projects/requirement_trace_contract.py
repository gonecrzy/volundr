from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from app.services.requirements.trace import (
    canonical_requirement_id,
    inventory_from_design_specification,
    normalize_requirement_semantics,
)


TRACE_CLASSIFICATIONS = {
    "source_trace_required",
    "source_or_geometry_trace",
    "geometry_verification_required",
    "human_review",
}

_STOP_WORDS = {
    "a",
    "an",
    "and",
    "be",
    "for",
    "from",
    "has",
    "have",
    "in",
    "include",
    "into",
    "must",
    "of",
    "on",
    "should",
    "the",
    "to",
    "up",
    "with",
}
_NUMERIC_TYPES = {
    "capacity",
    "count",
    "dimension",
    "explicit_count",
    "explicit_dimension",
    "explicit_numeric",
    "explicit_maximum",
    "explicit_minimum",
    "maximum",
    "minimum",
    "position",
    "spacing",
}
_SOURCE_TRACE_TYPES = {
    "assembly_relationship",
    "configurable_parameter",
    "exposed_control",
    "printable_component",
    "protected_identity",
    "protected_scaffold_identity",
    "required_output",
}
_CAPACITY_FEATURE_TYPES = {
    "capacity",
    "capacity_array",
    "container",
    "cavity",
    "pocket",
    "slot_array",
    "storage",
    "storage_array",
}
_CAPACITY_TARGET_TYPES = {
    "capacity",
    "clearance",
    "count",
    "fit",
    "occupancy",
    "slot_count",
    "supported_capacity",
}
_CAPACITY_MEASUREMENTS = {
    "capacity",
    "occupancy",
    "slot_count",
    "supported_capacity",
}


def build_requirement_trace_manifest(
    *,
    design_specification_payload: dict[str, Any] | None,
    design_plan_payload: dict[str, Any],
    source_component_ids: set[str],
    source_component_symbols: dict[str, str],
    source_feature_components: dict[str, str],
    source_feature_symbols: dict[str, str],
    source_output_ids: set[str],
    source_output_components: dict[str, list[str]],
    source_parameter_ids: set[str],
) -> dict[str, Any]:
    inventory = inventory_from_design_specification(design_specification_payload)
    items = _trace_items(design_specification_payload, inventory)
    normalized_features, normalization_decisions = _normalize_features(design_plan_payload)
    plan_components = _components(design_plan_payload)
    plan_outputs = _outputs(design_plan_payload)
    validation_targets = [
        item for item in design_plan_payload.get("validation_targets", []) or []
        if isinstance(item, dict)
    ]
    patterns = [
        item for item in design_plan_payload.get("patterns", []) or []
        if isinstance(item, dict)
    ]
    exposed_control_ids = _exposed_control_ids(design_plan_payload)
    plan_parameter_ids = {
        canonical_requirement_id(str(parameter.get("id")))
        for parameter in design_plan_payload.get("parameters", []) or []
        if isinstance(parameter, dict) and parameter.get("id")
    }
    findings: list[dict[str, Any]] = []
    obligations: list[dict[str, Any]] = []

    findings.extend(
        _component_output_conflicts(
            components=plan_components,
            outputs=plan_outputs,
            relationships=design_plan_payload.get("relationships", []) or [],
        )
    )

    for item in items:
        obligation, item_findings = _classify_item(
            item=item,
            plan_components=plan_components,
            plan_features=normalized_features,
            plan_outputs=plan_outputs,
            patterns=patterns,
            validation_targets=validation_targets,
            exposed_control_ids=exposed_control_ids,
            plan_parameter_ids=plan_parameter_ids,
            source_component_ids=source_component_ids,
            source_component_symbols=source_component_symbols,
            source_feature_components=source_feature_components,
            source_feature_symbols=source_feature_symbols,
            source_output_ids=source_output_ids,
            source_output_components=source_output_components,
            source_parameter_ids=source_parameter_ids,
        )
        obligations.append(obligation)
        findings.extend(item_findings)

    original = {
        "schema_version": "requirement-trace-original-v1",
        "inventory": deepcopy(inventory),
        "functional_requirements": deepcopy(
            (design_specification_payload or {}).get("functional_requirements", []) or []
        ),
        "components": deepcopy(design_plan_payload.get("components", []) or []),
        "features": deepcopy(design_plan_payload.get("features", []) or []),
        "patterns": deepcopy(design_plan_payload.get("patterns", []) or []),
        "outputs": deepcopy(
            design_plan_payload.get("printable_outputs", design_plan_payload.get("outputs", [])) or []
        ),
        "validation_targets": deepcopy(validation_targets),
    }
    normalized = {
        "schema_version": "requirement-trace-normalized-v1",
        "features": normalized_features,
        "obligations": obligations,
        "validation_targets": deepcopy(validation_targets),
        "normalization_decisions": normalization_decisions,
    }
    findings.extend(
        _trace_finding(
            "design_artifact.trace_alias_normalized",
            f"Normalized Plan ownership for feature `{decision.get('feature_id')}` to `{decision.get('component_id')}`.",
            feature_id=str(decision.get("feature_id")) if decision.get("feature_id") else None,
            component_id=str(decision.get("component_id")) if decision.get("component_id") else None,
            blocking=False,
            normalization_decision=str(decision.get("decision") or "alias"),
        )
        for decision in normalization_decisions
    )
    result = {
        "schema_version": "requirement-trace-contract-v1",
        "original": original,
        "normalized": normalized,
        "findings": findings,
    }
    return result


def _classify_item(
    *,
    item: dict[str, Any],
    plan_components: dict[str, dict[str, Any]],
    plan_features: list[dict[str, Any]],
    plan_outputs: dict[str, dict[str, Any]],
    patterns: list[dict[str, Any]],
    validation_targets: list[dict[str, Any]],
    exposed_control_ids: set[str],
    plan_parameter_ids: set[str],
    source_component_ids: set[str],
    source_component_symbols: dict[str, str],
    source_feature_components: dict[str, str],
    source_feature_symbols: dict[str, str],
    source_output_ids: set[str],
    source_output_components: dict[str, list[str]],
    source_parameter_ids: set[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    requirement_id = canonical_requirement_id(str(item.get("requirement_id") or item.get("id") or ""))
    requirement_type = str(item.get("type") or "qualitative_behavior")
    component_ids = _matching_component_ids(item, plan_components)
    output_ids = _matching_output_ids(item, plan_outputs)
    feature, feature_match = _resolve_feature(item, plan_features, patterns)
    target, target_match = _resolve_validation_target(item, feature, validation_targets)
    parameter_id = _matching_parameter_id(item, exposed_control_ids)
    exposed_control = parameter_id is not None
    explicit_feature_requirement = (
        requirement_type == "explicit_feature"
        and not _looks_like_component_relationship(item)
    )
    source_trace_required = (
        exposed_control
        or requirement_type in _SOURCE_TRACE_TYPES
        or bool(component_ids)
        or bool(output_ids)
    )
    findings: list[dict[str, Any]] = []
    feature_like = feature is not None or explicit_feature_requirement

    if source_trace_required:
        classification = "source_trace_required"
    elif requirement_type in _NUMERIC_TYPES:
        classification = "geometry_verification_required"
    elif feature is not None or explicit_feature_requirement:
        classification = "source_or_geometry_trace"
    else:
        classification = "human_review"

    obligation: dict[str, Any] = {
        "requirement_id": requirement_id,
        "requirement_type": requirement_type,
        "trace_classification": classification,
        "blocking": False,
        "status": "unresolved",
        "plan_feature_id": None,
        "component_ids": component_ids,
        "output_ids": output_ids,
        "owning_component_id": None,
        "function_id": None,
        "output_id": None,
        "validation_target_id": str(target.get("id")) if target and target.get("id") else None,
        "normalization_decision": None,
    }

    if feature_match.get("ambiguous"):
        obligation["blocking"] = True
        obligation["status"] = "trace_ambiguous"
        findings.append(
            _trace_finding(
                "design_artifact.requirement_trace_ambiguous",
                f"Requirement `{requirement_id}` matches multiple Plan features and cannot be linked safely.",
                item=item,
                obligation=obligation,
                blocking=True,
                metadata={
                    "candidate_matches": feature_match.get("candidates", []),
                    "rejected_matches": feature_match.get("rejected", []),
                    "normalization_rule": "typed_semantic_feature_matching",
                },
            )
        )
        return obligation, findings
    if target_match.get("ambiguous"):
        obligation["blocking"] = True
        obligation["status"] = "trace_ambiguous"
        findings.append(
            _trace_finding(
                "design_artifact.requirement_trace_ambiguous",
                f"Requirement `{requirement_id}` matches multiple validation targets and cannot be linked safely.",
                item=item,
                obligation=obligation,
                blocking=True,
                metadata={
                    "candidate_matches": target_match.get("candidates", []),
                    "rejected_matches": target_match.get("rejected", []),
                    "normalization_rule": "typed_semantic_validation_matching",
                },
            )
        )
        return obligation, findings
    if feature_match.get("explicit_missing"):
        obligation["blocking"] = True
        obligation["status"] = "required_feature_missing"
        findings.append(
            _trace_finding(
                "design_artifact.required_feature_missing",
                f"Explicit Plan feature link for requirement `{requirement_id}` does not resolve.",
                item=item,
                obligation=obligation,
                blocking=True,
                metadata={"normalization_rule": "explicit_feature_link"},
            )
        )
        return obligation, findings
    if feature_match.get("incompatible"):
        obligation["blocking"] = True
        obligation["status"] = "geometry_verification_unmapped"
        findings.append(
            _trace_finding(
                "design_artifact.requirement_trace_unverifiable",
                f"No Plan feature has compatible semantics for measurable requirement `{requirement_id}`.",
                item=item,
                obligation=obligation,
                blocking=True,
                metadata={
                    "candidate_matches": feature_match.get("considered", []),
                    "rejected_matches": feature_match.get("rejected", []),
                    "normalization_rule": "typed_semantic_feature_matching",
                },
            )
        )
        return obligation, findings

    if parameter_id is not None:
        obligation["parameter_id"] = parameter_id
        if parameter_id not in source_parameter_ids:
            obligation["blocking"] = True
            obligation["status"] = "source_trace_missing"
            findings.append(
                _trace_finding(
                    "design_artifact.requirement_trace_unverifiable",
                    f"Exposed control `{parameter_id}` has no matching source parameter trace.",
                    item=item,
                    obligation=obligation,
                    blocking=True,
                )
            )
        else:
            obligation["status"] = "source_parameter_trace"
        return obligation, findings

    if requirement_id in plan_parameter_ids:
        obligation["parameter_id"] = requirement_id
        obligation["status"] = "source_parameter_trace"
        return obligation, findings

    if component_ids:
        missing_components = [component_id for component_id in component_ids if component_id not in source_component_ids]
        output_ids = [
            output_id
            for component_id in component_ids
            if (output_id := _output_for_component(
                component_id,
                plan_outputs,
                source_output_ids,
                source_output_components,
            )) is not None
        ]
        obligation["output_ids"] = output_ids
        if missing_components:
            obligation["blocking"] = True
            obligation["status"] = "component_trace_missing"
            findings.append(
                _trace_finding(
                    "design_artifact.feature_function_trace_missing",
                    f"Required component trace is missing for `{', '.join(missing_components)}`.",
                    item=item,
                    obligation=obligation,
                    component_id=missing_components[0],
                    blocking=True,
                )
            )
        elif len(output_ids) != len(component_ids):
            obligation["blocking"] = True
            obligation["status"] = "output_trace_missing"
            findings.append(
                _trace_finding(
                    "design_artifact.output_trace_missing",
                    f"Required component relationship `{requirement_id}` has no complete printable output trace.",
                    item=item,
                    obligation=obligation,
                    blocking=True,
                )
            )
        else:
            obligation["status"] = "source_component_output_trace"
        return obligation, findings

    if output_ids:
        missing_outputs = [output_id for output_id in output_ids if output_id not in source_output_ids]
        if missing_outputs:
            obligation["blocking"] = True
            obligation["status"] = "output_trace_missing"
            findings.append(
                _trace_finding(
                    "design_artifact.output_trace_missing",
                    f"Required output trace is missing for `{', '.join(missing_outputs)}`.",
                    item=item,
                    obligation=obligation,
                    output_id=missing_outputs[0],
                    blocking=True,
                )
            )
        else:
            obligation["status"] = "source_output_trace"
        return obligation, findings

    if feature is not None:
        feature_id = str(feature.get("id"))
        owner = str(feature.get("component_id") or "") or None
        obligation["plan_feature_id"] = feature_id
        obligation["owning_component_id"] = owner

        if owner is None:
            obligation["blocking"] = classification == "source_trace_required" or feature_like
            obligation["status"] = "owner_missing"
            findings.append(
                _trace_finding(
                    "design_artifact.feature_owner_mismatch",
                    f"Plan feature `{feature_id}` has no unambiguous owning component.",
                    item=item,
                    obligation=obligation,
                    feature_id=feature_id,
                    blocking=obligation["blocking"],
                )
            )
            return obligation, findings
        if owner not in plan_components:
            obligation["blocking"] = True
            obligation["status"] = "owner_unknown"
            findings.append(
                _trace_finding(
                    "design_artifact.feature_owner_mismatch",
                    f"Plan feature `{feature_id}` refers to unknown component `{owner}`.",
                    item=item,
                    obligation=obligation,
                    feature_id=feature_id,
                    component_id=owner,
                    blocking=True,
                )
            )
            return obligation, findings

        source_owner = source_feature_components.get(feature_id)
        if source_owner is not None and source_owner != owner:
            obligation["blocking"] = True
            obligation["status"] = "source_owner_mismatch"
            findings.append(
                _trace_finding(
                    "design_artifact.feature_owner_mismatch",
                    f"Feature `{feature_id}` is generated for `{source_owner}` instead of approved component `{owner}`.",
                    item=item,
                    obligation=obligation,
                    feature_id=feature_id,
                    component_id=owner,
                    blocking=True,
                    detected=source_owner,
                )
            )
            return obligation, findings

        function_id = source_feature_symbols.get(feature_id)
        component_declares_feature = feature_id in set(
            str(value)
            for value in (plan_components.get(owner, {}).get("features", []) or [])
            if value
        )
        if (
            function_id is None
            and source_owner is None
            and owner in source_component_ids
            and component_declares_feature
        ):
            function_id = source_component_symbols.get(owner)
            if function_id:
                obligation["normalization_decision"] = "integral_feature_uses_owning_component_function"
        obligation["function_id"] = function_id
        output_id = _output_for_component(
            owner,
            plan_outputs,
            source_output_ids,
            source_output_components,
        )
        obligation["output_id"] = output_id
        if feature_match.get("normalized") or target_match.get("normalized"):
            obligation["normalization_decision"] = "unique_typed_requirement_trace"
            findings.append(
                _trace_finding(
                    "design_artifact.requirement_trace_normalized",
                    f"Uniquely linked requirement `{requirement_id}` to Plan feature `{feature_id}` and its validation target.",
                    item=item,
                    obligation=obligation,
                    feature_id=feature_id,
                    component_id=owner,
                    blocking=False,
                    normalization_decision="unique_typed_requirement_trace",
                    metadata={
                        "candidate_matches": feature_match.get("considered", []),
                        "rejected_matches": feature_match.get("rejected", []),
                        "selected_match": {
                            "feature_id": feature_id,
                            "validation_target_id": obligation.get("validation_target_id"),
                        },
                        "confidence_basis": feature_match.get("basis", []) + target_match.get("basis", []),
                        "normalization_rule": "unique_typed_requirement_feature_target",
                    },
                )
            )

        if owner not in source_component_ids:
            obligation["blocking"] = True
            obligation["status"] = "component_trace_missing"
            findings.append(
                _trace_finding(
                    "design_artifact.feature_function_trace_missing",
                    f"Feature `{feature_id}` has no generated owning component `{owner}`.",
                    item=item,
                    obligation=obligation,
                    feature_id=feature_id,
                    component_id=owner,
                    blocking=True,
                )
            )
        elif function_id is None and classification == "source_trace_required":
            obligation["blocking"] = True
            obligation["status"] = "function_trace_missing"
            findings.append(
                _trace_finding(
                    "design_artifact.feature_function_trace_missing",
                    f"Feature `{feature_id}` has no source function trace for a source-required obligation.",
                    item=item,
                    obligation=obligation,
                    feature_id=feature_id,
                    component_id=owner,
                    blocking=True,
                )
            )
        elif function_id is None and target is None:
            obligation["blocking"] = True
            obligation["status"] = "function_trace_missing"
            findings.append(
                _trace_finding(
                    "design_artifact.feature_function_trace_missing",
                    f"Feature `{feature_id}` has no feature or owning-component function trace and no geometry verification target.",
                    item=item,
                    obligation=obligation,
                    feature_id=feature_id,
                    component_id=owner,
                    blocking=True,
                )
            )
        elif output_id is None and classification == "source_trace_required":
            obligation["blocking"] = True
            obligation["status"] = "output_trace_missing"
            findings.append(
                _trace_finding(
                    "design_artifact.output_trace_missing",
                    f"Feature `{feature_id}` has no unambiguous printable output trace.",
                    item=item,
                    obligation=obligation,
                    feature_id=feature_id,
                    component_id=owner,
                    blocking=True,
                )
            )
        else:
            obligation["status"] = (
                "geometry_verification_target"
                if classification == "geometry_verification_required" and target is not None
                else "source_trace" if function_id else "geometry_verification_target"
            )

        if target is not None and classification == "geometry_verification_required":
            findings.append(
                _trace_finding(
                    "design_artifact.geometry_verification_deferred",
                    f"Requirement `{requirement_id}` will be verified from resulting geometry at `{target.get('id')}`.",
                    item=item,
                    obligation=obligation,
                    feature_id=feature_id,
                    component_id=owner,
                    blocking=False,
                )
            )
        return obligation, findings

    if target is not None:
        obligation["status"] = "geometry_verification_target"
        if classification == "geometry_verification_required":
            findings.append(
                _trace_finding(
                    "design_artifact.geometry_verification_deferred",
                    f"Requirement `{requirement_id}` will be verified from resulting geometry at `{target.get('id')}`.",
                    item=item,
                    obligation=obligation,
                    blocking=False,
                )
            )
        return obligation, findings

    if classification == "human_review":
        obligation["status"] = "human_review"
        findings.append(
            _trace_finding(
                "design_artifact.requirement_trace_unverifiable",
                f"Requirement `{requirement_id}` requires human or physical review rather than a definitive source trace.",
                item=item,
                obligation=obligation,
                blocking=False,
            )
        )
        return obligation, findings

    if classification == "geometry_verification_required":
        obligation["status"] = "geometry_verification_unmapped"
        findings.append(
            _trace_finding(
                "design_artifact.requirement_trace_unverifiable",
                f"Requirement `{requirement_id}` has no Plan feature or geometry verification target.",
                item=item,
                obligation=obligation,
                blocking=True,
            )
        )
        obligation["blocking"] = True
        return obligation, findings

    obligation["status"] = "required_feature_missing"
    obligation["blocking"] = True
    findings.append(
        _trace_finding(
            "design_artifact.required_feature_missing",
            f"Required feature for `{requirement_id}` is not represented in the approved Plan.",
            item=item,
            obligation=obligation,
            blocking=True,
        )
    )
    return obligation, findings


def _trace_items(
    specification: dict[str, Any] | None,
    inventory: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    items = {str(item.get("requirement_id")): deepcopy(item) for item in inventory}
    for entry in (specification or {}).get("functional_requirements", []) or []:
        if not isinstance(entry, dict) or entry.get("source") not in {"user", "clarification"}:
            continue
        requirement_id = canonical_requirement_id(str(entry.get("id") or entry.get("requirement_id") or ""))
        if not requirement_id:
            continue
        existing = items.get(requirement_id)
        if existing is not None:
            existing["label"] = str(entry.get("description") or entry.get("label") or existing.get("label") or requirement_id)
            existing["type"] = str(entry.get("type") or "qualitative_behavior")
            for key in (
                "kind",
                "operator",
                "subject",
                "object_type",
                "target",
                "value",
                "unit",
                "raw_evidence",
                "feature_id",
                "target_feature_id",
                "component_id",
                "target_component_id",
                "output_id",
                "target_output_id",
            ):
                if entry.get(key) is not None:
                    existing[key] = deepcopy(entry[key])
            existing.update(normalize_requirement_semantics(existing))
            continue
        items.setdefault(
            requirement_id,
            {
                "requirement_id": requirement_id,
                "id": requirement_id,
                "label": str(entry.get("description") or entry.get("label") or requirement_id),
                "value": True,
                "unit": None,
                "source": entry.get("source"),
                "type": str(entry.get("type") or "qualitative_behavior"),
                "protected": bool(entry.get("protected")),
                "evidence": {"description": entry.get("description")},
                "kind": entry.get("kind"),
                "operator": entry.get("operator"),
                "subject": entry.get("subject"),
                "object_type": entry.get("object_type"),
                "target": entry.get("target"),
                "raw_evidence": entry.get("raw_evidence") or entry.get("description"),
            },
        )
    return [items[key] for key in sorted(items)]


def _normalize_features(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    features: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    components = _components(payload)
    printable = [
        component_id
        for component_id, component in components.items()
        if _is_printable_component(component)
    ]
    for index, raw in enumerate(payload.get("features", []) or []):
        if not isinstance(raw, dict):
            continue
        feature = deepcopy(raw)
        feature_id = feature.get("id") or feature.get("feature_id")
        if not feature_id:
            features.append(feature)
            continue
        feature["id"] = str(feature_id)
        owner = feature.get("component_id") or feature.get("owner_component_id") or feature.get("owning_component_id")
        if owner:
            feature["component_id"] = str(owner)
            if "component_id" not in raw:
                decisions.append(
                    {
                        "rule_id": "design_artifact.trace_alias_normalized",
                        "feature_id": str(feature_id),
                        "component_id": str(owner),
                        "decision": "owner_component_alias",
                        "index": index,
                    }
                )
        elif len(printable) == 1 and _can_be_integral(feature, payload):
            feature["component_id"] = printable[0]
            decisions.append(
                {
                    "rule_id": "design_artifact.trace_alias_normalized",
                    "feature_id": str(feature_id),
                    "component_id": printable[0],
                    "decision": "sole_printable_component_owner",
                    "index": index,
                }
            )
        features.append(feature)
    return features, decisions


def _components(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(component.get("id")): component
        for component in payload.get("components", []) or []
        if isinstance(component, dict) and component.get("id")
    }


def _outputs(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_outputs = payload.get("printable_outputs", payload.get("outputs", [])) or []
    result: dict[str, dict[str, Any]] = {}
    for output in raw_outputs:
        if not isinstance(output, dict):
            continue
        output_id = output.get("id") or output.get("output_id")
        if not output_id:
            continue
        normalized = deepcopy(output)
        components = list(normalized.get("component_ids") or [])
        component_id = normalized.get("component_id")
        if component_id and component_id not in components:
            components.insert(0, component_id)
        normalized["component_ids"] = [str(value) for value in components if value]
        result[str(output_id)] = normalized
    return result


def _exposed_control_ids(payload: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for entry in payload.get("exposed_controls", []) or []:
        if isinstance(entry, str) and entry:
            result.add(canonical_requirement_id(entry))
        elif isinstance(entry, dict):
            value = entry.get("id") or entry.get("parameter_id")
            if value:
                result.add(canonical_requirement_id(str(value)))
    for parameter in payload.get("parameters", []) or []:
        if not isinstance(parameter, dict):
            continue
        if parameter.get("constraint_mode") == "configurable_parameter" and parameter.get("editable"):
            value = parameter.get("id")
            if value:
                result.add(canonical_requirement_id(str(value)))
    return result


def _matching_parameter_id(item: dict[str, Any], control_ids: set[str]) -> str | None:
    requirement_id = canonical_requirement_id(str(item.get("requirement_id") or item.get("id") or ""))
    return requirement_id if requirement_id in control_ids else None


def _matching_component_ids(
    item: dict[str, Any],
    components: dict[str, dict[str, Any]],
) -> list[str]:
    explicit = item.get("component_ids") or item.get("target_component_ids")
    if isinstance(explicit, list) and explicit:
        matches = [str(value) for value in explicit if str(value) in components]
        if len(matches) == len(explicit):
            return matches
    explicit_one = item.get("component_id") or item.get("target_component_id")
    if explicit_one and str(explicit_one) in components:
        return [str(explicit_one)]
    tokens = _tokens(
        str(item.get("requirement_id") or item.get("id") or "")
        + " "
        + str(item.get("label") or "")
        + " "
        + str(item.get("value") or "")
    )
    matches = []
    for component_id, component in components.items():
        identifiers = _tokens(
            component_id
            + " "
            + str(component.get("label") or "")
        )
        if identifiers and (identifiers & tokens):
            matches.append(component_id)
    return sorted(set(matches)) if len(matches) > 1 else []


def _matching_output_ids(
    item: dict[str, Any],
    outputs: dict[str, dict[str, Any]],
) -> list[str]:
    explicit = item.get("output_ids") or item.get("target_output_ids")
    if isinstance(explicit, list) and explicit:
        matches = [str(value) for value in explicit if str(value) in outputs]
        if len(matches) == len(explicit):
            return matches
    explicit_one = item.get("output_id") or item.get("target_output_id")
    if explicit_one and str(explicit_one) in outputs:
        return [str(explicit_one)]
    return []


def _resolve_feature(
    item: dict[str, Any],
    features: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Resolve a requirement to a Plan feature without product vocabulary.

    Explicit IDs and structured semantic fields are authoritative. Text and
    numeric evidence can support a unique match, but cannot manufacture a
    match when multiple typed candidates remain.
    """

    requirement_id = canonical_requirement_id(str(item.get("requirement_id") or item.get("id") or ""))
    info: dict[str, Any] = {"considered": [], "rejected": [], "basis": []}
    explicit_feature_id = item.get("feature_id") or item.get("target_feature_id")
    if explicit_feature_id:
        explicit = canonical_requirement_id(str(explicit_feature_id))
        matches = [feature for feature in features if canonical_requirement_id(str(feature.get("id"))) == explicit]
        if len(matches) == 1:
            info["basis"] = ["explicit_feature_id"]
            return matches[0], info
        info["explicit_missing"] = True
        info["rejected"] = [explicit]
        return None, info

    linked = [
        feature
        for feature in features
        if _contains_requirement_id(feature, requirement_id)
    ]
    if len(linked) == 1:
        info["basis"] = ["feature_requirement_ids"]
        return linked[0], info
    if len(linked) > 1:
        info["ambiguous"] = True
        info["candidates"] = [str(feature.get("id")) for feature in linked]
        return None, info

    value = item.get("value")
    pattern_features: list[dict[str, Any]] = []
    for pattern in patterns:
        feature_id = pattern.get("feature_id") or pattern.get("owning_feature_id")
        count = pattern.get("count")
        if isinstance(count, dict):
            count = count.get("value")
        if feature_id and _values_equal(count, value):
            pattern_features.extend(
                feature for feature in features if str(feature.get("id")) == str(feature_id)
            )
    if len(pattern_features) == 1:
        info["basis"] = ["pattern_count_value"]
        return pattern_features[0], info
    if len(pattern_features) > 1:
        info["ambiguous"] = True
        info["candidates"] = [str(feature.get("id")) for feature in pattern_features]
        return None, info

    scored: list[tuple[int, dict[str, Any], list[str]]] = []
    for feature in features:
        score, basis = _feature_semantic_score(item, feature)
        if score <= 0:
            continue
        scored.append((score, feature, basis))
    info["considered"] = [str(feature.get("id")) for _, feature, _ in scored]
    if not scored:
        if str(item.get("kind") or item.get("type") or "").lower() == "capacity" and features:
            info["incompatible"] = True
            info["rejected"] = [str(feature.get("id")) for feature in features]
        return None, info
    scored.sort(key=lambda value: (-value[0], str(value[1].get("id"))))
    best_score = scored[0][0]
    best = [entry for entry in scored if entry[0] == best_score]
    if len(best) > 1:
        info["ambiguous"] = True
        info["candidates"] = [str(feature.get("id")) for _, feature, _ in best]
        info["rejected"] = [str(feature.get("id")) for _, feature, _ in scored if feature not in [entry[1] for entry in best]]
        return None, info
    selected_score, selected, basis = best[0]
    info["basis"] = basis
    info["normalized"] = True
    return selected, info


def _resolve_validation_target(
    item: dict[str, Any],
    feature: dict[str, Any] | None,
    targets: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    requirement_id = canonical_requirement_id(str(item.get("requirement_id") or item.get("id") or ""))
    feature_id = str(feature.get("id")) if feature else None
    info: dict[str, Any] = {"considered": [], "rejected": [], "basis": []}
    explicit_target_id = item.get("validation_target_id") or item.get("verification_target_id")
    exact = [
        target
        for target in targets
        if (
            explicit_target_id
            and canonical_requirement_id(str(target.get("id") or "")) == canonical_requirement_id(str(explicit_target_id))
        )
        or canonical_requirement_id(str(target.get("requirement_id") or "")) == requirement_id
        or canonical_requirement_id(str(target.get("id") or "")) == requirement_id
        or _contains_requirement_id(target, requirement_id)
        or (feature_id and str(target.get("feature_id") or "") == feature_id)
    ]
    if len(exact) == 1:
        info["basis"] = ["explicit_validation_target_link"]
        return exact[0], info
    if len(exact) > 1:
        info["ambiguous"] = True
        info["candidates"] = [str(target.get("id")) for target in exact]
        return None, info

    scored: list[tuple[int, dict[str, Any], list[str]]] = []
    for target in targets:
        score, basis = _target_semantic_score(item, target)
        if score <= 0:
            continue
        scored.append((score, target, basis))
    info["considered"] = [str(target.get("id")) for _, target, _ in scored]
    if not scored:
        return None, info
    scored.sort(key=lambda value: (-value[0], str(value[1].get("id"))))
    best_score = scored[0][0]
    best = [entry for entry in scored if entry[0] == best_score]
    if len(best) > 1:
        info["ambiguous"] = True
        info["candidates"] = [str(target.get("id")) for _, target, _ in best]
        info["rejected"] = [str(target.get("id")) for _, target, _ in scored if target not in [entry[1] for entry in best]]
        return None, info
    _, selected, basis = best[0]
    info["basis"] = basis
    info["normalized"] = True
    return selected, info


def _feature_semantic_score(item: dict[str, Any], feature: dict[str, Any]) -> tuple[int, list[str]]:
    kind = str(item.get("kind") or item.get("type") or "").lower()
    if kind not in {"capacity", "count"}:
        return _legacy_feature_score(item, feature)

    feature_type = str(
        feature.get("semantic_type")
        or feature.get("kind")
        or feature.get("type")
        or ""
    ).lower()
    score = 0
    basis: list[str] = []
    if feature_type in _CAPACITY_FEATURE_TYPES:
        score += 60
        basis.append("compatible_feature_semantics")
    if feature.get("layout_mode") or feature.get("pattern_id"):
        score += 15
        basis.append("layout_semantics")
    if _feature_value_matches(feature, item.get("value")):
        score += 30
        basis.append("numeric_value")
    if _semantic_tokens(item) & _semantic_tokens(feature):
        score += 15
        basis.append("object_or_text_evidence")
    if score < 30:
        return 0, []
    return score, basis


def _target_semantic_score(item: dict[str, Any], target: dict[str, Any]) -> tuple[int, list[str]]:
    kind = str(item.get("kind") or item.get("type") or "").lower()
    target_type = str(target.get("measurement") or target.get("type") or "").lower()
    score = 0
    basis: list[str] = []
    if kind == "capacity" and (target_type in _CAPACITY_MEASUREMENTS or str(target.get("type") or "").lower() in _CAPACITY_TARGET_TYPES):
        score += 60
        basis.append("compatible_measurement")
    elif kind == "count" and target_type in _CAPACITY_TARGET_TYPES:
        score += 50
        basis.append("compatible_count_measurement")
    elif kind in {"dimension", "clearance", "fit", "spacing", "position", "thickness", "count"} and target_type in {"dimension", "spacing", "position", "thickness", "clearance", "fit", "count"}:
        score += 10
        basis.append("measurable_target")
    if _target_value_matches(target, item.get("value")):
        score += 30
        basis.append("numeric_value")
    if _semantic_tokens(item) & _semantic_tokens(target):
        score += 20
        basis.append("object_or_text_evidence")
    if score < 30:
        return 0, []
    return score, basis


def _legacy_feature_score(item: dict[str, Any], feature: dict[str, Any]) -> tuple[int, list[str]]:
    tokens = _tokens(
        str(item.get("requirement_id") or item.get("id") or "")
        + " "
        + str(item.get("label") or "")
        + " "
        + str(item.get("value") or "")
    )
    candidate_tokens = _tokens(
        str(feature.get("id") or "")
        + " "
        + str(feature.get("description") or "")
        + " "
        + str(feature.get("type") or "")
    )
    matches = tokens & candidate_tokens
    if len(matches) < 2:
        return 0, []
    return len(matches), ["legacy_text_evidence"]


def _contains_requirement_id(feature: dict[str, Any], requirement_id: str) -> bool:
    values = feature.get("requirement_ids") or feature.get("requirements") or []
    if isinstance(values, dict):
        values = values.keys()
    if isinstance(values, str):
        values = [values]
    return requirement_id in {
        canonical_requirement_id(str(value))
        for value in values
        if value
    }


def _feature_value_matches(feature: dict[str, Any], expected: Any) -> bool:
    for key in ("count", "capacity", "required_count", "slot_count", "value", "expected_value"):
        if key in feature and _values_equal(feature.get(key), expected):
            return True
    return _value_in_text(expected, " ".join(str(feature.get(key) or "") for key in ("id", "name", "description")))


def _target_value_matches(target: dict[str, Any], expected: Any) -> bool:
    for key in ("expected_value", "value", "count", "capacity"):
        if key in target and _values_equal(target.get(key), expected):
            return True
    return _value_in_text(expected, " ".join(str(target.get(key) or "") for key in ("id", "name", "description")))


def _value_in_text(expected: Any, text: str) -> bool:
    if isinstance(expected, dict):
        return False
    if _values_equal(expected, expected) and re.search(rf"\b{re.escape(str(expected))}\b", text):
        return True
    number_words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
    return any(
        value == expected and re.search(rf"\b{word}\b", text, flags=re.IGNORECASE)
        for word, value in number_words.items()
    )


def _semantic_tokens(item: dict[str, Any]) -> set[str]:
    value = " ".join(
        str(item.get(key) or "")
        for key in ("object_type", "subject", "target", "label", "description", "raw_evidence")
    )
    return _tokens(value)


def _output_for_component(
    component_id: str,
    plan_outputs: dict[str, dict[str, Any]],
    source_output_ids: set[str],
    source_output_components: dict[str, list[str]],
) -> str | None:
    matches = []
    for output_id, output in plan_outputs.items():
        if component_id not in output.get("component_ids", []):
            continue
        if output_id not in source_output_ids:
            continue
        if component_id not in source_output_components.get(output_id, []):
            continue
        matches.append(output_id)
    return matches[0] if len(matches) == 1 else None


def _component_output_conflicts(
    *,
    components: dict[str, dict[str, Any]],
    outputs: dict[str, dict[str, Any]],
    relationships: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    printable = {component_id for component_id, component in components.items() if _is_printable_component(component)}
    if len(printable) <= 1 or len(outputs) != 1:
        return []
    output_components = set(next(iter(outputs.values())).get("component_ids", []))
    if printable <= output_components:
        return []
    if any(
        isinstance(relationship, dict)
        and str(relationship.get("relation_type") or "").lower() in {"fuses", "integral", "contains"}
        for relationship in relationships
    ):
        return []
    return [
        _trace_finding(
            "design_artifact.component_output_conflict",
            "Multiple printable components are mapped to a single incomplete output without fusion semantics.",
            blocking=True,
            detected=sorted(output_components),
        )
    ]


def _is_printable_component(component: dict[str, Any]) -> bool:
    return bool(
        component.get("printable")
        or component.get("role") in {"printable_part", "printable_component"}
        or component.get("required_printable")
    )


def _can_be_integral(feature: dict[str, Any], payload: dict[str, Any]) -> bool:
    feature_id = str(feature.get("id") or feature.get("feature_id") or "")
    outputs = _outputs(payload)
    if any(feature_id in output.get("component_ids", []) for output in outputs.values()):
        return False
    for relationship in payload.get("relationships", []) or []:
        if not isinstance(relationship, dict):
            continue
        if str(relationship.get("child_id") or relationship.get("source_id") or "") != feature_id:
            continue
        if str(relationship.get("relation_type") or "").lower() in {"assembled", "placed", "independent", "mates", "connects"}:
            return False
    return feature.get("role") not in {"printable_part", "printable_component"}


def _looks_like_component_relationship(item: dict[str, Any]) -> bool:
    text = " ".join(
        str(item.get(key) or "")
        for key in ("requirement_id", "id", "label", "value", "evidence")
    ).lower()
    return "separate" in text or "assembly" in text


def _tokens(value: str) -> set[str]:
    return {
        token[:-1] if token.endswith("s") and len(token) > 3 else token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if token not in _STOP_WORDS and len(token) > 1
    }


def _values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    try:
        return abs(float(left) - float(right)) <= 1e-6
    except (TypeError, ValueError):
        return str(left) == str(right)


def _trace_finding(
    rule_id: str,
    explanation: str,
    *,
    item: dict[str, Any] | None = None,
    obligation: dict[str, Any] | None = None,
    feature_id: str | None = None,
    component_id: str | None = None,
    output_id: str | None = None,
    blocking: bool = True,
    detected: Any = None,
    normalization_decision: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item = item or {}
    obligation = obligation or {}
    result = {
        "rule_id": rule_id,
        "category": "design_artifact_consistency",
        "severity": "critical" if blocking else "warning",
        "is_blocking": blocking,
        "blocking": blocking,
        "phase": "pre_execution",
        "title": rule_id.replace("design_artifact.", "").replace("_", " ").title(),
        "explanation": explanation,
        "suggested_correction": "Review the requirement trace or verify the resulting geometry.",
        "requirement_id": obligation.get("requirement_id") or item.get("requirement_id"),
        "feature_id": feature_id or obligation.get("plan_feature_id"),
        "component_id": component_id or obligation.get("owning_component_id"),
        "function_id": obligation.get("function_id"),
        "output_id": output_id or obligation.get("output_id"),
        "trace_classification": obligation.get("trace_classification"),
        "normalization_decision": normalization_decision or obligation.get("normalization_decision"),
        "expected_value": item.get("value"),
        "detected_value": detected,
        "unit": item.get("unit"),
    }
    if metadata:
        result["metadata"] = deepcopy(metadata)
    return result
