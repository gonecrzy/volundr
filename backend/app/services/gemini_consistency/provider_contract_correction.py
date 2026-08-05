"""Pure methodology corrections for the Gemini provider-contract continuation.

This module deliberately contains no provider, worker, parser, or production
configuration dependency. It classifies study evidence and validates the
corrected bounded-repair contract only.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .geometry_slot_canonicalizer import GeometrySlotContractCanonicalizer


TRANSPORT_RESULTS = {"transport_failure", "quota_failure"}
QUALITY_PASS = {"pass", "pass_with_benign_format_variation"}
STAGES = ("requirements", "plan", "geometry", "repair")


def corrected_content_denominator(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Exclude transport/quota outcomes from content denominators."""
    transport = [item for item in records if item.get("intrinsic_quality", {}).get("result") in TRANSPORT_RESULTS or item.get("status_code") in {408, 429, 502, 503, 504, 599}]
    content = [item for item in records if item not in transport]
    passes = [item for item in content if item.get("intrinsic_quality", {}).get("result") in QUALITY_PASS]
    failures = [item for item in content if item not in passes]
    return {
        "total_records": len(records),
        "content_bearing_responses": len(content),
        "content_passes": len(passes),
        "content_failures": len(failures),
        "content_pass_rate": round(len(passes) / len(content), 6) if content else None,
        "transport_failures": sum(item.get("status_code") in {408, 502, 503, 504, 599} or item.get("intrinsic_quality", {}).get("result") == "transport_failure" for item in transport),
        "quota_failures": sum(item.get("status_code") == 429 or item.get("intrinsic_quality", {}).get("result") == "quota_failure" for item in transport),
        "transport_excluded_from_content": True,
    }


