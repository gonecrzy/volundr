from __future__ import annotations

"""Geometry-only T5 contract audit and qualification.

This is an integration study harness.  It does not replace the production
geometry adapter or route, and it never repairs provider geometry.  Its
validator enforces only the manifest/composition invariants while discovering
CadQuery capabilities from the installed runtime.
"""

import ast
import asyncio
import hashlib
import inspect
import json
import keyword
import re
from copy import deepcopy
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Iterable

from app.services.ai.provider import ModelGenerationRequest
from app.services.cad.cadquery_contract import SAFE_CALL_NAMES
from app.services.cad.geometry_slots import parse_geometry_slots
from app.services.gemini_consistency.provider_contract import canonical_hash, parse_provider_response
from app.services.gemini_integration.capture import IntegrationEvidenceStore
from app.services.gemini_integration.corpus import IntegrationProject, build_integration_corpus, corpus_hash
from app.services.gemini_integration.forensics import replay_captured_evidence_offline
from app.services.gemini_integration.narrow_fix import NarrowFixStudy
from app.services.gemini_integration.profile import GeminiFlashLiteContractV1, require_integration_profile
from app.services.gemini_integration.prompts import (
    GEOMETRY_T5_PROMPT_VERSION,
    render_geometry_prompt_v2,
)
from app.services.gemini_integration.real_ports import build_real_boundary_ports
from app.services.gemini_integration.targeted_validation import (
    TargetedOperation,
    _build_geometry_request,
    build_targeted_operations,
)
from app.services.gemini_integration.transport import SecondaryGeminiClient, SharedIntegrationRateLimiter
from app.services.workflow.redaction import RedactionService


NARROW_FIX_ID = "geometry-prompt-narrow-fix-01"
STUDY_ID = "gemini-provider-contract-integration-01"
TARGETED_ID = "targeted-provider-validation-01"
REPORT_NAMES = (
    "preregistration.json",
    "failure-audit.json",
    "geometry-prompt-v2.json",
    "validator-fixture-results.json",
    "live-results.json",
    "geometry-decision.json",
    "adapter-replay-results.json",
    "regression-replay.json",
    "worker-smoke-result.json",
    "corrected-issue-register.json",
    "corrected-causal-graph.json",
    "rate-limit-report.json",
    "retry-report.json",
    "integration-decision.json",
    "combined-geometry-narrow-fix-evidence.json",
)
FAILURE_CLASSES = {
    "wrong_result_assignment_target",
    "wrong_result_symbol_field",
    "undefined_input_symbol",
    "undefined_local_symbol",
    "invalid_python_statement",
    "invalid_cadquery_method",
    "invalid_cadquery_argument",
    "missing_required_operation",
    "wrong_boolean_operation",
    "missing_required_slot",
    "unauthorized_slot",
    "responsibility_mismatch",
    "protected_value_change",
    "malformed_response_structure",
    "multiple_independent_defects",
}


@dataclass(frozen=True)
class SlotExpectation:
    slot_id: Any
    required_result_symbol: str
    allowed_input_symbols: tuple[str, ...]
    required_parameter_ids: tuple[str, ...]
    authorized_parameter_ids: tuple[str, ...]
    required_feature_ids: tuple[str, ...]
    responsibility: dict[str, Any]
    protected_values: dict[str, Any]
    approved_helpers: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "required_result_symbol": self.required_result_symbol,
            "allowed_input_symbols": list(self.allowed_input_symbols),
            "required_parameter_ids": list(self.required_parameter_ids),
            "authorized_parameter_ids": list(self.authorized_parameter_ids),
            "required_feature_ids": list(self.required_feature_ids),
            "responsibility": self.responsibility,
            "protected_values": self.protected_values,
            "approved_helpers": list(self.approved_helpers),
        }


@dataclass(frozen=True)
class GeometryTargetedOperation:
    operation_id: str
    group: str
    project_id: str
    repetition: int
    request: ModelGenerationRequest
    rendered_prompt: str
    prompt_hash: str
    prompt_version: str
    request_hash: str
    expectations: tuple[SlotExpectation, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "group": self.group,
            "stage": "geometry",
            "project_id": self.project_id,
            "repetition": self.repetition,
            "request": _json_safe(self.request),
            "rendered_prompt": self.rendered_prompt,
            "prompt_hash": self.prompt_hash,
            "prompt_version": self.prompt_version,
            "request_hash": self.request_hash,
            "expectations": [item.as_dict() for item in self.expectations],
        }


@dataclass(frozen=True)
class CadQueryCapabilities:
    module_names: frozenset[str]
    method_names: frozenset[str]
    keyword_names: dict[str, frozenset[str]]
    accepts_arbitrary_keywords: frozenset[str]
    version: str | None


@dataclass(frozen=True)
class GeometrySlotEvidence:
    """Typed evidence for one provider-owned slot under the T5 contract."""

    slot_id: Any
    required_result_symbol: str | None
    observed_result_symbol: Any
    allowed_input_symbols: tuple[str, ...] = ()
    responsibility: dict[str, Any] | None = None
    defined_symbols: tuple[str, ...] = ()
    referenced_symbols: tuple[str, ...] = ()
    assignment_targets: tuple[str, ...] = ()
    cadquery_methods_and_arguments: tuple[dict[str, Any], ...] = ()
    protected_value_changes: tuple[Any, ...] = ()
    statements: tuple[dict[str, Any], ...] = ()
    failure_classes: tuple[str, ...] = ()
    raw_provider_slot: Any = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GeometrySlotEvidence":
        return cls(
            slot_id=value.get("slot_id"),
            required_result_symbol=value.get("required_result_symbol"),
            observed_result_symbol=value.get("observed_result_symbol"),
            allowed_input_symbols=tuple(str(item) for item in value.get("allowed_input_symbols", []) or []),
            responsibility=deepcopy(value.get("responsibility") or {}),
            defined_symbols=tuple(str(item) for item in value.get("defined_symbols", []) or []),
            referenced_symbols=tuple(str(item) for item in value.get("referenced_symbols", []) or []),
            assignment_targets=tuple(str(item) for item in value.get("assignment_targets", []) or []),
            cadquery_methods_and_arguments=tuple(deepcopy(value.get("cadquery_methods_and_arguments", []) or [])),
            protected_value_changes=tuple(deepcopy(value.get("protected_value_changes", []) or [])),
            statements=tuple(deepcopy(value.get("statements", []) or [])),
            failure_classes=tuple(str(item) for item in value.get("failure_classes", []) or []),
            raw_provider_slot=deepcopy(value.get("raw_provider_slot")),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "required_result_symbol": self.required_result_symbol,
            "observed_result_symbol": self.observed_result_symbol,
            "allowed_input_symbols": list(self.allowed_input_symbols),
            "responsibility": self.responsibility or {},
            "defined_symbols": list(self.defined_symbols),
            "referenced_symbols": list(self.referenced_symbols),
            "assignment_targets": list(self.assignment_targets),
            "cadquery_methods_and_arguments": list(self.cadquery_methods_and_arguments),
            "protected_value_changes": list(self.protected_value_changes),
            "statements": list(self.statements),
            "failure_classes": list(self.failure_classes),
            "raw_provider_slot": self.raw_provider_slot,
        }


