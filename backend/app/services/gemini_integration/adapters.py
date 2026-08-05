from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.services.gemini_consistency.geometry_slot_canonicalizer import (
    GeometrySlotContractCanonicalizer,
)
from app.services.gemini_consistency.provider_contract import (
    GeminiProviderContractAdapter,
    canonical_hash,
    parse_provider_response,
    semantic_signature,
)


def _text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(f"{key} {_text(item)}" for key, item in value.items()).casefold()
    if isinstance(value, list):
        return " ".join(_text(item) for item in value).casefold()
    return str(value).casefold() if value is not None else ""


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.casefold()) if token not in {"the", "of", "and", "with"}}


def _meaningful(value: Any, fields: tuple[str, ...]) -> bool:
    return isinstance(value, dict) and any(value.get(field) not in (None, "", [], {}) for field in fields)


def _provider_record(
    stage: str,
    raw: Any,
    context: dict[str, Any],
    *,
    required_slot_ids: list[Any] | None = None,
) -> dict[str, Any]:
    packet_expectations: dict[str, Any] = {}
    if required_slot_ids is not None:
        packet_expectations["must_return_exactly"] = [str(item) for item in required_slot_ids]
    adapter = GeminiProviderContractAdapter(
        stage=stage,
        contract={
            "required_slot_ids": [str(item) for item in required_slot_ids or []],
            "required_result_symbol": "body" if stage == "geometry" else None,
            "response_kind": "cadquery_source",
        },
    )
    return adapter.adapt(
        raw,
        {"stage": stage, "intrinsic_expectations": packet_expectations},
        provenance=context.get("provenance") or {},
        owned_ids={
            key: context[key]
            for key in ("project_id", "revision_id")
            if context.get(key) is not None
        },
    )


@dataclass(frozen=True)
class AdapterEvidence:
    stage: str
    accepted: bool
    raw_input: Any
    parsed: Any
    normalized: Any
    input_hash: str
    output_hash: str
    semantic_hash_before: str
    semantic_hash_after: str
    normalization_actions: list[dict[str, Any]] = field(default_factory=list)
    validation_result: dict[str, Any] = field(default_factory=dict)
    failure_class: str | None = None
    volundr_mapping: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "accepted": self.accepted,
            "raw_input": self.raw_input,
            "parsed": self.parsed,
            "normalized": self.normalized,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "semantic_hash_before": self.semantic_hash_before,
            "semantic_hash_after": self.semantic_hash_after,
            "normalization_actions": list(self.normalization_actions),
            "validation_result": dict(self.validation_result),
            "failure_class": self.failure_class,
            "volundr_mapping": dict(self.volundr_mapping),
            "provenance": dict(self.provenance),
        }


def _failure_for_quality(quality: dict[str, Any]) -> str | None:
    result = str(quality.get("result") or "")
    if result in {"", "pass", "pass_with_benign_format_variation"}:
        return None
    return {
        "fail_incomplete": "incomplete",
        "fail_conflicting": "conflicting",
        "fail_invented_critical_meaning": "invented_critical_meaning",
        "fail_invalid_api": "invalid_api",
        "fail_undefined_symbols": "undefined_symbols",
        "fail_structurally_empty": "structurally_empty",
        "fail_wrong_output_obligation": "wrong_output_obligation",
        "fail_wrong_geometry_strategy": "wrong_geometry_strategy",
    }.get(result, result or None)


def _evidence(
    stage: str,
    raw: Any,
    parsed: Any,
    normalized: Any,
    *,
    accepted: bool,
    actions: list[dict[str, Any]],
    validation: dict[str, Any],
    failure_class: str | None,
    context: dict[str, Any],
) -> AdapterEvidence:
    before = semantic_signature(parsed, {"stage": stage})
    after = semantic_signature(normalized, {"stage": stage})
    return AdapterEvidence(
        stage=stage,
        accepted=accepted,
        raw_input=raw,
        parsed=parsed,
        normalized=normalized,
        input_hash=canonical_hash(raw),
        output_hash=canonical_hash(normalized),
        semantic_hash_before=before,
        semantic_hash_after=after,
        normalization_actions=actions,
        validation_result=validation,
        failure_class=failure_class,
        volundr_mapping={
            "project_id": context.get("project_id"),
            "revision_id": context.get("revision_id"),
        },
        provenance=dict(context.get("provenance") or {}),
    )


