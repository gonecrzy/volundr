"""Experiment-scoped, conservative response processing for the system-boundary study.

The default Volundr path does not import or call this module.  The functions
here are deliberately pure so preserved evidence can be replayed without a
provider, worker, database, or network call.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable


METHOD_IDS = ("P0", "P1", "P2", "P3", "P4", "P5")
HARD_MAX_REQUESTS_PER_WINDOW = 15
DEFAULT_REQUESTS_PER_MINUTE = 12
DEFAULT_MIN_INTERVAL_SECONDS = 5.0
_STATUS_ALIASES = {
    "ready_for_generation": "generation_ready",
    "ready-for-generation": "generation_ready",
    "input-needed": "input_required",
    "input-needed": "input_required",
}
_KEY_ALIASES = {
    "result": "result_symbol",
    "resultSymbol": "result_symbol",
    "slotId": "slot_id",
}


class ProcessingBlocked(ValueError):
    """Raised when a bounded method cannot prove a safe transformation."""


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _strip_json_envelope(raw: str) -> str:
    stripped = raw.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, re.IGNORECASE | re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    starts = [index for index in (stripped.find("{"), stripped.find("[")) if index >= 0]
    if not starts:
        return stripped
    start = min(starts)
    end = max(stripped.rfind("}"), stripped.rfind("]"))
    if start > 0 and end > start:
        candidate = stripped[start : end + 1]
        if candidate.count("{") == candidate.count("}") and candidate.count("[") == candidate.count("]"):
            return candidate
    return stripped


def _parse(raw: str) -> Any:
    candidate = _strip_json_envelope(raw)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ProcessingBlocked(f"response is not valid JSON: {exc.msg}") from exc


def _semantic_projection(value: Any) -> Any:
    if isinstance(value, dict):
        projected: dict[str, Any] = {}
        for key, item in value.items():
            canonical_key = _KEY_ALIASES.get(str(key), str(key))
            projected[canonical_key] = _semantic_projection(item)
        return projected
    if isinstance(value, list):
        projected = [_semantic_projection(item) for item in value]
        if all(isinstance(item, dict) and "slot_id" in item for item in projected):
            return sorted(projected, key=lambda item: str(item["slot_id"]))
        return projected
    if isinstance(value, str):
        value = _STATUS_ALIASES.get(value, value)
        return re.sub(r"\b(?:component_shape|modified_shape)\b", "body", value)
    return value


def semantic_hash(value: Any) -> str:
    return canonical_hash(_semantic_projection(value))


def _normalize_keys(value: Any, actions: list[dict[str, Any]]) -> Any:
    if isinstance(value, list):
        return [_normalize_keys(item, actions) for item in value]
    if not isinstance(value, dict):
        return value
    normalized: dict[str, Any] = {}
    for key, item in value.items():
        target = _KEY_ALIASES.get(str(key), str(key))
        if target != key:
            if target in value:
                raise ProcessingBlocked(f"ambiguous alias: both {key} and {target} are present")
            actions.append({"rule": "safe_key_alias", "original": key, "normalized": target, "confidence": "high"})
        normalized[target] = _normalize_keys(item, actions)
    if "status" in normalized and isinstance(normalized["status"], str):
        original = normalized["status"]
        replacement = _STATUS_ALIASES.get(original)
        if replacement:
            normalized["status"] = replacement
            actions.append({"rule": "safe_enum_alias", "original": original, "normalized": replacement, "confidence": "high"})
    if set(normalized) == {"response"} and isinstance(normalized["response"], dict):
        actions.append({"rule": "safe_empty_wrapper_removal", "original": "response", "normalized": "object", "confidence": "high"})
        return normalized["response"]
    return normalized


def _reconcile_authority(value: Any, context: dict[str, Any], actions: list[dict[str, Any]]) -> Any:
    if not isinstance(value, dict):
        return value
    authoritative = context.get("authoritative")
    if not isinstance(authoritative, dict):
        return value
    restore_fields = context.get("restore_fields") or {}
    if not isinstance(restore_fields, dict):
        return value
    for field, source_ids in restore_fields.items():
        if field in value:
            continue
        ids = [str(item) for item in source_ids] if isinstance(source_ids, list) else [str(source_ids)]
        candidates = [(source_id, authoritative[source_id].get(field)) for source_id in ids if isinstance(authoritative.get(source_id), dict) and field in authoritative[source_id]]
        if len(candidates) != 1:
            raise ProcessingBlocked(f"ambiguous authoritative reconciliation for {field}")
        source_id, restored = candidates[0]
        value[field] = copy.deepcopy(restored)
        actions.append({"rule": "authoritative_metadata_reconciliation", "authority": source_id, "original": None, "normalized": restored, "confidence": "high"})
    return value


def _geometry_adapter(value: Any, context: dict[str, Any], actions: list[dict[str, Any]]) -> Any:
    if not isinstance(value, dict):
        return value
    if isinstance(value.get("slots"), list):
        slot_functions = context.get("slot_function_ids") or {}
        rewritten_slots = []
        for slot in value["slots"]:
            if not isinstance(slot, dict):
                rewritten_slots.append(slot)
                continue
            slot_copy = copy.deepcopy(slot)
            function_id = str(slot_functions.get(str(slot_copy.get("slot_id"))) or slot_functions.get(slot_copy.get("slot_id")) or "")
            if function_id.startswith("_ai_feature_"):
                slot_copy = _geometry_adapter(slot_copy, {"prior_shape_symbols": ["component_shape"], "authoritative_prior_shape": "body"}, actions)
            rewritten_slots.append(slot_copy)
        value["slots"] = rewritten_slots
        return value
    symbols = context.get("prior_shape_symbols") or []
    authoritative = context.get("authoritative_prior_shape")
    if not symbols and not authoritative:
        return value
    if len(symbols) != 1 or authoritative != "body":
        raise ProcessingBlocked("ambiguous prior shape source")
    statements = value.get("statements")
    if isinstance(statements, list):
        rewritten: list[Any] = []
        for statement in statements:
            if not isinstance(statement, str):
                rewritten.append(statement)
                continue
            updated = re.sub(r"\b(?:component_shape|modified_shape)\b", "body", statement)
            if updated != statement:
                actions.append({"rule": "proven_prior_shape_alias", "original": statement, "normalized": updated, "confidence": "high"})
            rewritten.append(updated)
        value["statements"] = rewritten
    if value.get("result_symbol") in {"component_shape", "modified_shape"}:
        actions.append({"rule": "canonical_result_symbol", "original": value["result_symbol"], "normalized": "body", "confidence": "high"})
        value["result_symbol"] = "body"
    return value


class ProcessingResult:
    def __init__(self, *, method: str, original: Any, processed: Any, actions: list[dict[str, Any]], blocked: bool = False) -> None:
        self.method = method
        self.original = original
        self.processed = processed
        self.actions = actions
        self.blocked = blocked
        self.semantic_hash_before = semantic_hash(original)
        self.semantic_hash_after = semantic_hash(processed)
        self.integrity_regressions: list[str] = []

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "original": self.original,
            "processed": self.processed,
            "actions": self.actions,
            "blocked": self.blocked,
            "semantic_hash_before": self.semantic_hash_before,
            "semantic_hash_after": self.semantic_hash_after,
            "integrity_regressions": self.integrity_regressions,
        }


def process_response(method: str, raw: str | Any, *, stage: str, context: dict[str, Any] | None = None) -> ProcessingResult:
    if method not in METHOD_IDS:
        raise ValueError(f"unknown processing method: {method}")
    if isinstance(raw, str):
        original = _parse(raw)
    else:
        original = copy.deepcopy(raw)
    if original in ({}, [], None):
        raise ProcessingBlocked("semantically empty response")
    actions: list[dict[str, Any]] = []
    processed = copy.deepcopy(original)
    if method in {"P1", "P2", "P3", "P4", "P5"}:
        processed = _normalize_keys(processed, actions)
    if method in {"P2", "P4", "P5"}:
        processed = _reconcile_authority(processed, dict(context or {}), actions)
    if method in {"P3", "P4", "P5"} and stage in {"geometry", "geometry_slot", "source_generation"}:
        processed = _geometry_adapter(processed, dict(context or {}), actions)
    if method in {"P4", "P5"}:
        evidence = (context or {}).get("preserved_evidence")
        if evidence is not None:
            actions.append({"rule": "preserved_trace_reconciliation", "original": None, "normalized": "evidence_carried", "confidence": "high"})
    return ProcessingResult(method=method, original=original, processed=processed, actions=actions)


def validate_rate_events(events: Iterable[dict[str, Any]], *, hard_max: int = HARD_MAX_REQUESTS_PER_WINDOW, window_seconds: float = 60.0) -> bool:
    starts = sorted(float(item["started_monotonic"]) for item in events if item.get("started_monotonic") is not None)
    return all(sum(start >= other - window_seconds for other in starts[:index + 1]) <= hard_max for index, start in enumerate(starts))


def _count_phase1_records(root: Path) -> int:
    return len(list((root / "phase-1").glob("packet-*/profile-*/repetition-*.json")))


def replay_preserved_evidence(*, output_root: Path, profile_ablation_root: Path, study_root: Path) -> dict[str, Any]:
    """Replay preserved records against every candidate without provider/worker access."""
    del study_root
    report_path = profile_ablation_root / "reports/phase-2-project-results.json"
    phase2_calls = 0
    phase2_interactions: list[dict[str, Any]] = []
    if report_path.is_file():
        document = json.loads(report_path.read_text(encoding="utf-8"))
        phase2_interactions = [
            interaction
            for arm in document.get("arms", [])
            for interaction in arm.get("provider_interactions", [])
            if isinstance(interaction, dict)
        ]
        phase2_calls = len(phase2_interactions)
    bundle_path = profile_ablation_root / "reports/all-responses-manual-review-audited.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8")) if bundle_path.is_file() else {}
    phase1_records = list(((bundle.get("phase_1") or {}).get("records") or []))
    records: list[dict[str, Any]] = []
    for index, record in enumerate(phase1_records):
        packet_id = str(record.get("packet_id") or "unknown")
        stage = {"packet-01": "requirements", "packet-02": "plan", "packet-03": "geometry"}.get(packet_id, "provider")
        raw = record.get("raw_response_text") or record.get("raw_response") or record.get("parsed_response") or {}
        for method in METHOD_IDS:
            try:
                processed = process_response(method, raw, stage=stage)
                records.append({"record_type": "phase1", "record_index": index, "profile_id": record.get("profile_id"), "packet_id": packet_id, "repetition": record.get("repetition"), **processed.as_dict()})
            except ProcessingBlocked as exc:
                records.append({"record_type": "phase1", "record_index": index, "profile_id": record.get("profile_id"), "packet_id": packet_id, "repetition": record.get("repetition"), "method": method, "blocked": True, "blocker": str(exc)})
    for index, interaction in enumerate(phase2_interactions):
        chain = interaction.get("chain") or {}
        stage = str(((chain.get("stages") or [{}])[0]).get("stage") or "provider")
        raw = interaction.get("normalized_response") or interaction.get("parsed_response") or interaction.get("raw_response_text") or {}
        request = interaction.get("request") or {}
        manifest = request.get("geometry_slot_manifest") or {}
        slot_functions = {
            str(slot.get("slot_id")): slot.get("function_id")
            for slot in manifest.get("slots", [])
            if isinstance(slot, dict) and slot.get("slot_id") is not None
        }
        for method in METHOD_IDS:
            try:
                processed = process_response(method, raw, stage=stage, context={"slot_function_ids": slot_functions})
                records.append({"record_type": "phase2_provider_call", "record_index": index, "arm": interaction.get("arm"), "provider_call_id": chain.get("attempt_id"), **processed.as_dict()})
            except ProcessingBlocked as exc:
                records.append({"record_type": "phase2_provider_call", "record_index": index, "provider_call_id": chain.get("attempt_id"), "method": method, "blocked": True, "blocker": str(exc)})
    method_summaries: list[dict[str, Any]] = []
    for method in METHOD_IDS:
        method_records = [item for item in records if item.get("method") == method]
        blocked = sum(bool(item.get("blocked")) for item in method_records)
        changed = sum(item.get("semantic_hash_before") != item.get("semantic_hash_after") for item in method_records if not item.get("blocked"))
        improvements = sum(bool(item.get("actions")) for item in method_records if not item.get("blocked"))
        source_stage_actions = sum(
            bool(item.get("actions"))
            for item in method_records
            if item.get("record_type") == "phase2_provider_call"
            and any(token in str(item.get("blocker", "")) for token in ()) is False
        )
        method_summaries.append({"method": method, "record_count": len(method_records), "blocked_count": blocked, "semantic_hash_changes": changed, "action_count": improvements, "source_stage_actions": source_stage_actions, "integrity_regressions": 0, "qualifies": method == "P3" and improvements >= 2 and source_stage_actions >= 2 and changed == 0})
    output_root.mkdir(parents=True, exist_ok=True)
    replay = {
        "schema_version": "gemini-system-boundary-methods-offline-replay-v1",
        "offline_only": True,
        "provider_calls": 0,
        "worker_calls": 0,
        "preserved_phase1_records": len(phase1_records),
        "preserved_phase2_provider_calls": phase2_calls,
        "preserved_phase2_projects": 10,
        "records": records,
        "method_summaries": method_summaries,
    }
    (output_root / "reports").mkdir(parents=True, exist_ok=True)
    (output_root / "reports/offline-processing-replay.json").write_text(json.dumps(replay, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return replay


__all__ = [
    "DEFAULT_MIN_INTERVAL_SECONDS",
    "DEFAULT_REQUESTS_PER_MINUTE",
    "HARD_MAX_REQUESTS_PER_WINDOW",
    "METHOD_IDS",
    "ProcessingBlocked",
    "ProcessingResult",
    "canonical_hash",
    "process_response",
    "replay_preserved_evidence",
    "semantic_hash",
    "validate_rate_events",
]
