"""Contracts for the Gemini complete-source CadQuery experiment.

This module validates provider-owned source without interpreting or rewriting
CadQuery. The existing worker-facing ``cadquery-v1`` validator remains the
source safety boundary.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping

from app.services.cad.cadquery_contract import (
    CadQueryContractError,
    CadQuerySourceMetadata,
    validate_cadquery_source,
)


DESIGN_CONTRACT_SCHEMA_VERSION = "executable-cadquery-design-contract-v1"
RESPONSE_SCHEMA_VERSION = "executable-cadquery-complete-source-v2"
SOURCE_CONTRACT_VERSION = "cadquery-v1"


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
    if len(outputs) != 1:
        raise ExecutableCadQueryContractError(
            "complete-source v2 requires exactly one frozen-contract output"
        )
    expected_output_id = str(outputs[0]["output_id"])
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
            f"source contract violation for {expected_output_id}: {exc}",
            failure_kind="source_contract_violation",
            boundary="source_contract",
            diagnostic=diagnose_cadquery_contract_error(source, str(exc)),
        )
        _attach_extraction_context(error, source, source_hash)
        raise error from exc
    if metadata.output_ids != [expected_output_id]:
        error = ExecutableCadQueryContractError(
            f"canonical output identity changed in source: expected only {expected_output_id}, "
            f"got {metadata.output_ids}",
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
    expected_solid_count = int(outputs[0]["expected_solid_count"])
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
        outputs=(
            ExecutableCadQuerySource(
                output_id=expected_output_id,
                parameters={},
                source=source,
                source_hash=source_hash,
                source_metadata=metadata,
            ),
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
        node = next((candidate for candidate in ast.walk(tree) if predicate(candidate)), None)
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