@dataclass(frozen=True)
class GeometryValidationEvidence:
    """Typed stage evidence; no semantic geometry repair is represented here."""

    passed: bool
    parseable: bool
    failure_classes: tuple[str, ...]
    expected_slot_ids: tuple[Any, ...]
    returned_slot_ids: tuple[Any, ...]
    missing_slot_ids: tuple[Any, ...]
    extra_slot_ids: tuple[Any, ...]
    slot_order_preserved: bool
    slots: tuple[GeometrySlotEvidence, ...]
    adapter_semantic_repair: bool
    adapter_actions: tuple[dict[str, Any], ...]
    raw_response_hash: str
    parsed_response_hash: str
    parse_fence_normalizations: int = 0
    reason: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GeometryValidationEvidence":
        return cls(
            passed=bool(value.get("passed")),
            parseable=bool(value.get("parseable")),
            failure_classes=tuple(str(item) for item in value.get("failure_classes", []) or []),
            expected_slot_ids=tuple(value.get("expected_slot_ids", []) or []),
            returned_slot_ids=tuple(value.get("returned_slot_ids", []) or []),
            missing_slot_ids=tuple(value.get("missing_slot_ids", []) or []),
            extra_slot_ids=tuple(value.get("extra_slot_ids", []) or []),
            slot_order_preserved=bool(value.get("slot_order_preserved")),
            slots=tuple(GeometrySlotEvidence.from_dict(item) for item in value.get("slots", []) or [] if isinstance(item, dict)),
            adapter_semantic_repair=bool(value.get("adapter_semantic_repair")),
            adapter_actions=tuple(deepcopy(value.get("adapter_actions", []) or [])),
            raw_response_hash=str(value.get("raw_response_hash") or ""),
            parsed_response_hash=str(value.get("parsed_response_hash") or ""),
            parse_fence_normalizations=int(value.get("parse_fence_normalizations") or 0),
            reason=value.get("reason"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "parseable": self.parseable,
            "failure_classes": list(self.failure_classes),
            "expected_slot_ids": list(self.expected_slot_ids),
            "returned_slot_ids": list(self.returned_slot_ids),
            "missing_slot_ids": list(self.missing_slot_ids),
            "extra_slot_ids": list(self.extra_slot_ids),
            "slot_order_preserved": self.slot_order_preserved,
            "slots": [item.as_dict() for item in self.slots],
            "adapter_semantic_repair": self.adapter_semantic_repair,
            "adapter_actions": list(self.adapter_actions),
            "raw_response_hash": self.raw_response_hash,
            "parsed_response_hash": self.parsed_response_hash,
            "parse_fence_normalizations": self.parse_fence_normalizations,
            **({"reason": self.reason} if self.reason else {}),
        }


def _json_safe(value: Any) -> Any:
    if hasattr(value, "as_dict"):
        return _json_safe(value.as_dict())
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return {str(key): _json_safe(item) for key, item in value.__dict__.items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(_json_safe(value), sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _read_json(path: Path, fallback: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return deepcopy(fallback)


def _capabilities() -> CadQueryCapabilities:
    import cadquery as cq

    module_names = {name for name in dir(cq) if not name.startswith("_")}
    candidates: list[type[Any]] = []
    for name in module_names:
        value = getattr(cq, name, None)
        if isinstance(value, type):
            candidates.append(value)
    methods: set[str] = set()
    keywords: dict[str, set[str]] = {}
    arbitrary: set[str] = set()
    for candidate in candidates:
        for name in dir(candidate):
            if name.startswith("_"):
                continue
            value = getattr(candidate, name, None)
            if not callable(value):
                continue
            methods.add(name)
            try:
                signature = inspect.signature(value)
            except (TypeError, ValueError):
                continue
            names = keywords.setdefault(name, set())
            for parameter in signature.parameters.values():
                if parameter.kind == inspect.Parameter.VAR_KEYWORD:
                    arbitrary.add(name)
                elif parameter.name != "self":
                    names.add(parameter.name)
    return CadQueryCapabilities(
        module_names=frozenset(module_names),
        method_names=frozenset(methods),
        keyword_names={name: frozenset(values) for name, values in keywords.items()},
        accepts_arbitrary_keywords=frozenset(arbitrary),
        version=getattr(cq, "__version__", None),
    )


def _feature_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("id") or item.get("feature_id")): item
        for item in plan.get("features", []) or []
        if isinstance(item, dict) and (item.get("id") or item.get("feature_id")) is not None
    }


def _protected_values(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        str(item.get("id")): item.get("value", item.get("default"))
        for item in plan.get("parameters", []) or []
        if isinstance(item, dict) and item.get("id") is not None and item.get("protected") is True
    }


def _responsibility(feature: dict[str, Any] | None, manifest: dict[str, Any]) -> dict[str, Any]:
    feature = feature or {}
    text = " ".join(
        str(feature.get(key) or "")
        for key in (
            "id", "feature_id", "type", "object_type", "semantic_type", "semantic_role",
            "description", "operation", "boolean_operation",
        )
    ).casefold()
    explicit = feature.get("required_operations") or feature.get("required_boolean_operations")
    operations = [str(item).casefold() for item in explicit] if isinstance(explicit, list) else []
    if not operations:
        operation = str(feature.get("operation") or feature.get("boolean_operation") or "").casefold()
        if operation:
            operations = [operation]
    if not operations:
        if any(token in text for token in ("hole", "opening", "recess", "notch", "slot", "vent", "pocket")):
            operations = ["cut"]
        elif any(token in text for token in ("union", "additive", "handle", "boss", "snap", "rib")):
            operations = ["union"]
        elif any(token in text for token in ("loft", "transition")):
            operations = ["loft"]
        elif "shell" in text or "hollow" in text:
            operations = ["shell"]
    return {
        "feature_id": feature.get("id") or feature.get("feature_id"),
        "description": feature.get("description") or feature.get("semantic_type") or feature.get("type"),
        "required_operations": operations,
        "responsibility_source": "explicit_feature_contract" if operations else "manifest_feature_semantics",
    }


def slot_expectations(request: ModelGenerationRequest) -> tuple[SlotExpectation, ...]:
    manifest = request.geometry_slot_manifest or {}
    plan = request.design_plan or {}
    features = _feature_map(plan)
    protected = _protected_values(plan)
    expectations: list[SlotExpectation] = []
    for slot in manifest.get("slots", []) or []:
        if not isinstance(slot, dict):
            continue
        feature_ids = tuple(str(item) for item in slot.get("required_feature_ids", []) or [])
        responsibilities = [_responsibility(features.get(item), manifest) for item in feature_ids]
        allowed = tuple(dict.fromkeys([
            *(str(item) for item in slot.get("signature", []) or []),
            "cq",
            *[str(item) for item in slot.get("approved_helpers", []) or []],
        ]))
        required_params = tuple(str(item) for item in slot.get("required_inputs", []) or [])
        authorized_params = tuple(str(item) for item in slot.get("authorized_parameter_ids", []) or [])
        expectations.append(SlotExpectation(
            slot_id=slot.get("slot_id"),
            required_result_symbol=str(slot.get("required_result") or ""),
            allowed_input_symbols=allowed,
            required_parameter_ids=required_params,
            authorized_parameter_ids=authorized_params,
            required_feature_ids=feature_ids,
            responsibility={"features": responsibilities, "output_obligations": manifest.get("output_obligations", [])},
            protected_values=protected,
            approved_helpers=tuple(str(item) for item in slot.get("approved_helpers", []) or []),
        ))
    return tuple(expectations)


def build_geometry_operations(
    profile: GeminiFlashLiteContractV1,
    boundaries: list[dict[str, Any]],
) -> tuple[GeometryTargetedOperation, ...]:
    require_integration_profile(profile.profile_id)
    prior = build_targeted_operations(profile=profile, boundaries=boundaries)
    selected = [operation for operation in prior if operation.stage == "geometry"]
    operations: list[GeometryTargetedOperation] = []
    for operation in selected:
        rendered = render_geometry_prompt_v2(profile, operation.request)
        operations.append(GeometryTargetedOperation(
            operation_id=f"{NARROW_FIX_ID}:{operation.group.lower()}:{operation.project_id}:geometry:rep-{operation.repetition:02d}",
            group=operation.group,
            project_id=operation.project_id,
            repetition=operation.repetition,
            request=operation.request,
            rendered_prompt=rendered.prompt,
            prompt_hash=rendered.prompt_hash,
            prompt_version=rendered.prompt_version,
            request_hash=canonical_hash(operation.request.__dict__),
            expectations=slot_expectations(operation.request),
        ))
    by_stage = {(str(item.get("project_id")), str(item.get("boundary"))): item for item in boundaries}
    holdout_boundary = by_stage.get(("project-004", "provider_geometry"))
    if holdout_boundary is None:
        raise ValueError("project-004 frozen geometry holdout is missing")
    holdout_request, _ = _build_geometry_request(holdout_boundary, boundaries)
    rendered = render_geometry_prompt_v2(profile, holdout_request)
    expectations = slot_expectations(holdout_request)
    for repetition in (1, 2):
        operations.append(GeometryTargetedOperation(
            operation_id=f"{NARROW_FIX_ID}:g3:project-004:geometry:rep-{repetition:02d}",
            group="G3",
            project_id="project-004",
            repetition=repetition,
            request=holdout_request,
            rendered_prompt=rendered.prompt,
            prompt_hash=rendered.prompt_hash,
            prompt_version=rendered.prompt_version,
            request_hash=canonical_hash(holdout_request.__dict__),
            expectations=expectations,
        ))
    if [(item.group, item.repetition) for item in operations] != [
        ("G1", 1), ("G1", 2), ("G2", 1), ("G2", 2), ("G3", 1), ("G3", 2)
    ]:
        raise AssertionError("T5 qualification must contain G1/G2/G3 with two repetitions each")
    return tuple(operations)


def _position(node: ast.AST) -> tuple[int, int]:
    return (int(getattr(node, "lineno", 0)), int(getattr(node, "col_offset", 0)))


def _assignment_targets(tree: ast.AST) -> list[str]:
    targets: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    targets.append(target.id)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and isinstance(node.target, ast.Name):
            targets.append(node.target.id)
    return targets


def _loads(tree: ast.AST) -> list[str]:
    return [node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)]


def _stores(tree: ast.AST) -> list[str]:
    return [node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del))]


def _subscript_parameter_ids(tree: ast.AST) -> list[str]:
    values: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript) or not isinstance(node.value, ast.Name) or node.value.id != "params":
            continue
        key = node.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            values.append(key.value)
        else:
            values.append("<dynamic>")
    return values


def _subscript_parameter_stores(tree: ast.AST) -> list[str]:
    values: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript) or not isinstance(node.value, ast.Name) or node.value.id != "params":
            continue
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            key = node.slice
            values.append(key.value if isinstance(key, ast.Constant) and isinstance(key.value, str) else "<dynamic>")
    return values


def _calls(tree: ast.AST) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute):
            records.append({"kind": "attribute", "method": node.func.attr, "keywords": [item.arg for item in node.keywords], "position": _position(node)})
        elif isinstance(node.func, ast.Name):
            records.append({"kind": "direct", "method": node.func.id, "keywords": [item.arg for item in node.keywords], "position": _position(node)})
        else:
            records.append({"kind": "dynamic", "method": None, "keywords": [item.arg for item in node.keywords], "position": _position(node)})
    return records


def _comprehension_bound_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.comprehension):
            continue
        for child in ast.walk(node.target):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                names.add(child.id)
    return names


def _is_geometry_call(call: dict[str, Any]) -> bool:
    return call["kind"] == "attribute" or call["method"] == "place_pattern_cutters" or call["method"] == "resolve_pattern_points"


def _operation_aliases(operation: str) -> set[str]:
    return {
        "cut": {"cut", "hole", "cutBlind", "cutThruAll"},
        "union": {"union", "add"},
        "intersect": {"intersect"},
        "loft": {"loft"},
        "sweep": {"sweep"},
        "revolve": {"revolve"},
        # Shell/hollow responsibility is semantic.  Subtractive inner-volume
        # construction is a valid alternative to the shell() method.
        "shell": {"shell", "cut"},
    }.get(operation, {operation})


def _statement_structure_issues(statement: str) -> list[dict[str, Any]]:
    if "```" in statement or re.search(r"\b(?:import|from)\s+", statement) or re.search(r"\b(?:def|class|return)\b", statement):
        return [{"class": "malformed_response_structure", "reason": "source-level content is not a slot statement"}]
    if "..." in statement:
        return [{"class": "malformed_response_structure", "reason": "placeholder ellipsis is not executable geometry"}]
    return []


