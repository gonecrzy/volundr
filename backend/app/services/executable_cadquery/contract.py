"""Contracts for the Gemini complete-source CadQuery experiment.

This module validates provider-owned source without interpreting or rewriting
CadQuery. The existing worker-facing ``cadquery-v1`` validator remains the
source safety boundary.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from copy import deepcopy
import hashlib
import json
import re
from typing import Any, Mapping

from app.services.cad.cadquery_contract import (
    CadQueryContractError,
    CadQuerySourceMetadata,
    validate_cadquery_source,
)
from app.services.requirements.policy import (
    REQUIREMENT_POLICIES,
    REQUIREMENT_POLICY_VERSION,
    resolve_product_requirement_policy,
)


DESIGN_CONTRACT_SCHEMA_VERSION = "executable-cadquery-design-contract-v1"
RESPONSE_SCHEMA_VERSION = "executable-cadquery-complete-source-v2"
SOURCE_CONTRACT_VERSION = "cadquery-v1"
PRODUCT_CONTRACT_MATERIALIZATION_VERSION = "executable-cadquery-product-contract-v3"


class ExecutableCadQueryContractError(ValueError):
    """Raised when the provider response or authoritative contract is invalid."""

    def __init__(
        self,
        message: str,
        *,
        failure_kind: str = "source_contract_violation",
        boundary: str = "source_contract",
        diagnostic: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_kind = failure_kind
        self.boundary = boundary
        self.diagnostic = diagnostic or {
            "code": "source_contract_violation",
            "line": None,
            "column": None,
            "node_type": None,
            "ast_path": None,
            "enclosing_scope": None,
            "message": message,
            "violation_count": 1,
        }
        self.extracted_source: str | None = None
        self.extracted_source_hash: str | None = None
        self.syntax_valid = False
        self.source_contract_valid = False


class ExecutableCadQueryResponseError(ExecutableCadQueryContractError):
    """Raised when a provider response cannot yield exactly one source module."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            failure_kind="response_empty_or_extraction_failure",
            boundary="provider_response",
        )


class ExecutableCadQuerySyntaxError(ExecutableCadQueryContractError):
    """Raised when the extracted module is not syntactically valid Python."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            failure_kind="python_syntax_error",
            boundary="source_contract",
        )


@dataclass(frozen=True)
class ExecutableCadQuerySource:
    output_id: str
    parameters: dict[str, Any]
    source: str
    source_hash: str
    source_metadata: CadQuerySourceMetadata


@dataclass(frozen=True)
class ExecutableCadQueryResponse:
    schema_version: str
    outputs: tuple[ExecutableCadQuerySource, ...]


def validate_executable_cadquery_design_contract(
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and return a JSON-safe authoritative design contract."""

    if not isinstance(contract, Mapping):
        raise ExecutableCadQueryContractError("design contract must be an object")
    if contract.get("schema_version") != DESIGN_CONTRACT_SCHEMA_VERSION:
        raise ExecutableCadQueryContractError("unsupported design contract schema_version")
    if not isinstance(contract.get("project_id"), str) or not contract["project_id"]:
        raise ExecutableCadQueryContractError("design contract project_id is required")
    for identity in ("workflow_id", "revision_id"):
        if not isinstance(contract.get(identity), str) or not contract[identity]:
            raise ExecutableCadQueryContractError(f"design contract {identity} is required")
    if contract.get("units") != "mm":
        raise ExecutableCadQueryContractError("design contract units must be mm")

    outputs = contract.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise ExecutableCadQueryContractError("design contract outputs are required")
    output_ids: list[str] = []
    for output in outputs:
        if not isinstance(output, Mapping):
            raise ExecutableCadQueryContractError("design contract outputs must be objects")
        output_id = output.get("output_id")
        if not isinstance(output_id, str) or not output_id:
            raise ExecutableCadQueryContractError("design contract output_id is required")
        if output_id in output_ids:
            raise ExecutableCadQueryContractError(f"duplicate design contract output_id: {output_id}")
        output_ids.append(output_id)
        if not isinstance(output.get("required"), bool):
            raise ExecutableCadQueryContractError(f"output {output_id} required must be boolean")
        if not isinstance(output.get("output_type"), str) or not output["output_type"]:
            raise ExecutableCadQueryContractError(f"output {output_id} output_type is required")
        expected_solid_count = output.get("expected_solid_count")
        if not isinstance(expected_solid_count, int) or expected_solid_count < 1:
            raise ExecutableCadQueryContractError(
                f"output {output_id} expected_solid_count must be a positive integer"
            )

    for collection_name in ("requirements", "relationships", "protected_facts"):
        collection = contract.get(collection_name)
        if not isinstance(collection, list):
            raise ExecutableCadQueryContractError(
                f"design contract {collection_name} must be a list"
            )
        for index, item in enumerate(collection):
            if not isinstance(item, Mapping):
                raise ExecutableCadQueryContractError(
                    f"design contract {collection_name}[{index}] must be an object"
                )

    return json.loads(json.dumps(dict(contract), sort_keys=True, default=str))