class GeminiRequirementsContractAdapter:
    stage = "requirements"

    def adapt(self, raw: Any, context: dict[str, Any]) -> AdapterEvidence:
        provider = _provider_record(self.stage, raw, context)
        parsed, _ = parse_provider_response(raw)
        normalized = provider.get("canonical_provider_record")
        actions = list(provider.get("actions") or [])
        if not provider.get("accepted") and not isinstance(normalized, dict):
            return _evidence(
                self.stage, raw, parsed, normalized, accepted=False, actions=actions,
                validation=provider.get("quality") or {},
                failure_class=_failure_for_quality(provider.get("quality") or {}), context=context,
            )
        if not isinstance(normalized, dict) or not isinstance(normalized.get("requirements"), list):
            source_records = [
                item
                for field in ("critical_dimensions", "functional_requirements")
                for item in (normalized.get(field, []) if isinstance(normalized, dict) else [])
                if isinstance(item, dict)
            ]
            if source_records:
                normalized["requirements"] = source_records
                actions.append({
                    "action_class": "semantic_requirement_projection",
                    "rule_id": "authoritative-requirement-records",
                    "original": ["critical_dimensions", "functional_requirements"],
                    "normalized": "requirements",
                    "authoritative_source": "Volundr requirements persistence contract",
                    "confidence": "high",
                    "ambiguity_status": "none",
                })
            else:
                return _evidence(self.stage, raw, parsed, normalized, accepted=False, actions=actions,
                                 validation={"reason": "requirements must be a non-empty list"},
                                 failure_class="structurally_empty", context=context)
        requirements = normalized["requirements"]
        if not requirements or any(not _meaningful(item, ("id", "subject", "description", "value", "operator")) for item in requirements):
            return _evidence(self.stage, raw, parsed, normalized, accepted=False, actions=actions,
                             validation={"reason": "requirements contain an empty semantic record"},
                             failure_class="structurally_empty", context=context)
        clarification = normalized.get("clarification_required") is True
        ready = normalized.get("generation_ready") is True
        if clarification and ready:
            return _evidence(self.stage, raw, parsed, normalized, accepted=False, actions=actions,
                             validation={"reason": "clarification_required conflicts with generation_ready"},
                             failure_class="conflicting_readiness", context=context)
        missing = [str(item) for item in context.get("fit_critical_missing", [])]
        question_text = _text(normalized.get("clarification_questions", []))
        for fact in missing:
            fact_tokens = _tokens(fact)
            claimed = [item for item in requirements if fact_tokens and fact_tokens <= _tokens(_text(item)) and item.get("value") is not None]
            if claimed:
                return _evidence(self.stage, raw, parsed, normalized, accepted=False, actions=actions,
                                 validation={"reason": f"provider invented fit-critical value: {fact}"},
                                 failure_class="invented_critical_meaning", context=context)
            if not clarification or ready or not fact_tokens <= _tokens(question_text):
                return _evidence(self.stage, raw, parsed, normalized, accepted=False, actions=actions,
                                 validation={"reason": f"missing explicit clarification for {fact}"},
                                 failure_class="missing_required_clarification", context=context)
        return _evidence(self.stage, raw, parsed, normalized, accepted=True, actions=actions,
                         validation={"valid": True, "missing_values_preserved": True},
                         failure_class=None, context=context)


