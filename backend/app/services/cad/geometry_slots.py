"""Volundr-owned geometry slots for direct and compact CAD generation.

The provider supplies only statements for stable function slots.  Function
identity, signatures, imports, the scaffold, and the output entrypoint remain
owned by Volundr and are assembled by the existing geometry-body validator.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from app.services.cad.geometry_bodies import (
    GeometryBodyError,
    _canonicalize_function,
    build_geometry_function_inventory,
)


GEOMETRY_SLOTS_SCHEMA_VERSION = "volundr-geometry-slots-v1"
GEOMETRY_SLOTS_CONTRACT_VERSION = GEOMETRY_SLOTS_SCHEMA_VERSION
LEGACY_GEOMETRY_CONTRACT = "legacy_contract"
GEOMETRY_SLOTS_MODE = "geometry_slots_v1"
GEOMETRY_SLOTS_AUTO_MODE = "auto"

# These are the names imported into the generated scaffold.  The broader
# legacy geometry-body symbol inventory intentionally remains unchanged for
# detailed plans and compatibility repairs.
SCAFFOLD_EXPOSED_HELPERS = (
    "place_pattern_cutters",
    "resolve_pattern_points",
)

_FENCED_JSON_RE = re.compile(
    r"\A\s*```(?:json)?\s*(?P<payload>.*?)```\s*\Z",
    re.IGNORECASE | re.DOTALL,
)
_SCAFFOLD_OWNED_NAMES = {
    "PARAMETERS",
    "Product",
    "PrintableOutput",
    "ParameterSpec",
    "build",
    "component",
    "feature",
    "shared_helper",
    "protected_interface",
    "resolve_pattern_points",
    "place_pattern_cutters",
}


class GeometrySlotError(ValueError):
    """A deterministic rejection of a slot response or merge."""

    def __init__(self, rule_id: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        self.rule_id = rule_id
        self.details = details or {}
        super().__init__(message)


@dataclass(frozen=True)
class GeometrySlotResponse:
    """Validated slots plus non-fatal missing and invalid classifications."""

    payload: dict[str, Any]
    records_by_slot: dict[int, dict[str, Any]]
    functions: dict[str, str]
    original_statements: dict[int, list[str]]
    canonical_statements: dict[int, list[str]]
    result_symbols: dict[int, str]
    slot_body_hashes: dict[int, str]
    completed_slot_ids: list[int]
    missing_slot_ids: list[int]
    invalid_slots: list[dict[str, Any]]
    extra_slot_ids: list[int]

    @property
    def is_complete(self) -> bool:
        return not self.missing_slot_ids and not self.invalid_slots


def select_geometry_contract(planning_depth: str, mode: str = GEOMETRY_SLOTS_AUTO_MODE) -> str:
    """Select the production geometry boundary for a planning route."""

    if mode not in {GEOMETRY_SLOTS_AUTO_MODE, LEGACY_GEOMETRY_CONTRACT, GEOMETRY_SLOTS_MODE}:
        raise ValueError(f"Unsupported geometry contract mode `{mode}`.")
    if mode == LEGACY_GEOMETRY_CONTRACT:
        return LEGACY_GEOMETRY_CONTRACT
    if mode == GEOMETRY_SLOTS_MODE:
        return GEOMETRY_SLOTS_CONTRACT_VERSION
    if planning_depth in {"direct_brief", "compact_plan"}:
        return GEOMETRY_SLOTS_CONTRACT_VERSION
    return LEGACY_GEOMETRY_CONTRACT


def build_geometry_slot_manifest(plan: dict[str, Any], *, planning_depth: str | None = None) -> dict[str, Any]:
    """Derive an authoritative, provider-safe slot manifest from the Plan."""

    inventory = build_geometry_function_inventory(plan)
    slots: list[dict[str, Any]] = []
    for slot_id, function in enumerate(inventory.get("functions", []) or []):
        if not isinstance(function, dict):
            continue
        function_id = str(function.get("function_id") or "")
        if not function_id:
            continue
        signature = _signature_arguments(str(function.get("signature") or "(params)"))
        required_features = (
            [str(function["feature_id"])] if function.get("feature_id") else []
        )
        required_inputs = [str(value) for value in function.get("required_inputs", []) or [] if value]
        authorized_parameters = {
            str(value)
            for value in function.get("allowed_parameters", []) or []
            if value
        }
        authorized_parameters.update(
            str(value)
            for key in ("required_direct_parameters", "allowed_derived_parameters")
            for value in function.get(key, []) or []
            if value
        )
        authorized_parameters.update(
            str(item.get("parameter_id"))
            for item in function.get("required_parameter_effects", []) or []
            if isinstance(item, dict) and item.get("parameter_id")
        )
        slots.append(
            {
                "slot_id": slot_id,
                "function_id": function_id,
                "signature": signature,
                "owner_component_id": str(function.get("owner_component_id") or ""),
                "required_feature_ids": required_features,
                "authorized_parameter_ids": sorted(authorized_parameters),
                "approved_helpers": list(SCAFFOLD_EXPOSED_HELPERS),
                "required_inputs": required_inputs,
                "required_result": str(function.get("required_return") or "shape"),
            }
        )
    return {
        "schema_version": GEOMETRY_SLOTS_SCHEMA_VERSION,
        "planning_depth": planning_depth,
        "slots": slots,
    }


def build_geometry_slot_brief(
    *,
    planning_depth: str,
    active_requirements: list[dict[str, Any]],
    requirement_delta: list[dict[str, Any]],
    preserved_requirements: list[dict[str, Any]],
    proposals: list[dict[str, Any]],
    design_plan: dict[str, Any],
    slot_manifest: dict[str, Any],
    exposed_controls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the reduced execution brief supplied to the geometry provider."""

    return {
        "schema_version": GEOMETRY_SLOTS_SCHEMA_VERSION,
        "planning_depth": planning_depth,
        "active_requirements": list(active_requirements),
        "revision_delta": list(requirement_delta),
        "preserved_requirements": list(preserved_requirements),
        "proposals": list(proposals),
        "components": list(design_plan.get("components", []) or []),
        "features": list(design_plan.get("features", []) or []),
        "printable_outputs": list(design_plan.get("printable_outputs", []) or []),
        "coordinate_frames": list(
            design_plan.get("coordinate_frames", design_plan.get("frames", [])) or []
        ),
        "relationships": list(design_plan.get("relationships", []) or []),
        "exposed_controls": list(exposed_controls or design_plan.get("exposed_controls", []) or []),
        "slots": [
            {
                "slot_id": item.get("slot_id"),
                "required_inputs": list(item.get("required_inputs", []) or []),
                "authorized_parameter_ids": list(item.get("authorized_parameter_ids", []) or []),
                "approved_helpers": list(item.get("approved_helpers", []) or []),
                "required_result": item.get("required_result"),
            }
            for item in slot_manifest.get("slots", []) or []
            if isinstance(item, dict)
        ],
        "restrictions": [
            "Return only the supplied slot records; do not return function declarations, arguments, imports, IDs, parameters, scaffold, or entrypoint code.",
            "Do not include raw full chat history, lifecycle metadata, unrelated database IDs, provider provenance, validation-target records, workflow events, old responses, or debug bundles.",
            "Use only the approved helpers and authorized params access listed for each slot.",
            "Volundr inserts returns, builds outputs, validates source, submits the worker, and performs verification.",
        ],
    }


