"""Contract-complexity diagnostic harness.

This module deliberately does not participate in normal project workflows.  It
reuses the existing source scaffold, source-authority checks, and CadQuery
worker while keeping diagnostic results outside project persistence.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import re
import textwrap
import time
from dataclasses import replace
from typing import Any, Iterable

from app.services.ai.provider import ModelGenerationRequest, ModelGenerationResult
from app.services.cad.cadquery_contract import (
    CadQueryContractError,
    validate_cadquery_source,
)
from app.services.cad.cadquery_source_authority import (
    CadQuerySourceAuthorityError,
    authority_from_generation_context,
    validate_cadquery_source_authority,
)
from app.services.cad.geometry_bodies import (
    GeometryBodyError,
    assemble_geometry_bodies,
    build_geometry_function_inventory,
)
from app.services.cad.source_scaffold import (
    SCAFFOLD_VERSION,
    ScaffoldSourceError,
    _component_geometry_name,
    _feature_geometry_name,
    render_cadquery_scaffold,
    validate_scaffold_integrity,
    validate_scaffold_source,
)


CURRENT_CONTRACT = "current_contract"
SIMPLIFIED_EXECUTION_BRIEF = "simplified_execution_brief"
INITIAL_ATTEMPTS = 2
DIAGNOSTIC_MATRIX_VERSION = "contract-complexity-model-comparison-v1"
SIMPLIFIED_BRIEF_VERSION = "simplified-execution-brief-v1"
_SIMPLIFIED_FENCE_RE = re.compile(
    r"```(?:python|py|cadquery)?\s*(?P<source>.*?)```",
    re.IGNORECASE | re.DOTALL,
)
_FUNCTION_NAME_RE = re.compile(r"^function_(?P<slot>[1-9][0-9]*)$")


def load_diagnostic_packages(root: Any) -> list[dict[str, Any]]:
    """Load and hash-check the three immutable diagnostic packages."""

    from pathlib import Path

    package_root = Path(root)
    packages: list[dict[str, Any]] = []
    for path in sorted(package_root.glob("*.json")):
        if path.stem == "manifest":
            continue
        package = json.loads(path.read_text(encoding="utf-8"))
        package_hash = package.get("package_hash")
        unsigned = dict(package)
        unsigned.pop("package_hash", None)
        actual_hash = hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if not package_hash or package_hash != actual_hash:
            raise ValueError(f"diagnostic input package hash mismatch: {path.name}")
        packages.append(package)
    if {str(item.get("family")) for item in packages} != {
        "five_tray_wall_carrier",
        "desktop_organizer",
        "screw_lid_container",
    }:
        raise ValueError("diagnostic input root must contain exactly the three frozen families")
    return packages


def build_attempt_matrix(
    packages: Iterable[dict[str, Any]],
    models: Iterable[str],
    *,
    attempts: int = INITIAL_ATTEMPTS,
) -> list[dict[str, Any]]:
    """Return the deterministic matrix; repair calls are not matrix cells."""

    package_list = sorted(packages, key=lambda item: str(item.get("family")))
    model_list = [str(model) for model in models]
    if attempts != INITIAL_ATTEMPTS:
        raise ValueError("the diagnostic comparison requires exactly two initial attempts")
    if len(package_list) != 3 or len(model_list) != 2:
        raise ValueError("the diagnostic comparison requires three packages and two models")
    matrix: list[dict[str, Any]] = []
    for package in package_list:
        for strategy in (CURRENT_CONTRACT, SIMPLIFIED_EXECUTION_BRIEF):
            for model in model_list:
                for attempt_number in range(1, attempts + 1):
                    matrix.append(
                        {
                            "family": str(package["family"]),
                            "source_project_id": str(package["source_project_id"]),
                            "strategy": strategy,
                            "model": model,
                            "attempt_number": attempt_number,
                        }
                    )
    return matrix


def _safe_requirement(requirement: dict[str, Any]) -> dict[str, Any]:
    return {
        key: requirement.get(key)
        for key in (
            "type",
            "kind",
            "subject",
            "target",
            "operator",
            "value",
            "unit",
            "explicit",
            "status",
        )
        if requirement.get(key) is not None
    }


def _safe_review_item(item: Any) -> dict[str, Any] | str:
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return str(item)
    return {
        key: item.get(key)
        for key in ("message", "description", "rule", "expected", "severity", "category")
        if item.get(key) is not None
    }


def _safe_frame(frame: Any) -> dict[str, Any] | str:
    if not isinstance(frame, dict):
        return str(frame)
    return {
        key: frame.get(key)
        for key in (
            "name",
            "description",
            "coordinate_space",
            "origin",
            "x_axis",
            "y_axis",
            "z_axis",
            "parent_frame",
        )
        if frame.get(key) is not None
    }


def _plan(package: dict[str, Any]) -> dict[str, Any]:
    plan = package.get("source_plan")
    if not isinstance(plan, dict):
        raise ValueError("diagnostic package has no source plan")
    return plan


def build_simplified_execution_brief(package: dict[str, Any]) -> dict[str, Any]:
    """Build the provider-facing brief without current contract metadata."""

    plan = _plan(package)
    active = package.get("active_requirements") or package.get("authoritative_requirements") or []
    components = [item for item in plan.get("components", []) or [] if isinstance(item, dict)]
    features = [item for item in plan.get("features", []) or [] if isinstance(item, dict)]
    outputs = [item for item in plan.get("printable_outputs", []) or [] if isinstance(item, dict)]
    component_slot_by_id = {
        str(item.get("id")): index
        for index, item in enumerate(components, start=1)
        if item.get("id")
    }
    component_slots = [
        {
            "slot": index,
            "role": item.get("role") or item.get("description") or "printable component",
            "parameters": [str(value) for value in item.get("parameters", []) if value],
            "required_feature_slots": [
                feature_index
                for feature_index, feature in enumerate(features, start=1)
                if feature.get("component_id") == item.get("id")
            ],
        }
        for index, item in enumerate(components, start=1)
    ]
    output_slots = [
        {
            "slot": index,
            "label": item.get("label") or item.get("name") or "printable output",
            "quantity": item.get("quantity") or 1,
            "required": bool(item.get("required", True)),
            "expected_solid_count": item.get("expected_solid_count") or 1,
            "component_slots": [
                component_slot_by_id[str(component_id)]
                for component_id in item.get("component_ids", []) or []
                if str(component_id) in component_slot_by_id
            ],
        }
        for index, item in enumerate(outputs, start=1)
    ]
    functional_features = [
        {
            "slot": index,
            "role": item.get("role") or item.get("feature_type") or item.get("type") or "functional feature",
            "feature_type": item.get("feature_type") or item.get("type"),
            "required": bool(item.get("required", True)),
            "component_slot": component_slot_by_id.get(str(item.get("component_id"))),
            "count": item.get("count"),
        }
        for index, item in enumerate(features, start=1)
        if item.get("required", True) or item.get("functional") or item.get("role")
    ]
    parameters = [item for item in plan.get("parameters", []) or [] if isinstance(item, dict)]
    explicit_dimensions = [
        {
            key: item.get(key)
            for key in ("label", "value", "unit", "type", "description")
            if item.get(key) is not None
        }
        for item in parameters
        if item.get("value") is not None
    ]
    provenance = package.get("provenance") if isinstance(package.get("provenance"), dict) else {}
    review_targets = package.get("verification_targets")
    review_items: list[Any] = []
    if isinstance(review_targets, dict):
        for value in review_targets.values():
            if isinstance(value, list):
                review_items.extend(value)
    return {
        "brief_version": SIMPLIFIED_BRIEF_VERSION,
        "requirements": [_safe_requirement(item) for item in active if isinstance(item, dict)],
        "proposals": copy.deepcopy(provenance.get("plan_proposals", [])),
        "component_slots": component_slots,
        "output_slots": output_slots,
        "functional_feature_slots": functional_features,
        "coordinate_frames": [_safe_frame(item) for item in package.get("coordinate_frames", []) or []],
        "explicit_dimensions": explicit_dimensions,
        "qualitative_review_items": [_safe_review_item(item) for item in review_items],
        "optional_controls": [],
        "required_artifacts": ["STEP", "STL", "BREP"],
    }


def build_simplified_function_specs(package: dict[str, Any]) -> list[dict[str, Any]]:
    """Assign Volundr-owned ordered slots and scaffold mappings."""

    plan = _plan(package)
    components = [item for item in plan.get("components", []) or [] if isinstance(item, dict)]
    features = [item for item in plan.get("features", []) or [] if isinstance(item, dict)]
    specs: list[dict[str, Any]] = []
    slot = 0
    for component in components:
        slot += 1
        component_id = str(component.get("id"))
        specs.append(
            {
                "slot": slot,
                "kind": "component",
                "function_id": f"_diag_component_{slot:03d}",
                "scaffold_function_id": _component_geometry_name(component_id),
                "signature": "(params)",
                "description": component.get("role") or component.get("description") or "printable component",
            }
        )
    component_ids = {str(item.get("id")) for item in components if item.get("id")}
    for feature in features:
        if str(feature.get("component_id") or "") not in component_ids:
            continue
        slot += 1
        feature_id = str(feature.get("id"))
        specs.append(
            {
                "slot": slot,
                "kind": "feature",
                "function_id": f"_diag_feature_{slot:03d}",
                "scaffold_function_id": _feature_geometry_name(feature_id),
                "signature": "(body, params)",
                "description": feature.get("role") or feature.get("feature_type") or feature.get("type") or "feature",
            }
        )
    if not specs:
        raise ValueError("diagnostic plan has no provider-owned geometry function slots")
    return specs


def _diagnostic_instruction(package: dict[str, Any]) -> str:
    fact_sheet = package.get("approved_fact_sheet")
    if not isinstance(fact_sheet, dict):
        return str(package.get("user_request") or "")
    return "\n".join(
        [
            str(package.get("user_request") or ""),
            "Approved diagnostic fact sheet:",
            *[f"- {key}: {value}" for key, value in fact_sheet.items()],
        ]
    )


def build_current_generation_request(package: dict[str, Any]) -> ModelGenerationRequest:
    """Build the unchanged current-contract generation request from frozen data."""

    plan = _plan(package)
    authority = authority_from_generation_context(design_plan_payload=plan)
    return ModelGenerationRequest(
        project_name=str(package.get("project_name") or package.get("family")),
        original_intent=str(package.get("user_request") or ""),
        user_instruction=_diagnostic_instruction(package),
        design_specification=copy.deepcopy(package.get("design_specification")),
        design_plan=copy.deepcopy(plan),
        source_authority=authority,
        active_requirements=copy.deepcopy(package.get("active_requirements") or []),
        generation_contract_version=SCAFFOLD_VERSION,
        planning_depth="compact_plan" if plan.get("schema_version") == "compact-cad-plan-v1" else "detailed_plan",
        geometry_execution_context=copy.deepcopy(package.get("geometry_execution_context")),
        prompt_context_pack=copy.deepcopy(package.get("prompt_context_pack")),
        provider_contract_manifest=copy.deepcopy(package.get("provider_contract_manifest")),
    )


def build_simplified_generation_request(package: dict[str, Any]) -> ModelGenerationRequest:
    """Create only a routing request; the provider receives the simplified prompt."""

    return ModelGenerationRequest(
        project_name=str(package.get("project_name") or package.get("family")),
        original_intent=str(package.get("user_request") or ""),
        user_instruction=_diagnostic_instruction(package),
        generation_contract_version=SCAFFOLD_VERSION,
        planning_depth="compact_plan",
        active_requirements=copy.deepcopy(package.get("active_requirements") or []),
    )


def build_simplified_prompt(package: dict[str, Any]) -> str:
    """Render a fixed prompt with no provider-authored contract identities."""

    brief = build_simplified_execution_brief(package)
    specs = build_simplified_function_specs(package)
    prompt_brief = {
        **brief,
        "function_slots": [
            {
                "slot": spec["slot"],
                "kind": spec["kind"],
                "signature": spec["signature"],
                "description": spec["description"],
            }
            for spec in specs
        ],
    }
    return "\n".join(
        [
            "You provide only ordered CadQuery implementation functions for a Volundr diagnostic.",
            "Do not return JSON, IDs, provenance, requirement references, validation metadata, decorators, or planning metadata.",
            "Return exactly one fenced Python block containing exactly the ordered functions below.",
            "Use only `import cadquery as cq` at module level and safe CadQuery/Python expressions inside functions.",
            "The function names must be function_1, function_2, and so on, matching slots in order; these names are temporary response slots, not product identities.",
            "Component functions use (params); feature functions use (body, params). Each function must return its resulting shape.",
            "Do not access files, network, subprocesses, environment variables, dynamic Python, or external modules.",
            "Volundr will own all stable components, features, outputs, requirements, provenance, function identities, scaffold signatures, validation, topology, and artifact handling.",
            "Frozen user request and approved answers:",
            _diagnostic_instruction(package),
            "Volundr-owned execution brief:",
            json.dumps(prompt_brief, indent=2, sort_keys=True),
        ]
    )


def build_simplified_repair_prompt(
    package: dict[str, Any],
    *,
    specs: list[dict[str, Any]],
    failed_function_id: str,
    traceback: str,
    function_signature: str,
    assigned_requirements: list[dict[str, Any]],
    allowed_apis: list[str],
    unaffected_function_hashes: dict[str, str],
) -> str:
    """Build the single bounded worker-informed repair prompt."""

    brief = build_simplified_execution_brief(package)
    return "\n".join(
        [
            "Repair one CadQuery function for a Volundr diagnostic only.",
            "Return exactly one fenced Python block containing every ordered function slot.",
            "Use function_1, function_2, and so on in the original order; do not return IDs, provenance, cross-references, or metadata.",
            "Change only the failed function slot. Preserve all unaffected function bodies byte-for-byte in meaning.",
            "Allowed CadQuery APIs/helpers:",
            json.dumps(sorted(allowed_apis), indent=2),
            "Function slots:",
            json.dumps(
                [
                    {
                        "slot": item["slot"],
                        "kind": item["kind"],
                        "signature": item["signature"],
                        "description": item["description"],
                    }
                    for item in specs
                ],
                indent=2,
            ),
            f"Failed Volundr-owned function: {failed_function_id}",
            f"Required signature: {function_signature}",
            "Assigned active requirements:",
            json.dumps(assigned_requirements, indent=2, sort_keys=True),
            "Exact worker traceback:",
            traceback,
            "Unaffected function hashes:",
            json.dumps(unaffected_function_hashes, indent=2, sort_keys=True),
            "Execution brief:",
            json.dumps(brief, indent=2, sort_keys=True),
        ]
    )


def extract_simplified_functions(
    raw_output: str,
    specs: list[dict[str, Any]],
) -> dict[str, str]:
    """Parse ordered temporary functions and map them to Volundr-owned slots."""

    matches = list(_SIMPLIFIED_FENCE_RE.finditer(raw_output))
    if not matches:
        raise ValueError("simplified response must contain one fenced Python block")
    source = matches[0].group("source").strip()
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ValueError(f"simplified response has invalid Python syntax: {exc.msg}") from exc
    nodes: list[ast.FunctionDef] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            if len(node.names) != 1 or node.names[0].name != "cadquery" or node.names[0].asname != "cq":
                raise ValueError("simplified response may only import cadquery as cq")
            continue
        if not isinstance(node, ast.FunctionDef):
            raise ValueError("simplified response may contain only ordered function definitions")
        nodes.append(node)
    if len(nodes) != len(specs):
        raise ValueError("simplified response function count does not match ordered function slots")
    functions: dict[str, str] = {}
    for node, spec in zip(nodes, specs, strict=True):
        expected_name = f"function_{spec['slot']}"
        if node.name != expected_name:
            raise ValueError("simplified response must use ordered function names")
        if node.decorator_list:
            raise ValueError("simplified response functions may not declare decorators")
        positional = list(node.args.posonlyargs) + list(node.args.args)
        expected_args = [item.strip() for item in str(spec["signature"]).strip("()").split(",") if item.strip()]
        if [argument.arg for argument in positional] != expected_args:
            raise ValueError(f"simplified function {expected_name} has the wrong signature")
        if node.args.defaults or node.args.kwonlyargs or node.args.vararg or node.args.kwarg:
            raise ValueError(f"simplified function {expected_name} has unsupported arguments")
        for child in ast.walk(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                raise ValueError("simplified functions may not contain imports")
        node.name = str(spec["function_id"])
        functions[str(spec["function_id"])] = textwrap.dedent(ast.unparse(node)).strip()
    return functions


def worker_feedback_function_id(error_text: str, specs: Iterable[dict[str, Any]]) -> str | None:
    """Return one named provider function only for a localized traceback."""

    if not error_text or "traceback" not in error_text.lower():
        return None
    names: list[str] = []
    for spec in specs:
        for key in ("function_id", "scaffold_function_id"):
            value = str(spec.get(key) or "")
            if value and re.search(rf"(?<![A-Za-z0-9_]){re.escape(value)}(?![A-Za-z0-9_])", error_text):
                names.append(value)
                break
    return names[0] if len(set(names)) == 1 else None


def _usage_fields(usage: Any) -> dict[str, Any]:
    if not isinstance(usage, dict):
        return {"prompt_tokens": None, "output_tokens": None, "total_tokens": None}
    prompt = usage.get("promptTokenCount", usage.get("prompt_tokens"))
    output = usage.get("candidatesTokenCount", usage.get("output_tokens"))
    total = usage.get("totalTokenCount", usage.get("total_tokens"))
    return {
        "prompt_tokens": prompt if isinstance(prompt, int) else None,
        "output_tokens": output if isinstance(output, int) else None,
        "total_tokens": total if isinstance(total, int) else None,
    }


def _function_hashes(functions: dict[str, str]) -> dict[str, str]:
    return {
        name: hashlib.sha256(source.encode("utf-8")).hexdigest()
        for name, source in functions.items()
    }


def _finding(rule_id: str, message: str, *, category: str = "diagnostic") -> dict[str, Any]:
    return {"rule_id": rule_id, "category": category, "message": message}


def _output_metrics(compile_result: Any) -> dict[str, Any]:
    outputs = list(getattr(compile_result, "outputs", []) or [])
    valid_solids = 0
    topology: list[dict[str, Any]] = []
    artifact_results: list[dict[str, Any]] = []
    for output in outputs:
        topology_metadata = getattr(output, "topology_metadata", None)
        if not isinstance(topology_metadata, dict):
            topology_metadata = {}
        solid_count = topology_metadata.get("detected_solid_count")
        if isinstance(solid_count, int) and topology_metadata.get("valid"):
            valid_solids += solid_count
        topology.append(
            {
                "output_id": getattr(output, "output_id", None),
                "valid": bool(topology_metadata.get("valid")),
                "detected_solid_count": solid_count,
                "expected_solid_count": topology_metadata.get("expected_solid_count"),
                "outcome": topology_metadata.get("outcome"),
            }
        )
        artifact_results.append(
            {
                "output_id": getattr(output, "output_id", None),
                "stl": bool(getattr(output, "stl_path", None)),
                "step": bool(getattr(output, "step_path", None)),
                "brep": bool(getattr(output, "brep_path", None)),
                "success": bool(getattr(output, "success", False)),
            }
        )
    return {
        "valid_solid_count": valid_solids,
        "topology": topology,
        "artifacts": artifact_results,
        "step_produced": any(item["step"] for item in artifact_results),
        "stl_produced": any(item["stl"] for item in artifact_results),
        "brep_produced": any(item["brep"] for item in artifact_results),
    }


def _quality(compile_result: Any, output_metrics: dict[str, Any]) -> str:
    if not compile_result or not bool(getattr(compile_result, "success", False)):
        return "blocked"
    if not output_metrics["artifacts"] or not all(item["success"] for item in output_metrics["artifacts"]):
        return "integrity_failure"
    if not all(item["valid"] for item in output_metrics["topology"]):
        return "topology_failure"
    return "diagnostic_geometry_candidate"


def _feature_evidence(package: dict[str, Any], function_specs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "source_presence_only",
        "required_features": [
            {
                "feature_id": item.get("id"),
                "feature_type": item.get("feature_type") or item.get("type"),
                "source_function": next(
                    (
                        spec.get("scaffold_function_id")
                        for spec in function_specs
                        if spec.get("kind") == "feature"
                        and str(spec.get("scaffold_function_id") or "").endswith(str(item.get("id")))
                    ),
                    None,
                ),
                "geometry_verified": False,
            }
            for item in (_plan(package).get("features", []) or [])
            if isinstance(item, dict) and (item.get("required", True) or item.get("functional"))
        ],
        "verification_targets_executed": False,
    }


def _base_record(
    package: dict[str, Any],
    *,
    strategy: str,
    model: str,
    attempt_number: int,
) -> dict[str, Any]:
    return {
        "diagnostic_matrix_version": DIAGNOSTIC_MATRIX_VERSION,
        "family": package.get("family"),
        "source_project_id": package.get("source_project_id"),
        "source_batch_id": package.get("source_batch_id"),
        "package_hash": package.get("package_hash"),
        "strategy": strategy,
        "provider": "gemini_api",
        "requested_model": model,
        "provider_model": None,
        "attempt_number": attempt_number,
        "response_validity": "not_started",
        "schema_or_contract_findings": [],
        "repair_invocation": {"invoked": False, "reason": "not_started", "attempts": 0},
        "repair_result": None,
        "source_assembled": False,
        "source_valid": False,
        "worker_reached": False,
        "worker_result": "not_started",
        "valid_solid_count": 0,
        "step_produced": False,
        "stl_produced": False,
        "brep_produced": False,
        "topology": [],
        "required_feature_evidence": {"status": "not_started"},
        "candidate_quality": "not_started",
        "provider_latency_ms": None,
        "prompt_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "elapsed_ms": None,
        "errors": [],
    }


async def _simplified_provider_call(provider: Any, prompt: str, request: ModelGenerationRequest) -> ModelGenerationResult:
    custom = getattr(provider, "generate_simplified_model", None)
    if custom is not None:
        result = await custom(prompt, request)
        if not isinstance(result, ModelGenerationResult):
            raise TypeError("simplified provider call must return ModelGenerationResult")
        return result
    routed = getattr(provider, "_run_routed_prompt", None)
    if routed is None:
        raise TypeError("provider does not expose the diagnostic prompt transport")
    raw, routing, latency, actual_model, usage, request_id = await routed(prompt, request)
    return ModelGenerationResult(
        raw_output=raw,
        provider=getattr(provider, "provider_id", "gemini_api"),
        provider_model=actual_model,
        routing_metadata=routing,
        provider_latency_ms=latency,
        usage_metadata=usage,
        provider_request_id=request_id,
    )


def _worker_error(result: Any) -> str:
    values = [getattr(result, "error_message", None)]
    for output in getattr(result, "outputs", []) or []:
        values.append(getattr(output, "compile_error", None))
    return "\n".join(str(value) for value in values if value)


def _requested_outputs(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in plan.get("printable_outputs", []) or [] if isinstance(item, dict)]


def _parameter_values(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        str(item["id"]): item.get("value")
        for item in plan.get("parameters", []) or []
        if isinstance(item, dict) and item.get("id") and item.get("value") is not None
    }


def _assemble_source(
    package: dict[str, Any],
    strategy: str,
    raw_output: str,
) -> tuple[str, dict[str, str], list[dict[str, Any]], list[dict[str, Any]]]:
    plan = _plan(package)
    if strategy == CURRENT_CONTRACT:
        inventory = build_geometry_function_inventory(plan)
        assembly = assemble_geometry_bodies(raw_output, inventory)
        return (
            render_cadquery_scaffold(plan, assembly.functions).source,
            assembly.functions,
            [],
            [{"function_id": key, "body_hash": value} for key, value in assembly.function_body_hashes.items()],
        )
    specs = build_simplified_function_specs(package)
    temporary = extract_simplified_functions(raw_output, specs)
    scaffold_functions = {
        spec["scaffold_function_id"]: _rename_function_source(
            temporary[spec["function_id"]],
            str(spec["scaffold_function_id"]),
        )
        for spec in specs
    }
    rendered = render_cadquery_scaffold(plan, scaffold_functions)
    return (
        rendered.source,
        scaffold_functions,
        [],
        [{"function_id": key, "body_hash": value} for key, value in _function_hashes(scaffold_functions).items()],
    )


def _validate_source(package: dict[str, Any], source: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    try:
        validate_cadquery_source(source, contract_version="cadquery-v1")
    except CadQueryContractError as exc:
        findings.append(_finding("cadquery.contract", str(exc), category="source_contract"))
    findings.extend(validate_scaffold_source(source))
    authority = authority_from_generation_context(design_plan_payload=_plan(package))
    try:
        authority_result = validate_cadquery_source_authority(source, authority)
    except CadQuerySourceAuthorityError as exc:
        findings.extend(exc.findings)
    else:
        findings.extend(authority_result.get("findings", []))
    findings.extend(validate_scaffold_integrity(source, render_cadquery_scaffold(
        _plan(package),
        {
            function_id: _extract_scaffold_function(source, function_id)
            for function_id in _expected_scaffold_function_ids(_plan(package))
        },
    )))
    return findings


def _expected_scaffold_function_ids(plan: dict[str, Any]) -> list[str]:
    ids = [
        _component_geometry_name(str(item["id"]))
        for item in plan.get("components", []) or []
        if isinstance(item, dict) and item.get("id")
    ]
    component_ids = {str(item.get("id")) for item in plan.get("components", []) or [] if isinstance(item, dict)}
    ids.extend(
        _feature_geometry_name(str(item["id"]))
        for item in plan.get("features", []) or []
        if isinstance(item, dict) and item.get("id") and str(item.get("component_id")) in component_ids
    )
    return ids


def _extract_scaffold_function(source: str, function_id: str) -> str:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_id:
            return textwrap.dedent(ast.unparse(node)).strip()
    raise ValueError(f"assembled source missing {function_id}")


def _rename_function_source(source: str, function_id: str) -> str:
    tree = ast.parse(source)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    if len(functions) != 1:
        raise ValueError("simplified function source must contain exactly one function")
    functions[0].name = function_id
    return textwrap.dedent(ast.unparse(functions[0])).strip()


async def _compile_worker(worker: Any, source: str, package: dict[str, Any], job_id: str) -> Any:
    return await worker.compile(
        source,
        job_id,
        source_contract_version="cadquery-v1",
        parameter_values=_parameter_values(_plan(package)),
        requested_outputs=_requested_outputs(_plan(package)),
    )


async def run_diagnostic_attempt(
    package: dict[str, Any],
    *,
    strategy: str,
    model: str,
    attempt_number: int,
    provider: Any,
    worker: Any,
    job_id: str,
    allow_worker_repair: bool = True,
) -> dict[str, Any]:
    """Run one initial cell and at most one bounded worker-informed repair."""

    if strategy not in {CURRENT_CONTRACT, SIMPLIFIED_EXECUTION_BRIEF}:
        raise ValueError(f"unknown diagnostic strategy: {strategy}")
    record = _base_record(package, strategy=strategy, model=model, attempt_number=attempt_number)
    started = time.perf_counter()
    request = (
        build_current_generation_request(package)
        if strategy == CURRENT_CONTRACT
        else build_simplified_generation_request(package)
    )
    prompt = build_simplified_prompt(package) if strategy == SIMPLIFIED_EXECUTION_BRIEF else None
    try:
        response = (
            await provider.generate_cadquery_model(request)
            if prompt is None
            else await _simplified_provider_call(provider, prompt, request)
        )
        record["provider"] = response.provider
        record["provider_model"] = response.provider_model or model
        record["provider_latency_ms"] = response.provider_latency_ms
        record.update(_usage_fields(response.usage_metadata))
        record["response_validity"] = "valid_response"
        raw_output = response.raw_output
        try:
            source, functions, _, hashes = _assemble_source(package, strategy, raw_output)
            record["source_assembled"] = True
            record["function_body_hashes"] = hashes
            source_findings = _validate_source(package, source)
            record["schema_or_contract_findings"].extend(source_findings)
            record["source_valid"] = not any(
                bool(item.get("is_blocking", True))
                for item in source_findings
                if isinstance(item, dict)
            )
        except (GeometryBodyError, ScaffoldSourceError, ValueError, CadQueryContractError) as exc:
            record["response_validity"] = "invalid_contract_response"
            record["schema_or_contract_findings"].append(
                _finding("diagnostic.response_contract", str(exc), category="response_contract")
            )
            record["errors"].append(str(exc))
            return _finish_record(record, started)
        record["required_feature_evidence"] = _feature_evidence(
            package,
            build_simplified_function_specs(package)
            if strategy == SIMPLIFIED_EXECUTION_BRIEF
            else [
                {
                    "kind": "feature",
                    "scaffold_function_id": _feature_geometry_name(str(item.get("id"))),
                }
                for item in _plan(package).get("features", []) or []
                if isinstance(item, dict) and item.get("id")
            ],
        )
        if not record["source_valid"]:
            record["candidate_quality"] = "blocked_before_worker"
            return _finish_record(record, started)
        worker_result = await _compile_worker(worker, source, package, job_id)
        record["worker_reached"] = True
        record["worker_result"] = "succeeded" if getattr(worker_result, "success", False) else (
            "timed_out" if getattr(worker_result, "timed_out", False) else "failed"
        )
        output_metrics = _output_metrics(worker_result)
        record.update(output_metrics)
        record["candidate_quality"] = _quality(worker_result, output_metrics)
        error_text = _worker_error(worker_result)
        specs = (
            build_simplified_function_specs(package)
            if strategy == SIMPLIFIED_EXECUTION_BRIEF
            else [{"function_id": item} for item in _expected_scaffold_function_ids(_plan(package))]
        )
        failed_id = worker_feedback_function_id(error_text, specs)
        if allow_worker_repair and failed_id:
            record["repair_invocation"] = {
                "invoked": True,
                "reason": "localized_worker_traceback",
                "failed_function_id": failed_id,
                "attempts": 1,
            }
            if strategy == CURRENT_CONTRACT:
                repair_request = replace(
                    request,
                    current_source=raw_output,
                    geometry_body_diagnostics=json.dumps(
                        {
                            "rule_id": "diagnostic.worker_feedback",
                            "failed_function": failed_id,
                            "traceback": error_text,
                            "unaffected_function_hashes": {
                                str(item["function_id"]): str(item["body_hash"])
                                for item in record.get("function_body_hashes", [])
                                if str(item["function_id"]) != failed_id
                            },
                        },
                        indent=2,
                        sort_keys=True,
                    ),
                    compiler_diagnostics=error_text,
                )
                repair_response = await provider.generate_cadquery_model(repair_request)
            else:
                simplified_specs = build_simplified_function_specs(package)
                failed_spec = next(
                    item
                    for item in simplified_specs
                    if item.get("scaffold_function_id") == failed_id
                    or item.get("function_id") == failed_id
                )
                repair_response = await _simplified_provider_call(
                    provider,
                    build_simplified_repair_prompt(
                        package,
                        specs=simplified_specs,
                        failed_function_id=failed_id,
                        traceback=error_text,
                        function_signature=str(failed_spec["signature"]),
                        assigned_requirements=copy.deepcopy(package.get("active_requirements") or []),
                        allowed_apis=["cq.Workplane", "cq.Workplane.box", "cq.Workplane.union", "cq.Workplane.cut"],
                        unaffected_function_hashes={
                            str(item["function_id"]): str(item["body_hash"])
                            for item in record.get("function_body_hashes", [])
                            if str(item["function_id"]) != failed_id
                        },
                    ),
                    build_simplified_generation_request(package),
                )
            record["repair_result"] = await _run_repair_result(
                package,
                strategy=strategy,
                response=repair_response,
                worker=worker,
                job_id=f"{job_id}-repair",
            )
        return _finish_record(record, started)
    except Exception as exc:  # diagnostic records must survive provider/worker failures
        record["response_validity"] = "provider_or_harness_error"
        record["errors"].append(str(exc))
        return _finish_record(record, started)


async def _run_repair_result(
    package: dict[str, Any],
    *,
    strategy: str,
    response: ModelGenerationResult,
    worker: Any,
    job_id: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "provider_model": response.provider_model,
        "provider_latency_ms": response.provider_latency_ms,
        **_usage_fields(response.usage_metadata),
        "response_validity": "valid_response",
        "source_assembled": False,
        "source_valid": False,
        "worker_reached": False,
        "worker_result": "not_started",
        "errors": [],
    }
    try:
        source, _, _, _ = _assemble_source(package, strategy, response.raw_output)
        result["source_assembled"] = True
        findings = _validate_source(package, source)
        result["schema_or_contract_findings"] = findings
        result["source_valid"] = not findings
        if not result["source_valid"]:
            result["worker_result"] = "blocked_before_worker"
            return result
        worker_result = await _compile_worker(worker, source, package, job_id)
        result["worker_reached"] = True
        result["worker_result"] = "succeeded" if getattr(worker_result, "success", False) else "failed"
        result.update(_output_metrics(worker_result))
        result["candidate_quality"] = _quality(worker_result, result)
    except Exception as exc:
        result["response_validity"] = "invalid_repair_response"
        result["errors"].append(str(exc))
    return result


def _finish_record(record: dict[str, Any], started: float) -> dict[str, Any]:
    record.setdefault("function_body_hashes", [])
    record["elapsed_ms"] = max(0, round((time.perf_counter() - started) * 1000))
    return record