class GeminiPlanContractAdapter:
    stage = "plan"

    def adapt(self, raw: Any, context: dict[str, Any]) -> AdapterEvidence:
        provider = _provider_record(self.stage, raw, context)
        parsed, _ = parse_provider_response(raw)
        normalized = provider.get("canonical_provider_record")
        actions = list(provider.get("actions") or [])
        if not provider.get("accepted") and not isinstance(normalized, dict):
            return _evidence(self.stage, raw, parsed, normalized, accepted=False, actions=actions,
                             validation=provider.get("quality") or {},
                             failure_class=_failure_for_quality(provider.get("quality") or {}), context=context)
        if not isinstance(normalized, dict):
            return _evidence(self.stage, raw, parsed, normalized, accepted=False, actions=actions,
                             validation={"reason": "Plan must be an object"}, failure_class="invalid_json", context=context)
        components = normalized.get("components")
        features = normalized.get("features") or []
        outputs = normalized.get("printable_outputs")
        if not isinstance(components, list) or not components or not isinstance(outputs, list) or not outputs:
            return _evidence(self.stage, raw, parsed, normalized, accepted=False, actions=actions,
                             validation={"reason": "Plan needs meaningful components and printable outputs"},
                             failure_class="structurally_empty", context=context)
        if any(not _meaningful(item, ("id", "component_id", "name", "label")) for item in components):
            return _evidence(self.stage, raw, parsed, normalized, accepted=False, actions=actions,
                             validation={"reason": "Plan contains an empty component"}, failure_class="structurally_empty", context=context)
        expected_count = context.get("expected_output_count")
        if expected_count is not None and len(outputs) != int(expected_count):
            return _evidence(self.stage, raw, parsed, normalized, accepted=False, actions=actions,
                             validation={"reason": "printable output count differs from frozen obligation"},
                             failure_class="wrong_output_obligation", context=context)
        component_ids = {str(item.get("id") or item.get("component_id")) for item in components}
        references: list[str] = []
        for item in [*features, *outputs, *(normalized.get("validation_targets") or [])]:
            if not isinstance(item, dict):
                continue
            refs = item.get("component_ids") or item.get("component_id")
            refs = refs if isinstance(refs, list) else [refs]
            references.extend(str(ref) for ref in refs if ref is not None)
        invalid = sorted(ref for ref in references if ref not in component_ids)
        if invalid:
            return _evidence(self.stage, raw, parsed, normalized, accepted=False, actions=actions,
                             validation={"invalid_component_references": invalid}, failure_class="invalid_reference", context=context)
        required_requirements = {str(item) for item in context.get("required_requirement_ids", [])}
        represented: set[str] = {
            str(item.get("id") or item.get("requirement_id"))
            for item in normalized.get("requirements", [])
            if isinstance(item, dict) and (item.get("id") or item.get("requirement_id")) is not None
        }

        def collect_requirement_ids(value: Any) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {"requirement_id", "source_requirement_id"} and item is not None:
                        represented.add(str(item))
                    elif key == "requirement_ids" and isinstance(item, list):
                        represented.update(str(entry) for entry in item)
                    collect_requirement_ids(item)
            elif isinstance(value, list):
                for item in value:
                    collect_requirement_ids(item)

        collect_requirement_ids(normalized)
        missing = sorted(required_requirements - represented)
        if missing:
            return _evidence(self.stage, raw, parsed, normalized, accepted=False, actions=actions,
                             validation={"missing_requirement_traceability": missing}, failure_class="missing_traceability", context=context)
        identity_map = {
            f"{kind}:{item.get('id')}": f"{context.get('project_id')}:{kind}:{item.get('id')}"
            for kind, records in (("component", components), ("feature", features), ("output", outputs))
            for item in records
            if isinstance(item, dict) and item.get("id") is not None
        }
        context = {**context, "identity_map": identity_map}
        return _evidence(self.stage, raw, parsed, normalized, accepted=True, actions=actions,
                         validation={"valid": True, "references_valid": True, "output_obligations_preserved": True},
                         failure_class=None, context=context)


