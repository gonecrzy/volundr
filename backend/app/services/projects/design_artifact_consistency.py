from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.services.cad.cadquery_contract import (
    CadQueryContractError,
    validate_cadquery_source,
)
from app.services.projects.requirement_trace_contract import build_requirement_trace_manifest


SCHEMA_VERSION = "design-artifact-consistency-v1"
VALIDATOR_VERSION = "design-artifact-consistency-v1"
READY_OUTPUT_STATES = {"ready", "ready_with_warnings", "validating"}


def certify_design_artifact_consistency(
    *,
    project_id: str,
    revision_id: str,
    design_specification_id: str | None,
    design_specification_payload: dict[str, Any] | None,
    design_plan_id: str | None,
    design_plan_payload: dict[str, Any],
    source: str,
    execution_parameters: dict[str, Any] | None = None,
    execution_manifest: dict[str, Any] | None = None,
    output_manifest: dict[str, Any] | None = None,
    parameter_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_hash = _sha256(source)
    findings: list[dict[str, Any]] = []
    component_mappings: list[dict[str, Any]] = []
    feature_mappings: list[dict[str, Any]] = []
    output_mappings: list[dict[str, Any]] = []
    parameter_mappings: list[dict[str, Any]] = []

    try:
        source_metadata = validate_cadquery_source(source, contract_version="cadquery-v1")
    except CadQueryContractError as exc:
        source_metadata = None
        findings.append(
            _finding(
                "design_artifact.source_contract_invalid",
                "Generated source failed CadQuery contract validation.",
                expected="cadquery-v1",
                detected=str(exc),
            )
        )

    plan_components = _plan_components(design_plan_payload)
    plan_features = _plan_features(design_plan_payload)
    plan_outputs = _plan_outputs(design_plan_payload)
    plan_parameters = _plan_parameters(design_plan_payload)
    derived_parameters = _derived_parameters(design_plan_payload)
    modern_parameter_contract = "exposed_controls" in design_plan_payload
    exposed_control_ids = {
        str(entry.get("parameter_id") or entry.get("id"))
        for entry in design_plan_payload.get("exposed_controls", []) or []
        if isinstance(entry, dict) and (entry.get("parameter_id") or entry.get("id"))
    }
    exposed_control_ids.update(
        str(entry)
        for entry in design_plan_payload.get("exposed_controls", []) or []
        if isinstance(entry, str) and entry
    )
    overrides = dict(parameter_overrides or {})
    if execution_manifest and isinstance(execution_manifest.get("parameter_overrides"), dict):
        overrides.update(execution_manifest["parameter_overrides"])

    source_component_ids = set(source_metadata.component_ids if source_metadata else [])
    source_output_ids = set(source_metadata.output_ids if source_metadata else [])
    source_parameter_ids = set(source_metadata.parameter_ids if source_metadata else [])
    source_defaults = dict(source_metadata.parameter_defaults if source_metadata else {})
    source_types = dict(source_metadata.parameter_types if source_metadata else {})
    source_units = dict(source_metadata.parameter_units if source_metadata else {})
    source_protected = dict(source_metadata.parameter_protected if source_metadata else {})
    source_requirement_ids = dict(
        source_metadata.parameter_source_requirement_ids if source_metadata else {}
    )
    source_parameter_sources = dict(source_metadata.parameter_sources if source_metadata else {})
    source_expected_solid_counts = dict(source_metadata.expected_solid_counts if source_metadata else {})
    source_output_components = dict(source_metadata.output_component_ids if source_metadata else {})
    source_symbols = _source_component_symbols(source) if source_metadata else {}
    source_features = _source_feature_components(source) if source_metadata else {}
    source_feature_symbols = _source_feature_symbols(source) if source_metadata else {}

    requirement_trace = build_requirement_trace_manifest(
        design_specification_payload=design_specification_payload,
        design_plan_payload=design_plan_payload,
        source_component_ids=source_component_ids,
        source_component_symbols=source_symbols,
        source_feature_components=source_features,
        source_feature_symbols=source_feature_symbols,
        source_output_ids=source_output_ids,
        source_output_components=source_output_components,
        source_parameter_ids=source_parameter_ids,
    )
    findings.extend(requirement_trace["findings"])
    normalized_trace_features = {
        str(feature.get("id")): feature
        for feature in requirement_trace.get("normalized", {}).get("features", [])
        if isinstance(feature, dict) and feature.get("id")
    }

    for component_id, component in plan_components.items():
        status = "consistent" if component_id in source_component_ids else "missing_source_component"
        component_mappings.append(
            {
                "plan_component_id": component_id,
                "source_component_id": component_id if component_id in source_component_ids else None,
                "source_symbol": source_symbols.get(component_id),
                "status": status,
            }
        )
        if status != "consistent":
            findings.append(
                _finding(
                    "design_artifact.component_missing",
                    f"planned component `{component_id}` has no matching CadQuery source component",
                    component_id=component_id,
                )
            )

    for feature_id, feature in plan_features.items():
        trace_feature = normalized_trace_features.get(feature_id, feature)
        trace_component_id = str(
            trace_feature.get("component_id")
            or feature.get("component_id")
            or feature.get("owner_component_id")
            or feature.get("owning_component_id")
            or ""
        ) or None
        required = bool(feature.get("protected")) or bool(
            feature.get("revision_targetable") or feature.get("targetable")
        )
        source_component_id = source_features.get(feature_id)
        integral_component_id = _integral_feature_component_source(
            feature_id=feature_id,
            feature=trace_feature,
            components=plan_components,
            source_component_ids=source_component_ids,
        )
        integral_in_component = (
            source_component_id is None
            and integral_component_id is not None
            and integral_component_id == trace_component_id
        )
        status = (
            "consistent"
            if source_component_id == trace_component_id
            else "integral_in_component_function"
            if integral_in_component
            else "missing_source_feature"
        )
        feature_mappings.append(
            {
                "plan_feature_id": feature_id,
                "plan_component_id": trace_component_id,
                "source_feature_id": feature_id if source_component_id else None,
                "source_component_id": source_component_id or integral_component_id,
                "source_symbol": source_symbols.get(integral_component_id) if integral_in_component else None,
                "required": required,
                "status": status,
            }
        )
        if status == "missing_source_feature":
            findings.append(
                _finding(
                    "design_artifact.feature_missing",
                    f"planned feature `{feature_id}` has no matching CadQuery source feature metadata",
                    feature_id=feature_id,
                    component_id=str(feature.get("component_id") or "") or None,
                    blocking=required,
                )
            )

    for output_id, output in plan_outputs.items():
        plan_component_ids = list(output.get("component_ids") or [])
        source_component_list = list(source_output_components.get(output_id, []))
        status = "consistent"
        if output_id not in source_output_ids:
            status = "missing_source_output"
            findings.append(
                _finding(
                    "design_artifact.output_missing",
                    f"planned output `{output_id}` has no matching CadQuery PrintableOutput",
                    output_id=output_id,
                )
            )
        elif sorted(plan_component_ids) != sorted(source_component_list):
            status = "component_mismatch"
            findings.append(
                _finding(
                    "design_artifact.output_component_mismatch",
                    f"planned output `{output_id}` has different component ownership in source",
                    output_id=output_id,
                    expected=plan_component_ids,
                    detected=source_component_list,
                )
            )
        if output_id in source_expected_solid_counts and output.get("expected_solid_count") is not None:
            if int(output["expected_solid_count"]) != int(source_expected_solid_counts[output_id]):
                status = "solid_count_policy_mismatch"
                findings.append(
                    _finding(
                        "design_artifact.output_solid_count_policy_mismatch",
                        f"planned output `{output_id}` expected solid count differs from source",
                        output_id=output_id,
                        expected=output.get("expected_solid_count"),
                        detected=source_expected_solid_counts[output_id],
                    )
                )
        output_mappings.append(
            {
                "plan_output_id": output_id,
                "source_output_id": output_id if output_id in source_output_ids else None,
                "plan_component_ids": plan_component_ids,
                "source_component_ids": source_component_list,
                "required": bool(output.get("required", True)),
                "status": status,
            }
        )

    unexpected_source_outputs = source_output_ids - set(plan_outputs)
    for output_id in sorted(unexpected_source_outputs):
        findings.append(
            _finding(
                "design_artifact.unexpected_source_output",
                f"source declares unexpected output `{output_id}` not present in the approved Design Plan",
                output_id=output_id,
            )
        )

    for parameter_id, parameter in plan_parameters.items():
        parameter_blocking = (
            not modern_parameter_contract
            or parameter_id in exposed_control_ids
        )
        plan_value = parameter.get("value")
        source_default = source_defaults.get(parameter_id)
        execution_value = (execution_parameters or {}).get(parameter_id)
        status = "consistent"
        if parameter_id not in source_parameter_ids:
            status = "missing_source_parameter"
            findings.append(
                _finding(
                    "design_artifact.parameter_missing",
                    f"planned parameter `{parameter_id}` has no matching CadQuery ParameterSpec",
                    parameter_id=parameter_id,
                    blocking=parameter_blocking,
                )
            )
        elif not _values_equal(plan_value, source_default):
            status = "source_default_mismatch"
            findings.append(
                _finding(
                    "design_artifact.parameter_value_mismatch",
                    f"parameter `{parameter_id}` is {plan_value!r} in the plan but {source_default!r} in source",
                    parameter_id=parameter_id,
                    expected=plan_value,
                    detected=source_default,
                    unit=parameter.get("unit"),
                    blocking=parameter_blocking,
                )
            )
        plan_type = _plan_parameter_type(parameter)
        source_type = source_types.get(parameter_id)
        if source_type is not None and plan_type is not None and source_type != plan_type:
            status = "source_type_mismatch"
            findings.append(
                _finding(
                    "design_artifact.parameter_type_mismatch",
                    f"parameter `{parameter_id}` type differs between Plan and source",
                    parameter_id=parameter_id,
                    expected=plan_type,
                    detected=source_type,
                    blocking=parameter_blocking,
                )
            )
        plan_unit = parameter.get("unit")
        source_unit = source_units.get(parameter_id)
        if plan_unit is not None and source_unit != plan_unit:
            status = "source_unit_mismatch"
            findings.append(
                _finding(
                    "design_artifact.parameter_unit_mismatch",
                    f"parameter `{parameter_id}` unit differs between Plan and source",
                    parameter_id=parameter_id,
                    expected=plan_unit,
                    detected=source_unit,
                    unit=str(plan_unit),
                    blocking=parameter_blocking,
                )
            )
        plan_protected = bool(parameter.get("protected", False))
        source_protected_value = source_protected.get(parameter_id)
        if bool(source_protected_value) != plan_protected:
            status = "source_protected_mismatch"
            findings.append(
                _finding(
                    "design_artifact.parameter_protected_mismatch",
                    f"parameter `{parameter_id}` protected flag differs between Plan and source",
                    parameter_id=parameter_id,
                    expected=plan_protected,
                    detected=source_protected_value,
                    blocking=parameter_blocking,
                )
            )
        source_requirement_id = parameter.get("source_requirement_id")
        source_requirement_id = str(source_requirement_id) if source_requirement_id else None
        source_declared_requirement_id = source_requirement_ids.get(parameter_id)
        if source_requirement_id and source_declared_requirement_id != source_requirement_id:
            status = "source_requirement_mapping_missing"
            findings.append(
                _finding(
                    "design_artifact.parameter_source_requirement_missing",
                    f"parameter `{parameter_id}` is not linked to its source requirement in CadQuery metadata",
                    parameter_id=parameter_id,
                    expected=source_requirement_id,
                    detected=source_declared_requirement_id,
                    blocking=parameter_blocking,
                )
            )
        plan_source = parameter.get("source")
        plan_source = str(plan_source) if plan_source else None
        source_declared_source = source_parameter_sources.get(parameter_id)
        if plan_source and source_declared_source != plan_source:
            status = "source_provenance_mismatch"
            findings.append(
                _finding(
                    "design_artifact.parameter_source_mismatch",
                    f"parameter `{parameter_id}` source provenance differs between Plan and source",
                    parameter_id=parameter_id,
                    expected=plan_source,
                    detected=source_declared_source,
                    blocking=parameter_blocking,
                )
            )
        if execution_parameters is not None and parameter_id in execution_parameters:
            if parameter_id not in overrides and not _values_equal(plan_value, execution_value):
                status = "execution_mismatch"
                findings.append(
                    _finding(
                        "design_artifact.execution_parameter_mismatch",
                        f"parameter `{parameter_id}` execution value does not match the approved Plan",
                        parameter_id=parameter_id,
                        expected=plan_value,
                        detected=execution_value,
                        unit=parameter.get("unit"),
                        blocking=parameter_blocking,
                    )
                )
            elif parameter_id in overrides:
                status = "execution_override"
        parameter_mappings.append(
            {
                "parameter_id": parameter_id,
                "plan_value": plan_value,
                "source_default": source_default,
                "execution_value": execution_value,
                "source_requirement_id": parameter.get("source_requirement_id"),
                "source_declared_requirement_id": source_requirement_ids.get(parameter_id),
                "source": parameter.get("source"),
                "source_declared_source": source_declared_source,
                "unit": parameter.get("unit"),
                "source_unit": source_units.get(parameter_id),
                "plan_type": plan_type,
                "source_type": source_types.get(parameter_id),
                "plan_protected": plan_protected,
                "source_protected": source_protected.get(parameter_id),
                "status": status,
            }
        )

    for parameter_id, parameter in derived_parameters.items():
        parameter_mappings.append(
            {
                "parameter_id": parameter_id,
                "plan_value": parameter.get("expression"),
                "source_default": None,
                "execution_value": None,
                "source_requirement_id": None,
                "source": "derived",
                "unit": parameter.get("unit"),
                "status": "derived_not_submitted",
            }
        )

    if execution_parameters is not None:
        for parameter_id in sorted(set(execution_parameters) - source_parameter_ids):
            findings.append(
                _finding(
                    "design_artifact.execution_parameter_undeclared",
                    f"submitted parameter `{parameter_id}` is not declared by the CadQuery source",
                    parameter_id=parameter_id,
                    detected=execution_parameters.get(parameter_id),
                    blocking=not modern_parameter_contract,
                )
            )

    post_requested = execution_manifest is not None or output_manifest is not None
    if output_manifest is not None and execution_manifest is None:
        findings.append(
            _finding(
                "design_artifact.execution_manifest_missing",
                "output artifacts exist but the execution manifest is missing",
                phase="post_execution",
            )
        )
    if execution_manifest is not None:
        _validate_execution_manifest(
            execution_manifest,
            plan_outputs=plan_outputs,
            source_hash=source_hash,
            findings=findings,
        )
    if output_manifest is not None:
        _validate_output_manifest(
            output_manifest,
            plan_outputs=plan_outputs,
            source_hash=source_hash,
            findings=findings,
        )

    blocking_findings = [finding for finding in findings if finding["is_blocking"]]
    pre_execution_passed = not any(
        finding["phase"] == "pre_execution" and finding["is_blocking"]
        for finding in findings
    )
    post_execution_passed = post_requested and not any(
        finding["phase"] == "post_execution" and finding["is_blocking"]
        for finding in findings
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "revision_id": revision_id,
        "design_specification_id": design_specification_id,
        "design_plan_id": design_plan_id,
        "source_hash": source_hash,
        "parameter_hash": _manifest_parameter_hash(output_manifest, execution_manifest),
        "output_manifest_hash": _json_hash(output_manifest) if output_manifest is not None else None,
        "pre_execution_passed": pre_execution_passed,
        "post_execution_passed": post_execution_passed,
        "revision_base_ready": pre_execution_passed and post_execution_passed and not blocking_findings,
        "configuration_ready": pre_execution_passed and post_execution_passed and not blocking_findings,
        "component_mappings": component_mappings,
        "feature_mappings": feature_mappings,
        "output_mappings": output_mappings,
        "parameter_mappings": parameter_mappings,
        "requirement_trace": requirement_trace,
        "findings": findings,
        "certified_at": datetime.now(timezone.utc).isoformat(),
        "validator_version": VALIDATOR_VERSION,
    }


def consistency_failure_message(result: dict[str, Any]) -> str:
    findings = [finding for finding in result.get("findings", []) if finding.get("is_blocking")]
    if not findings:
        return "Design consistency passed"
    lines = ["Volundr found an internal mismatch between the approved design plan and generated model."]
    lines.extend(str(finding.get("explanation") or finding.get("rule_id")) for finding in findings[:8])
    return "\n".join(lines)


def _validate_execution_manifest(
    manifest: dict[str, Any],
    *,
    plan_outputs: dict[str, dict[str, Any]],
    source_hash: str,
    findings: list[dict[str, Any]],
) -> None:
    manifest_source_hash = manifest.get("source_hash")
    if manifest_source_hash and manifest_source_hash != source_hash:
        findings.append(
            _finding(
                "design_artifact.execution_source_hash_mismatch",
                "execution manifest source hash does not match revision source",
                expected=source_hash,
                detected=manifest_source_hash,
                phase="post_execution",
            )
        )
    output_ids = set(str(output_id) for output_id in manifest.get("output_ids", []) if output_id)
    requested_ids = set(str(output_id) for output_id in manifest.get("requested_output_ids", []) if output_id)
    planned_ids = set(plan_outputs)
    for output_id in sorted(planned_ids - output_ids):
        if plan_outputs[output_id].get("required", True):
            findings.append(
                _finding(
                    "design_artifact.execution_required_output_missing",
                    f"required planned output `{output_id}` was not returned by execution",
                    output_id=output_id,
                    phase="post_execution",
                )
            )
    for output_id in sorted(output_ids - planned_ids):
        findings.append(
            _finding(
                "design_artifact.execution_unexpected_output",
                f"execution returned unexpected output `{output_id}`",
                output_id=output_id,
                phase="post_execution",
            )
        )
    for output in manifest.get("outputs", []):
        if not isinstance(output, dict):
            continue
        output_id = str(output.get("output_id") or "")
        topology = output.get("topology_metadata") if isinstance(output.get("topology_metadata"), dict) else {}
        if output_id in plan_outputs and plan_outputs[output_id].get("required", True):
            if not output.get("success"):
                findings.append(
                    _finding(
                        "design_artifact.execution_required_output_failed",
                        f"required output `{output_id}` failed during execution",
                        output_id=output_id,
                        detected=output.get("compile_error"),
                        phase="post_execution",
                    )
                )
            if not topology:
                findings.append(
                    _finding(
                        "design_artifact.topology_missing",
                        f"required output `{output_id}` has no topology metadata",
                        output_id=output_id,
                        phase="post_execution",
                    )
                )
            _validate_topology(output_id, plan_outputs[output_id], topology, findings)
    if requested_ids and requested_ids != planned_ids:
        findings.append(
            _finding(
                "design_artifact.execution_requested_outputs_mismatch",
                "execution requested outputs do not match approved Design Plan outputs",
                expected=sorted(planned_ids),
                detected=sorted(requested_ids),
                phase="post_execution",
            )
        )


def _validate_output_manifest(
    manifest: dict[str, Any],
    *,
    plan_outputs: dict[str, dict[str, Any]],
    source_hash: str,
    findings: list[dict[str, Any]],
) -> None:
    manifest_source_hash = (manifest.get("source") or {}).get("sha256")
    if manifest_source_hash and manifest_source_hash != source_hash:
        findings.append(
            _finding(
                "design_artifact.manifest_source_hash_mismatch",
                "output manifest source hash does not match revision source",
                expected=source_hash,
                detected=manifest_source_hash,
                phase="post_execution",
            )
        )
    manifest_outputs = {
        str(output.get("output_id")): output
        for output in manifest.get("outputs", [])
        if isinstance(output, dict) and output.get("output_id")
    }
    for output_id, plan_output in plan_outputs.items():
        manifest_output = manifest_outputs.get(output_id)
        if manifest_output is None:
            findings.append(
                _finding(
                    "design_artifact.manifest_required_output_missing",
                    f"required planned output `{output_id}` is missing from the output manifest",
                    output_id=output_id,
                    phase="post_execution",
                )
            )
            continue
        if sorted(manifest_output.get("component_ids") or []) != sorted(plan_output.get("component_ids") or []):
            findings.append(
                _finding(
                    "design_artifact.manifest_component_mismatch",
                    f"manifest output `{output_id}` component ownership does not match the approved Design Plan",
                    output_id=output_id,
                    expected=plan_output.get("component_ids"),
                    detected=manifest_output.get("component_ids"),
                    phase="post_execution",
                )
            )
        state = str(manifest_output.get("state") or "")
        if plan_output.get("required", True) and state not in READY_OUTPUT_STATES:
            findings.append(
                _finding(
                    "design_artifact.manifest_required_output_not_ready",
                    f"required manifest output `{output_id}` is not ready",
                    output_id=output_id,
                    detected=state,
                    phase="post_execution",
                )
            )
        topology = manifest_output.get("topology") if isinstance(manifest_output.get("topology"), dict) else {}
        if plan_output.get("required", True) and not topology:
            findings.append(
                _finding(
                    "design_artifact.manifest_topology_missing",
                    f"required manifest output `{output_id}` has no topology metadata",
                    output_id=output_id,
                    phase="post_execution",
                )
            )
        _validate_topology(output_id, plan_output, manifest_output, findings, phase="post_execution")
    for output_id in sorted(set(manifest_outputs) - set(plan_outputs)):
        findings.append(
            _finding(
                "design_artifact.manifest_unexpected_output",
                f"output manifest includes unexpected output `{output_id}`",
                output_id=output_id,
                phase="post_execution",
            )
        )


def _validate_topology(
    output_id: str,
    plan_output: dict[str, Any],
    topology: dict[str, Any],
    findings: list[dict[str, Any]],
    *,
    phase: str = "post_execution",
) -> None:
    expected = plan_output.get("expected_solid_count")
    detected = topology.get("detected_solid_count")
    if expected is not None and detected is not None and int(expected) != int(detected):
        findings.append(
            _finding(
                "design_artifact.solid_count_mismatch",
                f"output `{output_id}` detected solid count does not match the approved policy",
                output_id=output_id,
                expected=expected,
                detected=detected,
                phase=phase,
            )
        )


def _finding(
    rule_id: str,
    explanation: str,
    *,
    phase: str = "pre_execution",
    parameter_id: str | None = None,
    component_id: str | None = None,
    feature_id: str | None = None,
    output_id: str | None = None,
    expected: Any = None,
    detected: Any = None,
    unit: str | None = None,
    blocking: bool = True,
    requirement_id: str | None = None,
    function_id: str | None = None,
    trace_classification: str | None = None,
    normalization_decision: str | None = None,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "category": "design_artifact_consistency",
        "severity": "critical" if blocking else "warning",
        "is_blocking": blocking,
        "blocking": blocking,
        "phase": phase,
        "title": rule_id.replace("design_artifact.", "").replace("_", " ").title(),
        "explanation": explanation,
        "suggested_correction": (
            "Regenerate from the approved Design Plan or review technical mismatches."
        ),
        "parameter_id": parameter_id,
        "component_id": component_id,
        "feature_id": feature_id,
        "output_id": output_id,
        "expected_value": expected,
        "detected_value": detected,
        "unit": unit,
        "requirement_id": requirement_id,
        "function_id": function_id,
        "trace_classification": trace_classification,
        "normalization_decision": normalization_decision,
    }


def _plan_components(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(component.get("id")): component
        for component in payload.get("components", [])
        if isinstance(component, dict) and component.get("id")
    }


def _plan_features(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(feature.get("id")): feature
        for feature in payload.get("features", [])
        if isinstance(feature, dict) and feature.get("id")
    }


def _integral_feature_component_source(
    *,
    feature_id: str,
    feature: dict[str, Any],
    components: dict[str, dict[str, Any]],
    source_component_ids: set[str],
) -> str | None:
    component_id = str(feature.get("component_id") or "") or None
    if component_id is None or component_id not in source_component_ids:
        return None
    component = components.get(component_id)
    if component is None:
        return None
    declared_features = {
        str(value)
        for value in (component.get("features", []) or [])
        if value
    }
    if feature_id not in declared_features:
        return None
    if feature.get("role") in {"printable_part", "printable_component", "independent_part"}:
        return None
    if feature.get("independent") or feature.get("separate_output"):
        return None
    return component_id


def _plan_outputs(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    outputs: dict[str, dict[str, Any]] = {}
    for output in payload.get("printable_outputs", []):
        if not isinstance(output, dict):
            continue
        output_id = output.get("id") or output.get("output_id")
        if not output_id:
            continue
        normalized = dict(output)
        component_ids = list(normalized.get("component_ids") or [])
        component_id = normalized.get("component_id")
        if component_id and component_id not in component_ids:
            component_ids.insert(0, component_id)
        normalized["component_ids"] = component_ids
        normalized.setdefault("required", True)
        outputs[str(output_id)] = normalized
    return outputs


def _plan_parameters(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(parameter.get("id")): parameter
        for parameter in payload.get("parameters", [])
        if isinstance(parameter, dict) and parameter.get("id")
    }


def _plan_parameter_type(parameter: dict[str, Any]) -> str | None:
    declared = parameter.get("type") or parameter.get("parameter_type")
    if isinstance(declared, str) and declared:
        return {
            "number": "float",
            "integer": "int",
            "boolean": "bool",
        }.get(declared, declared)
    value = parameter.get("value")
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, str):
        return "str"
    return None


def _derived_parameters(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(parameter.get("id")): parameter
        for parameter in payload.get("derived_parameters", [])
        if isinstance(parameter, dict) and parameter.get("id")
    }


def _source_component_symbols(source: str) -> dict[str, str]:
    import ast

    tree = ast.parse(source)
    result: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and getattr(decorator.func, "id", None) == "component"
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
                and isinstance(decorator.args[0].value, str)
            ):
                result[decorator.args[0].value] = node.name
    return result


