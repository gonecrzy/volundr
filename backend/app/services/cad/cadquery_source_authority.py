from __future__ import annotations

import ast
import json
from copy import deepcopy
from typing import Any

from app.services.cad.cadquery_contract import (
    CadQueryContractError,
    CadQuerySourceMetadata,
    validate_cadquery_source,
)
from app.services.cad.parameter_effects import (
    build_parameter_effect_contract,
    classify_derived_dependency_findings,
    validate_parameter_effects,
)
from app.services.cad.pattern_coordinates import validate_pattern_push_points_source
from app.services.cad.patterns import exposed_control_ids, parameter_requires_effect
from app.services.requirements.trace import values_match


SCHEMA_VERSION = "cadquery-source-authority-v1"
VALIDATOR_VERSION = "cadquery-source-authority-v1"


class CadQuerySourceAuthorityError(ValueError):
    def __init__(self, findings: list[dict[str, Any]]) -> None:
        self.findings = findings
        message = "; ".join(finding["rule_id"] for finding in findings)
        super().__init__(message)


def build_cadquery_source_authority(
    design_plan_payload: dict[str, Any] | None,
    *,
    allowed_revision_parameters: list[str] | tuple[str, ...] = (),
) -> dict[str, Any] | None:
    if not design_plan_payload:
        return None
    functional_parameter_ids = _functional_parameter_ids(design_plan_payload)
    standard_lookup_input_ids = _standard_lookup_input_ids(design_plan_payload)
    parameters = [
        _authority_parameter(parameter)
        for parameter in design_plan_payload.get("parameters", []) or []
        if isinstance(parameter, dict) and parameter.get("id")
    ]
    parameter_ids = {parameter["id"] for parameter in parameters}
    for derived in design_plan_payload.get("derived_parameters", []) or []:
        if not isinstance(derived, dict) or not derived.get("id") or derived.get("value") is None:
            continue
        if str(derived["id"]) in parameter_ids:
            continue
        parameters.append(
            _authority_parameter(
                {
                    **derived,
                    "editable": False,
                    "protected": False,
                    "required": False,
                    "source": "calculated",
                }
            )
        )
        parameter_ids.add(str(derived["id"]))
    for parameter in parameters:
        parameter["functional"] = parameter["id"] in functional_parameter_ids
        if parameter["id"] in standard_lookup_input_ids:
            parameter["required"] = False
    components = [
        {"id": str(component["id"]), "required": True}
        for component in design_plan_payload.get("components", []) or []
        if isinstance(component, dict) and component.get("id")
    ]
    features = [
        _authority_feature(feature)
        for feature in design_plan_payload.get("features", []) or []
        if isinstance(feature, dict) and feature.get("id")
    ]
    functional_feature_ids = _functional_feature_ids(design_plan_payload)
    for feature in features:
        feature["functional"] = (
            feature["id"] in functional_feature_ids
            or str(feature.get("type") or "").lower() in {"retention", "support", "containment"}
        )
        if feature["id"] in functional_feature_ids:
            feature["required"] = True
    outputs = [
        _authority_output(output)
        for output in design_plan_payload.get("printable_outputs", []) or []
        if isinstance(output, dict) and (output.get("id") or output.get("output_id"))
    ]
    retention_interfaces = [
        {
            key: interface.get(key)
            for key in (
                "id",
                "strategy",
                "component_id",
                "feature_id",
                "retained_object_requirement_id",
                "retention_direction",
                "removal_direction",
                "parameters",
            )
            if interface.get(key) is not None
        }
        for interface in (design_plan_payload.get("functional_contract") or {}).get("retention_interfaces", []) or []
        if isinstance(interface, dict)
    ]
    authority = {
        "schema_version": SCHEMA_VERSION,
        "parameters": parameters,
        "components": components,
        "features": features,
        "outputs": outputs,
        "retention_interfaces": retention_interfaces,
        "feature_layouts": [
            item for item in design_plan_payload.get("feature_layouts", []) or []
            if isinstance(item, dict)
        ],
        "exposed_control_ids": sorted(exposed_control_ids(design_plan_payload))
        if "exposed_controls" in design_plan_payload
        else None,
        "allowed_revision_parameters": sorted(str(item) for item in allowed_revision_parameters),
    }
    effect_contract = build_parameter_effect_contract(design_plan_payload)
    authority["parameter_effect_contract"] = effect_contract
    authority["derived_parameter_manifest"] = list(effect_contract.get("derived_parameters", []))
    authority["parameter_effect_manifest"] = list(effect_contract.get("functions", []))
    authority["pattern_manifest"] = list(effect_contract.get("patterns", []))
    findings = validate_cadquery_source_authority_inventory(authority)
    if findings:
        raise CadQuerySourceAuthorityError(findings)
    return authority


