"""Pure provider-contract scoring, regularity, and adapter primitives.

This module intentionally knows nothing about the current Volundr parser,
worker, topology, verification, database, or provider transport.  It may
consume frozen packet expectations and raw provider responses only.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from copy import deepcopy
from typing import Any, Iterable


QUALITY_RESULTS = (
    "pass",
    "pass_with_benign_format_variation",
    "fail_incomplete",
    "fail_conflicting",
    "fail_invented_critical_meaning",
    "fail_invalid_api",
    "fail_undefined_symbols",
    "fail_structurally_empty",
    "fail_wrong_output_obligation",
    "fail_wrong_geometry_strategy",
    "transport_failure",
    "quota_failure",
)
QUALITY_PASS = {"pass", "pass_with_benign_format_variation"}
_ENUM_ALIASES = {
    "ready_for_generation": "generation_ready",
    "ready-for-generation": "generation_ready",
    "input-needed": "input_required",
}
_FIELD_ALIASES = {"result": "result_symbol", "resultSymbol": "result_symbol", "slotId": "slot_id"}
_BENIGN_KEYS = {"notes", "note", "metadata"}
_ACTION_CLASSES = {
    "format_normalization",
    "field_alias_normalization",
    "enum_normalization",
    "optional_field_normalization",
    "generated_identity_canonicalization",
    "authoritative_identity_attachment",
    "authoritative_provenance_attachment",
    "slot_attachment",
    "result_symbol_normalization",
    "prior_shape_alias_normalization",
    "rejected_ambiguity",
    "rejected_contract_violation",
}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _strip_json_fence(raw: str) -> tuple[str, int]:
    stripped = raw.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip(), 1
    return stripped, 0


def parse_provider_response(raw: str | dict[str, Any]) -> tuple[Any, int]:
    if isinstance(raw, dict):
        return deepcopy(raw), 0
    candidate, fence_count = _strip_json_fence(raw)
    try:
        return json.loads(candidate), fence_count
    except (TypeError, json.JSONDecodeError):
        return None, fence_count


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.casefold()
    if isinstance(value, (int, float, bool)):
        return str(value).casefold()
    if isinstance(value, dict):
        return " ".join(f"{_text(key)} {_text(item)}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(_text(item) for item in value)
    return ""


def _objects(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _meaningful(item: Any, fields: Iterable[str]) -> bool:
    return isinstance(item, dict) and any(item.get(field) not in (None, "", [], {}) for field in fields)


def _result(result: str, *, missing: list[str] | None = None, conflicting: list[str] | None = None, invented: list[str] | None = None, api: list[str] | None = None, symbols: list[str] | None = None, empty: list[str] | None = None, geometry: list[str] | None = None) -> dict[str, Any]:
    if result not in QUALITY_RESULTS:
        raise ValueError(result)
    return {
        "result": result,
        "missing_meaning": sorted(set(missing or [])),
        "conflicting_meaning": sorted(set(conflicting or [])),
        "invented_critical_meaning": sorted(set(invented or [])),
        "api_findings": sorted(set(api or [])),
        "undefined_symbol_findings": sorted(set(symbols or [])),
        "structural_emptiness_findings": sorted(set(empty or [])),
        "geometry_strategy_findings": sorted(set(geometry or [])),
    }


def extract_requirement_operators(parsed: Any) -> list[str]:
    operators: list[str] = []
    if isinstance(parsed, dict):
        for key, value in parsed.items():
            if str(key).casefold() == "operator" and isinstance(value, str):
                operators.append(value)
            operators.extend(extract_requirement_operators(value))
    elif isinstance(parsed, list):
        for value in parsed:
            operators.extend(extract_requirement_operators(value))
    return sorted(set(operators))


def _empty_nested(parsed: dict[str, Any]) -> list[str]:
    fields = {
        "requirements": ("id", "description", "subject", "value", "operator"),
        "components": ("id", "component_id", "name", "label"),
        "features": ("id", "feature_id", "description", "semantic_role", "name"),
        "relationships": ("id", "relationship_id", "source_id", "target_id", "relationship_type"),
        "printable_outputs": ("id", "output_id", "component_id", "component_ids", "description", "name"),
        "validation_targets": ("id", "target_id", "component_id", "measurement", "value"),
        "slots": ("slot_id", "statements", "result_symbol"),
    }
    findings: list[str] = []
    for field, meaningful_fields in fields.items():
        value = parsed.get(field)
        if not isinstance(value, list):
            continue
        for index, item in enumerate(value):
            if not _meaningful(item, meaningful_fields):
                findings.append(f"{field}[{index}] has no meaning-bearing fields")
    return findings


def _evaluate_requirements(packet: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    empty = _empty_nested(parsed)
    if empty:
        return _result("fail_structurally_empty", empty=empty)
    expectations = packet.get("intrinsic_expectations") or {}
    text = _text(parsed)
    missing: list[str] = []
    invented: list[str] = []
    if expectations.get("must_request"):
        clarification = parsed.get("clarification_required") is True or bool(_objects(parsed.get("clarification_questions")))
        ready = parsed.get("generation_ready") is True or str(parsed.get("outcome", "")).casefold() in {"ready", "generation_ready"}
        if not clarification:
            invented.append("generation-ready decision omitted materially required fit clarification")
        if ready and not clarification:
            invented.append("generation-ready output omitted clarification")
        for fact in expectations["must_request"]:
            normalized_fact = fact.casefold()
            generic_fit_answer = (normalized_fact == "phone width" or normalized_fact.startswith("phone thickness")) and (("fit dimension" in text or "phone dimensions" in text) or ("dimensions" in text and "phone" in text))
            generic_angle_answer = normalized_fact == "desired angle" and "viewing angle" in text
            if not generic_fit_answer and not generic_angle_answer and normalized_fact.replace(" ", "_") not in text and normalized_fact not in text:
                missing.append(fact)
    for fact in expectations.get("must_preserve", []):
        if str(fact).casefold() not in text:
            missing.append(str(fact))
    prohibited = ("fit clearance", "phone width", "phone thickness", "viewing angle")
    for item in _objects(parsed.get("requirements")) + _objects(parsed.get("critical_dimensions")):
        item_text = _text(item)
        if any(term in item_text for term in prohibited) and str(item.get("source", "")).casefold() == "user":
            if not any(str(fact).casefold() in item_text for fact in expectations.get("must_preserve", [])):
                invented.append(f"critical fact promoted as user input: {item_text}")
    if missing:
        return _result("fail_incomplete", missing=missing, invented=invented)
    if invented:
        return _result("fail_invented_critical_meaning", invented=invented)
    return _result("pass")


def _evaluate_plan(packet: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    empty = _empty_nested(parsed)
    if empty:
        return _result("fail_structurally_empty", empty=empty)
    components = _objects(parsed.get("components"))
    outputs = _objects(parsed.get("printable_outputs"))
    if parsed.get("plan_ready") is True and (not components or not outputs):
        return _result("fail_structurally_empty", empty=["plan_ready requires meaningful components and printable outputs"])
    expected = packet.get("intrinsic_expectations") or {}
    expected_count = expected.get("output_count")
    if expected_count is not None and len(outputs) != expected_count:
        return _result("fail_wrong_output_obligation", conflicting=[f"expected {expected_count} outputs, returned {len(outputs)}"])
    component_ids = {str(item.get("component_id") or item.get("id")) for item in components}
    identity = []
    for item in _objects(parsed.get("features")) + outputs:
        for field in ("component_id", "component_ids"):
            refs = item.get(field)
            values = refs if isinstance(refs, list) else [refs]
            for ref in values:
                if ref is not None and str(ref) not in component_ids:
                    identity.append(f"reference to nonexistent component: {ref}")
    if identity:
        return _result("fail_conflicting", conflicting=identity)
    text = _text(parsed)
    missing: list[str] = []
    for feature in expected.get("required_features", []):
        feature_text = str(feature).casefold()
        aliases = {
            "five trays": (
                "five trays",
                "5 trays",
                "five stacked vertical trays",
                "five vertical trays",
                "five tray",
            ),
            "mostly open side walls": ("open side walls", "open_side_walls", "open side wall"),
            "bottom drainage": ("bottom drainage", "bottom drainage openings", "drainage"),
            "two retention strap slots": ("two retention strap slots", "retention strap slots", "strap slots"),
        }.get(feature_text, (feature_text,))
        if not any(alias in text for alias in aliases):
            missing.append(str(feature))
    if missing:
        return _result("fail_incomplete", missing=missing)
    return _result("pass")


def _evaluate_geometry(packet: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    empty = _empty_nested(parsed)
    if empty:
        return _result("fail_structurally_empty", empty=empty)
    slots = _objects(parsed.get("slots") or parsed.get("functions"))
    expected = packet.get("intrinsic_expectations") or {}
    expected_ids = {str(item) for item in expected.get("must_return_exactly", []) or expected.get("slot_ids", [])}
    if not expected_ids:
        expected_ids = {str(item.get("slot_id")) for item in slots}
    returned_ids = {str(item.get("slot_id")) for item in slots if item.get("slot_id") is not None}
    if returned_ids != expected_ids:
        return _result("fail_wrong_geometry_strategy", missing=[f"slot {item}" for item in expected_ids - returned_ids], conflicting=[f"unknown slot {item}" for item in returned_ids - expected_ids])
    api: list[str] = []
    symbols: list[str] = []
    missing: list[str] = []
    strategy: list[str] = []
    for slot in slots:
        slot_id = str(slot.get("slot_id"))
        statements = slot.get("statements") if isinstance(slot.get("statements"), list) else []
        if not statements or not slot.get("result_symbol"):
            return _result("fail_structurally_empty", empty=[f"slot {slot_id} has no statements or result symbol"])
        slot_text = _text(slot)
        if re.search(r"\.rotate\s*\(\s*rotation\s*=|\.holes\s*\(|\.assembly\s*\(", slot_text):
            api.append(f"slot {slot_id} contains invalid CadQuery API usage")
        if re.search(r"\b(?:missing_shape|undefined_[a-z0-9_]*|unknown_[a-z0-9_]*)\b", slot_text):
            symbols.append(f"slot {slot_id} references undefined symbol")
        if expected.get("must_cut") and "cut" not in slot_text and "hole" not in slot_text:
            missing.append("authorized subtractive cut")
        if expected.get("must_union") and "union" not in slot_text:
            missing.append("overlapping additive union")
        if expected.get("must_loft") and "loft" not in slot_text:
            missing.append("transition loft")
        for token in ("box", "extrude", "loft", "union", "cut", "hole", "workplane", "fillet", "chamfer"):
            if token in slot_text:
                strategy.append(token)
    if api:
        return _result("fail_invalid_api", api=api)
    if symbols:
        return _result("fail_undefined_symbols", symbols=symbols)
    if missing:
        return _result("fail_incomplete", missing=missing)
    return _result("pass")


def _evaluate_geometry_source(packet: dict[str, Any], raw: str) -> dict[str, Any]:
    """Score a complete provider-owned source response without using Volundr parsing."""
    text = raw.casefold()
    if not text.strip():
        return _result("fail_structurally_empty", empty=["empty geometry source"])
    api: list[str] = []
    symbols: list[str] = []
    if re.search(r"\.rotate\s*\(\s*rotation\s*=|\.holes\s*\(|\.assembly\s*\(", text):
        api.append("source contains invalid CadQuery API usage")
    if re.search(r"\b(?:missing_shape|undefined_[a-z0-9_]*|unknown_[a-z0-9_]*)\b", text):
        symbols.append("source references undefined symbol")
    if api:
        return _result("fail_invalid_api", api=api)
    if symbols:
        return _result("fail_undefined_symbols", symbols=symbols)
    expectations = packet.get("intrinsic_expectations") or {}
    missing: list[str] = []
    if "build(" not in text or "printableoutput" not in text:
        missing.append("complete printable geometry response")
    if expectations.get("must_cut") and not any(token in text for token in (".cut", ".hole")):
        missing.append("authorized subtractive cut")
    if expectations.get("must_union") and ".union" not in text:
        missing.append("overlapping additive union")
    if expectations.get("must_loft") and ".loft" not in text:
        missing.append("transition loft")
    if expectations.get("must_return_exactly"):
        if len(re.findall(r"output_id\s*=\s*['\"](?:1|2|3|4)['\"]", text)) < len(expectations["must_return_exactly"]):
            missing.append("all requested geometry responsibilities")
        for token in ("rectangular", "hollow", "circular", "internal"):
            if token not in text:
                missing.append(f"geometry responsibility: {token}")
    if missing:
        return _result("fail_incomplete", missing=missing)
    return _result("pass")


def _evaluate_repair(packet: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    if _empty_nested(parsed):
        return _result("fail_structurally_empty", empty=_empty_nested(parsed))
    expected = packet.get("intrinsic_expectations") or {}
    if expected.get("repair_boundary") and not parsed.get("repair_boundary") and not parsed.get("slots"):
        return _result("fail_incomplete", missing=["bounded repair result"])
    return _result("pass")


def evaluate_intrinsic(packet: dict[str, Any], response: str | dict[str, Any], *, diagnostic_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Score provider meaning only; diagnostic context is intentionally ignored."""
    del diagnostic_context
    parsed, _ = parse_provider_response(response)
    if not isinstance(parsed, dict):
        if str(packet.get("stage")) == "geometry" and isinstance(response, str):
            return _evaluate_geometry_source(packet, response)
        return _result("fail_conflicting", missing=["valid JSON object"])
    stage = str(packet.get("stage"))
    if stage == "requirements":
        return _evaluate_requirements(packet, parsed)
    if stage == "plan":
        return _evaluate_plan(packet, parsed)
    if stage == "geometry":
        return _evaluate_geometry(packet, parsed)
    if stage == "repair":
        return _evaluate_repair(packet, parsed)
    return _result("fail_conflicting", missing=[f"unsupported stage: {stage}"])