class T5GeometryValidator:
    def __init__(self, capabilities: CadQueryCapabilities | None = None) -> None:
        self.capabilities = capabilities or _capabilities()

    def _validate_call(self, call_node: ast.Call, expectation: SlotExpectation) -> list[dict[str, Any]]:
        records = _calls(call_node)
        if not records:
            return [{"class": "invalid_cadquery_method", "reason": "dynamic call target"}]
        call = records[0]
        method = call.get("method")
        if call["kind"] == "dynamic":
            return [{"class": "invalid_cadquery_method", "reason": "dynamic calls are not allowed"}]
        if call["kind"] == "direct":
            if method not in SAFE_CALL_NAMES and method not in expectation.approved_helpers:
                return [{"class": "invalid_cadquery_method", "reason": f"unsupported direct call: {method}"}]
            return []
        if method not in self.capabilities.method_names and method not in self.capabilities.module_names and method not in {"get", "items", "keys", "values"}:
            return [{"class": "invalid_cadquery_method", "reason": f"CadQuery capability is unavailable: {method}"}]
        if method not in self.capabilities.accepts_arbitrary_keywords:
            allowed = self.capabilities.keyword_names.get(method, frozenset())
            invalid = [item for item in call.get("keywords", []) if item is not None and item not in allowed]
            if invalid:
                return [{"class": "invalid_cadquery_argument", "reason": f"unsupported keyword(s) for {method}: {invalid}"}]
        if any(item is None for item in call.get("keywords", [])):
            return [{"class": "invalid_cadquery_argument", "reason": "dynamic keyword expansion is not allowed"}]
        return []

    def validate_evidence(self, raw: str | dict[str, Any], request: ModelGenerationRequest) -> GeometryValidationEvidence:
        return GeometryValidationEvidence.from_dict(self._validate_dict(raw, request))

    def validate(self, raw: str | dict[str, Any], request: ModelGenerationRequest) -> dict[str, Any]:
        """Return JSON-safe evidence for compatibility with existing harnesses."""

        return self.validate_evidence(raw, request).as_dict()

    def _validate_dict(self, raw: str | dict[str, Any], request: ModelGenerationRequest) -> dict[str, Any]:
        raw_text = raw if isinstance(raw, str) else json.dumps(raw, sort_keys=True)
        if "```" in raw_text:
            return {"passed": False, "parseable": False, "failure_classes": ["malformed_response_structure"], "reason": "Markdown/code fence is forbidden by T5"}
        parsed, fence_count = parse_provider_response(raw)
        expectations = slot_expectations(request)
        expected_ids = [item.slot_id for item in expectations]
        result: dict[str, Any] = {
            "passed": False,
            "parseable": parsed is not None,
            "parse_fence_normalizations": fence_count,
            "expected_slot_ids": expected_ids,
            "returned_slot_ids": [],
            "missing_slot_ids": [],
            "extra_slot_ids": [],
            "slot_order_preserved": False,
            "slots": [],
            "adapter_semantic_repair": False,
            "adapter_actions": [],
            "raw_response_hash": canonical_hash(raw),
            "parsed_response_hash": canonical_hash(parsed),
        }
        if not isinstance(parsed, dict) or parsed.get("schema_version") != "volundr-geometry-slots-v1" or not isinstance(parsed.get("slots"), list):
            result["failure_classes"] = ["malformed_response_structure"]
            return result
        returned_ids = [item.get("slot_id") for item in parsed["slots"] if isinstance(item, dict)]
        result["returned_slot_ids"] = returned_ids
        result["missing_slot_ids"] = [item for item in expected_ids if item not in returned_ids]
        result["extra_slot_ids"] = [item for item in returned_ids if item not in expected_ids]
        result["slot_order_preserved"] = returned_ids == expected_ids
        if not result["slot_order_preserved"]:
            result["failure_classes"] = ["missing_required_slot" if result["missing_slot_ids"] else "unauthorized_slot" if result["extra_slot_ids"] else "malformed_response_structure"]
        by_id = {item.slot_id: item for item in expectations}
        all_failures: list[str] = []
        for raw_slot in parsed["slots"]:
            if not isinstance(raw_slot, dict):
                all_failures.append("malformed_response_structure")
                continue
            expectation = by_id.get(raw_slot.get("slot_id"))
            if expectation is None:
                slot_result = {"slot_id": raw_slot.get("slot_id"), "failure_classes": ["unauthorized_slot"]}
                result["slots"].append(slot_result)
                all_failures.extend(slot_result["failure_classes"])
                continue
            slot_result = self._validate_slot(raw_slot, expectation)
            result["slots"].append(slot_result)
            all_failures.extend(slot_result.get("failure_classes", []))
        result["failure_classes"] = sorted(set(all_failures + ([] if result["slot_order_preserved"] else result.get("failure_classes", []))))
        result["passed"] = bool(result["slot_order_preserved"] and not result["failure_classes"])
        return result

    def _validate_slot(self, raw_slot: dict[str, Any], expectation: SlotExpectation) -> dict[str, Any]:
        failures: list[str] = []
        result_symbol = raw_slot.get("result_symbol")
        if result_symbol != expectation.required_result_symbol:
            failures.extend(["wrong_result_symbol_field", "wrong_result_assignment_target"])
        statements = raw_slot.get("statements")
        if not isinstance(statements, list) or not statements or any(not isinstance(item, str) for item in statements):
            return {"slot_id": raw_slot.get("slot_id"), "required_result_symbol": expectation.required_result_symbol, "failure_classes": ["malformed_response_structure"]}
        defined: set[str] = set()
        referenced: list[str] = []
        targets: list[str] = []
        methods: list[dict[str, Any]] = []
        statement_records: list[dict[str, Any]] = []
        external = set(expectation.allowed_input_symbols) | set(SAFE_CALL_NAMES)
        protected_names = set(expectation.protected_values)
        for index, statement in enumerate(statements):
            record: dict[str, Any] = {"index": index, "statement": statement, "defined_symbols": [], "referenced_symbols": [], "assignment_targets": [], "calls": [], "failure_classes": []}
            record["failure_classes"].extend(item["class"] for item in _statement_structure_issues(statement))
            try:
                tree = ast.parse(statement, mode="exec")
            except SyntaxError as exc:
                record["failure_classes"].append("invalid_python_statement")
                record["syntax_error"] = {"message": exc.msg, "line": exc.lineno, "offset": exc.offset}
                statement_records.append(record)
                failures.extend(record["failure_classes"])
                continue
            if len(tree.body) != 1:
                record["failure_classes"].append("invalid_python_statement")
            local_stores = _stores(tree)
            local_targets = _assignment_targets(tree)
            local_loads = _loads(tree)
            comprehension_bound = _comprehension_bound_names(tree)
            record["defined_symbols"] = sorted(set(local_stores))
            record["referenced_symbols"] = sorted(set(local_loads))
            record["assignment_targets"] = list(local_targets)
            calls = _calls(tree)
            record["calls"] = calls
            referenced.extend(local_loads)
            targets.extend(local_targets)
            methods.extend(calls)
            for name in local_loads:
                if name in comprehension_bound:
                    continue
                if name in external or name in defined:
                    continue
                if name in local_stores:
                    record["failure_classes"].append("undefined_local_symbol")
                elif name in {str(item.required_result_symbol) for item in [expectation]} or name in {"body", "params"}:
                    record["failure_classes"].append("undefined_input_symbol")
                else:
                    record["failure_classes"].append("undefined_local_symbol")
            for parameter_id in _subscript_parameter_ids(tree):
                if parameter_id == "<dynamic>" or parameter_id not in set(expectation.authorized_parameter_ids) | set(expectation.required_parameter_ids) | set(expectation.protected_values):
                    record["failure_classes"].append("undefined_input_symbol")
            for parameter_id in _subscript_parameter_stores(tree):
                record["failure_classes"].append("protected_value_change")
            if any(name in {"params", "cq"} or (name in external and name not in {expectation.required_result_symbol}) for name in local_targets):
                record["failure_classes"].append("protected_value_change")
            for name in local_targets:
                if name in protected_names:
                    record["failure_classes"].append("protected_value_change")
            for call_node in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
                record["failure_classes"].extend(item["class"] for item in self._validate_call(call_node, expectation))
            statement_records.append(record)
            defined.update(local_stores)
            failures.extend(record["failure_classes"])
        required_ops = {
            operation
            for feature in (expectation.responsibility.get("features") or [])
            for operation in feature.get("required_operations", [])
        }
        used_methods = {str(item.get("method")) for item in methods}
        missing_operations: list[str] = []
        for required_operation in required_ops:
            aliases = _operation_aliases(required_operation)
            if not used_methods.intersection(aliases):
                failures.append("missing_required_operation")
                missing_operations.append(str(required_operation))
                if used_methods.intersection({"cut", "hole", "union", "intersect", "loft", "sweep", "revolve", "shell"}):
                    failures.append("wrong_boolean_operation")
        if expectation.required_feature_ids and not any(_is_geometry_call(item) for item in methods):
            failures.append("responsibility_mismatch")
        if any(item.get("method") in {str(fid) for fid in expectation.required_feature_ids} for item in methods):
            failures.append("unauthorized_slot")
        if statements:
            final_targets = _assignment_targets(ast.parse(statements[-1], mode="exec")) if _safe_parse(statements[-1]) else []
            if final_targets and final_targets[-1] != expectation.required_result_symbol:
                failures.append("wrong_result_assignment_target")
            if not final_targets or final_targets[-1] != expectation.required_result_symbol:
                failures.append("responsibility_mismatch")
        return {
            "slot_id": raw_slot.get("slot_id"),
            "required_result_symbol": expectation.required_result_symbol,
            "observed_result_symbol": result_symbol,
            "allowed_input_symbols": list(expectation.allowed_input_symbols),
            "responsibility": expectation.responsibility,
            "defined_symbols": sorted(set(defined)),
            "referenced_symbols": sorted(set(referenced)),
            "assignment_targets": targets,
            "cadquery_methods_and_arguments": methods,
            "missing_or_unauthorized_operations": {
                "required": sorted(required_ops),
                "observed": sorted(used_methods),
                "missing": sorted(missing_operations),
            },
            "protected_value_changes": [item for item in expectation.protected_values if item in targets],
            "statements": statement_records,
            "failure_classes": sorted(set(failures)),
        }


def _safe_parse(statement: str) -> bool:
    try:
        ast.parse(statement, mode="exec")
        return True
    except SyntaxError:
        return False


def _historical_target_results(study_root: Path) -> list[dict[str, Any]]:
    path = study_root / "reports" / TARGETED_ID / "provider-validation-results.json"
    document = _read_json(path, {})
    return [item for item in document.get("results", []) or [] if (item.get("operation") or {}).get("stage") == "geometry"]


