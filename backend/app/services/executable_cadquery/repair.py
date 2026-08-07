"""Bounded repair policy for complete-source executable CadQuery generation."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import hashlib
import re
from typing import Any

from app.services.executable_cadquery.dialect import (
    CADQUERY_V1_SOURCE_SKELETON,
    cadquery_v1_source_dialect,
    cadquery_v1_source_dialect_hash,
    cadquery_v1_source_skeleton_hash,
)
from app.services.executable_cadquery.recovery import RecoveryRouter


REPAIR_ENVELOPE_SCHEMA_VERSION = "executable-cadquery-repair-envelope-v1"
AUTOMATIC_PROVIDER_OPERATION_BUDGET = 9
REPAIR_LEVEL_BUDGETS = {"L0": 3, "L1": 3, "L2": 2, "L3": 4}

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
    """Compatibility wrapper around the centralized recovery classifier."""

    return RecoveryRouter.classify_failure(boundary, evidence)


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
    previous_provider_response: str | None = None,
    previous_normalized_error: str | None = None,
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
    if not isinstance(worker, Mapping):
        worker = {}
    contract = _structured_facts(design_contract)
    if not isinstance(contract, Mapping):
        contract = {}
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
    expected_output_policy = [
        {
            key: item[key]
            for key in ("output_id", "required", "expected_solid_count", "allow_disconnected_solids")
            if key in item
        }
        for item in contract.get("outputs", [])
        if isinstance(item, Mapping) and item.get("output_id")
    ]
    topology = _structured_facts(topology_result)
    if not isinstance(topology, Mapping):
        topology = {}
    topology_outputs = topology.get("outputs") if isinstance(topology, Mapping) else None
    if isinstance(topology_outputs, Mapping):
        failing_output_ids = sorted(
            str(output_id)
            for output_id, item in topology_outputs.items()
            if isinstance(item, Mapping) and item.get("valid") is False
        )
        preserved_valid_output_ids = sorted(
            str(output_id)
            for output_id, item in topology_outputs.items()
            if isinstance(item, Mapping) and item.get("valid") is True
        )
    else:
        output_id = topology.get("output_id") if isinstance(topology, Mapping) else None
        failing_output_ids = [str(output_id)] if topology.get("valid") is False and output_id else []
        preserved_valid_output_ids = [str(output_id)] if topology.get("valid") is True and output_id else []
    structured_history = _structured_facts(repair_history or [])
    topology_attempt_history = [
        item
        for item in structured_history
        if isinstance(item, Mapping) and item.get("topology_result") is not None
    ]
    execution_diagnostic = _structured_facts(worker.get("execution_diagnostics") or worker.get("diagnostics") or {})
    semantic_repair_facts = _semantic_repair_facts(semantic_result, contract)
    return {
        "schema_version": REPAIR_ENVELOPE_SCHEMA_VERSION,
        "repair_level": repair_level,
        "generation_session_id": generation_session_id,
        "logical_operation_id": logical_operation_id,
        "parent_operation_id": parent_operation_id,
        "repair_ordinal": int(repair_ordinal),
        "canonical_output_ids": output_ids,
        "design_contract": contract,
        "source_dialect": cadquery_v1_source_dialect(),
        "source_dialect_hash": cadquery_v1_source_dialect_hash(),
        "canonical_source_skeleton": CADQUERY_V1_SOURCE_SKELETON,
        "canonical_source_skeleton_hash": cadquery_v1_source_skeleton_hash(),
        "replacement_instruction": (
            "Return one complete replacement implementation; do not return a patch, excerpt, or construction strategy."
        ),
        "previous_complete_source": previous_source,
        "previous_source_hash": previous_source_hash,
        "previous_result_hash": previous_result_hash,
        "prior_provider_response": previous_provider_response,
        "prior_normalized_error": _redact_normalized_error(previous_normalized_error),
        "provider_attempt": _structured_facts(provider_attempt),
        "worker_result": worker,
        "execution_diagnostic": execution_diagnostic,
        "expected_output_policy": expected_output_policy,
        "topology_result": topology,
        "topology_attempt_history": topology_attempt_history,
        "prior_l2_attempt_metrics": _prior_l2_attempt_metrics(structured_history),
        "failing_output_ids": failing_output_ids,
        "preserved_valid_output_ids": preserved_valid_output_ids,
        "semantic_result": _structured_facts(semantic_result),
        "passed_machine_requirements": semantic_repair_facts["passed_machine_requirements"],
        "failed_machine_requirements": semantic_repair_facts["failed_machine_requirements"],
        "semantic_repair_facts": semantic_repair_facts["failed_facts"],
        "protected_facts": _structured_facts(protected_facts or []),
        "repair_history": _structured_facts(repair_history or []),
        "requested_delta": requested_delta,
    }


def _semantic_repair_facts(
    semantic_result: Mapping[str, Any] | None,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Project machine-required semantic facts into a repair-safe envelope."""

    semantic = semantic_result if isinstance(semantic_result, Mapping) else {}
    findings = {
        str(item.get("requirement_id")): item
        for item in semantic.get("findings", [])
        if isinstance(item, Mapping) and item.get("requirement_id")
    }
    passed_claims = {str(item) for item in semantic.get("passed", []) if item}
    failed_claims = {str(item) for item in semantic.get("failed", []) if item}
    passed: list[str] = []
    failed: list[str] = []
    failed_facts: list[dict[str, Any]] = []
    for requirement in contract.get("requirements", []):
        if not isinstance(requirement, Mapping) or not requirement.get("requirement_id"):
            continue
        requirement_id = str(requirement["requirement_id"])
        if str(requirement.get("policy") or "machine_required") != "machine_required":
            continue
        finding = findings.get(requirement_id, {})
        observed = str(finding.get("result") or finding.get("status") or "")
        is_passed = observed in {"passed", "verified"} or requirement_id in passed_claims
        is_failed = observed in {"failed", "violated"} or requirement_id in failed_claims
        if is_passed:
            passed.append(requirement_id)
        if is_failed:
            failed.append(requirement_id)
            failed_facts.append(
                {
                    "requirement_id": requirement_id,
                    "expected_value": _structured_facts(
                        finding.get("expected_value", requirement.get("expected"))
                    ),
                    "measured_value": _structured_facts(
                        finding.get("measured_value", finding.get("measurements"))
                    ),
                    "tolerance": finding.get("tolerance", requirement.get("tolerance")),
                    "measurement_method": finding.get(
                        "verification_policy", requirement.get("verification_policy")
                    ),
                    "measurement_source": finding.get("evidence_source") or "final_mesh",
                    "status": "failed",
                }
            )
    return {
        "passed_machine_requirements": passed,
        "failed_machine_requirements": failed,
        "failed_facts": failed_facts,
    }