def _semantic_projection(value: Any) -> Any:
    if isinstance(value, dict):
        projected: dict[str, Any] = {}
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
            key_text = str(key)
            if key_text in _BENIGN_KEYS:
                continue
            if key_text == "id" or (key_text.endswith("_id") and key_text not in {"slot_id", "source_requirement_id"}):
                continue
            canonical_key = _FIELD_ALIASES.get(key_text, key_text)
            if canonical_key == "status" and isinstance(item, str):
                item = _ENUM_ALIASES.get(item, item)
            if canonical_key == "result_symbol" and item in {"modified_shape", "component_shape"}:
                item = "body"
            projected[canonical_key] = _semantic_projection(item)
        return projected
    if isinstance(value, list):
        items = [_semantic_projection(item) for item in value]
        if all(isinstance(item, dict) and "slot_id" in item for item in items):
            return sorted(items, key=lambda item: str(item["slot_id"]))
        return items
    return value


def semantic_signature(value: Any, packet: dict[str, Any] | None = None) -> str:
    del packet
    return canonical_hash(_semantic_projection(value))


def _shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _shape(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, list):
        return ["list", len(value), [_shape(item) for item in value]]
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


def structural_signature(value: Any) -> str:
    return canonical_hash(_shape(value))


def _collect_identity(value: Any, path: str = "root") -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            if key_text == "id" or key_text.endswith("_id") or key_text in {"result_symbol", "function_id"}:
                if isinstance(item, (str, int)):
                    found.append({"path": f"{path}.{key_text}", "value": str(item)})
            found.extend(_collect_identity(item, f"{path}.{key_text}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_collect_identity(item, f"{path}[{index}]"))
    return found


def identity_signature(value: Any) -> str:
    return canonical_hash(sorted(_collect_identity(value), key=lambda item: (item["path"], item["value"])))


def decision_signature(value: Any) -> str:
    if not isinstance(value, dict):
        return canonical_hash(None)
    keys = {key: value.get(key) for key in ("clarification_required", "generation_ready", "plan_ready", "repair_complete", "outcome", "status") if key in value}
    return canonical_hash(keys)


def geometry_strategy_signature(value: Any) -> str:
    text = _text(value)
    tokens = [token for token in ("workplane", "box", "extrude", "loft", "union", "cut", "hole", "fillet", "chamfer", "translate", "rotate") if token in text]
    return canonical_hash(tokens)


def _normalized_entropy(values: list[str]) -> float:
    if len(values) <= 1:
        return 0.0
    counts = Counter(values)
    entropy = -sum((count / len(values)) * math.log(count / len(values), 2) for count in counts.values())
    return entropy / math.log(len(counts), 2) if len(counts) > 1 else 0.0


def contract_entropy(records: list[Any], packet: dict[str, Any] | None = None) -> float:
    if not records:
        return 0.0
    dimensions = [
        [semantic_signature(item, packet) for item in records],
        [structural_signature(item) for item in records],
        [identity_signature(item) for item in records],
        [decision_signature(item) for item in records],
        [geometry_strategy_signature(item) for item in records],
    ]
    return round(sum(_normalized_entropy(values) for values in dimensions) / len(dimensions), 12)


def _difference_count(left: Any, right: Any) -> int:
    if type(left) is not type(right):
        return 1
    if isinstance(left, dict):
        keys = set(left) | set(right)
        return sum(_difference_count(left.get(key), right.get(key)) for key in keys)
    if isinstance(left, list):
        return abs(len(left) - len(right)) + sum(_difference_count(a, b) for a, b in zip(left, right))
    return 0 if left == right else 1


def _benign_normalize(value: Any) -> tuple[Any, int]:
    actions = 0
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            target = _FIELD_ALIASES.get(str(key), str(key))
            if target != key:
                actions += 1
            normalized, child_actions = _benign_normalize(item)
            actions += child_actions
            result[target] = normalized
        if result.get("status") in _ENUM_ALIASES:
            result["status"] = _ENUM_ALIASES[result["status"]]
            actions += 1
        return result, actions
    if isinstance(value, list):
        normalized: list[Any] = []
        for item in value:
            item_value, child_actions = _benign_normalize(item)
            normalized.append(item_value)
            actions += child_actions
        return normalized, actions
    return value, actions


def canonicalization_distance(raw: str | dict[str, Any], normalized: Any) -> int:
    parsed, fence_actions = parse_provider_response(raw)
    benign, actions = _benign_normalize(parsed)
    return max(1, fence_actions + actions) + _difference_count(benign, normalized) * 10


def _action(action_class: str, rule_id: str, original: Any, normalized: Any, *, authoritative_source: str, confidence: str = "high", ambiguity: str = "none") -> dict[str, Any]:
    if action_class not in _ACTION_CLASSES:
        raise ValueError(action_class)
    return {
        "action_class": action_class,
        "rule_id": rule_id,
        "original": original,
        "normalized": normalized,
        "authoritative_source": authoritative_source,
        "confidence": confidence,
        "ambiguity_status": ambiguity,
    }


def _adapter_normalize(value: Any, actions: list[dict[str, Any]], path: str = "root") -> Any:
    if isinstance(value, list):
        return [_adapter_normalize(item, actions, f"{path}[{index}]") for index, item in enumerate(value)]
    if not isinstance(value, dict):
        return value
    normalized: dict[str, Any] = {}
    for key, item in value.items():
        target = _FIELD_ALIASES.get(str(key), str(key))
        if target in normalized:
            actions.append(_action("rejected_ambiguity", "alias-collision", key, target, authoritative_source=path, confidence="high", ambiguity="ambiguous"))
            continue
        if target != key:
            action_class = "result_symbol_normalization" if target == "result_symbol" else "field_alias_normalization"
            actions.append(_action(action_class, "safe-field-alias", key, target, authoritative_source=path))
        normalized[target] = _adapter_normalize(item, actions, f"{path}.{target}")
    if normalized.get("status") in _ENUM_ALIASES:
        original = normalized["status"]
        normalized["status"] = _ENUM_ALIASES[original]
        actions.append(_action("enum_normalization", "status-alias", original, normalized["status"], authoritative_source=path))
    if normalized.get("result_symbol") in {"modified_shape", "component_shape"}:
        original = normalized["result_symbol"]
        normalized["result_symbol"] = "body"
        actions.append(_action("result_symbol_normalization", "required-body-symbol", original, "body", authoritative_source=path))
    if isinstance(normalized.get("statements"), list):
        statements: list[Any] = []
        for statement in normalized["statements"]:
            if isinstance(statement, str):
                updated = re.sub(r"\b(?:modified_shape|component_shape)\b", "body", statement)
                if updated != statement:
                    actions.append(_action("prior_shape_alias_normalization", "unambiguous-prior-shape", statement, updated, authoritative_source=path))
                statements.append(updated)
            else:
                statements.append(statement)
        normalized["statements"] = statements
    return normalized


class GeminiProviderContractAdapter:
    """Translate provider representation into a Volundr-owned semantic record."""

    def __init__(self, *, stage: str, contract: dict[str, Any]) -> None:
        self.stage = stage
        self.contract = deepcopy(contract)

    def adapt(self, raw: str | dict[str, Any], packet: dict[str, Any], *, provenance: dict[str, Any] | None = None, protected_values: dict[str, Any] | None = None, owned_ids: dict[str, Any] | None = None) -> dict[str, Any]:
        raw_value, _ = parse_provider_response(raw)
        if raw_value is None and self.stage == "geometry" and isinstance(raw, str):
            quality = evaluate_intrinsic(packet, raw)
            canonical = {"response_kind": self.contract.get("response_kind", "cadquery_source"), "source": raw}
            before_hash = canonical_hash(raw)
            actions: list[dict[str, Any]] = []
            if quality["result"] not in QUALITY_PASS:
                actions.append(_action("rejected_contract_violation", "intrinsic-quality-floor", quality["result"], quality, authoritative_source="provider-contract", confidence="high"))
                return {"accepted": False, "quality": quality, "actions": actions, "canonical_provider_record": canonical, "semantic_hash_before": before_hash, "semantic_hash_after": semantic_signature(canonical, packet)}
            normalized_text = raw.casefold()
            protected = protected_values or {}
            missing_protected = [f"{key}={value}" for key, value in protected.items() if str(value).casefold() not in normalized_text]
            if missing_protected:
                actions.append(_action("rejected_contract_violation", "protected-value-preservation", missing_protected, "preserved", authoritative_source="Volundr protected values"))
                return {"accepted": False, "quality": quality, "actions": actions, "canonical_provider_record": canonical, "semantic_hash_before": before_hash, "semantic_hash_after": semantic_signature(canonical, packet)}
            for key, value in (owned_ids or {}).items():
                actions.append(_action("authoritative_identity_attachment", f"owned-{key}", None, value, authoritative_source="Volundr"))
            if provenance:
                actions.append(_action("authoritative_provenance_attachment", "owned-provenance", None, provenance, authoritative_source="Volundr"))
            after_hash = semantic_signature(canonical, packet)
            for item in actions:
                item["semantic_hash_before"] = before_hash
                item["semantic_hash_after"] = after_hash
            return {"accepted": True, "quality": quality, "actions": actions, "canonical_provider_record": canonical, "semantic_hash_before": before_hash, "semantic_hash_after": after_hash, "volundr_mapping": {"owned_ids": owned_ids or {}, "protected_values": protected, "provenance": provenance or {}}}
        if raw_value is None:
            quality = _result("fail_conflicting", missing=["valid provider response"])
            action = _action("rejected_contract_violation", "valid-response-object", None, quality, authoritative_source="provider-contract", confidence="high")
            return {"accepted": False, "quality": quality, "actions": [action], "canonical_provider_record": None, "semantic_hash_before": canonical_hash(raw), "semantic_hash_after": canonical_hash(None)}
        before_hash = semantic_signature(raw_value, packet)
        actions: list[dict[str, Any]] = []
        normalized = _adapter_normalize(raw_value, actions)
        quality = evaluate_intrinsic(packet, normalized)
        if quality["result"] not in QUALITY_PASS:
            actions.append(_action("rejected_contract_violation", "intrinsic-quality-floor", quality["result"], quality, authoritative_source="provider-contract", confidence="high"))
            return {"accepted": False, "quality": quality, "actions": actions, "canonical_provider_record": normalized, "semantic_hash_before": before_hash, "semantic_hash_after": semantic_signature(normalized, packet)}
        if self.stage == "geometry":
            slots = _objects(normalized.get("slots"))
            required_slots = [str(item) for item in self.contract.get("required_slot_ids", [])]
            returned_slots = [str(item.get("slot_id")) for item in slots]
            if required_slots and returned_slots != required_slots:
                actions.append(_action("rejected_contract_violation", "slot-completeness", returned_slots, required_slots, authoritative_source="Volundr slot manifest"))
                return {"accepted": False, "quality": quality, "actions": actions, "canonical_provider_record": normalized, "semantic_hash_before": before_hash, "semantic_hash_after": semantic_signature(normalized, packet)}
            required_symbol = self.contract.get("required_result_symbol")
            if required_symbol and any(item.get("result_symbol") != required_symbol for item in slots):
                actions.append(_action("rejected_contract_violation", "required-result-symbol", returned_slots, required_symbol, authoritative_source="Volundr slot manifest"))
                return {"accepted": False, "quality": quality, "actions": actions, "canonical_provider_record": normalized, "semantic_hash_before": before_hash, "semantic_hash_after": semantic_signature(normalized, packet)}
            for slot in slots:
                actions.append(_action("slot_attachment", "volundr-slot-attachment", None, slot.get("slot_id"), authoritative_source="Volundr slot manifest"))
        protected = protected_values or {}
        normalized_text = _text(normalized)
        missing_protected = [f"{key}={value}" for key, value in protected.items() if str(value).casefold() not in normalized_text]
        if missing_protected:
            actions.append(_action("rejected_contract_violation", "protected-value-preservation", missing_protected, "preserved", authoritative_source="Volundr protected values"))
            return {"accepted": False, "quality": quality, "actions": actions, "canonical_provider_record": normalized, "semantic_hash_before": before_hash, "semantic_hash_after": semantic_signature(normalized, packet)}
        for key, value in (owned_ids or {}).items():
            actions.append(_action("authoritative_identity_attachment", f"owned-{key}", None, value, authoritative_source="Volundr"))
        if provenance:
            actions.append(_action("authoritative_provenance_attachment", "owned-provenance", None, provenance, authoritative_source="Volundr"))
        after_hash = semantic_signature(normalized, packet)
        for item in actions:
            item["semantic_hash_before"] = before_hash
            item["semantic_hash_after"] = after_hash
        return {
            "accepted": True,
            "quality": quality,
            "actions": actions,
            "canonical_provider_record": normalized,
            "semantic_hash_before": before_hash,
            "semantic_hash_after": after_hash,
            "volundr_mapping": {"owned_ids": owned_ids or {}, "protected_values": protected, "provenance": provenance or {}},
        }


__all__ = [
    "QUALITY_RESULTS",
    "GeminiProviderContractAdapter",
    "canonical_hash",
    "canonicalization_distance",
    "contract_entropy",
    "decision_signature",
    "evaluate_intrinsic",
    "extract_requirement_operators",
    "geometry_strategy_signature",
    "identity_signature",
    "parse_provider_response",
    "semantic_signature",
    "structural_signature",
]