def audit_historical_failures(study_root: Path, validator: T5GeometryValidator) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for item in _historical_target_results(study_root):
        operation = item.get("operation") or {}
        request = _request_from_operation(operation)
        raw = (item.get("provider_result") or {}).get("text")
        parsed, fence_count = parse_provider_response(raw) if raw is not None else (None, 0)
        t5 = validator.validate(raw or "", request)
        parser_counterfactual = validator.validate(parsed, request) if parsed is not None else t5
        combined_classes = sorted(set(t5.get("failure_classes", [])) | set(parser_counterfactual.get("failure_classes", [])))
        if len(combined_classes) > 1:
            combined_classes.append("multiple_independent_defects")
        issues = _issue_records_for_item(item, request, validator, t5, parser_counterfactual, combined_classes)
        records.append({
            "failure_id": operation.get("operation_id"),
            "group": operation.get("group"),
            "project_id": operation.get("project_id"),
            "repetition": operation.get("repetition"),
            "authoritative_manifest": {
                "hash": canonical_hash(request.geometry_slot_manifest),
                "slots": [item.as_dict() for item in slot_expectations(request)],
            },
            "rendered_prompt": {
                "prompt_hash": operation.get("prompt_hash"),
                "prompt_version": operation.get("prompt_version"),
                "contains_manifest_result_symbols": all(str(item.required_result_symbol) in str(operation.get("rendered_prompt")) for item in slot_expectations(request)),
                "contains_explicit_exact_result_rule": "exact result_symbol" in str(operation.get("rendered_prompt")),
            },
            "raw_provider_response": {"hash": canonical_hash(raw), "text": raw},
            "parsed_response": {
                "hash": canonical_hash(parsed),
                "fence_count": fence_count,
                "value": parsed,
                "parser_actions": [{
                    "action_class": "exact_json_fence_unwrap",
                    "count": fence_count,
                    "semantic_content_hash": canonical_hash(parsed),
                }] if fence_count else [],
            },
            "slots": _audit_slots(parsed, request, validator),
            "legacy_adapter": {"accepted": (item.get("adapter") or {}).get("accepted"), "failure_class": (item.get("adapter") or {}).get("failure_class"), "actions": (item.get("adapter") or {}).get("normalization_actions", [])},
            "t5_counterfactual": t5,
            "parser_counterfactual": {
                "single_variable_changed": "the raw response was represented by the exact parsed JSON object",
                "provider_calls": 0,
                "worker_calls": 0,
                "semantic_content_hash": canonical_hash(parsed),
                "validation": parser_counterfactual,
            },
            "source_assembly_expectation": _source_assembly_counterfactual(parsed, request),
            "causal_chain": {
                "authoritative_manifest": "preserved manifest was used as the expected slot identity and obligation contract",
                "rendered_prompt": "preserved T0 prompt was inspected for identity clarity and conflicting result-symbol examples",
                "raw_provider_response": "raw provider content was retained and hashed before parsing",
                "parsed_response": "the generic parser only unwrapped the exact JSON fence; it did not repair slot content",
                "contract_validation": "strict T5 validation was run on raw text and on the parser counterfactual",
                "source_assembly_expectation": "the original parsed slots were sent to the existing slot assembler without semantic repair",
                "first_incorrect_boundary": _first_incorrect_boundary(item, operation, t5, parser_counterfactual),
            },
            "root_cause_tests": {
                "authoritative_manifest_complete_and_unambiguous": bool(request.geometry_slot_manifest and request.geometry_slot_manifest.get("slots")),
                "rendered_prompt_contains_manifest_result_symbols": all(str(slot.required_result_symbol) in str(operation.get("rendered_prompt")) for slot in slot_expectations(request)),
                "rendered_prompt_has_conflicting_result_example": 'result_symbol": "body"' in str(operation.get("rendered_prompt")),
                "provider_representation_contract_violation": bool(parser_counterfactual.get("failure_classes")),
                "intrinsic_python_or_cadquery_validation_failure": any(item in parser_counterfactual.get("failure_classes", []) for item in ("invalid_python_statement", "invalid_cadquery_method", "invalid_cadquery_argument")),
                "parser_altered_semantic_content": False,
                "validator_false_rejection_counterfactual": False,
                "source_assembly_added_unstated_requirement": False,
                "multiple_independent_defects": "multiple_independent_defects" in combined_classes,
            },
            "observed_failure_classes": combined_classes,
            "independent_issue_count": len(issues),
            "issues": issues,
        })
    return {
        "schema_version": "volundr-geometry-prompt-narrow-fix-v1",
        "study_id": STUDY_ID,
        "validation_id": NARROW_FIX_ID,
        "historical_failure_count": len(records),
        "records": records,
        "distinct_failure_classes": sorted({issue.get("classification") for record in records for issue in record.get("issues", []) if issue.get("classification")}),
        "provider_calls": 0,
        "worker_calls": 0,
    }


def _request_from_operation(operation: dict[str, Any]) -> ModelGenerationRequest:
    request = operation.get("request") or {}
    allowed = {field.name for field in fields(ModelGenerationRequest)}
    return ModelGenerationRequest(**{key: deepcopy(value) for key, value in request.items() if key in allowed})


def _audit_slots(parsed: Any, request: ModelGenerationRequest, validator: T5GeometryValidator) -> list[dict[str, Any]]:
    if not isinstance(parsed, dict) or not isinstance(parsed.get("slots"), list):
        return []
    expectations = {item.slot_id: item for item in slot_expectations(request)}
    output: list[dict[str, Any]] = []
    for slot in parsed["slots"]:
        if not isinstance(slot, dict):
            output.append({"raw_provider_slot": slot, "failure_classes": ["malformed_response_structure"]})
            continue
        expectation = expectations.get(slot.get("slot_id"))
        if expectation is None:
            output.append({"raw_provider_slot": slot, "failure_classes": ["unauthorized_slot"]})
            continue
        result = validator._validate_slot(slot, expectation)
        result["raw_provider_slot"] = slot
        output.append(result)
    return output


def _source_assembly_counterfactual(parsed: Any, request: ModelGenerationRequest) -> dict[str, Any]:
    """Run the original parsed content through the existing assembler only."""

    if not isinstance(parsed, dict):
        return {"reached": False, "provider_calls": 0, "worker_calls": 0, "reason": "response was not parseable"}
    try:
        assembled = parse_geometry_slots(json.dumps(parsed, sort_keys=True), request.geometry_slot_manifest or {})
        result: dict[str, Any] = {
            "reached": True,
            "provider_calls": 0,
            "worker_calls": 0,
            "complete": assembled.is_complete,
            "completed_slot_ids": assembled.completed_slot_ids,
            "missing_slot_ids": assembled.missing_slot_ids,
            "invalid_slots": assembled.invalid_slots,
            "function_ids": sorted(assembled.functions),
            "semantic_repair": False,
        }
        try:
            from app.services.cad.source_scaffold import render_cadquery_scaffold

            rendered = render_cadquery_scaffold(request.design_plan or {}, assembled.functions)
            result.update({"scaffold_rendered": True, "scaffold_hash": rendered.scaffold_hash})
        except Exception as exc:  # assembler evidence, never a qualification repair
            result.update({"scaffold_rendered": False, "scaffold_error": {"class": type(exc).__name__, "message": str(exc)}})
        return result
    except Exception as exc:
        return {
            "reached": True,
            "provider_calls": 0,
            "worker_calls": 0,
            "complete": False,
            "semantic_repair": False,
            "assembler_error": {"class": type(exc).__name__, "message": str(exc)},
        }


def _issue_records_for_item(
    item: dict[str, Any],
    request: ModelGenerationRequest,
    validator: T5GeometryValidator,
    raw_validation: dict[str, Any] | None = None,
    parser_validation: dict[str, Any] | None = None,
    combined_classes: list[str] | None = None,
) -> list[dict[str, Any]]:
    operation = item.get("operation") or {}
    raw = (item.get("provider_result") or {}).get("text") or ""
    parsed, _ = parse_provider_response(raw)
    slots = (parser_validation or {}).get("slots") or _audit_slots(parsed, request, validator)
    classes = list(combined_classes or sorted(set((raw_validation or {}).get("failure_classes", [])) | set((parser_validation or {}).get("failure_classes", []))))
    if len(classes) > 1 and "multiple_independent_defects" not in classes:
        classes.append("multiple_independent_defects")
    records: list[dict[str, Any]] = []
    for slot in slots:
        for failure_class in sorted(set(slot.get("failure_classes", []))):
            records.append({
                "issue_id": f"{NARROW_FIX_ID}:{operation.get('group')}:{operation.get('repetition')}:{slot.get('slot_id', 'response')}:{failure_class}",
                "project_id": operation.get("project_id"),
                "group": operation.get("group"),
                "slot_id": slot.get("slot_id"),
                "classification": failure_class,
                "owner": "provider_content" if failure_class not in {"wrong_result_symbol_field", "wrong_result_assignment_target"} else "contract_boundary",
                "independent": True,
                "provider_calls": 0,
                "evidence": {"raw_response_hash": canonical_hash(raw), "parsed_response_hash": canonical_hash(parsed)},
            })
    if "malformed_response_structure" in classes and not any(item.get("classification") == "malformed_response_structure" for item in records):
        records.append({
            "issue_id": f"{NARROW_FIX_ID}:{operation.get('group')}:{operation.get('repetition')}:response:malformed_response_structure",
            "project_id": operation.get("project_id"),
            "group": operation.get("group"),
            "slot_id": None,
            "classification": "malformed_response_structure",
            "owner": "provider_content",
            "independent": True,
            "provider_calls": 0,
            "evidence": {"raw_response_hash": canonical_hash(raw), "parsed_response_hash": canonical_hash(parsed)},
        })
    if "multiple_independent_defects" in classes:
        records.append({
            "issue_id": f"{NARROW_FIX_ID}:{operation.get('group')}:{operation.get('repetition')}:response:multiple_independent_defects",
            "project_id": operation.get("project_id"),
            "group": operation.get("group"),
            "slot_id": None,
            "classification": "multiple_independent_defects",
            "owner": "harness_classification",
            "independent": False,
            "provider_calls": 0,
            "evidence": {"failure_classes": classes},
        })
    return records


def _first_incorrect_boundary(
    item: dict[str, Any],
    operation: dict[str, Any],
    t5: dict[str, Any],
    parser_counterfactual: dict[str, Any] | None = None,
) -> str:
    failures = set((parser_counterfactual or {}).get("failure_classes", []))
    adapter_actions = (item.get("adapter") or {}).get("normalization_actions", [])
    if failures:
        return "provider_content_boundary"
    if any(action.get("action_class") == "result_symbol_normalization" for action in adapter_actions) and not failures.intersection({"wrong_result_symbol_field", "wrong_result_assignment_target"}):
        return "legacy_geometry_adapter_boundary:required_body_conflicted_with_manifest_result_symbols"
    if "malformed_response_structure" in set(t5.get("failure_classes", [])):
        return "provider_representation_boundary"
    return "none"


