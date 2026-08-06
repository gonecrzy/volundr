"""Bounded repair policy for complete-source executable CadQuery generation."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import hashlib
from typing import Any


REPAIR_ENVELOPE_SCHEMA_VERSION = "executable-cadquery-repair-envelope-v1"
AUTOMATIC_PROVIDER_OPERATION_BUDGET = 7
REPAIR_LEVEL_BUDGETS = {"L0": 1, "L1": 2, "L2": 1, "L3": 2}

_IMMEDIATE_STOP_FAILURES = {
    "authentication_failure",
    "authorization_failure",
    "database_integrity_failure",
    "artifact_root_escape",
    "missing_provider_credentials",
    "exhausted_transport_policy",
    "worker_environment_failure",
    "protected_fact_regression",
}


def classify_executable_failure(boundary: str, evidence: Mapping[str, Any] | None) -> str:
    """Normalize structured evidence into the repair taxonomy."""

    facts = evidence if isinstance(evidence, Mapping) else {}
    message = str(facts.get("normalized_error") or facts.get("message") or "").lower()
    exception_type = str(facts.get("exception_type") or "").lower()
    boundary = str(boundary or "").lower()

    if boundary == "provider_response" or facts.get("schema_error"):
        return "provider_response_contract_failure"
    if boundary in {"auth", "authentication"}:
        return "authentication_failure"
    if boundary in {"authorization", "permission"}:
        return "authorization_failure"
    if boundary in {"database", "database_integrity"}:
        return "database_integrity_failure"
    if boundary == "artifact" and facts.get("root_escape"):
        return "artifact_root_escape"
    if boundary == "artifact":
        if facts.get("stl_failure"):
            return "stl_export_failure"
        if facts.get("step_failure"):
            return "step_export_failure"
        return "artifact_integrity_failure"
    if boundary == "source_contract":
        if "syntax" in message or "parse" in message:
            return "python_syntax_error"
        return "source_contract_violation"
    if boundary == "execution":
        if facts.get("timed_out") or "timeout" in message:
            return "worker_timeout"
        if exception_type == "nameerror" or "nameerror" in message:
            return "python_name_error"
        if exception_type == "typeerror" or "typeerror" in message:
            return "python_type_error"
        if "selector" in message or "selector" in exception_type:
            return "cadquery_selector_error"
        if "cadquery" in message or "ocp" in message:
            return "cadquery_api_error"
        return "source_execution_error"
    if boundary == "topology":
        if facts.get("empty") or facts.get("volume", 1) in {0, 0.0, None}:
            return "empty_shape"
        if facts.get("unsupported"):
            return "unsupported_shape"
        if facts.get("invalid") or facts.get("valid") is False:
            if facts.get("expected_solid_count") != facts.get("detected_solid_count"):
                return "solid_count_mismatch"
            return "invalid_shape"
        if facts.get("expected_solid_count") != facts.get("detected_solid_count"):
            return "solid_count_mismatch"
        return "topology_validation_failure"
    if boundary in {"semantic", "semantic_verification", "protected_facts"}:
        if facts.get("protected_fact_regression") or facts.get("regressed"):
            return "protected_fact_regression"
        if facts.get("unverifiable"):
            return "semantic_requirement_unverifiable"
        return "semantic_requirement_failed"
    if facts.get("worker_environment_failure"):
        return "worker_environment_failure"
    if facts.get("missing_provider_credentials"):
        return "missing_provider_credentials"
    return "source_execution_error"


def build_executable_cadquery_repair_envelope(
    *,
    repair_level: str,
    generation_session_id: str,
    logical_operation_id: str,
    parent_operation_id: str | None,
    repair_ordinal: int,
    previous_source: str | None,
    previous_source_hash: str | None,
    previous_result_hash: str | None,
    design_contract: Mapping[str, Any],
    provider_attempt: Mapping[str, Any] | None = None,
    worker_result: Mapping[str, Any] | None = None,
    topology_result: Mapping[str, Any] | None = None,
    semantic_result: Mapping[str, Any] | None = None,
    protected_facts: list[Mapping[str, Any]] | None = None,
    repair_history: list[Mapping[str, Any]] | None = None,
    requested_delta: str | None = None,
) -> dict[str, Any]:
    """Build a versioned fact envelope without adding implementation advice."""

    if repair_level not in {"L0", "L1", "L2", "L3", "L4"}:
        raise ValueError(f"unsupported executable repair level: {repair_level}")
    worker = _structured_facts(worker_result)
    contract = _structured_facts(design_contract)
    output_ids = sorted(
        str(item.get("output_id"))
        for item in contract.get("outputs", [])
        if isinstance(item, Mapping) and item.get("output_id")
    )
    if not output_ids:
        output_ids = sorted(
            str(item)
            for item in worker.get("output_ids", [])
            if item is not None
        )
    return {
        "schema_version": REPAIR_ENVELOPE_SCHEMA_VERSION,
        "repair_level": repair_level,
        "generation_session_id": generation_session_id,
        "logical_operation_id": logical_operation_id,
        "parent_operation_id": parent_operation_id,
        "repair_ordinal": int(repair_ordinal),
        "canonical_output_ids": output_ids,
        "design_contract": contract,
        "previous_complete_source": previous_source,
        "previous_source_hash": previous_source_hash,
        "previous_result_hash": previous_result_hash,
        "provider_attempt": _structured_facts(provider_attempt),
        "worker_result": worker,
        "topology_result": _structured_facts(topology_result),
        "semantic_result": _structured_facts(semantic_result),
        "protected_facts": _structured_facts(protected_facts or []),
        "repair_history": _structured_facts(repair_history or []),
        "requested_delta": requested_delta,
    }


def compare_executable_progress(
    repair_level: str,
    *,
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compare only measurable result facts relevant to the active level."""

    before = previous if isinstance(previous, Mapping) else {}
    after = current if isinstance(current, Mapping) else {}
    reasons: list[str] = []
    if repair_level == "L1":
        if _number(after.get("phase_index")) > _number(before.get("phase_index")):
            reasons.append("later_execution_phase")
        before_outputs = set(before.get("completed_output_ids") or [])
        after_outputs = set(after.get("completed_output_ids") or [])
        if after_outputs > before_outputs:
            reasons.append("additional_required_output")
        if before.get("error_signature") and before.get("error_signature") != after.get("error_signature"):
            reasons.append("prior_error_signature_removed")
    elif repair_level == "L2":
        if before.get("valid") is not True and after.get("valid") is True:
            reasons.append("topology_became_valid")
        if _number(after.get("detected_solid_count")) == _number(after.get("expected_solid_count")) and _number(before.get("detected_solid_count")) != _number(before.get("expected_solid_count")):
            reasons.append("solid_count_reached_expected")
    elif repair_level == "L3":
        before_failed = set(before.get("failed_requirement_ids") or [])
        after_failed = set(after.get("failed_requirement_ids") or [])
        before_passed = set(before.get("passed_requirement_ids") or [])
        after_passed = set(after.get("passed_requirement_ids") or [])
        if len(after_failed) < len(before_failed):
            reasons.append("failed_obligation_count_decreased")
        if after_passed > before_passed:
            reasons.append("additional_requirement_pass")
        if len(after.get("unverifiable_requirement_ids") or []) < len(before.get("unverifiable_requirement_ids") or []):
            reasons.append("measurement_became_available")
    elif repair_level == "L0":
        if before.get("contract_valid") is not True and after.get("contract_valid") is True:
            reasons.append("source_contract_passed")
        if before.get("failure_signature") and before.get("failure_signature") != after.get("failure_signature"):
            reasons.append("contract_failure_signature_removed")
    elif repair_level == "L4":
        if after.get("requested_delta_applied") is True:
            reasons.append("requested_delta_applied")

    protected_regression = bool(after.get("protected_fact_regression"))
    if protected_regression:
        reasons.append("protected_fact_regression")
    return {
        "repair_level": repair_level,
        "measurable_progress": bool(reasons) and not protected_regression,
        "protected_fact_regression": protected_regression,
        "progress_reasons": reasons,
        "progress_result": "regressed" if protected_regression else "progressed" if reasons else "no_progress",
    }