def parse_geometry_slots(raw_output: str, manifest: dict[str, Any]) -> GeometrySlotResponse:
    """Validate provider slots while retaining valid partial progress."""

    payload = _parse_payload(raw_output)
    records = payload.get("slots")
    if not isinstance(records, list):
        raise GeometrySlotError(
            "geometry_slot.invalid_json",
            "Geometry slot response must contain a slots array.",
        )
    specs = _manifest_specs(manifest)
    expected_ids = list(specs)
    seen: set[int] = set()
    records_by_slot: dict[int, dict[str, Any]] = {}
    functions: dict[str, str] = {}
    original_statements: dict[int, list[str]] = {}
    canonical_statements: dict[int, list[str]] = {}
    result_symbols: dict[int, str] = {}
    hashes: dict[int, str] = {}
    invalid: list[dict[str, Any]] = []

    for record in records:
        if not isinstance(record, dict) or not _valid_slot_id(record.get("slot_id")):
            raise GeometrySlotError(
                "geometry_slot.invalid_json",
                "Each geometry slot must contain an integer slot_id.",
            )
        slot_id = int(record["slot_id"])
        if slot_id in seen:
            raise GeometrySlotError(
                "geometry_slot.duplicate_slot",
                f"duplicate geometry slot `{slot_id}` was returned more than once.",
            )
        if slot_id not in specs:
            raise GeometrySlotError(
                "geometry_slot.unknown_slot",
                f"unknown geometry slot `{slot_id}` was returned.",
            )
        seen.add(slot_id)
        spec = specs[slot_id]
        statements = record.get("statements")
        result_symbol = record.get("result_symbol")
        records_by_slot[slot_id] = dict(record)
        if not isinstance(statements, list) or not statements or not all(
            isinstance(line, str) for line in statements
        ):
            invalid.append(
                _invalid_slot(
                    slot_id,
                    spec,
                    "geometry_slot.invalid_statement",
                    "Slot statements must be a non-empty array of strings.",
                    statements,
                    result_symbol,
                )
            )
            continue
        try:
            canonical, function_source, evidence = _canonicalize_function(
                function_id=str(spec["function_id"]),
                statements=statements,
                result_symbol=result_symbol,
                signature=_signature_text(spec["signature"]),
                allowed_parameters={str(value) for value in spec.get("authorized_parameter_ids", []) or []},
                scaffold_owned_identifiers={
                    *_SCAFFOLD_OWNED_NAMES,
                    *(str(item["function_id"]) for item in specs.values()),
                },
                approved_helpers={str(value) for value in spec.get("approved_helpers", []) or []},
            )
        except GeometryBodyError as exc:
            invalid.append(
                _invalid_slot(
                    slot_id,
                    spec,
                    _slot_rule(exc.rule_id),
                    str(exc),
                    statements,
                    result_symbol,
                    details=exc.details,
                )
            )
            continue
        functions[str(spec["function_id"])] = function_source
        original_statements[slot_id] = list(statements)
        canonical_statements[slot_id] = list(canonical)
        result_symbols[slot_id] = str(result_symbol)
        hashes[slot_id] = _slot_hash(
            slot_id=slot_id,
            function_id=str(spec["function_id"]),
            statements=canonical,
            result_symbol=str(result_symbol),
        )
        # Keep stable evidence available to attempt artifacts without exposing
        # it as provider-owned structure.
        records_by_slot[slot_id]["symbol_evidence"] = evidence

    completed = [slot_id for slot_id in expected_ids if slot_id in canonical_statements]
    missing = [slot_id for slot_id in expected_ids if slot_id not in seen]
    return GeometrySlotResponse(
        payload=payload,
        records_by_slot=records_by_slot,
        functions={
            str(specs[slot_id]["function_id"]): functions[str(specs[slot_id]["function_id"])]
            for slot_id in completed
        },
        original_statements={slot_id: original_statements[slot_id] for slot_id in completed},
        canonical_statements={slot_id: canonical_statements[slot_id] for slot_id in completed},
        result_symbols={slot_id: result_symbols[slot_id] for slot_id in completed},
        slot_body_hashes={slot_id: hashes[slot_id] for slot_id in completed},
        completed_slot_ids=completed,
        missing_slot_ids=missing,
        invalid_slots=invalid,
        extra_slot_ids=[],
    )