def select_settings_from_content(profile_summaries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Select settings only from content evidence, never transport completion."""
    qualified = [profile for profile, summary in profile_summaries.items() if summary.get("content_bearing_responses", 0) and summary.get("content_pass_rate") == 1.0]
    if not qualified:
        decision = "no_settings_profile_qualified"
    elif len(qualified) == 1:
        decision = qualified[0]
    else:
        ranked = sorted(qualified, key=lambda profile: (profile_summaries[profile].get("contract_entropy", 1.0), profile))
        first, second = ranked[:2]
        if profile_summaries[first].get("contract_entropy") is not None and profile_summaries[first].get("contract_entropy") < profile_summaries[second].get("contract_entropy"):
            decision = first
        else:
            decision = "settings_tie_requires_larger_holdout"
    return {
        "decision": decision,
        "qualified_by_content": qualified,
        "content_denominators": {profile: summary.get("content_bearing_responses", 0) for profile, summary in profile_summaries.items()},
        "content_pass_rates": {profile: summary.get("content_pass_rate") for profile, summary in profile_summaries.items()},
        "transport_failures": {profile: summary.get("transport_failures", 0) for profile, summary in profile_summaries.items()},
        "transport_cannot_disqualify": True,
    }


def evaluate_requirements_correction(packet: dict[str, Any], response: Any) -> dict[str, Any]:
    """Evaluate the narrow missing-fit contract used by the correction study."""
    if not isinstance(response, dict):
        return {"result": "fail_structural_emptiness", "reasons": ["requirements response is not an object"]}
    facts = packet.get("frozen_facts") or {}
    expectations = packet.get("intrinsic_expectations") or {}
    missing_terms = [str(item).casefold() for item in expectations.get("must_request", [])]
    text = json_like_text(response)
    clarification = bool(response.get("clarification_required"))
    questions = json_like_text(response.get("clarification_questions", []))
    if missing_terms:
        missing_questions = [term for term in missing_terms if not _term_tokens_present(term, questions)]
        if missing_questions:
            return {"result": "fail_missing_critical_meaning", "reasons": [f"missing clarification question: {term}" for term in missing_questions]}
        if not clarification or bool(response.get("generation_ready")):
            return {"result": "fail_invented_critical_meaning", "reasons": ["critical fit facts were not a blocking clarification"]}
        return {"result": "pass", "clarification_required": True, "requested_terms": missing_terms}
    preservation_terms = [str(item).casefold() for item in expectations.get("must_preserve", [])]
    missing_preserved = [term for term in preservation_terms if term not in text]
    if missing_preserved:
        return {"result": "fail_missing_meaning", "reasons": [f"preserved requirement absent: {term}" for term in missing_preserved]}
    forbidden = [str(item).casefold() for item in expectations.get("must_not_claim", [])]
    claimed_forbidden = [term for term in forbidden if term in text]
    if claimed_forbidden:
        return {"result": "fail_invented_critical_meaning", "reasons": [f"unsafe claim: {term}" for term in claimed_forbidden]}
    return {"result": "pass"}


def _term_tokens_present(term: str, text: str) -> bool:
    """Accept ordinary word-order variation such as ``diameter of the cable``."""
    tokens = [token for token in term.replace("_", " ").split() if token not in {"with", "the", "of", "and"}]
    return bool(tokens) and all(token in text for token in tokens)


def json_like_text(value: Any) -> str:
    """Return deterministic searchable text without depending on a parser."""
    import json

    return json.dumps(value, sort_keys=True, default=str).casefold()


def source_contract_passed(record: dict[str, Any]) -> bool:
    """Whether the assembled provider source passed Volundr's source gate."""
    chain = record.get("chain") or record.get("diagnostic_current_build", {}).get("current_build_chain") or {}
    stages = chain.get("stages") or []
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        if stage.get("source_contract_passed_hard_checks") is True:
            return True
        if stage.get("source_contract_result") in {"passed", "pass", "valid"}:
            return True
    return bool(record.get("source_contract_passed") or record.get("source_contract_result") in {"passed", "pass", "valid"})


def worker_reach_semantics(record: dict[str, Any]) -> dict[str, Any]:
    """Classify worker reach independently from CAD/topology success."""
    chain = record.get("chain") or record.get("diagnostic_current_build", {}).get("current_build_chain") or {}
    stages = chain.get("stages") or []
    worker = record.get("worker") or record.get("worker_result") or {}
    worker_event = record.get("worker_event") or {}
    job_id = record.get("worker_job_id") or worker.get("job_id") or worker_event.get("job_id")
    submitted = bool(record.get("worker_submitted") or record.get("source_submitted") or job_id)
    runtime_failed = bool(
        record.get("worker_runtime_failed")
        or worker.get("runtime_error")
        or worker.get("error_category") in {"runtime", "cadquery", "worker_runtime"}
        or worker.get("status") in {"runtime_failed", "failed_runtime"}
    )
    completed = bool(record.get("worker_completed") or worker.get("completed") or worker.get("status") in {"completed", "succeeded", "failed"})
    stage_worker = any(isinstance(item, dict) and (item.get("worker_job_id") or item.get("worker_reached") or item.get("worker_submitted")) for item in stages)
    reached = bool(record.get("worker_reached") or submitted or runtime_failed or completed or stage_worker)
    return {
        "source_contract_passed": source_contract_passed(record),
        "worker_ready_valid_source": source_contract_passed(record) and submitted,
        "worker_reached": reached,
        "worker_completed": completed,
        "worker_runtime_failed": runtime_failed,
        "job_id": job_id,
        "worker_reach_inferred_from_runtime_failure": runtime_failed and reached,
    }


def clarification_outcome(*, facts: dict[str, Any], response: Any, answer_submitted: bool, resumed: bool) -> str:
    """Apply the frozen clarification taxonomy deterministically."""
    response = response if isinstance(response, dict) else {}
    missing = [key for key, value in facts.items() if value in {None, "missing", "unknown"}]
    required = bool(missing)
    requested = bool(response.get("clarification_required"))
    if required and requested and not answer_submitted:
        return "clarification_not_answered"
    if required and requested and answer_submitted and resumed:
        return "clarification_answered"
    if required and requested and answer_submitted and not resumed:
        return "clarification_answer_failed"
    if required and not requested:
        return "clarification_required_incorrectly"
    if not required and requested:
        return "clarification_required_incorrectly"
    return "clarification_not_required"


def earliest_blocker(*, stages: list[dict[str, Any]], default: str = "interrupted") -> str:
    order = {stage: index for index, stage in enumerate(STAGES)}
    for stage in sorted(stages, key=lambda item: order.get(str(item.get("stage")), len(order))):
        blocker = stage.get("blocker")
        if blocker:
            return str(blocker)
    return default


def furthest_valid_stage(*, stages: list[dict[str, Any]], default: str = "project_created") -> str:
    stage_names = [str(item.get("stage")) for item in stages if item.get("reached") and item.get("passed")]
    if not stage_names:
        return default
    order = {stage: index for index, stage in enumerate(STAGES)}
    return max(stage_names, key=lambda stage: order.get(stage, -1))


def holdout_configuration_audit(record: dict[str, Any], *, selected_thinking_profile: str) -> dict[str, Any]:
    actual = record.get("thinking_profile")
    config = record.get("generation_config") or {}
    if actual == "H0-current-stage-specific":
        classification = "holdout_h0_current_stage_specific"
    elif actual != selected_thinking_profile:
        classification = "holdout_wrong_thinking_configuration"
    else:
        classification = "selected_thinking_configuration"
    return {
        "actual_thinking_profile": actual,
        "selected_thinking_profile": selected_thinking_profile,
        "explicit_thinking_config_present": "thinkingConfig" in config,
        "selected_configuration_valid": classification == "selected_thinking_configuration" and (actual != "H1-provider-default" or "thinkingConfig" not in config),
        "classification": classification,
    }


def repair_packet_validity(packet: dict[str, Any]) -> dict[str, Any]:
    facts = packet.get("frozen_facts") or {}
    source = packet.get("repair_source")
    reasons: list[str] = []
    if not isinstance(source, dict) or not isinstance(source.get("slots"), list) or not source.get("slots"):
        reasons.append("complete original response or invalid slot is absent")
    if not facts.get("invalid_slot_ids"):
        reasons.append("invalid slot IDs are absent")
    if not facts.get("completed_slot_ids"):
        reasons.append("completed immutable slot IDs are absent")
    valid = not reasons
    return {"valid": valid, "classification": "valid_repair_packet" if valid else "invalid_test_packet_missing_repair_source", "reasons": reasons}


def _slot_map(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        return {}
    return {str(item.get("slot_id")): item for item in value if isinstance(item, dict) and item.get("slot_id") is not None}


def evaluate_bounded_repair(packet: dict[str, Any], response: Any) -> dict[str, Any]:
    validity = repair_packet_validity(packet)
    if not validity["valid"]:
        return {"result": validity["classification"], "reasons": validity["reasons"]}
    if not isinstance(response, dict):
        return {"result": "fail_incomplete", "reasons": ["repair response is not an object"]}
    repaired = response.get("repaired_items")
    if not isinstance(repaired, list) or not repaired:
        return {"result": "fail_incomplete", "reasons": ["actual repaired payload is absent"]}
    facts = packet["frozen_facts"]
    invalid_ids = {str(item) for item in facts["invalid_slot_ids"]}
    completed_ids = {str(item) for item in facts["completed_slot_ids"]}
    source_slots = _slot_map(packet["repair_source"].get("slots"))
    repaired_ids: set[str] = set()
    for item in repaired:
        if not isinstance(item, dict) or not item.get("statements"):
            return {"result": "fail_incomplete", "reasons": ["repaired item has no statements"]}
        slot_id = str(item.get("slot_id"))
        repaired_ids.add(slot_id)
        if slot_id not in invalid_ids:
            return {"result": "fail_conflicting", "reasons": [f"repaired slot {slot_id} is outside repair boundary"]}
        if item.get("result_symbol") != facts.get("required_result_symbol", "body"):
            return {"result": "fail_conflicting", "reasons": [f"slot {slot_id} has wrong result symbol"]}
        statements = "\n".join(str(statement) for statement in item.get("statements", []))
        source = source_slots.get(slot_id) or {}
        source_statements = "\n".join(str(statement) for statement in source.get("statements", []))
        required_symbol = str(facts.get("required_result_symbol", "body"))
        invalid_symbol = str(source.get("result_symbol") or "")
        if invalid_symbol and invalid_symbol != required_symbol and f"{invalid_symbol} =" in statements:
            return {"result": "fail_conflicting", "reasons": [f"slot {slot_id} still assigns invalid result symbol {invalid_symbol}"]}
        if "prior_shape = prior_shape" in source_statements and "prior_shape = prior_shape" in statements:
            return {"result": "fail_conflicting", "reasons": [f"slot {slot_id} still uses the undefined prior-shape alias"]}
        if "radius_value" in source_statements and "radius_value" in statements:
            return {"result": "fail_conflicting", "reasons": [f"slot {slot_id} still uses the invalid CadQuery keyword"]}
    if repaired_ids != invalid_ids:
        return {"result": "fail_incomplete", "reasons": ["not every invalid slot was replaced"]}
    if {str(item) for item in response.get("preserved_item_ids", [])} != completed_ids:
        return {"result": "fail_conflicting", "reasons": ["completed immutable slots were not preserved by identity"]}
    for slot_id in completed_ids:
        if slot_id not in source_slots:
            return {"result": "fail_conflicting", "reasons": [f"completed source slot {slot_id} is missing"]}
    if response.get("rejected_changes") is not None and not isinstance(response.get("rejected_changes"), list):
        return {"result": "fail_conflicting", "reasons": ["rejected_changes is not a list"]}
    if response.get("applied_changes"):
        return {"result": "fail_conflicting", "reasons": ["repair includes applied unrelated changes"]}
    return {"result": "pass", "repaired_slot_ids": sorted(repaired_ids), "preserved_slot_ids": sorted(completed_ids), "semantic_change_boundary": "declared invalid slots only", "source_snapshot": deepcopy(packet["repair_source"])}


def evaluate_executable_repair(packet: dict[str, Any], response: Any) -> dict[str, Any]:
    """Evaluate a complete model-owned replacement for a source-bearing packet."""
    validity = repair_packet_validity(packet)
    if not validity["valid"]:
        return {"result": validity["classification"], "reasons": validity["reasons"]}
    if not isinstance(response, dict) or not isinstance(response.get("repaired_items"), list):
        return {"result": "fail_incomplete", "reasons": ["complete repaired_items payload is absent"]}
    facts = packet["frozen_facts"]
    invalid_ids = {str(item) for item in facts["invalid_slot_ids"]}
    completed_ids = {str(item) for item in facts["completed_slot_ids"]}
    repaired_items = response["repaired_items"]
    repaired_ids = [str(item.get("slot_id")) for item in repaired_items if isinstance(item, dict)]
    if len(repaired_items) != len(invalid_ids) or set(repaired_ids) != invalid_ids or len(repaired_ids) != len(set(repaired_ids)):
        return {"result": "fail_incomplete", "reasons": ["exactly one replacement item per invalid slot is required"]}
    if {str(item) for item in response.get("preserved_item_ids", [])} != completed_ids:
        return {"result": "fail_conflicting", "reasons": ["completed protected items were not preserved"]}
    source_by_id = _slot_map(packet["repair_source"].get("slots"))
    for item in repaired_items:
        if not isinstance(item, dict) or not isinstance(item.get("statements"), list) or not item["statements"]:
            return {"result": "fail_incomplete", "reasons": ["replacement item has no executable statements"]}
        if item.get("result_symbol") != facts.get("required_result_symbol", "body"):
            return {"result": "fail_conflicting", "reasons": ["result_symbol does not match required result symbol"]}
        statements = [str(statement) for statement in item["statements"]]
        text = "\n".join(statements)
        for defect in facts.get("defect_patterns", []):
            if str(defect).casefold().startswith("missing "):
                continue
            if _compact(str(defect)) in _compact(text):
                return {"result": "fail_conflicting", "reasons": [f"declared defect remains: {defect}"]}
        for required_statement in facts.get("required_statements", []):
            if _compact(str(required_statement)) not in _compact(text):
                return {"result": "fail_incomplete", "reasons": [f"required repaired operation is absent: {required_statement}"]}
        operation_family = str(facts.get("expected_operation_family") or "")
        if operation_family and operation_family.casefold() not in text.casefold():
            return {"result": "fail_wrong_geometry_strategy", "reasons": [f"expected operation family is absent: {operation_family}"]}
        for key, value in (facts.get("protected_dimensions") or {}).items():
            if str(value) not in text:
                return {"result": "fail_conflicting", "reasons": [f"protected dimension {key}={value} changed or disappeared"]}
        allowed = set(str(name) for name in facts.get("allowed_names", [])) | {str(facts.get("required_result_symbol", "body"))}
        validation = GeometrySlotContractCanonicalizer().validate({"required_result_symbol": facts.get("required_result_symbol", "body"), "allowed_names": sorted(allowed)}, statements)
        if not validation["valid"]:
            return {"result": "fail_conflicting", "reasons": [validation["reason"]]}
        if str(item.get("slot_id")) not in source_by_id:
            return {"result": "fail_conflicting", "reasons": ["replacement slot is absent from source manifest"]}
    if response.get("rejected_changes") is not None and not isinstance(response.get("rejected_changes"), list):
        return {"result": "fail_conflicting", "reasons": ["rejected_changes is not a list"]}
    if response.get("applied_changes"):
        return {"result": "fail_conflicting", "reasons": ["unauthorized changes were applied"]}
    return {"result": "pass", "repaired_slot_ids": sorted(invalid_ids), "preserved_slot_ids": sorted(completed_ids), "executable_replacement": True, "semantic_signature": canonical_repair_signature(response)}


def canonical_repair_signature(response: Any) -> str:
    items = response.get("repaired_items", []) if isinstance(response, dict) else []
    normalized = sorted((item for item in items if isinstance(item, dict)), key=lambda item: str(item.get("slot_id")))
    return json_like_hash(normalized)


def json_like_hash(value: Any) -> str:
    import hashlib
    import json

    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


__all__ = [
    "corrected_content_denominator",
    "clarification_outcome",
    "earliest_blocker",
    "evaluate_bounded_repair",
    "evaluate_executable_repair",
    "evaluate_requirements_correction",
    "furthest_valid_stage",
    "holdout_configuration_audit",
    "repair_packet_validity",
    "select_settings_from_content",
    "source_contract_passed",
    "worker_reach_semantics",
]