class GeminiGeometryContractAdapter:
    stage = "geometry"

    def adapt(self, raw: Any, context: dict[str, Any]) -> AdapterEvidence:
        expected_ids = list(context.get("expected_slot_ids") or [])
        provider = _provider_record(self.stage, raw, context, required_slot_ids=expected_ids)
        parsed, _ = parse_provider_response(raw)
        normalized = provider.get("canonical_provider_record")
        actions = list(provider.get("actions") or [])
        if not provider.get("accepted") and not isinstance(normalized, dict):
            return _evidence(self.stage, raw, parsed, normalized, accepted=False, actions=actions,
                             validation=provider.get("quality") or {},
                             failure_class=_failure_for_quality(provider.get("quality") or {}), context=context)
        if not isinstance(normalized, dict) or not isinstance(normalized.get("slots"), list):
            return _evidence(self.stage, raw, parsed, normalized, accepted=False, actions=actions,
                             validation={"reason": "geometry response must contain slots"}, failure_class="missing_slots", context=context)
        slots = normalized["slots"]
        returned_ids = [str(item.get("slot_id")) for item in slots if isinstance(item, dict)]
        expected_text = [str(item) for item in expected_ids]
        if returned_ids != expected_text:
            failure = "missing_slots" if set(returned_ids) != set(expected_text) else "slot_order_changed"
            return _evidence(self.stage, raw, parsed, normalized, accepted=False, actions=actions,
                             validation={"expected_slot_ids": expected_text, "returned_slot_ids": returned_ids}, failure_class=failure, context=context)
        allowed_names = [str(item) for item in context.get("allowed_names", [])]
        canonicalizer = GeometrySlotContractCanonicalizer()
        for slot in slots:
            if not isinstance(slot, dict) or slot.get("result_symbol") != "body":
                return _evidence(self.stage, raw, parsed, normalized, accepted=False, actions=actions,
                                 validation={"reason": "every slot must assign body"}, failure_class="invalid_result_assignment", context=context)
            statements = slot.get("statements")
            if not isinstance(statements, list) or not statements:
                return _evidence(self.stage, raw, parsed, normalized, accepted=False, actions=actions,
                                 validation={"reason": "slot statements are empty"}, failure_class="structurally_empty", context=context)
            text = "\n".join(str(item) for item in statements)
            if re.search(r"\.rotate\s*\(\s*rotation\s*=|\.holes\s*\(|\.assembly\s*\(", text):
                return _evidence(self.stage, raw, parsed, normalized, accepted=False, actions=actions,
                                 validation={"reason": "invalid CadQuery API"}, failure_class="invalid_api", context=context)
            if re.search(r"\b(?:missing_shape|undefined_[a-z0-9_]*|unknown_[a-z0-9_]*)\b", text):
                return _evidence(self.stage, raw, parsed, normalized, accepted=False, actions=actions,
                                 validation={"reason": "undefined symbol"}, failure_class="undefined_symbols", context=context)
            canonical = canonicalizer.canonicalize({
                "slot_id": slot.get("slot_id"),
                "statements": statements,
                "required_result_symbol": "body",
                "authoritative_input_symbols": ["body"],
                "allowed_names": allowed_names,
            })
            if not canonical.get("accepted"):
                reason = str(canonical.get("reason") or "geometry slot rejected")
                failure = "undefined_symbols" if reason.startswith("undefined_names") else "invalid_result_assignment" if "result symbol" in reason else "ambiguous_geometry" if canonical.get("ambiguity") else "invalid_geometry"
                return _evidence(self.stage, raw, parsed, normalized, accepted=False, actions=actions + list(canonical.get("actions") or []), validation=canonical.get("validation") or {}, failure_class=failure, context=context)
            if canonical.get("normalized_statements") != statements:
                slot["statements"] = canonical["normalized_statements"]
                actions.extend(canonical.get("actions") or [])
        return _evidence(self.stage, raw, parsed, normalized, accepted=True, actions=actions,
                         validation={"valid": True, "numeric_literals_preserved": True, "operation_order_preserved": True, "required_result_symbol": "body"},
                         failure_class=None, context=context)


__all__ = [
    "AdapterEvidence",
    "GeminiGeometryContractAdapter",
    "GeminiPlanContractAdapter",
    "GeminiRequirementsContractAdapter",
]