def merge_geometry_slots(
    initial: GeometrySlotResponse,
    completion: GeometrySlotResponse,
    manifest: dict[str, Any],
) -> GeometrySlotResponse:
    """Merge one focused response without allowing completed-slot mutation."""

    completed_initial = set(initial.completed_slot_ids)
    changed_completed = sorted(completed_initial & set(completion.records_by_slot))
    if changed_completed:
        raise GeometrySlotError(
            "geometry_slot.completed_slot_changed",
            "Focused completion attempted to change a completed slot.",
            details={"slot_ids": changed_completed},
        )
    combined_completed = sorted(completed_initial | set(completion.completed_slot_ids))
    specs = _manifest_specs(manifest)
    records_by_slot = dict(initial.records_by_slot)
    records_by_slot.update(completion.records_by_slot)
    functions = dict(initial.functions)
    functions.update(completion.functions)
    original = dict(initial.original_statements)
    original.update(completion.original_statements)
    canonical = dict(initial.canonical_statements)
    canonical.update(completion.canonical_statements)
    symbols = dict(initial.result_symbols)
    symbols.update(completion.result_symbols)
    hashes = dict(initial.slot_body_hashes)
    hashes.update(completion.slot_body_hashes)
    invalid = [
        item
        for item in [*initial.invalid_slots, *completion.invalid_slots]
        if int(item.get("slot_id", -1)) not in set(combined_completed)
    ]
    expected_ids = list(specs)
    missing = [slot_id for slot_id in expected_ids if slot_id not in set(records_by_slot)]
    return GeometrySlotResponse(
        payload={
            "schema_version": GEOMETRY_SLOTS_SCHEMA_VERSION,
            "slots": [records_by_slot[slot_id] for slot_id in expected_ids if slot_id in records_by_slot],
        },
        records_by_slot=records_by_slot,
        functions={
            str(specs[slot_id]["function_id"]): functions[str(specs[slot_id]["function_id"])]
            for slot_id in combined_completed
        },
        original_statements={slot_id: original[slot_id] for slot_id in combined_completed},
        canonical_statements={slot_id: canonical[slot_id] for slot_id in combined_completed},
        result_symbols={slot_id: symbols[slot_id] for slot_id in combined_completed},
        slot_body_hashes={slot_id: hashes[slot_id] for slot_id in combined_completed},
        completed_slot_ids=combined_completed,
        missing_slot_ids=missing,
        invalid_slots=invalid,
        extra_slot_ids=[],
    )