def _source_feature_components(source: str) -> dict[str, str]:
    import ast

    tree = ast.parse(source)
    result: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if not (
                isinstance(decorator, ast.Call)
                and getattr(decorator.func, "id", None) == "feature"
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
                and isinstance(decorator.args[0].value, str)
            ):
                continue
            component_id = None
            for keyword in decorator.keywords:
                if (
                    keyword.arg == "component"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                ):
                    component_id = keyword.value.value
            if component_id:
                result[decorator.args[0].value] = component_id
    return result


def _source_feature_symbols(source: str) -> dict[str, str]:
    import ast

    tree = ast.parse(source)
    result: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if not (
                isinstance(decorator, ast.Call)
                and getattr(decorator.func, "id", None) == "feature"
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
                and isinstance(decorator.args[0].value, str)
            ):
                continue
            result[decorator.args[0].value] = node.name
    return result


def _values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    try:
        return abs(float(left) - float(right)) <= 1e-6
    except (TypeError, ValueError):
        return left == right


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def _manifest_parameter_hash(
    output_manifest: dict[str, Any] | None,
    execution_manifest: dict[str, Any] | None,
) -> str | None:
    if output_manifest and output_manifest.get("parameter_hash"):
        return str(output_manifest["parameter_hash"])
    if execution_manifest and execution_manifest.get("parameter_hash"):
        return str(execution_manifest["parameter_hash"])
    return None