def authority_from_generation_context(
    *,
    design_plan_payload: dict[str, Any] | None,
    revision_plan_payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    allowed_revision_parameters: list[str] = []
    if revision_plan_payload:
        allowed_revision_parameters.extend(
            str(parameter_id)
            for parameter_id in revision_plan_payload.get("allowed_parameter_changes", []) or []
            if parameter_id
        )
        for change in revision_plan_payload.get("requested_changes", []) or []:
            if not isinstance(change, dict):
                continue
            if change.get("target_type") == "product_parameter" and change.get("target_id"):
                allowed_revision_parameters.append(str(change["target_id"]))
    return build_cadquery_source_authority(
        design_plan_payload,
        allowed_revision_parameters=allowed_revision_parameters,
    )


def validate_cadquery_source_authority_inventory(authority: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for collection_name in ("parameters", "components", "features", "outputs"):
        ids = [
            str(item.get("id"))
            for item in authority.get(collection_name, []) or []
            if isinstance(item, dict) and item.get("id")
        ]
        for duplicate_id in _duplicates(ids):
            findings.append(
                _finding(
                    f"cadquery.authority_duplicate_{collection_name[:-1]}",
                    f"Approved Design Plan contains duplicate {collection_name[:-1]} id `{duplicate_id}`.",
                    identity_id=duplicate_id,
                )
            )
    component_ids = {
        str(component.get("id"))
        for component in authority.get("components", []) or []
        if isinstance(component, dict) and component.get("id")
    }
    for output in authority.get("outputs", []) or []:
        if not isinstance(output, dict):
            continue
        output_id = str(output.get("id") or "")
        output_components = [str(value) for value in output.get("component_ids", []) if value]
        if not output_components:
            findings.append(
                _finding(
                    "cadquery.authority_output_component_missing",
                    f"Approved output `{output_id}` has no component mapping.",
                    output_id=output_id,
                )
            )
        for component_id in output_components:
            if component_id not in component_ids:
                findings.append(
                    _finding(
                        "cadquery.authority_output_component_invalid",
                        f"Approved output `{output_id}` references unknown component `{component_id}`.",
                        output_id=output_id,
                        component_id=component_id,
                    )
                )
        if output.get("required", True) and output.get("expected_solid_count") is None:
            findings.append(
                _finding(
                    "cadquery.authority_output_solid_count_missing",
                    f"Required output `{output_id}` has no expected solid-count policy.",
                    output_id=output_id,
                )
            )
    for parameter in authority.get("parameters", []) or []:
        if not isinstance(parameter, dict):
            continue
        parameter_id = str(parameter.get("id") or "")
        if parameter.get("required", True) and not parameter.get("type"):
            findings.append(
                _finding(
                    "cadquery.authority_parameter_type_missing",
                    f"Required parameter `{parameter_id}` has no approved type.",
                    parameter_id=parameter_id,
                )
            )
        if parameter.get("protected") and parameter.get("value") is None:
            findings.append(
                _finding(
                    "cadquery.authority_protected_parameter_value_missing",
                    f"Protected parameter `{parameter_id}` has no approved value.",
                    parameter_id=parameter_id,
                )
            )
    return findings


def validate_cadquery_source_authority(
    source: str,
    authority: dict[str, Any] | None,
) -> dict[str, Any]:
    if not authority:
        return {
            "schema_version": VALIDATOR_VERSION,
            "passed_hard_checks": True,
            "findings": [],
        }
    contract = authority.get("parameter_effect_contract")
    diagnostic_findings = []
    if isinstance(contract, dict):
        diagnostic_findings = [
            deepcopy(item)
            for item in classify_derived_dependency_findings(contract, source=None)
            if not item.get("blocking", item.get("is_blocking", True))
        ]
    findings = validate_cadquery_source_authority_inventory(authority)
    try:
        metadata = validate_cadquery_source(source, contract_version="cadquery-v1")
    except CadQueryContractError as exc:
        findings.append(
            _finding(
                "cadquery.contract",
                "Generated source does not satisfy the cadquery-v1 source contract.",
                detected_value=str(exc),
            )
        )
        raise CadQuerySourceAuthorityError(findings) from exc
    findings.extend(
        _validate_source_against_authority(
            source=source,
            source_metadata=metadata,
            authority=authority,
        )
    )
    identity_diagnostics = _source_local_identity_diagnostics(source, authority)
    if findings:
        raise CadQuerySourceAuthorityError(findings)
    return {
        "schema_version": VALIDATOR_VERSION,
        "passed_hard_checks": True,
        "findings": [],
        "diagnostic_findings": diagnostic_findings + identity_diagnostics,
    }


def format_authoritative_identity_section(authority: dict[str, Any] | None) -> str:
    if not authority:
        return ""
    lines = [
        "AUTHORITATIVE SOURCE IDENTITIES",
        "",
        "You must implement every required identity below exactly.",
        "Do not rename, alias, replace, shorten, or invent product IDs.",
        "Python function and variable names may differ, but decorator/metadata IDs must match exactly.",
        "Every required parameter must be declared as a module-level ParameterSpec so the scaffold remains inspectable.",
        "Only explicitly exposed controls must remain source-sensitive through params[\"parameter_id\"] or their approved internal chain.",
        "Ordinary requirements and proposals may be implemented with safe local values or literals when the resulting geometry is checked after execution.",
        "",
        "Authoritative identity inventory JSON:",
        json.dumps(authority, indent=2, sort_keys=True),
        "",
        "Required parameters:",
    ]
    for parameter in authority.get("parameters", []) or []:
        lines.append(
            "- {id}: type={type}, value={value}, unit={unit}, protected={protected}, required={required}".format(
                id=parameter.get("id"),
                type=parameter.get("type"),
                value=parameter.get("value"),
                unit=parameter.get("unit"),
                protected=parameter.get("protected"),
                required=parameter.get("required", True),
            )
        )
    lines.append("Required components:")
    for component in authority.get("components", []) or []:
        lines.append(f"- {component.get('id')}")
    lines.append("Required features:")
    for feature in authority.get("features", []) or []:
        if not feature.get("required"):
            continue
        lines.append(
            f"- {feature.get('id')} on component {feature.get('component_id')} "
            f"(protected={feature.get('protected')})"
        )
    lines.append("Required outputs:")
    for output in authority.get("outputs", []) or []:
        lines.append(
            "- {id}: component_ids={component_ids}, expected_solid_count={expected_solid_count}, required={required}".format(
                id=output.get("id"),
                component_ids=output.get("component_ids"),
                expected_solid_count=output.get("expected_solid_count"),
                required=output.get("required", True),
            )
        )
    lines.append("Canonical repeated patterns:")
    for pattern in authority.get("pattern_manifest", []) or []:
        coordinate_description = (
            f"space={pattern.get('coordinate_space')}, "
            f"frame={pattern.get('coordinate_frame_id') or 'unspecified'}, "
            f"axis={pattern.get('arrangement_axis') or 'unspecified'}, "
            f"consumer={pattern.get('consumer_operation') or 'provider-selected'}"
        )
        if pattern.get("effect_required", True):
            lines.append(
                f"- {pattern.get('pattern_id')}: use params[{pattern.get('point_parameter_id')!r}] "
                f"for {pattern.get('pattern_type')} points ({coordinate_description}); "
                "provider must not replace or truncate it."
            )
        else:
            lines.append(
                f"- {pattern.get('pattern_id')}: fixed layout; use the approved feature-layout positions "
                f"({coordinate_description}) and do not infer future count or spacing sensitivity."
            )
    lines.extend(
        [
            "",
            "Before returning source, verify that each required identity appears exactly once in the required role.",
        ]
    )
    return "\n".join(lines)


def _validate_source_against_authority(
    *,
    source: str,
    source_metadata: CadQuerySourceMetadata,
    authority: dict[str, Any],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    structured_source = _is_structured_scaffold_source(source)
    if structured_source:
        findings.extend(_validate_parameter_effect_manifest(source, authority))
        findings.extend(
            validate_pattern_push_points_source(
                source,
                authority.get("pattern_manifest", []) or [],
            )
        )
    ast_metadata = _ast_identity_metadata(source)
    source_parameter_ids = set(source_metadata.parameter_ids)
    source_component_ids = set(source_metadata.component_ids) | set(ast_metadata["component_ids"])
    source_output_ids = set(source_metadata.output_ids)
    source_feature_components = dict(ast_metadata["feature_components"])
    source_param_refs = set(ast_metadata["parameter_references"])
    source_param_geometry_effects = set(ast_metadata["parameter_geometry_effects"])
    source_feature_invocations = dict(ast_metadata["feature_invocations"])
    source_feature_result_used = dict(ast_metadata["feature_result_used"])
    source_feature_component_builders = dict(ast_metadata["feature_component_builders"])
    source_defaults = dict(source_metadata.parameter_defaults)
    source_types = dict(source_metadata.parameter_types)
    source_units = dict(source_metadata.parameter_units)
    source_protected = dict(source_metadata.parameter_protected)
    source_requirement_ids = dict(source_metadata.parameter_source_requirement_ids)
    source_sources = dict(source_metadata.parameter_sources)
    effect_parameter_ids = {
        str(obligation.get("parameter_id"))
        for manifest in authority.get("parameter_effect_manifest", []) or []
        if isinstance(manifest, dict)
        for obligation in manifest.get("required_parameter_effects", []) or []
        if isinstance(obligation, dict) and obligation.get("parameter_id")
    } if structured_source else set()
    effect_invalid_parameter_ids = {
        str(finding.get("parameter_id"))
        for finding in findings
        if finding.get("category") == "geometry_body" and finding.get("parameter_id")
    }
    approved_parameter_ids = {
        str(parameter.get("id"))
        for parameter in authority.get("parameters", []) or []
        if isinstance(parameter, dict) and parameter.get("id")
    }
    modern_control_contract = authority.get("exposed_control_ids") is not None
    exposed_control_ids = {
        str(parameter_id)
        for parameter_id in authority.get("exposed_control_ids", []) or []
        if parameter_id
    }
    approved_component_ids = {
        str(component.get("id"))
        for component in authority.get("components", []) or []
        if isinstance(component, dict) and component.get("id")
    }
    approved_output_ids = {
        str(output.get("id"))
        for output in authority.get("outputs", []) or []
        if isinstance(output, dict) and output.get("id")
    }
    for parameter in authority.get("parameters", []) or []:
        if not isinstance(parameter, dict) or not parameter.get("id"):
            continue
        parameter_id = str(parameter["id"])
        required = bool(parameter.get("required", True))
        if modern_control_contract:
            # Ordinary modern plans are requirement-led and may implement
            # values as literals or locals.  Only explicitly exposed
            # controls require a matching ParameterSpec identity here.
            required = parameter_id in exposed_control_ids
        if required and parameter_id not in source_parameter_ids:
            findings.append(
                _finding(
                    "cadquery.required_parameter_missing",
                    f"Required parameter `{parameter_id}` is missing from source ParameterSpec metadata.",
                    parameter_id=parameter_id,
                )
            )
        if (
            required
            and parameter_id not in source_param_refs
            and parameter_requires_effect(
                parameter,
                exposed_control_ids=(
                    set(authority.get("exposed_control_ids"))
                    if authority.get("exposed_control_ids") is not None
                    else None
                ),
                legacy_default=True,
            )
            and (parameter_id not in effect_parameter_ids or parameter_id in effect_invalid_parameter_ids)
        ):
            findings.append(
                _finding(
                    "cadquery.required_parameter_unused",
                    f"Required parameter `{parameter_id}` is not referenced through params[\"{parameter_id}\"].",
                    parameter_id=parameter_id,
                )
            )
        if parameter_id not in source_parameter_ids:
            continue
        if (
            parameter_id in source_param_refs
            and parameter_id not in source_param_geometry_effects
            and (parameter.get("protected") or parameter.get("functional"))
            and parameter_requires_effect(
                parameter,
                exposed_control_ids=(
                    set(authority.get("exposed_control_ids"))
                    if authority.get("exposed_control_ids") is not None
                    else None
                ),
                legacy_default=True,
            )
            and (parameter_id not in effect_parameter_ids or parameter_id in effect_invalid_parameter_ids)
        ):
            findings.append(
                _finding(
                    "cadquery.protected_parameter_no_geometry_effect"
                    if parameter.get("protected")
                    else "cadquery.functional_parameter_unused",
                    f"Parameter `{parameter_id}` is referenced but its value does not reach a geometry operation.",
                    parameter_id=parameter_id,
                )
            )
        mismatch = _parameter_metadata_mismatch(
            parameter,
            source_default=source_defaults.get(parameter_id),
            source_type=source_types.get(parameter_id),
            source_unit=source_units.get(parameter_id),
            source_protected=source_protected.get(parameter_id),
            source_requirement_id=source_requirement_ids.get(parameter_id),
            source_source=source_sources.get(parameter_id),
        )
        if mismatch:
            findings.append(mismatch)
    allowed_revision_parameters = {
        str(parameter_id)
        for parameter_id in authority.get("allowed_revision_parameters", []) or []
        if parameter_id
    }
    for parameter_id in sorted(source_parameter_ids - approved_parameter_ids - allowed_revision_parameters):
        findings.append(
            _finding(
                "cadquery.unapproved_identity_added",
                f"Source declares unapproved parameter identity `{parameter_id}`.",
                parameter_id=parameter_id,
                detected_value=parameter_id,
            )
        )
    for component in authority.get("components", []) or []:
        if not isinstance(component, dict) or not component.get("id"):
            continue
        component_id = str(component["id"])
        if component.get("required", True) and component_id not in source_component_ids:
            findings.append(
                _finding(
                    "cadquery.required_component_missing",
                    f"Required component `{component_id}` is missing from source metadata.",
                    component_id=component_id,
                )
            )
    for component_id in sorted(source_component_ids - approved_component_ids):
        findings.append(
            _finding(
                "cadquery.unapproved_identity_added",
                f"Source declares unapproved component identity `{component_id}`.",
                component_id=component_id,
                detected_value=component_id,
            )
        )
    for feature in authority.get("features", []) or []:
        if not isinstance(feature, dict) or not feature.get("id"):
            continue
        feature_id = str(feature["id"])
        required = bool(feature.get("required", feature.get("protected", False)))
        if not required:
            continue
        expected_component = str(feature.get("component_id") or "")
        detected_component = source_feature_components.get(feature_id)
        if detected_component is None:
            findings.append(
                _finding(
                    "cadquery.required_feature_missing",
                    f"Required feature `{feature_id}` is missing from source metadata.",
                    feature_id=feature_id,
                    component_id=expected_component or None,
                )
            )
        elif expected_component and detected_component != expected_component:
            findings.append(
                _finding(
                    "cadquery.component_identity_mismatch",
                    f"Feature `{feature_id}` is mapped to component `{detected_component}` instead of `{expected_component}`.",
                    feature_id=feature_id,
                    expected_value=expected_component,
                    detected_value=detected_component,
                )
            )
        elif not source_feature_invocations.get(feature_id, False):
            findings.append(
                _finding(
                    "functional.feature_declared_not_invoked",
                    f"Required feature `{feature_id}` is declared but its builder is never invoked.",
                    feature_id=feature_id,
                    component_id=expected_component or None,
                )
                )
        elif feature.get("functional") and not source_feature_result_used.get(feature_id, False):
            findings.append(
                _finding(
                    "functional.feature_result_discarded",
                    f"Functional feature `{feature_id}` is invoked but its returned geometry is discarded.",
                    feature_id=feature_id,
                    component_id=expected_component or None,
                )
            )
        elif feature.get("functional") and source_feature_component_builders.get(feature_id, False):
            findings.append(
                _finding(
                    "functional.protected_feature_missing",
                    f"Functional feature `{feature_id}` is only declared on the component builder; no dedicated feature builder was identified.",
                    feature_id=feature_id,
                    component_id=expected_component or None,
                )
            )
    for output in authority.get("outputs", []) or []:
        if not isinstance(output, dict) or not output.get("id"):
            continue
        output_id = str(output["id"])
        if output.get("required", True) and output_id not in source_output_ids:
            findings.append(
                _finding(
                    "cadquery.required_output_missing",
                    f"Required output `{output_id}` is missing from source PrintableOutput metadata.",
                    output_id=output_id,
                )
            )
            continue
        expected_components = sorted(str(value) for value in output.get("component_ids", []) if value)
        detected_components = sorted(source_metadata.output_component_ids.get(output_id, []))
        if output_id in source_output_ids and expected_components != detected_components:
            findings.append(
                _finding(
                    "cadquery.output_component_mismatch",
                    f"Output `{output_id}` is mapped to components {detected_components} instead of {expected_components}.",
                    output_id=output_id,
                    expected_value=expected_components,
                    detected_value=detected_components,
                )
            )
        expected_solid_count = output.get("expected_solid_count")
        detected_solid_count = source_metadata.expected_solid_counts.get(output_id)
        if (
            output_id in source_output_ids
            and expected_solid_count is not None
            and detected_solid_count is not None
            and int(expected_solid_count) != int(detected_solid_count)
        ):
            findings.append(
                _finding(
                    "cadquery.output_identity_mismatch",
                    f"Output `{output_id}` has expected_solid_count {detected_solid_count} instead of {expected_solid_count}.",
                    output_id=output_id,
                    expected_value=expected_solid_count,
                    detected_value=detected_solid_count,
                )
            )
    for output_id in sorted(source_output_ids - approved_output_ids):
        findings.append(
            _finding(
                "cadquery.unapproved_identity_added",
                f"Source declares unapproved output identity `{output_id}`.",
                output_id=output_id,
                detected_value=output_id,
            )
        )
    return findings


def _source_local_identity_diagnostics(
    source: str,
    authority: dict[str, Any],
) -> list[dict[str, Any]]:
    """Record provider locals without promoting them to plan identities."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    protected = {
        str(value)
        for collection in ("parameters", "components", "features", "outputs")
        for item in authority.get(collection, []) or []
        if isinstance(item, dict)
        for value in (item.get("id"),)
        if value
    }
    protected.update(
        str(value) for value in authority.get("exposed_control_ids", []) or [] if value
    )
    diagnostics: list[dict[str, Any]] = []
    for function in (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)):
        for node in ast.walk(function):
            if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Store):
                continue
            symbol = str(node.id)
            if symbol in {"params", "PARAMETERS"} or symbol in protected:
                continue
            diagnostics.append(
                {
                    "rule_id": "source.local_implementation_variable",
                    "category": "source_identity",
                    "severity": "info",
                    "is_blocking": False,
                    "function_id": function.name,
                    "symbol": symbol,
                    "reason": "provider-owned local implementation variable; not exported as a plan identity",
                    "line": getattr(node, "lineno", None),
                    "column": getattr(node, "col_offset", None),
                }
            )
    return diagnostics


def _authority_parameter(parameter: dict[str, Any]) -> dict[str, Any]:
    value = parameter.get("value")
    return {
        "id": str(parameter["id"]),
        "type": _normalize_parameter_type(
            str(parameter.get("type") or parameter.get("parameter_type") or _infer_parameter_type(parameter))
        ),
        "unit": parameter.get("unit"),
        "value": value,
        "protected": bool(parameter.get("protected", False)),
        "required": bool(parameter.get("required", True)),
        "source_requirement_id": parameter.get("source_requirement_id"),
        "source": parameter.get("source"),
        "component_id": parameter.get("component_id"),
        "provenance": parameter.get("provenance"),
        "constraint_mode": parameter.get("constraint_mode"),
    }


def _standard_lookup_input_ids(plan: dict[str, Any] | None) -> set[str]:
    if not isinstance(plan, dict):
        return set()
    ids: set[str] = set()
    for parameter in list(plan.get("parameters", []) or []) + list(plan.get("derived_parameters", []) or []):
        if not isinstance(parameter, dict):
            continue
        provenance = parameter.get("provenance")
        if not isinstance(provenance, dict) or provenance.get("relationship") != "standard_lookup":
            continue
        for key in ("source_requirement_ids", "source_parameter_ids"):
            ids.update(str(value) for value in provenance.get(key, []) or [] if value)
    return ids


def _functional_parameter_ids(plan: dict[str, Any] | None) -> set[str]:
    if not isinstance(plan, dict):
        return set()
    contract = plan.get("functional_contract")
    if not isinstance(contract, dict):
        return set()
    ids: set[str] = set()
    for collection in ("mounting_interfaces", "support_interfaces", "containment_interfaces", "retention_interfaces"):
        for interface in contract.get(collection, []) or []:
            if not isinstance(interface, dict):
                continue
            for key in ("object_requirement_id", "hole_diameter_parameter_id", "floor_thickness_parameter_id"):
                if interface.get(key):
                    ids.add(str(interface[key]))
            for parameter in interface.get("parameters", []) or []:
                if isinstance(parameter, dict) and parameter.get("id"):
                    ids.add(str(parameter["id"]))
    return ids


def _functional_feature_ids(plan: dict[str, Any] | None) -> set[str]:
    if not isinstance(plan, dict):
        return set()
    contract = plan.get("functional_contract")
    if not isinstance(contract, dict):
        return set()
    return {
        str(interface["feature_id"])
        for interface in contract.get("retention_interfaces", []) or []
        if isinstance(interface, dict) and interface.get("feature_id")
    }


def _normalize_parameter_type(parameter_type: str) -> str:
    return {
        "number": "float",
        "integer": "int",
        "boolean": "bool",
    }.get(parameter_type, parameter_type)


def _authority_feature(feature: dict[str, Any]) -> dict[str, Any]:
    protected = bool(feature.get("protected", False))
    return {
        "id": str(feature["id"]),
        "component_id": str(feature.get("component_id") or ""),
        "type": feature.get("type"),
        "protected": protected,
        "required": bool(feature.get("required", protected or feature.get("revision_targetable") or feature.get("targetable"))),
        "parameters": [str(parameter_id) for parameter_id in feature.get("parameters", []) or []],
    }


def _authority_output(output: dict[str, Any]) -> dict[str, Any]:
    output_id = str(output.get("id") or output.get("output_id"))
    component_ids = [str(value) for value in output.get("component_ids", []) or [] if value]
    component_id = output.get("component_id")
    if component_id and str(component_id) not in component_ids:
        component_ids.append(str(component_id))
    expected_solid_count = output.get("expected_solid_count")
    if expected_solid_count is None:
        expected_solid_count = 1
    return {
        "id": output_id,
        "component_id": component_ids[0] if len(component_ids) == 1 else None,
        "component_ids": component_ids,
        "required": bool(output.get("required", True)),
        "expected_solid_count": expected_solid_count,
        "allow_disconnected_solids": bool(output.get("allow_disconnected_solids", False)),
        "quantity": output.get("quantity", 1),
    }


def _infer_parameter_type(parameter: dict[str, Any]) -> str:
    value = parameter.get("value")
    unit = str(parameter.get("unit") or "").lower()
    parameter_id = str(parameter.get("id") or "").lower()
    if isinstance(value, bool):
        return "bool"
    if unit == "count" or parameter_id.endswith("_count") or parameter_id in {"count", "quantity"}:
        return "int"
    if unit in {"mm", "millimeter", "millimeters", "deg", "degree", "degrees"}:
        return "float"
    if isinstance(value, int | float) and not isinstance(value, bool):
        return "float"
    if isinstance(value, str):
        return "str"
    return "float"


def _parameter_metadata_mismatch(
    parameter: dict[str, Any],
    *,
    source_default: Any,
    source_type: str | None,
    source_unit: str | None,
    source_protected: bool | None,
    source_requirement_id: str | None,
    source_source: str | None,
) -> dict[str, Any] | None:
    parameter_id = str(parameter["id"])
    if not values_match(source_default, parameter.get("value")):
        return _finding(
            "cadquery.protected_value_mismatch"
            if parameter.get("protected")
            else "cadquery.required_parameter_metadata_mismatch",
            f"Parameter `{parameter_id}` default is {source_default!r} instead of approved value {parameter.get('value')!r}.",
            parameter_id=parameter_id,
            expected_value=parameter.get("value"),
            detected_value=source_default,
        )
    if source_type is not None and parameter.get("type") and source_type != parameter.get("type"):
        return _finding(
            "cadquery.required_parameter_metadata_mismatch",
            f"Parameter `{parameter_id}` type is `{source_type}` instead of `{parameter.get('type')}`.",
            parameter_id=parameter_id,
            expected_value=parameter.get("type"),
            detected_value=source_type,
        )
    if parameter.get("unit") is not None and source_unit != parameter.get("unit"):
        return _finding(
            "cadquery.required_parameter_metadata_mismatch",
            f"Parameter `{parameter_id}` unit is `{source_unit}` instead of `{parameter.get('unit')}`.",
            parameter_id=parameter_id,
            expected_value=parameter.get("unit"),
            detected_value=source_unit,
        )
    if bool(source_protected) != bool(parameter.get("protected", False)):
        return _finding(
            "cadquery.required_parameter_metadata_mismatch",
            f"Parameter `{parameter_id}` protected flag is `{source_protected}` instead of `{parameter.get('protected')}`.",
            parameter_id=parameter_id,
            expected_value=parameter.get("protected"),
            detected_value=source_protected,
        )
    expected_requirement_id = parameter.get("source_requirement_id")
    if expected_requirement_id and source_requirement_id != expected_requirement_id:
        return _finding(
            "cadquery.required_parameter_metadata_mismatch",
            f"Parameter `{parameter_id}` source_requirement_id is `{source_requirement_id}` instead of `{expected_requirement_id}`.",
            parameter_id=parameter_id,
            expected_value=expected_requirement_id,
            detected_value=source_requirement_id,
        )
    expected_source = parameter.get("source")
    if expected_source and source_source != expected_source:
        return _finding(
            "cadquery.required_parameter_metadata_mismatch",
            f"Parameter `{parameter_id}` source is `{source_source}` instead of `{expected_source}`.",
            parameter_id=parameter_id,
            expected_value=expected_source,
            detected_value=source_source,
        )
    return None


def _ast_identity_metadata(source: str) -> dict[str, Any]:
    tree = ast.parse(source)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    component_ids: list[str] = []
    feature_components: dict[str, str] = {}
    feature_functions: dict[str, str] = {}
    component_function_names: set[str] = set()
    parameter_references: list[str] = []
    parameter_geometry_effects: set[str] = set()
    parameter_loads: dict[str, list[ast.Subscript]] = {}
    geometry_methods = {
        "box",
        "chamfer",
        "circle",
        "cut",
        "cylinder",
        "extrude",
        "fillet",
        "hole",
        "loft",
        "mirror",
        "polygon",
        "pushPoints",
        "rect",
        "rotate",
        "translate",
        "union",
        "workplane",
    }
    geometry_call_names: set[str] = set()
    geometry_function_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr in geometry_methods
            for call in ast.walk(node)
        )
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name):
                    if decorator.func.id == "component":
                        component_id = _string_arg(decorator)
                        if component_id:
                            component_ids.append(component_id)
                            component_function_names.add(node.name)
                    if decorator.func.id == "feature":
                        feature_id = _string_arg(decorator)
                        component_id = _string_keyword(decorator, "component")
                        if feature_id and component_id:
                            feature_components[feature_id] = component_id
                            feature_functions[feature_id] = node.name
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "params":
            parameter_id = _subscript_string(node.slice)
            if parameter_id:
                parameter_references.append(parameter_id)
                parameter_loads.setdefault(parameter_id, []).append(node)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "params"
            and node.args
        ):
            parameter_id = _subscript_string(node.args[0])
            if parameter_id:
                parameter_references.append(parameter_id)
                parameter_loads.setdefault(parameter_id, []).append(node)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                geometry_call_names.add(node.func.attr)
            elif isinstance(node.func, ast.Name):
                geometry_call_names.add(node.func.id)
    for function in (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)):
        aliases: dict[str, set[str]] = {}
        assignments = [node for node in ast.walk(function) if isinstance(node, ast.Assign)]
        for _ in range(len(assignments) + 1):
            changed = False
            for assignment in assignments:
                if len(assignment.targets) != 1 or not isinstance(assignment.targets[0], ast.Name):
                    continue
                dependencies = _expression_parameter_dependencies(assignment.value, aliases)
                target = assignment.targets[0].id
                if dependencies and aliases.get(target) != dependencies:
                    aliases[target] = dependencies
                    changed = True
            if not changed:
                break
        has_geometry_call = any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr in geometry_methods
            for call in ast.walk(function)
        )
        for call in (node for node in ast.walk(function) if isinstance(node, ast.Call)):
            if isinstance(call.func, ast.Attribute) and call.func.attr in geometry_methods:
                for argument in call.args + [keyword.value for keyword in call.keywords]:
                    parameter_geometry_effects.update(
                        _expression_parameter_dependencies(argument, aliases)
                    )
            elif isinstance(call.func, ast.Name) and call.func.id == "range" and has_geometry_call:
                for argument in call.args:
                    parameter_geometry_effects.update(
                        _expression_parameter_dependencies(argument, aliases)
                    )
    for parameter_id, loads in parameter_loads.items():
        for load in loads:
            ancestor = parents.get(load)
            while ancestor is not None and not isinstance(ancestor, ast.FunctionDef):
                if isinstance(ancestor, ast.Call):
                    if isinstance(ancestor.func, ast.Attribute) and ancestor.func.attr in geometry_methods:
                        parameter_geometry_effects.add(parameter_id)
                    elif isinstance(ancestor.func, ast.Name) and ancestor.func.id in geometry_function_names:
                        parameter_geometry_effects.add(parameter_id)
                    elif isinstance(ancestor.func, ast.Name) and ancestor.func.id == "range":
                        function = next(
                            (
                                candidate
                                for candidate in ast.walk(tree)
                                if isinstance(candidate, ast.FunctionDef)
                                and load in {descendant for descendant in ast.walk(candidate)}
                            ),
                            None,
                        )
                        if function is not None and any(
                            isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Attribute)
                            and call.func.attr in geometry_methods
                            for call in ast.walk(function)
                        ):
                            parameter_geometry_effects.add(parameter_id)
                ancestor = parents.get(ancestor)
    call_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    feature_invocations = {
        feature_id: function_name in call_names
        for feature_id, function_name in feature_functions.items()
    }
    feature_result_used = {
        feature_id: any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == function_name
            and isinstance(parents.get(node), (ast.Assign, ast.AnnAssign, ast.Return, ast.Call, ast.Attribute, ast.keyword))
            for node in ast.walk(tree)
        )
        for feature_id, function_name in feature_functions.items()
    }
    feature_component_builders = {
        feature_id: function_name in component_function_names
        for feature_id, function_name in feature_functions.items()
    }
    return {
        "component_ids": _dedupe(component_ids),
        "feature_components": feature_components,
        "parameter_references": _dedupe(parameter_references),
        "parameter_geometry_effects": sorted(parameter_geometry_effects),
        "feature_invocations": feature_invocations,
        "feature_result_used": feature_result_used,
        "feature_component_builders": feature_component_builders,
    }


def _validate_parameter_effect_manifest(
    source: str, authority: dict[str, Any]
) -> list[dict[str, Any]]:
    contract = authority.get("parameter_effect_contract")
    if not isinstance(contract, dict):
        return []
    findings: list[dict[str, Any]] = []
    classified_dependencies = classify_derived_dependency_findings(contract, source=source)
    for dependency_finding in classified_dependencies:
        if isinstance(dependency_finding, dict) and dependency_finding.get(
            "blocking", dependency_finding.get("is_blocking", True)
        ):
            findings.append(dependency_finding)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return findings
    nodes_by_name = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    component_nodes: dict[str, ast.FunctionDef] = {}
    feature_nodes: dict[str, ast.FunctionDef] = {}
    for node in nodes_by_name.values():
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Name):
                continue
            stable_id = _string_arg(decorator)
            if decorator.func.id == "component" and stable_id:
                component_nodes[stable_id] = node
            elif decorator.func.id == "feature" and stable_id:
                feature_nodes[stable_id] = node
    for manifest in contract.get("functions", []) or []:
        if not isinstance(manifest, dict) or not manifest.get("function_id"):
            continue
        function_id = str(manifest["function_id"])
        node = nodes_by_name.get(function_id)
        if node is None:
            feature_id = manifest.get("feature_id")
            if feature_id:
                node = feature_nodes.get(str(feature_id))
            if node is None and manifest.get("owner_component_id"):
                node = component_nodes.get(str(manifest["owner_component_id"]))
        if node is None:
            continue
        effect_findings = validate_parameter_effects(
            ast.unparse(node),
            manifest,
            derived_parameters=list(contract.get("derived_parameters", [])),
            patterns=list(contract.get("patterns", [])),
        )
        for finding in effect_findings:
            finding.setdefault("title", "Geometry parameter effect contract violation")
            finding.setdefault(
                "suggested_correction",
                "Use the required direct parameter or an approved derived parameter in the intended geometry operation.",
            )
            findings.append(finding)
    return findings


def _is_structured_scaffold_source(source: str) -> bool:
    return "# VOLUNDR_SCAFFOLD_VERSION:" in source


def _expression_parameter_dependencies(
    expression: ast.AST,
    aliases: dict[str, set[str]],
) -> set[str]:
    dependencies: set[str] = set()
    for node in ast.walk(expression):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "params":
            parameter_id = _subscript_string(node.slice)
            if parameter_id:
                dependencies.add(parameter_id)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "params"
            and node.func.attr == "get"
            and node.args
        ):
            parameter_id = _subscript_string(node.args[0])
            if parameter_id:
                dependencies.add(parameter_id)
        elif isinstance(node, ast.Name):
            dependencies.update(aliases.get(node.id, set()))
    return dependencies


def _string_arg(node: ast.Call) -> str | None:
    value = node.args[0] if node.args else None
    if value is None:
        for keyword in node.keywords:
            if keyword.arg == "id":
                value = keyword.value
                break
    if value is None:
        return None
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return None


def _string_keyword(node: ast.Call, name: str) -> str | None:
    for keyword in node.keywords:
        if keyword.arg != name:
            continue
        if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
            return keyword.value.value
    return None


def _subscript_string(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _finding(
    rule_id: str,
    message: str,
    *,
    parameter_id: str | None = None,
    component_id: str | None = None,
    feature_id: str | None = None,
    output_id: str | None = None,
    identity_id: str | None = None,
    expected_value: Any = None,
    detected_value: Any = None,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "category": "source_contract",
        "severity": "critical",
        "is_blocking": True,
        "title": "CadQuery source identity contract violation",
        "explanation": message,
        "suggested_correction": "Regenerate or repair the CadQuery source using the exact approved source identities.",
        "parameter_id": parameter_id,
        "component_id": component_id,
        "feature_id": feature_id,
        "output_id": output_id,
        "identity_id": identity_id,
        "expected_value": deepcopy(expected_value),
        "detected_value": deepcopy(detected_value),
        "metadata": {"validator_version": VALIDATOR_VERSION},
    }


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
