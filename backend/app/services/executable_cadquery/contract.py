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
    ) -> None:
        super().__init__(message)
        self.failure_kind = failure_kind
        self.boundary = boundary


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
    try:
        ast.parse(source)
    except SyntaxError as exc:
        raise ExecutableCadQuerySyntaxError(f"invalid Python syntax: {exc.msg}") from exc
    try:
        metadata = validate_cadquery_source(source, contract_version=SOURCE_CONTRACT_VERSION)
    except CadQueryContractError as exc:
        raise ExecutableCadQueryContractError(
            f"source contract violation for {expected_output_id}: {exc}",
            failure_kind="source_contract_violation",
            boundary="source_contract",
        ) from exc
    if metadata.output_ids != [expected_output_id]:
        raise ExecutableCadQueryContractError(
            f"canonical output identity changed in source: expected only {expected_output_id}, "
            f"got {metadata.output_ids}",
            failure_kind="source_contract_violation",
            boundary="source_contract",
        )
    expected_solid_count = int(outputs[0]["expected_solid_count"])
    detected_solid_count = metadata.expected_solid_counts.get(expected_output_id)
    if detected_solid_count != expected_solid_count:
        raise ExecutableCadQueryContractError(
            f"expected solid count contract mismatch for {expected_output_id}: "
            f"expected {expected_solid_count}, got {detected_solid_count}",
            failure_kind="source_contract_violation",
            boundary="source_contract",
        )
    return ExecutableCadQueryResponse(
        schema_version=RESPONSE_SCHEMA_VERSION,
        outputs=(
            ExecutableCadQuerySource(
                output_id=expected_output_id,
                parameters={},
                source=source,
                source_hash=hashlib.sha256(source.encode("utf-8")).hexdigest(),
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