def build_focused_slot_completion(
    response: GeometrySlotResponse,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Build the only slot scope allowed for the one focused completion call."""

    specs = _manifest_specs(manifest)
    invalid_ids = {
        int(item["slot_id"])
        for item in response.invalid_slots
        if _valid_slot_id(item.get("slot_id"))
    }
    requested = [
        slot_id
        for slot_id in specs
        if slot_id in set(response.missing_slot_ids) or slot_id in invalid_ids
    ]
    focused_manifest = {
        "schema_version": GEOMETRY_SLOTS_SCHEMA_VERSION,
        "planning_depth": manifest.get("planning_depth"),
        "slots": [specs[slot_id] for slot_id in requested],
    }
    return {
        "requested_slot_ids": requested,
        "slot_manifest": focused_manifest,
        "invalid_slots": [
            item for item in response.invalid_slots if int(item.get("slot_id", -1)) in set(requested)
        ],
        "preserved_slot_hashes": {
            str(slot_id): response.slot_body_hashes[slot_id]
            for slot_id in response.completed_slot_ids
            if slot_id in response.slot_body_hashes
        },
    }


def _manifest_specs(manifest: dict[str, Any]) -> dict[int, dict[str, Any]]:
    if manifest.get("schema_version") != GEOMETRY_SLOTS_SCHEMA_VERSION:
        raise GeometrySlotError(
            "geometry_slot.invalid_manifest",
            f"Slot manifest must use schema_version {GEOMETRY_SLOTS_SCHEMA_VERSION}.",
        )
    result: dict[int, dict[str, Any]] = {}
    slots = manifest.get("slots")
    if not isinstance(slots, list) or not slots:
        raise GeometrySlotError("geometry_slot.invalid_manifest", "Slot manifest must contain slots.")
    for spec in slots:
        if not isinstance(spec, dict) or not _valid_slot_id(spec.get("slot_id")):
            raise GeometrySlotError("geometry_slot.invalid_manifest", "Manifest slots need integer slot IDs.")
        slot_id = int(spec["slot_id"])
        if slot_id in result:
            raise GeometrySlotError("geometry_slot.invalid_manifest", f"Duplicate manifest slot `{slot_id}`.")
        if not isinstance(spec.get("function_id"), str) or not spec["function_id"]:
            raise GeometrySlotError("geometry_slot.invalid_manifest", f"Slot `{slot_id}` lacks a function ID.")
        signature = spec.get("signature")
        if not isinstance(signature, list) or not all(isinstance(value, str) for value in signature):
            raise GeometrySlotError("geometry_slot.invalid_manifest", f"Slot `{slot_id}` has an invalid signature.")
        result[slot_id] = dict(spec)
    return result


def _parse_payload(raw_output: str) -> dict[str, Any]:
    text = raw_output.strip()
    match = _FENCED_JSON_RE.fullmatch(text)
    if match:
        text = match.group("payload").strip()
    elif text.startswith("```") or not text.startswith("{"):
        raise GeometrySlotError(
            "geometry_slot.invalid_json",
            "Geometry slot response must be JSON only; prose and source wrappers are not allowed.",
        )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GeometrySlotError("geometry_slot.invalid_json", f"Geometry slot response is not valid JSON: {exc.msg}.") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != GEOMETRY_SLOTS_SCHEMA_VERSION:
        raise GeometrySlotError(
            "geometry_slot.invalid_json",
            f"Geometry slot response must use schema_version {GEOMETRY_SLOTS_SCHEMA_VERSION}.",
        )
    return payload


def _signature_arguments(signature: str) -> list[str]:
    text = signature.strip()
    if not (text.startswith("(") and text.endswith(")")):
        raise GeometrySlotError("geometry_slot.invalid_manifest", f"Invalid function signature `{signature}`.")
    inner = text[1:-1].strip()
    return [part.strip() for part in inner.split(",") if part.strip()]


def _signature_text(arguments: Any) -> str:
    if not isinstance(arguments, list) or not all(isinstance(value, str) for value in arguments):
        raise GeometrySlotError("geometry_slot.invalid_manifest", "Slot signature must be an argument-name array.")
    return "(" + ", ".join(arguments) + ")"


def _valid_slot_id(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _slot_rule(rule_id: str) -> str:
    if rule_id == "geometry_body.invalid_statement":
        return "geometry_slot.invalid_statement"
    if rule_id == "geometry_body.result_symbol_invalid":
        return "geometry_slot.result_symbol_invalid"
    return rule_id


def _invalid_slot(
    slot_id: int,
    spec: dict[str, Any],
    rule_id: str,
    message: str,
    statements: Any,
    result_symbol: Any,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "slot_id": slot_id,
        "function_id": str(spec.get("function_id") or ""),
        "rule_id": rule_id,
        "message": message,
        "statements": statements,
        "result_symbol": result_symbol,
        "details": details or {},
    }


def _slot_hash(*, slot_id: int, function_id: str, statements: list[str], result_symbol: str) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "slot_id": slot_id,
                "function_id": function_id,
                "statements": statements,
                "result_symbol": result_symbol,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