def decide_executable_repair(
    *,
    repair_level: str,
    repair_ordinal: int,
    source_hash: str | None,
    previous_source_hash: str | None,
    failure_class: str,
    previous_failure_class: str | None,
    progress: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply terminal conditions and per-level repair budgets."""

    if progress.get("protected_fact_regression") or failure_class == "protected_fact_regression":
        return {
            "decision": "stop",
            "stop_reason": "protected_fact_regression",
            "progress_result": "regressed",
        }
    if failure_class in _IMMEDIATE_STOP_FAILURES:
        return {
            "decision": "stop",
            "stop_reason": failure_class,
            "progress_result": "blocked",
        }
    if source_hash and previous_source_hash and source_hash == previous_source_hash:
        return {
            "decision": "stop",
            "stop_reason": "repeated_source_hash",
            "progress_result": "no_progress",
        }
    if not progress.get("measurable_progress", False):
        if failure_class == previous_failure_class and previous_failure_class:
            reason = "repeated_normalized_error"
        else:
            reason = "no_measurable_progress"
        return {
            "decision": "stop",
            "stop_reason": reason,
            "progress_result": "no_progress",
        }
    budget = REPAIR_LEVEL_BUDGETS.get(repair_level, 0)
    if repair_ordinal >= budget:
        return {
            "decision": "stop",
            "stop_reason": "repair_budget_exhausted",
            "progress_result": "progressed",
        }
    return {
        "decision": "repair",
        "stop_reason": None,
        "progress_result": "progressed",
    }


def _structured_facts(value: Any) -> Any:
    """Copy structured evidence while excluding unsafe diagnostic channels."""

    forbidden_keys = {
        "traceback",
        "host_path",
        "host_paths",
        "environment",
        "env",
        "prompt",
        "raw_prompt",
        "api_key",
        "token",
        "stdout",
        "stderr",
    }
    if isinstance(value, Mapping):
        return {
            str(key): _structured_facts(item)
            for key, item in value.items()
            if str(key).lower() not in forbidden_keys
        }
    if isinstance(value, (list, tuple)):
        return [_structured_facts(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("-inf")


def source_result_hash(payload: Mapping[str, Any]) -> str:
    """Hash a normalized structured result for durable repeat detection."""

    encoded = repr(_structured_facts(payload)).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