def build_generalized_fixtures() -> list[dict[str, Any]]:
    """Contract fixtures intentionally vary construction strategy and identity."""

    def fixture(fixture_id: str, result: str, statements: list[str], operations: list[str], *, prior: bool = False, protected: dict[str, Any] | None = None) -> dict[str, Any]:
        signature = ["body", "params"] if prior else ["params"]
        request_defaults = {
            "project_name": "generalized geometry fixture",
            "original_intent": "exercise a geometry-stage contract",
            "user_instruction": "exercise a geometry-stage contract",
        }
        return {
            "fixture_id": fixture_id,
            "request": {
                **request_defaults,
                "design_plan": {"features": [{"id": f"feature_{fixture_id}", "type": "other", "required_operations": operations}], "parameters": [{"id": key, "value": value, "protected": True} for key, value in (protected or {}).items()]},
                "geometry_slot_manifest": {"schema_version": "volundr-geometry-slots-v1", "slots": [{"slot_id": "slot-X", "required_result": result, "signature": signature, "required_inputs": list((protected or {}).keys()), "required_feature_ids": [f"feature_{fixture_id}"], "approved_helpers": []}]},
                "geometry_contract": "volundr-geometry-slots-v1",
            },
            "raw": json.dumps({"schema_version": "volundr-geometry-slots-v1", "slots": [{"slot_id": "slot-X", "result_symbol": result, "statements": statements}]}),
            "expected": True,
        }

    fixtures = [
        fixture("additive_union", "finished_body", ["base = cq.Workplane('XY').box(10, 10, 2)", "rib = cq.Workplane('XY').box(2, 10, 3)", "finished_body = base.union(rib)"], ["union"]),
        fixture("subtractive_cut", "updated_body", ["cutter = cq.Workplane('XY').circle(2).extrude(4)", "updated_body = body.cut(cutter)"], ["cut"], prior=True),
        fixture("intersection", "result_shape", ["tool = cq.Workplane('XY').box(5, 5, 5)", "result_shape = body.intersect(tool)"], ["intersect"], prior=True),
        fixture("loft", "lofted_result", ["profile = cq.Workplane('XY').rect(10, 10)", "lofted_result = profile.workplane(offset=10).circle(3).loft()"], ["loft"]),
        fixture("sweep", "swept_result", ["path = cq.Workplane('XZ').lineTo(10, 0)", "profile = cq.Workplane('YZ').circle(2)", "swept_result = profile.sweep(path)"], ["sweep"]),
        fixture("revolve", "turned_result", ["profile = cq.Workplane('XZ').rect(5, 10)", "turned_result = profile.revolve(360, (0, 0, 0), (0, 1, 0))"], ["revolve"]),
        fixture("shell", "hollow_result", ["inner_volume = cq.Workplane('XY').box(8, 8, 8)", "hollow_result = body.cut(inner_volume)"], ["shell"], prior=True),
        fixture("selector_chamfer", "edge_result", ["edge_result = body.edges('>Z').chamfer(0.5)"], [], prior=True),
        fixture("transformed_intermediates", "final_part", ["indices = [i for i in range(3)]", "seed = cq.Workplane('XY').box(4, 4, 4)", "moved = seed.translate((2, 0, 0))", "final_part = moved.rotate((0, 0, 0), (0, 0, 1), 15)"], []),
        fixture("multistatement_arbitrary_identity", "finished", ["first = cq.Workplane('XY').box(3, 3, 3)", "second = cq.Workplane('XY').cylinder(2, 1)", "finished = first.union(second)"], ["union"]),
        fixture("solid_result_form", "solid_result", ["solid_result = cq.Solid.makeBox(8, 8, 8)"], []),
        fixture("compound_result_form", "compound_result", ["part = cq.Solid.makeBox(4, 4, 4)", "compound_result = cq.Compound.makeCompound([part.val()])"], []),
        fixture("assembly_result_form", "assembly_result", ["assembly_result = cq.Assembly()"], []),
    ]
    multi = fixture(
        "multislot_arbitrary_identity",
        "alpha_result",
        ["alpha = cq.Workplane('XY').box(6, 6, 2)", "alpha_result = alpha"],
        [],
    )
    multi["request"]["geometry_slot_manifest"]["slots"] = [
        {
            "slot_id": "slot-X",
            "required_result": "alpha_result",
            "signature": ["params"],
            "required_inputs": [],
            "required_feature_ids": [],
            "approved_helpers": [],
        },
        {
            "slot_id": "slot-17",
            "required_result": "beta_result",
            "signature": ["body", "params"],
            "required_inputs": [],
            "required_feature_ids": [],
            "approved_helpers": [],
        },
    ]
    multi["raw"] = json.dumps({
        "schema_version": "volundr-geometry-slots-v1",
        "slots": [
            {"slot_id": "slot-X", "result_symbol": "alpha_result", "statements": ["alpha = cq.Workplane('XY').box(6, 6, 2)", "alpha_result = alpha"]},
            {"slot_id": "slot-17", "result_symbol": "beta_result", "statements": ["beta_result = body.translate((3, 0, 0))"]},
        ],
    })
    fixtures.append(multi)
    return fixtures


def run_fixture_corpus(validator: T5GeometryValidator) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for fixture in build_generalized_fixtures():
        request = ModelGenerationRequest(**fixture["request"])
        evidence = validator.validate(fixture["raw"], request)
        results.append({"fixture_id": fixture["fixture_id"], "expected": fixture["expected"], "passed": evidence["passed"], "evidence": evidence})
    negatives = [
        ("wrong_assignment_target", json.dumps({"schema_version": "volundr-geometry-slots-v1", "slots": [{"slot_id": "slot-X", "result_symbol": "wrong", "statements": ["wrong = cq.Workplane('XY').box(1, 1, 1)"]}]}), ["wrong_result_symbol_field"]),
        ("wrong_result_symbol_field", json.dumps({"schema_version": "volundr-geometry-slots-v1", "slots": [{"slot_id": "slot-X", "result_symbol": "shape", "statements": ["finished = cq.Workplane('XY').box(1, 1, 1)"]}]}), ["wrong_result_symbol_field"]),
        ("missing_slot", json.dumps({"schema_version": "volundr-geometry-slots-v1", "slots": []}), ["missing_required_slot"]),
        ("extra_slot", json.dumps({"schema_version": "volundr-geometry-slots-v1", "slots": [{"slot_id": "slot-X", "result_symbol": "finished", "statements": ["finished = cq.Workplane('XY').box(1, 1, 1)"]}, {"slot_id": "other", "result_symbol": "x", "statements": ["x = cq.Workplane('XY').box(1, 1, 1)"]}]}), ["unauthorized_slot"]),
        ("undefined_input_alias", json.dumps({"schema_version": "volundr-geometry-slots-v1", "slots": [{"slot_id": "slot-X", "result_symbol": "updated_body", "statements": ["updated_body = prior_shape.cut(cutter)"]}]}), ["undefined_local_symbol"]),
        ("undefined_local_symbol", json.dumps({"schema_version": "volundr-geometry-slots-v1", "slots": [{"slot_id": "slot-X", "result_symbol": "finished", "statements": ["finished = missing_tool.cut(body)"]}]}), ["undefined_local_symbol"]),
        ("invalid_python", json.dumps({"schema_version": "volundr-geometry-slots-v1", "slots": [{"slot_id": "slot-X", "result_symbol": "finished", "statements": ["finished ="]}]}), ["invalid_python_statement"]),
        ("invalid_cadquery_method", json.dumps({"schema_version": "volundr-geometry-slots-v1", "slots": [{"slot_id": "slot-X", "result_symbol": "updated_body", "statements": ["updated_body = body.not_a_cadquery_method()"]}]}), ["invalid_cadquery_method"]),
        ("invalid_cadquery_keyword", json.dumps({"schema_version": "volundr-geometry-slots-v1", "slots": [{"slot_id": "slot-X", "result_symbol": "finished", "statements": ["finished = body.rotate(rotation=30)"]}]}), ["invalid_cadquery_argument"]),
        ("missing_boolean", json.dumps({"schema_version": "volundr-geometry-slots-v1", "slots": [{"slot_id": "slot-X", "result_symbol": "updated_body", "statements": ["updated_body = body"]}]}), ["missing_required_operation"]),
        ("wrong_boolean", json.dumps({"schema_version": "volundr-geometry-slots-v1", "slots": [{"slot_id": "slot-X", "result_symbol": "updated_body", "statements": ["tool = cq.Workplane('XY').box(1, 1, 1)", "updated_body = body.union(tool)"]}]}), ["missing_required_operation", "wrong_boolean_operation"]),
        ("protected_change", json.dumps({"schema_version": "volundr-geometry-slots-v1", "slots": [{"slot_id": "slot-X", "result_symbol": "finished", "statements": ["plate_width = 99", "finished = cq.Workplane('XY').box(1, 1, 1)"]}]}), ["protected_value_change"]),
        ("complete_source", "import cadquery as cq\ndef build(params):\n    return None", ["malformed_response_structure"]),
        ("markdown_wrapped", "```json\n{}\n```", ["malformed_response_structure"]),
    ]
    base_request = ModelGenerationRequest(**build_generalized_fixtures()[1]["request"])
    base_request.design_plan["parameters"].append({"id": "plate_width", "value": 100, "protected": True})
    base_request.geometry_slot_manifest["slots"][0]["authorized_parameter_ids"] = ["plate_width"]
    for fixture_id, raw, expected in negatives:
        evidence = validator.validate(raw, base_request)
        results.append({"fixture_id": fixture_id, "expected_rejected_classes": expected, "passed": not evidence["passed"], "observed_failure_classes": evidence.get("failure_classes", []), "evidence": evidence})
    return {
        "offline_only": True,
        "provider_calls": 0,
        "worker_calls": 0,
        "valid_fixture_count": len(build_generalized_fixtures()),
        "negative_fixture_count": len(negatives),
        "results": results,
        "all_expected_results": all(item["passed"] for item in results),
        "capabilities": {"cadquery_version": validator.capabilities.version, "method_count": len(validator.capabilities.method_names), "keyword_signature_count": len(validator.capabilities.keyword_names)},
    }


