"""Contracts for the Gemini complete-source CadQuery experiment.

This module validates provider-owned source without interpreting or rewriting
CadQuery. The existing worker-facing ``cadquery-v1`` validator remains the
source safety boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping

from app.services.cad.cadquery_contract import (
    CadQueryContractError,
    CadQuerySourceMetadata,
    validate_cadquery_source,
)


DESIGN_CONTRACT_SCHEMA_VERSION = "executable-cadquery-design-contract-v1"
RESPONSE_SCHEMA_VERSION = "executable-cadquery-response-v1"
SOURCE_CONTRACT_VERSION = "cadquery-v1"


class ExecutableCadQueryContractError(ValueError):
    """Raised when the provider response or authoritative contract is invalid."""


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
    """Parse a strict provider envelope containing complete source units.

    The parser intentionally does not strip Markdown fences or repair source.
    A provider response that is not already compatible is a contract failure
    and must be repaired by returning a complete replacement response.
    """

    contract = validate_executable_cadquery_design_contract(design_contract)
    try:
        payload = json.loads(raw_output)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ExecutableCadQueryContractError("response is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ExecutableCadQueryContractError("response envelope must be an object")
    if payload.get("schema_version") != RESPONSE_SCHEMA_VERSION:
        raise ExecutableCadQueryContractError("unsupported response schema_version")

    expected_outputs = {
        str(item["output_id"]): item
        for item in contract["outputs"]
        if isinstance(item, dict)
    }
    raw_outputs = payload.get("outputs")
    if not isinstance(raw_outputs, list) or not raw_outputs:
        raise ExecutableCadQueryContractError("response outputs are required")

    parsed: list[ExecutableCadQuerySource] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_outputs):
        if not isinstance(item, dict):
            raise ExecutableCadQueryContractError(f"response outputs[{index}] must be an object")
        output_id = item.get("output_id")
        if not isinstance(output_id, str) or not output_id:
            raise ExecutableCadQueryContractError("response output_id is required")
        if output_id in seen:
            raise ExecutableCadQueryContractError(f"duplicate response output_id: {output_id}")
        seen.add(output_id)
        expected = expected_outputs.get(output_id)
        if expected is None:
            raise ExecutableCadQueryContractError(
                f"canonical output identity changed: unexpected output {output_id}"
            )
        source = item.get("source")
        if not isinstance(source, str) or not source.strip():
            raise ExecutableCadQueryContractError(
                f"complete source is required for output {output_id}"
            )
        parameters = item.get("parameters", {})
        if not isinstance(parameters, dict):
            raise ExecutableCadQueryContractError(
                f"parameters for output {output_id} must be an object"
            )
        try:
            metadata = validate_cadquery_source(source, contract_version=SOURCE_CONTRACT_VERSION)
        except CadQueryContractError as exc:
            raise ExecutableCadQueryContractError(
                f"source contract violation for {output_id}: {exc}"
            ) from exc
        source_output_ids = set(metadata.output_ids)
        if source_output_ids != {output_id}:
            raise ExecutableCadQueryContractError(
                f"canonical output identity changed in source for {output_id}: "
                f"expected only {output_id}, got {sorted(source_output_ids)}"
            )
        expected_solid_count = int(expected["expected_solid_count"])
        detected_solid_count = metadata.expected_solid_counts.get(output_id)
        if detected_solid_count != expected_solid_count:
            raise ExecutableCadQueryContractError(
                f"expected solid count contract mismatch for {output_id}: "
                f"expected {expected_solid_count}, got {detected_solid_count}"
            )
        parsed.append(
            ExecutableCadQuerySource(
                output_id=output_id,
                parameters=json.loads(json.dumps(parameters, sort_keys=True, default=str)),
                source=source,
                source_hash=hashlib.sha256(source.encode("utf-8")).hexdigest(),
                source_metadata=metadata,
            )
        )

    missing = set(expected_outputs) - seen
    if missing:
        raise ExecutableCadQueryContractError(
            f"canonical output identity missing from response: {sorted(missing)}"
        )
    return ExecutableCadQueryResponse(
        schema_version=RESPONSE_SCHEMA_VERSION,
        outputs=tuple(parsed),
    )