def _prior_l2_attempt_metrics(history: Any) -> list[dict[str, Any]]:
    """Project prior L2 attempts into a compact, neutral metric record."""

    metrics: list[dict[str, Any]] = []
    for item in history if isinstance(history, list) else []:
        if not isinstance(item, Mapping) or item.get("repair_level") != "L2":
            continue
        topology = item.get("topology_result")
        if not isinstance(topology, Mapping):
            continue
        metrics.append(
            {
                "attempt_number": item.get("attempt_number"),
                "repair_level": "L2",
                "source_hash": item.get("source_hash"),
                "result_hash": item.get("result_hash"),
                "topology": dict(topology),
            }
        )
    return metrics


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
    same_diagnostic_signature = bool(
        before.get("diagnostic_signature")
        and before.get("diagnostic_signature") == after.get("diagnostic_signature")
    )
    if repair_level == "L1":
        if _number(after.get("phase_index")) > _number(before.get("phase_index")):
            reasons.append("later_execution_phase")
        before_outputs = set(before.get("completed_output_ids") or [])
        after_outputs = set(after.get("completed_output_ids") or [])
        if after_outputs > before_outputs:
            reasons.append("additional_required_output")
        before_error_signature = before.get("error_signature") or before.get("failure_signature")
        after_error_signature = after.get("error_signature") or after.get("failure_signature")
        if before_error_signature and before_error_signature != after_error_signature:
            reasons.append("prior_error_signature_removed")
        if before.get("diagnostic_signature") and before.get("diagnostic_signature") != after.get("diagnostic_signature"):
            reasons.append("execution_diagnostic_changed")
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
        violation_count_decreased = (
            _number(after.get("violation_count")) < _number(before.get("violation_count"))
        )
        no_decrease_streak = (
            int(before.get("no_violation_decrease_streak") or 0) + 1
            if before.get("violation_count") is not None
            and after.get("violation_count") is not None
            and not violation_count_decreased
            else 0
        )
        if before.get("contract_valid") is not True and after.get("contract_valid") is True:
            reasons.append("source_contract_passed")
        if (
            before.get("extracted_source_hash")
            and before.get("extracted_source_hash") != after.get("extracted_source_hash")
        ):
            reasons.append("extracted_source_hash_changed")
        if (
            before.get("diagnostic_signature")
            and before.get("diagnostic_signature") != after.get("diagnostic_signature")
        ):
            reasons.append("diagnostic_code_changed")
        if violation_count_decreased:
            reasons.append("violation_count_decreased")
        if before.get("syntax_valid") is False and after.get("syntax_valid") is True:
            reasons.append("syntax_became_valid")
        if before.get("failure_signature") and before.get("failure_signature") != after.get("failure_signature"):
            reasons.append("contract_failure_signature_removed")
        if (
            before.get("no_violation_decrease_streak", 0) >= 2
            or (same_diagnostic_signature and not violation_count_decreased)
        ):
            reasons.clear()
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
        "same_diagnostic_signature": same_diagnostic_signature,
        "violation_count_decreased": (
            repair_level == "L0"
            and _number(after.get("violation_count")) < _number(before.get("violation_count"))
        ),
        "no_violation_decrease_streak": (
            no_decrease_streak if repair_level == "L0" else 0
        ),
        "no_violation_decrease_across_two_repairs": (
            repair_level == "L0" and no_decrease_streak >= 2
        ),
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
    if (
        repair_level == "L0"
        and progress.get("same_diagnostic_signature")
        and not progress.get("violation_count_decreased")
    ):
        return {
            "decision": "stop",
            "stop_reason": "repeated_normalized_error",
            "progress_result": "no_progress",
        }
    if repair_level == "L0" and progress.get("no_violation_decrease_across_two_repairs"):
        return {
            "decision": "stop",
            "stop_reason": "no_violation_decrease_across_two_repairs",
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


def _redact_normalized_error(value: str | None) -> str | None:
    if value is None:
        return None
    redacted = re.sub(
        r"(?i)(?:GEMINI_API_KEY_2|GEMINI_API_KEY|api[_-]?key|authorization|token)\s*[=:]\s*[^\s,;]+",
        "[redacted]",
        str(value),
    )
    redacted = re.sub(r"(?i)(?:/root/|/home/|/users/|[A-Za-z]:[\\/])[^\s,;]+", "[path]", redacted)
    return redacted[:800]


def source_result_hash(payload: Mapping[str, Any]) -> str:
    """Hash a normalized structured result for durable repeat detection."""

    encoded = repr(_structured_facts(payload)).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