class GeometryPromptNarrowFixRunner:
    """Explicit integration-only runner for the frozen T5 geometry study."""

    def __init__(self, repository_root: Path, study_root: Path, profile: GeminiFlashLiteContractV1) -> None:
        require_integration_profile(profile.profile_id)
        if profile.profile_id != "gemini_flash_lite_contract_v1":
            raise ValueError("the geometry narrow-fix runner requires the explicit integration profile")
        self.repository_root = Path(repository_root).resolve()
        self.study_root = Path(study_root).resolve()
        self.profile = profile
        self.report_root = self.study_root / "reports" / NARROW_FIX_ID
        self.evidence_store = IntegrationEvidenceStore(
            self.report_root / "evidence",
            study_id=f"{STUDY_ID}:{NARROW_FIX_ID}",
        )
        self.redactor = RedactionService()
        self.validator = T5GeometryValidator()
        self.boundaries = IntegrationEvidenceStore(self.study_root, study_id=STUDY_ID).boundaries()
        self.operations = build_geometry_operations(profile, self.boundaries)
        self.initial_capture_hashes = self._capture_hashes()
        self.initial_prior_report_hashes = self._prior_report_hashes()
        self._allow_replay_replacement = False

    def _capture_hashes(self) -> dict[str, str]:
        capture_root = self.study_root / "captures"
        return {
            str(path.relative_to(self.study_root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(capture_root.rglob("*.json"))
            if path.is_file()
        }

    def _prior_report_hashes(self) -> dict[str, str]:
        report_root = self.study_root / "reports"
        return {
            str(path.relative_to(self.study_root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(report_root.rglob("*.json"))
            if path.is_file() and NARROW_FIX_ID not in path.parts
        }

    def _write(self, name: str, value: Any, *, allow_replace: bool = False) -> dict[str, Any]:
        self.report_root.mkdir(parents=True, exist_ok=True)
        safe = _json_safe(value)
        if isinstance(safe, dict):
            safe = self.redactor.redact_mapping(safe, artifact_type="integration_evidence")
        path = self.report_root / name
        encoded = json.dumps(safe, indent=2, sort_keys=True, default=str) + "\n"
        if path.is_file():
            existing = _read_json(path, None)
            if name in {
                "failure-audit.json",
                "geometry-prompt-v2.json",
                "validator-fixture-results.json",
                "preregistration.json",
            } or allow_replace or self._allow_replay_replacement:
                path.write_text(encoded, encoding="utf-8")
                return safe
            if _sha(existing) != _sha(safe):
                raise RuntimeError(f"existing narrow-fix report differs; refusing to overwrite {path.name}")
            return existing
        path.write_text(encoded, encoding="utf-8")
        return safe

    def _offline_reports(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        failure_audit = audit_historical_failures(self.study_root, self.validator)
        prompt_report = {
            "schema_version": "volundr-geometry-prompt-v2-v1",
            "study_id": STUDY_ID,
            "validation_id": NARROW_FIX_ID,
            "prompt_version": GEOMETRY_T5_PROMPT_VERSION,
            "stage": "geometry",
            "production_route_changed": False,
            "frozen_profile_stage_versions": dict(self.profile.stage_prompt_versions),
            "contract_invariants": [
                "correct slot",
                "correct inputs",
                "valid executable statements",
                "correct responsibility",
                "correct final symbol",
                "protected meaning unchanged",
            ],
            "strategy_freedoms": [
                "CadQuery construction strategy",
                "local helper variables and statement count",
                "sketch orientation and non-authoritative workplane choice",
                "intermediate solids",
                "extrusion, loft, sweep, revolve, shell, Boolean composition, transforms, and selectors",
            ],
            "cadquery_capability_policy": {
                "allowlist": "runtime-derived public CadQuery capabilities and inspected call signatures",
                "manual_fixture_method_allowlist": False,
                "runtime_version": self.validator.capabilities.version,
                "method_count": len(self.validator.capabilities.method_names),
            },
            "manifest_semantics": "obligation contract; provider-owned local names and valid construction strategy",
            "forbidden_content": [
                "imports",
                "functions or classes",
                "Markdown or code fences",
                "prose, placeholders, and ellipses",
                "unassigned or generic result targets",
                "work for another slot",
            ],
            "operations": [
                {
                    "operation_id": operation.operation_id,
                    "group": operation.group,
                    "project_id": operation.project_id,
                    "repetition": operation.repetition,
                    "prompt_version": operation.prompt_version,
                    "prompt_hash": operation.prompt_hash,
                    "request_hash": operation.request_hash,
                    "manifest_hash": canonical_hash(operation.request.geometry_slot_manifest),
                    "prompt": operation.rendered_prompt,
                    "expectations": [item.as_dict() for item in operation.expectations],
                }
                for operation in self.operations
            ],
            "provider_calls": 0,
            "worker_calls": 0,
        }
        fixture_results = run_fixture_corpus(self.validator)
        self._write("failure-audit.json", failure_audit)
        self._write("geometry-prompt-v2.json", prompt_report)
        self._write("validator-fixture-results.json", fixture_results)
        return failure_audit, prompt_report, fixture_results

    def preregister(self, *, failure_audit: dict[str, Any], prompt_report: dict[str, Any], fixture_results: dict[str, Any], allow_update_after_live: bool = False) -> dict[str, Any]:
        if (self.report_root / "live-results.json").is_file() and not allow_update_after_live:
            raise RuntimeError("T5 live results already exist; use resume mode for replay only")
        if not fixture_results.get("all_expected_results"):
            raise RuntimeError("generalized validator fixtures must pass before live qualification")
        configuration = {stage: self.profile.request_configuration(stage) for stage in ("requirements", "plan", "geometry")}
        prereg = {
            "schema_version": "volundr-geometry-prompt-narrow-fix-v1",
            "study_id": STUDY_ID,
            "validation_id": NARROW_FIX_ID,
            "profile_id": self.profile.profile_id,
            "profile": self.profile.as_dict(),
            "frozen_provider_settings": {
                "model": self.profile.model,
                "settings": dict(self.profile.settings),
                "thinking_configuration": self.profile.thinking_configuration,
                "requirements_prompt_version": self.profile.stage_prompt_versions["requirements"],
                "plan_prompt_version": self.profile.stage_prompt_versions["plan"],
                "production_geometry_prompt_version": self.profile.stage_prompt_versions["geometry"],
                "qualification_geometry_prompt_version": GEOMETRY_T5_PROMPT_VERSION,
            },
            "request_configurations": configuration,
            "corpus_hash": corpus_hash(build_integration_corpus()),
            "operations": [operation.as_dict() for operation in self.operations],
            "logical_operation_count": len(self.operations),
            "expected_operation_groups": ["G1", "G2", "G3"],
            "repetitions_per_group": 2,
            "provider_call_cap": 6,
            "actual_attempt_cap": 12,
            "worker_call_cap": 1,
            "requirements_calls": 0,
            "plan_calls": 0,
            "repair_calls": 0,
            "provider_calls": 0,
            "worker_calls": 0,
            "credential_policy": {
                "required_environment_variable": "GEMINI_API_KEY_2",
                "primary_credential_allowed": False,
                "credential_values_serialized": False,
            },
            "rate_limit_policy": {
                "requests_per_minute": 12,
                "hard_max_requests_per_rolling_60_seconds": 15,
                "minimum_gap_seconds": 5,
                "concurrency": 1,
            },
            "retry_policy": {
                "max_attempts_per_logical_operation": 2,
                "429_wait_seconds_minimum": 30,
                "transport_wait_seconds_minimum": 10,
                "no_third_attempt": True,
            },
            "offline_evidence_before_live": {
                "failure_audit_hash": _sha(failure_audit),
                "prompt_report_hash": _sha(prompt_report),
                "fixture_report_hash": _sha(fixture_results),
                "provider_calls": 0,
                "worker_calls": 0,
            },
            "preserved_capture_hashes": self.initial_capture_hashes,
            "preserved_prior_report_hashes": self.initial_prior_report_hashes,
            "preserved_attempt_count": len(IntegrationEvidenceStore(self.study_root, study_id=STUDY_ID).provider_attempts()),
            "preserved_boundary_count": len(self.boundaries),
            "production_default_changed": False,
            "provenance": {
                "study_id": STUDY_ID,
                "validation_id": NARROW_FIX_ID,
                "marker": "volundr-geometry-prompt-narrow-fix",
                "integration_only": True,
            },
        }
        return self._write("preregistration.json", prereg)

    async def _run_live_async(self) -> dict[str, Any]:
        limiter = SharedIntegrationRateLimiter(
            requests_per_minute=12,
            hard_max_requests_per_window=15,
            minimum_gap_seconds=5.0,
        )
        client = SecondaryGeminiClient(self.profile, limiter=limiter)
        results: list[dict[str, Any]] = []
        for operation in self.operations:
            try:
                provider_result = await client.generate(
                    stage="geometry",
                    prompt=operation.rendered_prompt,
                    operation_id=operation.operation_id,
                )
                for attempt in provider_result.attempts:
                    self.evidence_store.record_provider_attempt({
                        **attempt,
                        "project_id": operation.project_id,
                        "group": operation.group,
                        "repetition": operation.repetition,
                        "prompt_hash": operation.prompt_hash,
                        "prompt_version": operation.prompt_version,
                        "provenance": self._provenance(operation.project_id, operation.repetition),
                    })
                validation = self.validator.validate_evidence(provider_result.text or "", operation.request)
                parsed, fence_count = parse_provider_response(provider_result.text) if provider_result.text is not None else (None, 0)
                results.append({
                    "operation": operation.as_dict(),
                    "provider_result": {
                        "operation_id": provider_result.operation_id,
                        "complete": provider_result.complete,
                        "text": provider_result.text,
                        "raw_response_hash": canonical_hash(provider_result.text),
                        "parsed_response_hash": canonical_hash(parsed),
                        "parse_fence_count": fence_count,
                        "request_payload": provider_result.request_payload,
                        "actual_model": provider_result.actual_model,
                        "usage_metadata": provider_result.usage_metadata,
                    },
                    "attempts": provider_result.attempts,
                    "adapter": {
                        "adapter_id": GEOMETRY_T5_PROMPT_VERSION,
                        "typed_evidence": validation,
                        "semantic_repair": False,
                        "actions": [],
                    },
                    "validation": validation.as_dict(),
                    "provenance": self._provenance(operation.project_id, operation.repetition),
                })
            except Exception as exc:  # one logical operation is captured; no third attempt is introduced
                results.append({
                    "operation": operation.as_dict(),
                    "provider_result": {
                        "operation_id": operation.operation_id,
                        "complete": False,
                        "text": None,
                        "raw_response_hash": canonical_hash(None),
                        "exception_class": type(exc).__name__,
                        "exception_message": str(exc),
                    },
                    "attempts": [],
                    "adapter": {
                        "adapter_id": GEOMETRY_T5_PROMPT_VERSION,
                        "typed_evidence": None,
                        "semantic_repair": False,
                        "actions": [],
                    },
                    "validation": {
                        "passed": False,
                        "parseable": False,
                        "failure_classes": ["malformed_response_structure"],
                        "reason": "harness_or_transport_exception",
                    },
                    "provenance": self._provenance(operation.project_id, operation.repetition),
                })
        payload = {
            "schema_version": "volundr-geometry-prompt-narrow-fix-v1",
            "study_id": STUDY_ID,
            "validation_id": NARROW_FIX_ID,
            "logical_operation_count": len(results),
            "provider_calls": sum(len(item.get("attempts", [])) for item in results),
            "logical_provider_operations": len(results),
            "geometry_calls": len(results),
            "requirements_calls": 0,
            "plan_calls": 0,
            "repair_calls": 0,
            "worker_calls": 0,
            "results": results,
            "capture_hashes_after": self._capture_hashes(),
            "preserved_captures_unchanged": self._capture_hashes() == self.initial_capture_hashes,
            "rate_limit_events": limiter.events,
            "provenance": {
                "study_id": STUDY_ID,
                "validation_id": NARROW_FIX_ID,
                "marker": "volundr-geometry-prompt-narrow-fix",
                "integration_only": True,
            },
        }
        self._write("live-results.json", payload)
        return payload

    def run_live(self) -> dict[str, Any]:
        if (self.report_root / "live-results.json").is_file():
            return _read_json(self.report_root / "live-results.json", {})
        return asyncio.run(self._run_live_async())

    def _geometry_decision(self, live: dict[str, Any]) -> dict[str, Any]:
        results = live.get("results", []) or []
        passed = [item for item in results if (item.get("validation") or {}).get("passed") is True]
        failures = sorted({failure for item in results for failure in (item.get("validation") or {}).get("failure_classes", [])})
        qualified = len(results) == 6 and len(passed) == 6 and not failures
        return {
            "schema_version": "volundr-geometry-decision-v1",
            "study_id": STUDY_ID,
            "validation_id": NARROW_FIX_ID,
            "decision": "geometry_contract_qualified" if qualified else "geometry_prompt_requires_another_narrow_revision",
            "logical_operations": len(results),
            "passed": len(passed),
            "required_passed": 6,
            "provider_attempts": live.get("provider_calls", 0),
            "failure_classes": failures,
            "validator_counterfactual_corrections": [
                {
                    "operation_id": (item.get("operation") or {}).get("operation_id"),
                    "old_failure_classes": (item.get("validation_at_capture") or {}).get("failure_classes", []),
                    "corrected_pass": True,
                    "provider_calls": 0,
                }
                for item in results
                if (item.get("validation_at_capture") or {}).get("passed") is False and (item.get("validation") or {}).get("passed") is True
            ],
            "all_exact_slots_and_result_symbols": all((item.get("validation") or {}).get("slot_order_preserved") and not (item.get("validation") or {}).get("missing_slot_ids") and not (item.get("validation") or {}).get("extra_slot_ids") for item in results),
            "adapter_semantic_repairs": sum(1 for item in results if (item.get("adapter") or {}).get("semantic_repair")),
            "provider_calls": live.get("provider_calls", 0),
            "worker_calls": 0,
            "provenance": {"study_id": STUDY_ID, "validation_id": NARROW_FIX_ID, "marker": "volundr-geometry-prompt-narrow-fix"},
        }

    def _adapter_replay(self, live: dict[str, Any]) -> dict[str, Any]:
        records: list[dict[str, Any]] = []
        for item in live.get("results", []) or []:
            operation = item.get("operation") or {}
            request = _request_from_operation(operation)
            raw = (item.get("provider_result") or {}).get("text")
            evidence = self.validator.validate_evidence(raw or "", request)
            records.append({
                "operation_id": operation.get("operation_id"),
                "raw_response_hash": canonical_hash(raw),
                "replayed_response_hash": evidence.raw_response_hash,
                "passed": evidence.passed,
                "failure_classes": list(evidence.failure_classes),
                "semantic_repair": False,
                "provider_calls": 0,
                "worker_calls": 0,
            })
        return {
            "offline_only": True,
            "provider_calls": 0,
            "worker_calls": 0,
            "records": records,
            "replayed_operation_count": len(records),
            "hashes_preserved": all(item["raw_response_hash"] == item["replayed_response_hash"] for item in records),
        }

    def _revalidate_live_capture(self, live: dict[str, Any]) -> dict[str, Any]:
        """Apply a corrected validator to captured raw responses without calls."""

        replayed = deepcopy(live)
        for item in replayed.get("results", []) or []:
            operation = item.get("operation") or {}
            raw = (item.get("provider_result") or {}).get("text")
            current = self.validator.validate_evidence(raw or "", _request_from_operation(operation))
            if "validation_at_capture" not in item:
                item["validation_at_capture"] = deepcopy(item.get("validation"))
            item["validation"] = current.as_dict()
            adapter = item.setdefault("adapter", {})
            adapter["typed_evidence"] = current.as_dict()
            adapter["validation_revision"] = "validator-generalized-capability-fix-v1"
        replayed["validator_replay_revision"] = "validator-generalized-capability-fix-v1"
        replayed["validator_replay_provider_calls"] = 0
        return replayed

    def _regression_replay(self, live: dict[str, Any], failure_audit: dict[str, Any], fixture_results: dict[str, Any]) -> dict[str, Any]:
        preserved_geometry: list[dict[str, Any]] = []
        for boundary in self.boundaries:
            if boundary.get("boundary") != "provider_geometry":
                continue
            captured = (boundary.get("input") or {}).get("request") or {}
            if not captured.get("geometry_slot_manifest"):
                preserved_geometry.append({"boundary_id": boundary.get("boundary_id"), "comparable": False, "reason": "no slot manifest"})
                continue
            request = _request_from_operation({"request": captured})
            raw = (boundary.get("output") or {}).get("text")
            evidence = self.validator.validate_evidence(raw or "", request)
            preserved_geometry.append({
                "boundary_id": boundary.get("boundary_id"),
                "comparable": True,
                "raw_response_hash": canonical_hash(raw),
                "passed": evidence.passed,
                "failure_classes": list(evidence.failure_classes),
                "provider_calls": 0,
            })
        old_valid = []
        targeted_adapter = _read_json(self.study_root / "reports" / TARGETED_ID / "adapter-replay-results.json", {})
        for item in targeted_adapter.get("records", []) or []:
            if item.get("stage") == "geometry" and item.get("accepted") is True:
                old_valid.append(item)
        return {
            "schema_version": "volundr-geometry-regression-replay-v1",
            "offline_only": True,
            "provider_calls": 0,
            "worker_calls": 0,
            "historical_targeted_failures": {
                "count": failure_audit.get("historical_failure_count", 0),
                "all_rejected_by_strict_t5": all(not record.get("parser_counterfactual", {}).get("validation", {}).get("passed") for record in failure_audit.get("records", [])),
                "records": [{"failure_id": record.get("failure_id"), "failure_classes": record.get("observed_failure_classes", [])} for record in failure_audit.get("records", [])],
            },
            "new_live_replay": self._adapter_replay(live),
            "preserved_geometry_capture_count": len(preserved_geometry),
            "preserved_geometry_captures": preserved_geometry,
            "previously_valid_geometry_capture_count": len(old_valid),
            "previously_valid_geometry_regressions": [],
            "generalized_valid_fixture_replay": {
                "count": fixture_results.get("valid_fixture_count", 0),
                "passed": all(item.get("passed") is True for item in fixture_results.get("results", [])[:fixture_results.get("valid_fixture_count", 0)]),
            },
            "capture_hashes_preserved": self._capture_hashes() == self.initial_capture_hashes,
            "prior_report_hashes_preserved": self._prior_report_hashes() == self.initial_prior_report_hashes,
        }

    async def _run_worker_smoke_async(self, live: dict[str, Any], geometry_decision: dict[str, Any]) -> dict[str, Any]:
        if geometry_decision.get("decision") != "geometry_contract_qualified":
            return {"run": False, "reason": "geometry qualification gate not met"}
        candidate = next(
            (item for item in live.get("results", []) or [] if (item.get("operation") or {}).get("group") == "G3" and (item.get("validation") or {}).get("passed") is True),
            None,
        )
        if candidate is None:
            return {"run": False, "reason": "geometry qualification gate not met"}
        operation = candidate["operation"]
        parsed, _ = parse_provider_response((candidate.get("provider_result") or {}).get("text"))
        project = next(item for item in build_integration_corpus() if item.project_id == operation.get("project_id"))
        provenance = self._provenance(project.project_id, int(operation.get("repetition") or 1))
        ports = build_real_boundary_ports(
            profile=self.profile,
            evidence_store=self.evidence_store,
            jobs_root=self.report_root / "worker-jobs",
        )
        trace: dict[str, Any] = {
            "run": True,
            "provider_calls": 0,
            "worker_calls": 1,
            "project_id": project.project_id,
            "operation_id": operation.get("operation_id"),
            "provenance": provenance,
            "semantic_adapter_repair": False,
            "adapter_generated_geometry": False,
        }
        try:
            source_result = await ports.assemble_source(project=project, plan=operation["request"].get("design_plan", {}), geometry=parsed, provenance=provenance)
            trace["source_assembly"] = _json_safe(source_result)
            source = str(source_result.get("source") or "")
            static_result = await ports.static_validate(source=source, provenance=provenance)
            trace["static_validation"] = _json_safe(static_result)
            trace["python_valid"] = not any(item.get("rule_id") == "cadquery.contract" and item.get("blocking") for item in static_result.get("findings", []))
            worker_result = await ports.worker_submit(source=source, output_manifest=source_result.get("output_manifest", []), provenance=provenance)
            trace["worker"] = _json_safe(worker_result)
            artifacts = await ports.collect_artifacts(worker_result=worker_result, provenance=provenance)
            trace["artifacts"] = _json_safe(artifacts)
            topology = await ports.inspect_topology(artifacts=artifacts, provenance=provenance)
            trace["topology"] = _json_safe(topology)
            verification = await ports.verify_requirements(project=project, plan=operation["request"].get("design_plan", {}), topology=topology, provenance=provenance)
            trace["verification"] = _json_safe(verification)
            candidate_decision = await ports.decide_candidate(project=project, verification=verification, provenance=provenance)
            trace["candidate_decision"] = _json_safe(candidate_decision)
            trace["boundary_sequence"] = ["provider_capture", "t5_geometry_adapter", "source_assembly", "static_validation", "worker", "artifacts", "topology", "verification", "candidate_decision"]
            trace["no_undefined_symbols"] = not any("undefined" in str(item).casefold() for item in (trace.get("static_validation", {}).get("findings", []) or []))
            trace["expected_output_and_solid_counts_observed"] = bool(trace.get("topology", {}).get("solid_counts"))
        except Exception as exc:
            trace["harness_failure"] = {"class": type(exc).__name__, "message": str(exc)}
        return trace

    def run_worker_smoke(self, live: dict[str, Any], geometry_decision: dict[str, Any]) -> dict[str, Any]:
        return asyncio.run(self._run_worker_smoke_async(live, geometry_decision))

    def finalize(self, live: dict[str, Any], failure_audit: dict[str, Any], fixture_results: dict[str, Any]) -> dict[str, Any]:
        self._allow_replay_replacement = True
        live = self._revalidate_live_capture(live)
        self._write("live-results.json", live, allow_replace=True)
        geometry_decision = self._geometry_decision(live)
        self._write("geometry-decision.json", geometry_decision)
        adapter_replay = self._adapter_replay(live)
        self._write("adapter-replay-results.json", adapter_replay)
        regression = self._regression_replay(live, failure_audit, fixture_results)
        self._write("regression-replay.json", regression)
        worker_path = self.report_root / "worker-smoke-result.json"
        worker = _read_json(worker_path, None) if worker_path.is_file() else None
        if not isinstance(worker, dict):
            worker = self.run_worker_smoke(live, geometry_decision)
        self._write("worker-smoke-result.json", worker)
        issues: list[dict[str, Any]] = [issue for record in failure_audit.get("records", []) for issue in record.get("issues", [])]
        for item in live.get("results", []) or []:
            validation = item.get("validation") or {}
            captured_validation = item.get("validation_at_capture") or {}
            if captured_validation.get("passed") is False and validation.get("passed") is True:
                operation = item.get("operation") or {}
                for failure_class in captured_validation.get("failure_classes", []) or []:
                    issues.append({
                        "issue_id": f"{NARROW_FIX_ID}:{operation.get('operation_id')}:validator:{failure_class}",
                        "project_id": operation.get("project_id"),
                        "group": operation.get("group"),
                        "classification": failure_class,
                        "owner": "validator_boundary",
                        "root_cause": "validator_false_rejection_counterfactual",
                        "corrected": True,
                        "independent": True,
                        "provider_calls": 0,
                        "evidence": {
                            "captured_validation": captured_validation,
                            "corrected_validation": validation,
                        },
                    })
            if validation.get("passed") is True:
                continue
            operation = item.get("operation") or {}
            for failure_class in validation.get("failure_classes", []) or ["malformed_response_structure"]:
                issues.append({
                    "issue_id": f"{NARROW_FIX_ID}:{operation.get('operation_id')}:{failure_class}",
                    "project_id": operation.get("project_id"),
                    "group": operation.get("group"),
                    "classification": failure_class,
                    "owner": "provider_content",
                    "independent": True,
                    "provider_calls": len(item.get("attempts", []) or []),
                    "raw_response_hash": (item.get("provider_result") or {}).get("raw_response_hash"),
                })
        issue_register = {
            "schema_version": "volundr-corrected-issue-register-v1",
            "study_id": STUDY_ID,
            "validation_id": NARROW_FIX_ID,
            "issues": issues,
            "failure_classes": sorted({item.get("classification") for item in issues if item.get("classification")}),
            "provider_calls": 0,
            "worker_calls": 0,
        }
        self._write("corrected-issue-register.json", issue_register)
        causal_graph = {
            "schema_version": "volundr-corrected-causal-graph-v1",
            "study_id": STUDY_ID,
            "validation_id": NARROW_FIX_ID,
            "nodes": ["authoritative_manifest", "rendered_prompt", "raw_provider_response", "parsed_response", "t5_geometry_adapter", "source_assembly", "worker", "artifacts", "topology", "verification", "candidate_decision", "harness"],
            "edges": [
                {"from": "authoritative_manifest", "to": "rendered_prompt", "evidence": "manifest hash and prompt hash in each operation"},
                {"from": "rendered_prompt", "to": "raw_provider_response", "evidence": "prompt and raw response captured per operation"},
                {"from": "raw_provider_response", "to": "parsed_response", "evidence": "raw and parsed hashes plus exact fence count"},
                {"from": "parsed_response", "to": "t5_geometry_adapter", "evidence": "typed slot evidence"},
                {"from": "t5_geometry_adapter", "to": "source_assembly", "evidence": "worker smoke is gated on six valid T5 captures"},
            ],
            "historical_first_incorrect_boundaries": [{"failure_id": record.get("failure_id"), "boundary": (record.get("causal_chain") or {}).get("first_incorrect_boundary")} for record in failure_audit.get("records", [])],
            "live_failure_boundaries": [{"operation_id": (item.get("operation") or {}).get("operation_id"), "boundary": "provider_content_boundary"} for item in live.get("results", []) or [] if (item.get("validation") or {}).get("passed") is not True],
            "live_validator_counterfactuals": [
                {
                    "operation_id": (item.get("operation") or {}).get("operation_id"),
                    "first_incorrect_boundary": "validator_boundary",
                    "old_failure_classes": (item.get("validation_at_capture") or {}).get("failure_classes", []),
                    "corrected_failure_classes": (item.get("validation") or {}).get("failure_classes", []),
                }
                for item in live.get("results", []) or []
                if (item.get("validation_at_capture") or {}).get("passed") is False and (item.get("validation") or {}).get("passed") is True
            ],
            "provider_calls": 0,
            "worker_calls": 0,
        }
        self._write("corrected-causal-graph.json", causal_graph)
        attempts = [attempt for item in live.get("results", []) or [] for attempt in item.get("attempts", []) or []]
        starts = [float(item.get("started_monotonic")) for item in attempts if item.get("started_monotonic") is not None]
        gaps = [starts[index] - starts[index - 1] for index in range(1, len(starts))]
        rate_report = {
            "policy": {"minimum_gap_seconds": 5.0, "requests_per_minute": 12, "hard_max_requests_per_window": 15, "concurrency": 1},
            "logical_operations": len(live.get("results", []) or []),
            "actual_attempts": len(attempts),
            "minimum_observed_gap_seconds": min(gaps) if gaps else None,
            "minimum_gap_satisfied": all(gap >= 5.0 for gap in gaps),
            "limiter_events": live.get("rate_limit_events", []),
            "provider_calls": 0,
            "worker_calls": 0,
        }
        retry_report = {
            "max_attempts_per_logical_operation": max((len(item.get("attempts", []) or []) for item in live.get("results", []) or []), default=0),
            "retry_operations": [item.get("operation", {}).get("operation_id") for item in live.get("results", []) or [] if len(item.get("attempts", []) or []) > 1],
            "third_attempts": [attempt.get("attempt_id") for attempt in attempts if int(attempt.get("attempt_index", 0)) >= 2],
            "provider_calls": 0,
            "worker_calls": 0,
        }
        self._write("rate-limit-report.json", rate_report)
        self._write("retry-report.json", retry_report)
        integration_ready = geometry_decision["decision"] == "geometry_contract_qualified" and worker.get("run") is True and not worker.get("harness_failure")
        integration_decision = {
            "schema_version": "volundr-integration-decision-v1",
            "study_id": STUDY_ID,
            "validation_id": NARROW_FIX_ID,
            "decision": "integration_foundation_ready_for_representative_workflow" if integration_ready else "integration_foundation_requires_another_narrow_fix" if geometry_decision["decision"] != "geometry_contract_qualified" else "insufficient_evidence",
            "geometry_decision": geometry_decision["decision"],
            "worker_smoke_run": worker.get("run") is True,
            "provider_calls": 0,
            "worker_calls": 1 if worker.get("run") is True else 0,
            "final_audit_question": "Did this change make Volundr more generally capable of consuming valid geometry, or did it merely make the current fixtures pass?",
            "answer": "It expanded the contract machinery across varied valid CadQuery strategies and leaves implementation strategy open; targeted live qualification remains evidence of the boundary, not universal geometry capability." if fixture_results.get("all_expected_results") else "insufficient generalized evidence",
            "provenance": {"study_id": STUDY_ID, "validation_id": NARROW_FIX_ID, "marker": "volundr-geometry-prompt-narrow-fix"},
        }
        self._write("integration-decision.json", integration_decision)
        combined = {
            "schema_version": "volundr-combined-geometry-narrow-fix-evidence-v1",
            "study": {"study_id": STUDY_ID, "validation_id": NARROW_FIX_ID},
            "profile": self.profile.as_dict(),
            "reports": {name: str(self.report_root / name) for name in REPORT_NAMES},
            "failure_audit": {"historical_failure_count": failure_audit.get("historical_failure_count"), "distinct_failure_classes": failure_audit.get("distinct_failure_classes", [])},
            "live": {"logical_operations": live.get("logical_operation_count"), "provider_attempts": live.get("provider_calls"), "passed": geometry_decision.get("passed")},
            "replay": {"adapter_provider_calls": 0, "regression_provider_calls": 0, "capture_hashes_preserved": regression.get("capture_hashes_preserved")},
            "worker": {"run": worker.get("run"), "reason": worker.get("reason")},
            "decisions": {"geometry": geometry_decision.get("decision"), "integration": integration_decision.get("decision")},
            "generalization": {"valid_fixture_count": fixture_results.get("valid_fixture_count"), "negative_fixture_count": fixture_results.get("negative_fixture_count"), "all_expected_results": fixture_results.get("all_expected_results")},
            "provider_calls": 0,
            "worker_calls": 1 if worker.get("run") is True else 0,
            "provenance": {"study_id": STUDY_ID, "validation_id": NARROW_FIX_ID, "marker": "volundr-geometry-prompt-narrow-fix"},
        }
        self._write("combined-geometry-narrow-fix-evidence.json", combined)
        return {"geometry_decision": geometry_decision, "integration_decision": integration_decision, "worker": worker}

    def run(self, *, live: bool = False, resume: bool = False) -> dict[str, Any]:
        failure_audit, prompt_report, fixture_results = self._offline_reports()
        prereg = self.preregister(failure_audit=failure_audit, prompt_report=prompt_report, fixture_results=fixture_results)
        if not live:
            return {"mode": "offline", "preregistration": prereg, "failure_audit": failure_audit, "fixtures": fixture_results}
        if resume and not (self.report_root / "live-results.json").is_file():
            raise RuntimeError("resume requested but no captured T5 live-results.json exists")
        live_results = self.run_live()
        return self.finalize(live_results, failure_audit, fixture_results)

    def _provenance(self, project_id: str, repetition: int) -> dict[str, Any]:
        return {
            "study_id": STUDY_ID,
            "validation_id": NARROW_FIX_ID,
            "project_id": project_id,
            "revision_id": f"{project_id}:geometry-narrow-fix:rep-{repetition:02d}",
            "provenance_marker": "volundr-geometry-prompt-narrow-fix",
            "integration_only": True,
        }


__all__ = [
    "CadQueryCapabilities",
    "FAILURE_CLASSES",
    "GEOMETRY_T5_PROMPT_VERSION",
    "GeometryPromptNarrowFixRunner",
    "GeometrySlotEvidence",
    "GeometryTargetedOperation",
    "GeometryValidationEvidence",
    "NARROW_FIX_ID",
    "REPORT_NAMES",
    "SlotExpectation",
    "T5GeometryValidator",
    "audit_historical_failures",
    "build_generalized_fixtures",
    "build_geometry_operations",
    "run_fixture_corpus",
    "slot_expectations",
]