def build_executable_cadquery_product_contract(
    *,
    project_id: str,
    workflow_id: str,
    revision_id: str,
    specification: Mapping[str, Any],
    active_requirements: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Materialize an executable contract from authoritative product state.

    This is the production/user contract source.  Frozen replay uses the
    separate corpus loader and does not pass through this function.  The
    materializer preserves requirement provenance and policy while only
    selecting a verifier when the canonical requirement fields make that
    choice defensible.
    """

    if not isinstance(specification, Mapping):
        raise ExecutableCadQueryContractError(
            "product design specification is required",
            failure_kind="requirement_state_missing",
            boundary="requirements",
        )
    requirements = [
        item
        for item in active_requirements
        if isinstance(item, Mapping) and str(item.get("requirement_id") or item.get("id") or "").strip()
    ]
    if not requirements:
        raise ExecutableCadQueryContractError(
            "product contract requires authoritative requirements; refusing an empty requirement set",
            failure_kind="requirement_state_missing",
            boundary="requirements",
        )

    outputs = _product_contract_outputs(specification)
    output_ids = {str(item["output_id"]) for item in outputs}
    contract_requirements: list[dict[str, Any]] = []
    protected_facts: list[dict[str, Any]] = []
    for item in sorted(requirements, key=lambda value: str(value.get("requirement_id") or value.get("id"))):
        requirement = _product_contract_requirement(item, outputs, outputs[0]["output_id"])
        contract_requirements.append(requirement)
        if requirement["authority"] == "required" and requirement.get("protected", True) is True:
            protected_facts.append(
                {
                    "requirement_id": requirement["requirement_id"],
                    "authoritative_value": deepcopy(requirement["expected"]),
                    "origin": requirement["origin"],
                    "authority": requirement["authority"],
                }
            )

    relationships = specification.get("relationships")
    relationships = deepcopy(relationships) if isinstance(relationships, list) else []
    contract = {
        "schema_version": DESIGN_CONTRACT_SCHEMA_VERSION,
        "contract_source": "production_requirement_ledger",
        "contract_materialization_version": PRODUCT_CONTRACT_MATERIALIZATION_VERSION,
        "project_id": project_id,
        "workflow_id": workflow_id,
        "revision_id": revision_id,
        "units": str(specification.get("units") or "mm"),
        "outputs": outputs,
        "requirements": contract_requirements,
        "relationships": relationships,
        "protected_facts": protected_facts,
        "product_state": {
            "design_specification_schema": specification.get("schema_version"),
            "requirement_policy_version": REQUIREMENT_POLICY_VERSION,
            "purpose": specification.get("purpose"),
            "object_type": specification.get("object_type"),
        },
    }
    return validate_executable_cadquery_design_contract(contract)


def _product_contract_outputs(specification: Mapping[str, Any]) -> list[dict[str, Any]]:
    declared = specification.get("outputs") or specification.get("printable_outputs")
    raw_outputs = declared if isinstance(declared, list) else []
    if not raw_outputs:
        raw_outputs = [{"output_id": specification.get("object_type") or "primary_output"}]
    outputs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_outputs):
        if not isinstance(raw, Mapping):
            raise ExecutableCadQueryContractError(
                f"product output {index + 1} is not an object",
                failure_kind="requirement_state_invalid",
                boundary="requirements",
            )
        output_id = _stable_contract_id(
            raw.get("output_id") or raw.get("id") or raw.get("component_id"),
            fallback=f"primary_output_{index + 1}",
        )
        if output_id in seen:
            raise ExecutableCadQueryContractError(
                f"duplicate product output identity: {output_id}",
                failure_kind="requirement_state_invalid",
                boundary="requirements",
            )
        seen.add(output_id)
        expected_solid_count = raw.get("expected_solid_count", raw.get("solid_count", 1))
        if not isinstance(expected_solid_count, int) or expected_solid_count < 1:
            raise ExecutableCadQueryContractError(
                f"product output {output_id} has an invalid expected solid count",
                failure_kind="requirement_state_invalid",
                boundary="requirements",
            )
        output = {
            "output_id": output_id,
            "label": str(raw.get("label") or output_id.replace("_", " ").title()),
            "required": bool(raw.get("required", True)),
            "output_type": str(raw.get("output_type") or "printable_component"),
            "expected_solid_count": expected_solid_count,
        }
        component_ids = raw.get("component_ids")
        if isinstance(component_ids, (list, tuple, set)):
            values = [str(value) for value in component_ids if str(value).strip()]
            if values:
                output["component_ids"] = values
        component_id = raw.get("component_id")
        if component_id is not None and str(component_id).strip():
            output["component_id"] = str(component_id)
        aliases = raw.get("aliases")
        if isinstance(aliases, list):
            output["aliases"] = [str(alias) for alias in aliases if str(alias).strip()]
        for key in ("source", "authority", "protected", "raw_evidence", "provenance"):
            if raw.get(key) is not None:
                output[key] = deepcopy(raw[key])
        if "source" not in output:
            output["source"] = "ai_assumption"
        if "authority" not in output:
            output["authority"] = "flexible"
        output.setdefault("protected", False)
        outputs.append(output)
    return outputs


def _product_contract_requirement(
    item: Mapping[str, Any],
    outputs: list[Mapping[str, Any]],
    default_output_id: str,
) -> dict[str, Any]:
    provider_policy = item.get("policy") or item.get("classification")
    item = resolve_product_requirement_policy(item)
    requirement_id = _stable_contract_id(item.get("requirement_id") or item.get("id"), fallback="requirement")
    raw_value = item.get("expected", item.get("value"))
    output_count = _is_output_count_requirement(item)
    expected = (
        {"count": int(raw_value), "independent": True}
        if output_count and isinstance(raw_value, (int, float)) and int(raw_value) == raw_value
        else _expected_contract_value(raw_value)
    )
    source = str(item.get("source") or "initial_user")
    explicit = bool(item.get("explicit", source in {"initial_user", "clarification_user", "revision_user", "physical_test_feedback"}))
    normalized_authority = str(item.get("authority") or ("explicit" if explicit else "flexible"))
    authority = "flexible" if not explicit or normalized_authority in {"flexible", "provisional", "proposed", "ai_assumption"} else "required"
    classification = str(item.get("policy") or item.get("classification") or "machine_required")
    protected = bool(item.get("protected", explicit and authority == "required"))
    scope, scope_kind = _resolve_product_requirement_scope(item, outputs, default_output_id)
    requirement: dict[str, Any] = {
        "requirement_id": requirement_id,
        "expected": expected,
        "classification": classification,
        "origin": "user_explicit" if explicit else "model_design_choice",
        "authority": authority,
        "protected": protected,
        "source": source,
        "policy_version": REQUIREMENT_POLICY_VERSION,
        "policy_source": "application",
    }
    if isinstance(provider_policy, str) and provider_policy in REQUIREMENT_POLICIES and provider_policy != classification:
        requirement["provider_policy"] = provider_policy
    if item.get("policy_reason") is not None:
        requirement["policy_reason"] = str(item["policy_reason"])
    if scope is not None:
        requirement["scope"] = scope
    if scope_kind is not None:
        requirement["scope_kind"] = scope_kind
    if item.get("tolerance") is not None:
        requirement["tolerance"] = item["tolerance"]
    verification_policy = item.get("verification_policy")
    if output_count:
        requirement["verification_policy"] = "required_output_identity"
    elif verification_policy:
        requirement["verification_policy"] = str(verification_policy)
    elif _is_bounds_expectation(expected):
        requirement["verification_policy"] = "final_mesh_bounds"
    for key in ("kind", "operator", "subject", "object_type", "raw_evidence"):
        if item.get(key) is not None:
            requirement[key] = deepcopy(item[key])
    if item.get("provenance") is not None:
        requirement["provenance"] = deepcopy(item["provenance"])
    return requirement


def _resolve_product_requirement_scope(
    item: Mapping[str, Any],
    outputs: list[Mapping[str, Any]],
    default_output_id: str,
) -> tuple[str | None, str | None]:
    """Resolve explicit requirement identity without silently choosing output one."""

    if _is_output_count_requirement(item):
        return None, "assembly"

    registry: dict[str, Mapping[str, Any]] = {
        str(output.get("output_id")): output
        for output in outputs
        if output.get("output_id")
    }
    normalized: dict[str, list[str]] = {}
    for output_id, output in registry.items():
        identities: list[Any] = [output_id, output.get("component_id")]
        for key in ("aliases", "output_aliases", "component_ids"):
            value = output.get(key)
            if isinstance(value, (list, tuple, set)):
                identities.extend(value)
            elif isinstance(value, str):
                identities.append(value)
        for identity in identities:
            key = _normalize_identity(identity)
            if key:
                normalized.setdefault(key, []).append(output_id)

    explicit_values: list[tuple[str, Any]] = []
    for field in ("scope", "target", "output_id", "component_id", "subject", "object_type"):
        value = item.get(field)
        if value in (None, "", []):
            continue
        if isinstance(value, (list, tuple, set)):
            explicit_values.extend((field, entry) for entry in value)
        else:
            explicit_values.append((field, value))
    if not explicit_values:
        if len(registry) == 1:
            return default_output_id, "output_local"
        return None, None

    identity_explicit_values = [
        (field, value)
        for field, value in explicit_values
        if field not in {"subject", "object_type"}
    ]
    if not identity_explicit_values:
        descriptive_matches: list[str] = []
        for _, value in explicit_values:
            descriptive_matches.extend(normalized.get(_normalize_identity(value), []))
        descriptive_matches = list(dict.fromkeys(descriptive_matches))
        if len(descriptive_matches) == 1:
            return descriptive_matches[0], "output_local"
        if len(descriptive_matches) > 1:
            return "/".join(descriptive_matches), "unresolved"
        if len(registry) == 1:
            return default_output_id, "output_local"
        return None, None
    lowered = {_normalize_identity(value) for _, value in identity_explicit_values}
    if lowered & {"assembly", "global"}:
        if len(lowered) == 1:
            return None, "assembly"
        return "/".join(str(value) for _, value in identity_explicit_values), "unresolved"

    resolved: list[str] = []
    unresolved: list[str] = []
    for field, value in explicit_values:
        identity = _normalize_identity(value)
        matches = list(dict.fromkeys(normalized.get(identity, [])))
        if len(matches) == 1:
            resolved.append(matches[0])
        elif len(matches) > 1:
            unresolved.append(str(value))
        elif field in {"scope", "target", "output_id", "component_id"}:
            # A declared scope/target that is not in the output registry is
            # authoritative evidence of an unresolved scope. Subject and
            # object_type are often descriptive prose, so unknown values in
            # those fields do not override a valid explicit target.
            unresolved.append(str(value))
    if unresolved and not resolved:
        # Preserve the explicit identity for the semantic resolver to fail
        # closed. Never redirect an unknown or ambiguous scope to output one.
        return "/".join(dict.fromkeys(unresolved)), "unresolved"
    if unresolved:
        return "/".join(dict.fromkeys([*resolved, *unresolved])), "unresolved"
    if len(set(resolved)) == 1:
        return resolved[0], "output_local"
    return "/".join(dict.fromkeys(resolved)), "multi_output"


def _normalize_identity(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")


def _is_output_count_requirement(item: Mapping[str, Any]) -> bool:
    values = [item.get(key) for key in ("kind", "type", "subject", "object_type", "target", "raw_evidence")]
    text = " ".join(str(value or "").casefold() for value in values)
    return any(token in text for token in ("output", "printable", "component", "part")) and (
        str(item.get("kind") or item.get("type") or "").casefold() == "count"
        or "count" in text
        or "number" in text
    )


def _expected_contract_value(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        expected = deepcopy(dict(value))
        if {"x", "y", "z"}.issubset(expected) and not {"width", "depth", "height"}.issubset(expected):
            return {
                "width": expected["x"],
                "depth": expected["y"],
                "height": expected["z"],
            }
        return expected
    if value is None:
        return {}
    return {"value": deepcopy(value)}


def _is_bounds_expectation(expected: Mapping[str, Any]) -> bool:
    return (
        {"width", "depth", "height"}.issubset(expected)
        or {"width", "depth", "thickness"}.issubset(expected)
    )


def _resolve_product_classification(item: Mapping[str, Any]) -> str:
    """Compatibility wrapper for callers of the former contract-local helper."""

    return resolve_product_requirement_policy(item)["policy"]


def _stable_contract_id(value: Any, *, fallback: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").lower()).strip("_")
    return normalized or fallback


def parse_executable_cadquery_response(
    raw_output: str,
    design_contract: Mapping[str, Any],
) -> ExecutableCadQueryResponse:
    """Extract and validate one complete provider-owned CadQuery module.

    The only accepted response forms are raw Python or one fenced Python
    block. The extracted source is passed unchanged to the existing
    ``cadquery-v1`` validator; this function never reconstructs or patches it.
    """

    contract = validate_executable_cadquery_design_contract(design_contract)
    outputs = contract["outputs"]
    expected_output_ids = [str(output["output_id"]) for output in outputs]
    source = _extract_complete_source(raw_output)
    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    try:
        ast.parse(source)
    except SyntaxError as exc:
        error = ExecutableCadQuerySyntaxError(
            f"invalid Python syntax: {exc.msg}",
        )
        error.diagnostic = {
            "code": "python_syntax_error",
            "line": exc.lineno,
            "column": exc.offset,
            "node_type": "SyntaxError",
            "ast_path": None,
            "enclosing_scope": "module",
            "message": f"invalid Python syntax: {exc.msg}",
            "violation_count": 1,
        }
        _attach_extraction_context(error, source, source_hash)
        raise error from exc
    try:
        metadata = validate_cadquery_source(source, contract_version=SOURCE_CONTRACT_VERSION)
    except CadQueryContractError as exc:
        error = ExecutableCadQueryContractError(
            f"source contract violation for {expected_output_ids}: {exc}",
            failure_kind="source_contract_violation",
            boundary="source_contract",
            diagnostic=diagnose_cadquery_contract_error(source, str(exc)),
        )
        _attach_extraction_context(error, source, source_hash)
        raise error from exc
    if set(metadata.output_ids) != set(expected_output_ids):
        error = ExecutableCadQueryContractError(
            "canonical output identity changed in source: "
            f"expected {expected_output_ids}, got {metadata.output_ids}",
            failure_kind="source_contract_violation",
            boundary="source_contract",
        )
        error.diagnostic = _diagnostic(
            code="canonical_output_identity_mismatch",
            message=str(error),
            source=source,
            predicate=lambda node: isinstance(node, ast.Call)
            and _diagnostic_call_name(node.func) == "PrintableOutput",
        )
        _attach_extraction_context(error, source, source_hash)
        raise error
    for output in outputs:
        expected_output_id = str(output["output_id"])
        expected_solid_count = int(output["expected_solid_count"])
        detected_solid_count = metadata.expected_solid_counts.get(expected_output_id)
        if detected_solid_count != expected_solid_count:
            error = ExecutableCadQueryContractError(
                f"expected solid count contract mismatch for {expected_output_id}: "
                f"expected {expected_solid_count}, got {detected_solid_count}",
                failure_kind="source_contract_violation",
                boundary="source_contract",
            )
            error.diagnostic = _diagnostic(
                code="expected_solid_count_mismatch",
                message=str(error),
                source=source,
                predicate=lambda node: isinstance(node, ast.Call)
                and _diagnostic_call_name(node.func) == "PrintableOutput",
            )
            _attach_extraction_context(error, source, source_hash)
            raise error
    return ExecutableCadQueryResponse(
        schema_version=RESPONSE_SCHEMA_VERSION,
        outputs=tuple(
            ExecutableCadQuerySource(
                output_id=str(output["output_id"]),
                parameters={},
                source=source,
                source_hash=source_hash,
                source_metadata=metadata,
            )
            for output in outputs
        ),
    )


def _extract_complete_source(raw_output: str) -> str:
    if not isinstance(raw_output, str) or not raw_output.strip():
        raise ExecutableCadQueryResponseError("provider response is empty")
    fence_count = raw_output.count("```")
    if fence_count:
        if fence_count != 2:
            raise ExecutableCadQueryResponseError(
                "provider response must contain exactly one fenced Python block"
            )
        match = re.fullmatch(
            r"[ \t\r\n]*```python[ \t]*\r?\n(?P<source>[\s\S]*?)\r?\n```[ \t\r\n]*",
            raw_output,
        )
        if match is None:
            raise ExecutableCadQueryResponseError(
                "provider response fenced block must be exactly one Python block with no prose"
            )
        source = match.group("source")
    else:
        source = raw_output
        first_line = next((line.strip() for line in source.splitlines() if line.strip()), "")
        starts_like_python = bool(
            re.match(r"(?:#|import |from |def |class |@|[A-Za-z_]\w*\s*=)", first_line)
        )
        if not starts_like_python:
            raise ExecutableCadQueryResponseError(
                "provider response must be raw Python or exactly one fenced Python block"
            )
        if any(marker in source for marker in ("Here is", "Here’s", "Sure,", "```")):
            raise ExecutableCadQueryResponseError(
                "provider response contains prose outside the complete Python module"
            )
    if not source.strip():
        raise ExecutableCadQueryResponseError("provider response contains no Python source")
    return source


def diagnose_cadquery_contract_error(source: str, message: str) -> dict[str, Any]:
    """Normalize an existing validator message into stable AST diagnostics."""

    tree = ast.parse(source)
    lowered = message.lower()
    code = "source_contract_violation"
    diagnostic_message = message
    predicate = lambda _node: False
    top_level_type: str | None = None

    if "try/except is not allowed" in lowered:
        code = "try_statement_forbidden"
        diagnostic_message = "try/except is not allowed"
        predicate = lambda node: isinstance(node, ast.Try)
    elif "with statements are not allowed" in lowered:
        code = "with_statement_forbidden"
        diagnostic_message = "with statements are not allowed"
        predicate = lambda node: isinstance(node, (ast.With, ast.AsyncWith))
    elif "global/nonlocal statements are not allowed" in lowered:
        code = "global_nonlocal_forbidden"
        diagnostic_message = "global and nonlocal statements are not allowed"
        predicate = lambda node: isinstance(node, (ast.Global, ast.Nonlocal))
    elif "imports are only allowed at top level" in lowered:
        code = "nested_import_forbidden"
        diagnostic_message = "imports inside functions are not allowed"
        predicate = lambda node: isinstance(node, (ast.Import, ast.ImportFrom))
    elif "dunder attribute access is not allowed" in lowered:
        code = "dunder_access_forbidden"
        diagnostic_message = "dunder attribute access is not allowed"
        predicate = lambda node: isinstance(node, ast.Attribute) and node.attr.startswith("__")
    elif "dynamic calls are not allowed" in lowered:
        code = "dynamic_call_forbidden"
        diagnostic_message = "dynamic calls are not allowed"
        predicate = lambda node: isinstance(node, ast.Call) and not isinstance(
            node.func, (ast.Name, ast.Attribute)
        )
    elif "unsafe call is not allowed:" in lowered:
        name = message.split(":", 1)[-1].strip()
        code = "unsafe_call_forbidden"
        diagnostic_message = f"unsafe call is not allowed: {name}"
        predicate = lambda node: isinstance(node, ast.Call) and _diagnostic_call_name(node.func) == name
    elif "generated source cannot perform artifact writing" in lowered:
        code = "artifact_export_forbidden"
        diagnostic_message = "artifact exports are not allowed in generated source"
        predicate = lambda node: isinstance(node, ast.Call) and (
            _diagnostic_call_name(node.func) in {"export", "save", "write", "write_bytes", "write_text"}
            or _diagnostic_dotted_name(node.func) == "cq.exporters.export"
        )
    elif "unsupported direct function call:" in lowered:
        name = message.split(":", 1)[-1].strip()
        code = "unsupported_direct_call"
        diagnostic_message = f"unsupported direct function call: {name}"
        predicate = lambda node: isinstance(node, ast.Call) and _diagnostic_call_name(node.func) == name
    elif "unsupported top-level statement:" in lowered:
        top_level_type = message.split(":", 1)[-1].strip()
        code = f"top_level_{top_level_type.lower()}_forbidden"
        diagnostic_message = f"top-level {top_level_type.lower()} statements are not allowed"
    elif "top-level assignment" in lowered:
        code = "top_level_assignment_forbidden"
        diagnostic_message = "top-level assignments must be static declarations"
        predicate = lambda node: isinstance(node, (ast.Assign, ast.AnnAssign))

    node = None
    if top_level_type:
        node = next(
            (candidate for candidate in tree.body if type(candidate).__name__ == top_level_type),
            None,
        )
    if node is None:
        top_level_nodes = set(tree.body)
        node = next(
            (
                candidate
                for candidate in ast.walk(tree)
                if predicate(candidate) and candidate not in top_level_nodes
            ),
            None,
        )
    return _diagnostic(
        code=code,
        message=diagnostic_message,
        source=source,
        node=node,
    )


def _attach_extraction_context(
    error: ExecutableCadQueryContractError,
    source: str,
    source_hash: str,
) -> None:
    error.extracted_source = source
    error.extracted_source_hash = source_hash
    error.syntax_valid = not isinstance(error, ExecutableCadQuerySyntaxError)
    error.source_contract_valid = False


def _diagnostic(
    *,
    code: str,
    message: str,
    source: str,
    node: ast.AST | None = None,
    predicate: Any | None = None,
) -> dict[str, Any]:
    tree = ast.parse(source)
    if node is None and predicate is not None:
        node = next((candidate for candidate in ast.walk(tree) if predicate(candidate)), None)
    elif node is not None and not any(candidate is node for candidate in ast.walk(tree)):
        node = next(
            (
                candidate
                for candidate in ast.walk(tree)
                if type(candidate) is type(node)
                and getattr(candidate, "lineno", None) == getattr(node, "lineno", None)
                and getattr(candidate, "col_offset", None) == getattr(node, "col_offset", None)
            ),
            None,
        )
    path, scope = _ast_context(tree, node) if node is not None else (None, "module")
    return {
        "code": code,
        "line": getattr(node, "lineno", None),
        "column": getattr(node, "col_offset", None),
        "node_type": type(node).__name__ if node is not None else None,
        "ast_path": path,
        "enclosing_scope": scope,
        "message": message,
        "violation_count": 1,
    }


def _ast_context(tree: ast.AST, target: ast.AST | None) -> tuple[str | None, str]:
    if target is None:
        return None, "module"
    found: tuple[str, str] | None = None

    def visit(node: ast.AST, path: str, scope: str) -> None:
        nonlocal found
        if node is target:
            found = (path, scope)
            return
        child_scope = node.name if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else scope
        for field_name, value in ast.iter_fields(node):
            if isinstance(value, ast.AST):
                visit(value, f"{path}.{field_name}", child_scope)
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    if isinstance(item, ast.AST):
                        visit(item, f"{path}.{field_name}[{index}]", child_scope)
            if found is not None:
                return

    visit(tree, "module", "module")
    return found or (None, "module")


def _diagnostic_call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _diagnostic_dotted_name(node: ast.expr) -> str | None:
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None
