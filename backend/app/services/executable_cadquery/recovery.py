"""Central recovery policy and routing for executable CadQuery workflows.

This module deliberately contains no CAD-generation logic.  It translates a
durable failure observation into one bounded recovery decision so callers do
not need to scatter owner/action/repair-level conditionals through the
workflow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


CANONICAL_STAGES: tuple[str, ...] = (
    "conversation",
    "clarification",
    "design_contract",
    "provider_transport",
    "source_extraction",
    "python_syntax",
    "source_contract",
    "worker_workspace",
    "module_import",
    "build_execution",
    "output_materialization",
    "topology",
    "semantic_measurement",
    "semantic_policy",
    "artifact_export",
    "package_generation",
    "preview_rendering",
    "candidate_review",
    "acceptance",
    "user_revision",
    "independent_final_review",
)

RECOVERY_POLICY_VERSION = "executable-cadquery-recovery-policy-v1"

INVALIDATION_TARGETS: frozenset[str] = frozenset(
    set(CANONICAL_STAGES) | {"worker", "artifacts", "package", "preview"}
)

RECOVERY_ACTIONS: frozenset[str] = frozenset(
    {
        "deterministic_cleanup",
        "retry_stage",
        "retry_transport",
        "gemini_contract_repair",
        "gemini_execution_repair",
        "gemini_topology_repair",
        "gemini_semantic_repair",
        "application_owned_fix",
        "rerun_export",
        "rerun_verifier",
        "rebuild_preview",
        "require_review",
        "terminal_external_blocker",
    }
)


@dataclass(frozen=True)
class RecoveryPolicy:
    """Static routing rule for one normalized failure class."""

    owner: str
    action: str
    maximum_attempts: int
    progress_requirement: str
    restart_stage: str
    evidence_inputs: tuple[str, ...]
    terminal_conditions: tuple[str, ...]
    invalidates: tuple[str, ...] = ()
    repair_level: str | None = None
    recoverability: str = "retryable"

    def __post_init__(self) -> None:
        if self.action not in RECOVERY_ACTIONS:
            raise ValueError(f"unknown recovery action: {self.action}")
        if self.restart_stage not in CANONICAL_STAGES:
            raise ValueError(f"unknown recovery stage: {self.restart_stage}")
        if self.maximum_attempts < 0:
            raise ValueError("maximum_attempts cannot be negative")
        unknown_invalidations = set(self.invalidates) - INVALIDATION_TARGETS
        if unknown_invalidations:
            raise ValueError(f"unknown invalidation stages: {sorted(unknown_invalidations)}")


@dataclass(frozen=True)
class FailureObservation:
    """Facts collected at the earliest failing stage."""

    observed_stage: str
    failure_class: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    attempt_ordinal: int = 1
    progress: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.observed_stage not in CANONICAL_STAGES:
            raise ValueError(f"unknown observed stage: {self.observed_stage}")
        if self.attempt_ordinal < 1:
            raise ValueError("attempt_ordinal must be positive")


@dataclass(frozen=True)
class RecoveryDecision:
    """The router's complete, persistence-ready decision."""

    observed_stage: str
    failure_class: str
    first_incorrect_owner: str
    recoverability: str
    recommended_action: str
    repair_level: str | None
    attempt_ordinal: int
    evidence: Mapping[str, Any]
    progress: Mapping[str, Any]
    restart_stage: str
    invalidates: tuple[str, ...]
    terminal: bool
    terminal_reason: str | None
    evidence_inputs: tuple[str, ...]
    terminal_conditions: tuple[str, ...]

    def to_record(self) -> dict[str, Any]:
        """Return a JSON-safe record for the workflow orchestrator to persist."""

        return {
            "schema_version": "executable-cadquery-recovery-decision-v1",
            "policy_version": RECOVERY_POLICY_VERSION,
            "observation": {
                "observed_stage": self.observed_stage,
                "failure_class": self.failure_class,
                "evidence": dict(self.evidence),
                "attempt_ordinal": self.attempt_ordinal,
                "progress": dict(self.progress),
            },
            "first_incorrect_owner": self.first_incorrect_owner,
            "recoverability": self.recoverability,
            "recommended_action": self.recommended_action,
            "repair_level": self.repair_level,
            "restart_stage": self.restart_stage,
            "invalidates": list(self.invalidates),
            "terminal": self.terminal,
            "terminal_reason": self.terminal_reason,
            "evidence_inputs": list(self.evidence_inputs),
            "terminal_conditions": list(self.terminal_conditions),
        }


def _policy(
    *,
    owner: str,
    action: str,
    maximum_attempts: int,
    progress_requirement: str,
    restart_stage: str,
    evidence_inputs: tuple[str, ...],
    terminal_conditions: tuple[str, ...],
    invalidates: tuple[str, ...] = (),
    repair_level: str | None = None,
    recoverability: str = "retryable",
) -> RecoveryPolicy:
    return RecoveryPolicy(
        owner=owner,
        action=action,
        maximum_attempts=maximum_attempts,
        progress_requirement=progress_requirement,
        restart_stage=restart_stage,
        evidence_inputs=evidence_inputs,
        terminal_conditions=terminal_conditions,
        invalidates=invalidates,
        repair_level=repair_level,
        recoverability=recoverability,
    )


RECOVERY_POLICIES: dict[str, RecoveryPolicy] = {
    "provider_transport_failure": _policy(
        owner="provider_transport",
        action="retry_transport",
        maximum_attempts=2,
        progress_requirement="a provider response or explicit retryable transport result is recorded",
        restart_stage="provider_transport",
        evidence_inputs=("request_start_timestamp", "exception_type", "normalized_transport_error"),
        terminal_conditions=("transport retry ceiling exhausted",),
    ),
    "provider_rate_limit": _policy(
        owner="provider_transport",
        action="retry_transport",
        maximum_attempts=2,
        progress_requirement="the established 429 fallback policy completes",
        restart_stage="provider_transport",
        evidence_inputs=("status_code", "credential_slot", "rate_limit_429_classification"),
        terminal_conditions=("rate-limit retry ceiling exhausted",),
    ),
    "provider_authentication_failure": _policy(
        owner="provider_transport",
        action="terminal_external_blocker",
        maximum_attempts=0,
        progress_requirement="the existing API-key authentication boundary is restored",
        restart_stage="provider_transport",
        evidence_inputs=("status_code", "credential_slot", "response_received"),
        terminal_conditions=("provider authentication failure",),
        recoverability="terminal",
    ),
    "provider_response_empty": _policy(
        owner="geometry",
        action="gemini_contract_repair",
        maximum_attempts=3,
        progress_requirement="a non-empty provider response is received",
        restart_stage="source_extraction",
        evidence_inputs=("raw_response_hash", "response_length", "response_received"),
        terminal_conditions=("same empty response state repeats",),
        invalidates=("worker", "topology", "semantic_measurement", "semantic_policy", "artifacts", "package", "preview"),
        repair_level="L0",
    ),
    "provider_source_extraction_failure": _policy(
        owner="geometry",
        action="gemini_contract_repair",
        maximum_attempts=3,
        progress_requirement="one complete source module is extracted from the received response",
        restart_stage="source_extraction",
        evidence_inputs=("raw_response_hash", "response_length", "extraction_diagnostic"),
        terminal_conditions=("same extraction failure repeats",),
        invalidates=("worker", "topology", "semantic_measurement", "semantic_policy", "artifacts", "package", "preview"),
        repair_level="L0",
    ),
    "provider_timeout": _policy(
        owner="provider_transport",
        action="retry_transport",
        maximum_attempts=2,
        progress_requirement="transport response or explicit retryable status",
        restart_stage="provider_transport",
        evidence_inputs=("provider_status", "retry_after_seconds"),
        terminal_conditions=("provider authentication failure", "retry ceiling exhausted"),
    ),
    "python_syntax_error": _policy(
        owner="geometry",
        action="gemini_contract_repair",
        maximum_attempts=3,
        progress_requirement="source parses and contract violations decrease",
        restart_stage="source_extraction",
        evidence_inputs=("source_hash", "syntax_diagnostic", "complete_prior_source"),
        terminal_conditions=("same source hash repeats", "same normalized error repeats"),
        invalidates=("worker", "topology", "semantic_measurement", "semantic_policy", "artifacts", "package", "preview"),
        repair_level="L0",
    ),
    "provider_response_contract_failure": _policy(
        owner="geometry",
        action="gemini_contract_repair",
        maximum_attempts=3,
        progress_requirement="complete source is extracted and contract-valid",
        restart_stage="source_extraction",
        evidence_inputs=("raw_response_hash", "extraction_diagnostic", "complete_prior_source"),
        terminal_conditions=("same source hash repeats", "same normalized error repeats"),
        invalidates=("worker_workspace", "module_import", "build_execution", "topology", "semantic_measurement", "semantic_policy", "artifact_export", "package_generation", "preview_rendering"),
        repair_level="L0",
    ),
    "response_empty_or_extraction_failure": _policy(
        owner="geometry",
        action="gemini_contract_repair",
        maximum_attempts=3,
        progress_requirement="one complete source module is extracted",
        restart_stage="source_extraction",
        evidence_inputs=("raw_response_hash", "extraction_diagnostic", "complete_prior_source"),
        terminal_conditions=("same source hash repeats", "same normalized error repeats"),
        invalidates=("worker", "topology", "semantic_measurement", "semantic_policy", "artifacts", "package", "preview"),
        repair_level="L0",
    ),
    "source_contract_violation": _policy(
        owner="geometry",
        action="gemini_contract_repair",
        maximum_attempts=3,
        progress_requirement="source-contract violations decrease",
        restart_stage="source_extraction",
        evidence_inputs=("source_hash", "contract_diagnostic", "complete_prior_source"),
        terminal_conditions=("same source hash repeats", "same normalized error repeats"),
        invalidates=("worker_workspace", "module_import", "build_execution", "topology", "semantic_measurement", "semantic_policy", "artifact_export", "package_generation", "preview_rendering"),
        repair_level="L0",
    ),
    "python_name_error": _policy(
        owner="geometry",
        action="gemini_execution_repair",
        maximum_attempts=3,
        progress_requirement="execution reaches a later phase",
        restart_stage="source_extraction",
        evidence_inputs=("source_hash", "worker_diagnostic", "complete_prior_source"),
        terminal_conditions=("same source hash repeats", "two repairs without progress"),
        invalidates=("worker_workspace", "module_import", "build_execution", "topology", "semantic_measurement", "semantic_policy", "artifact_export", "package_generation", "preview_rendering"),
        repair_level="L1",
    ),
    "python_type_error": _policy(
        owner="geometry",
        action="gemini_execution_repair",
        maximum_attempts=3,
        progress_requirement="execution reaches a later phase",
        restart_stage="source_extraction",
        evidence_inputs=("source_hash", "worker_diagnostic", "complete_prior_source"),
        terminal_conditions=("same source hash repeats", "two repairs without progress"),
        invalidates=("worker_workspace", "module_import", "build_execution", "topology", "semantic_measurement", "semantic_policy", "artifact_export", "package_generation", "preview_rendering"),
        repair_level="L1",
    ),
    "cadquery_api_error": _policy(
        owner="geometry",
        action="gemini_execution_repair",
        maximum_attempts=3,
        progress_requirement="execution reaches a later phase",
        restart_stage="source_extraction",
        evidence_inputs=("source_hash", "worker_diagnostic", "complete_prior_source"),
        terminal_conditions=("same source hash repeats", "two repairs without progress"),
        invalidates=("worker_workspace", "module_import", "build_execution", "topology", "semantic_measurement", "semantic_policy", "artifact_export", "package_generation", "preview_rendering"),
        repair_level="L1",
    ),
    "cadquery_selector_error": _policy(
        owner="geometry",
        action="gemini_execution_repair",
        maximum_attempts=3,
        progress_requirement="execution reaches a later phase",
        restart_stage="source_extraction",
        evidence_inputs=("source_hash", "worker_diagnostic", "complete_prior_source"),
        terminal_conditions=("same source hash repeats", "two repairs without progress"),
        invalidates=("worker_workspace", "module_import", "build_execution", "topology", "semantic_measurement", "semantic_policy", "artifact_export", "package_generation", "preview_rendering"),
        repair_level="L1",
    ),
    "source_execution_error": _policy(
        owner="geometry",
        action="gemini_execution_repair",
        maximum_attempts=3,
        progress_requirement="execution reaches a later phase",
        restart_stage="source_extraction",
        evidence_inputs=("source_hash", "worker_diagnostic", "complete_prior_source"),
        terminal_conditions=("same source hash repeats", "two repairs without progress"),
        invalidates=("worker", "topology", "semantic_measurement", "semantic_policy", "artifacts", "package", "preview"),
        repair_level="L1",
    ),
    "worker_workspace_initialization_failure": _policy(
        owner="application",
        action="retry_stage",
        maximum_attempts=2,
        progress_requirement="workspace is initialized without changing source",
        restart_stage="worker_workspace",
        evidence_inputs=("workspace_path", "worker_diagnostic", "source_hash"),
        terminal_conditions=("worker infrastructure failure repeats",),
        invalidates=("worker", "topology", "semantic_measurement", "semantic_policy", "artifacts", "package", "preview"),
    ),
    "worker_environment_failure": _policy(
        owner="application",
        action="retry_stage",
        maximum_attempts=2,
        progress_requirement="worker environment becomes available without changing source",
        restart_stage="worker_workspace",
        evidence_inputs=("worker_diagnostic", "source_hash"),
        terminal_conditions=("worker infrastructure failure repeats",),
        invalidates=("module_import", "build_execution", "topology", "semantic_measurement", "semantic_policy", "artifact_export", "package_generation", "preview_rendering"),
    ),
    "worker_timeout": _policy(
        owner="application",
        action="retry_stage",
        maximum_attempts=2,
        progress_requirement="worker reaches completion without changing source",
        restart_stage="build_execution",
        evidence_inputs=("worker_diagnostic", "source_hash", "elapsed_seconds"),
        terminal_conditions=("worker timeout repeats",),
        invalidates=("topology", "semantic_measurement", "semantic_policy", "artifacts", "package", "preview"),
    ),
    "empty_shape": _policy(
        owner="geometry",
        action="gemini_topology_repair",
        maximum_attempts=2,
        progress_requirement="topology becomes valid",
        restart_stage="source_extraction",
        evidence_inputs=("source_hash", "topology_report", "complete_prior_source"),
        terminal_conditions=("same source hash repeats", "two repairs without progress"),
        invalidates=("topology", "semantic_measurement", "semantic_policy", "artifact_export", "package_generation", "preview_rendering"),
        repair_level="L2",
    ),
    "invalid_shape": _policy(
        owner="geometry",
        action="gemini_topology_repair",
        maximum_attempts=2,
        progress_requirement="topology becomes valid",
        restart_stage="source_extraction",
        evidence_inputs=("source_hash", "topology_report", "complete_prior_source"),
        terminal_conditions=("same source hash repeats", "two repairs without progress"),
        invalidates=("topology", "semantic_measurement", "semantic_policy", "artifact_export", "package_generation", "preview_rendering"),
        repair_level="L2",
    ),
    "solid_count_mismatch": _policy(
        owner="geometry",
        action="gemini_topology_repair",
        maximum_attempts=2,
        progress_requirement="required output solid counts converge",
        restart_stage="source_extraction",
        evidence_inputs=("source_hash", "topology_report", "required_output_ids", "complete_prior_source"),
        terminal_conditions=("same source hash repeats", "two repairs without progress"),
        invalidates=("topology", "semantic_measurement", "semantic_policy", "artifact_export", "package_generation", "preview_rendering"),
        repair_level="L2",
    ),
    "unsupported_shape": _policy(
        owner="geometry",
        action="gemini_topology_repair",
        maximum_attempts=2,
        progress_requirement="topology becomes supported and valid",
        restart_stage="source_extraction",
        evidence_inputs=("source_hash", "topology_report", "complete_prior_source"),
        terminal_conditions=("same source hash repeats", "two repairs without progress"),
        invalidates=("topology", "semantic_measurement", "semantic_policy", "artifacts", "package", "preview"),
        repair_level="L2",
    ),
    "topology_validation_failure": _policy(
        owner="application",
        action="application_owned_fix",
        maximum_attempts=2,
        progress_requirement="topology verifier produces a deterministic result",
        restart_stage="topology",
        evidence_inputs=("topology_report", "measurement_available"),
        terminal_conditions=("topology verifier remains unavailable",),
        invalidates=("semantic_measurement", "semantic_policy", "artifacts", "package", "preview"),
    ),
    "semantic_requirement_failed": _policy(
        owner="geometry",
        action="gemini_semantic_repair",
        maximum_attempts=4,
        progress_requirement="fewer failed machine requirements without protected-fact regression",
        restart_stage="source_contract",
        evidence_inputs=("source_hash", "measurement_report", "failed_requirement_ids", "complete_prior_source"),
        terminal_conditions=("same source hash repeats", "two repairs without progress", "protected fact regression"),
        invalidates=("worker", "topology", "semantic_measurement", "semantic_policy", "artifacts", "package", "preview"),
        repair_level="L3",
    ),
    "semantic_requirement_unverifiable": _policy(
        owner="application",
        action="application_owned_fix",
        maximum_attempts=2,
        progress_requirement="measurement becomes available or requirement is explicitly review-required",
        restart_stage="semantic_measurement",
        evidence_inputs=("requirement_policy", "measurement_available", "measurement_report"),
        terminal_conditions=("coverage defect repeats", "no verifier and no review classification"),
        invalidates=("semantic_measurement", "semantic_policy", "package", "preview"),
    ),
    "stl_export_failure": _policy(
        owner="artifact_pipeline",
        action="rerun_export",
        maximum_attempts=2,
        progress_requirement="STL is regenerated from the immutable valid shape",
        restart_stage="artifact_export",
        evidence_inputs=("shape_identity", "step_hash", "export_diagnostic"),
        terminal_conditions=("export failure repeats", "artifact integrity failure"),
        invalidates=("package_generation", "preview_rendering"),
    ),
    "step_export_failure": _policy(
        owner="artifact_pipeline",
        action="rerun_export",
        maximum_attempts=2,
        progress_requirement="STEP is regenerated from the immutable valid shape",
        restart_stage="artifact_export",
        evidence_inputs=("shape_identity", "stl_hash", "export_diagnostic"),
        terminal_conditions=("export failure repeats", "artifact integrity failure"),
        invalidates=("package_generation", "preview_rendering"),
    ),
    "preview_render_failure": _policy(
        owner="presentation",
        action="rebuild_preview",
        maximum_attempts=2,
        progress_requirement="preview is rebuilt from valid BREP/STEP",
        restart_stage="preview_rendering",
        evidence_inputs=("brep_hash", "step_hash", "preview_diagnostic"),
        terminal_conditions=("preview failure repeats",),
        invalidates=(),
    ),
    "package_generation_failure": _policy(
        owner="package_service",
        action="retry_stage",
        maximum_attempts=2,
        progress_requirement="package is regenerated from immutable valid artifacts",
        restart_stage="package_generation",
        evidence_inputs=("artifact_hashes", "package_manifest", "package_diagnostic"),
        terminal_conditions=("package generation failure repeats", "artifact integrity failure"),
        invalidates=("preview_rendering",),
    ),
    "artifact_integrity_failure": _policy(
        owner="application",
        action="require_review",
        maximum_attempts=1,
        progress_requirement="artifact identity and hashes are coherent",
        restart_stage="package_generation",
        evidence_inputs=("registered_hash", "downloaded_hash", "package_manifest"),
        terminal_conditions=("hash mismatch",),
        invalidates=("package_generation", "preview_rendering"),
        recoverability="terminal",
    ),
    "protected_fact_regression": _policy(
        owner="geometry",
        action="require_review",
        maximum_attempts=1,
        progress_requirement="protected facts remain unchanged",
        restart_stage="semantic_policy",
        evidence_inputs=("prior_measurement_report", "current_measurement_report", "protected_facts"),
        terminal_conditions=("any protected fact regresses",),
        invalidates=("semantic_policy", "artifacts", "package", "preview"),
        recoverability="terminal",
    ),
    "authentication_failure": _policy(
        owner="provider_transport",
        action="terminal_external_blocker",
        maximum_attempts=0,
        progress_requirement="credential boundary is restored externally",
        restart_stage="provider_transport",
        evidence_inputs=("provider_status", "credential_slot"),
        terminal_conditions=("authentication failure",),
        recoverability="terminal",
    ),
    "missing_provider_credentials": _policy(
        owner="provider_transport",
        action="terminal_external_blocker",
        maximum_attempts=0,
        progress_requirement="provider credentials are restored externally",
        restart_stage="provider_transport",
        evidence_inputs=("credential_slot",),
        terminal_conditions=("missing credentials",),
        recoverability="terminal",
    ),
    "authorization_failure": _policy(
        owner="application",
        action="terminal_external_blocker",
        maximum_attempts=0,
        progress_requirement="authorization boundary is restored externally",
        restart_stage="provider_transport",
        evidence_inputs=("safe_diagnostic", "actor_identity"),
        terminal_conditions=("authorization failure",),
        recoverability="terminal",
    ),
    "database_integrity_failure": _policy(
        owner="application",
        action="terminal_external_blocker",
        maximum_attempts=0,
        progress_requirement="database integrity is restored externally",
        restart_stage="design_contract",
        evidence_inputs=("safe_diagnostic", "transaction_id"),
        terminal_conditions=("database integrity failure",),
        recoverability="terminal",
    ),
    "artifact_root_escape": _policy(
        owner="application",
        action="terminal_external_blocker",
        maximum_attempts=0,
        progress_requirement="artifact path isolation is restored externally",
        restart_stage="artifact_export",
        evidence_inputs=("safe_diagnostic", "artifact_path"),
        terminal_conditions=("artifact root escape",),
        recoverability="terminal",
    ),
}


class RecoveryRouter:
    """Select one bounded recovery action from a failure observation."""

    @staticmethod
    def classify_failure(boundary: str, evidence: Mapping[str, Any] | None) -> str:
        """Normalize raw subsystem evidence into a policy registry key."""

        facts = evidence if isinstance(evidence, Mapping) else {}
        message = str(facts.get("normalized_error") or facts.get("message") or "").lower()
        exception_type = str(facts.get("exception_type") or "").lower()
        failure_kind = str(facts.get("failure_kind") or "").lower()
        normalized_boundary = str(boundary or "").lower()

        if facts.get("missing_provider_credentials") or "credential is not configured" in message:
            return "missing_provider_credentials"

        if normalized_boundary == "provider_response":
            response_received = facts.get("response_received")
            status_code = facts.get("status_code", facts.get("provider_status"))
            try:
                status_code = int(status_code) if status_code is not None else None
            except (TypeError, ValueError):
                status_code = None
            if response_received is False:
                if status_code == 429:
                    return "provider_rate_limit"
                if (
                    status_code in {401, 403}
                    or facts.get("authentication_failure")
                    or "authentication" in message
                    or "unauthorized" in message
                ):
                    return "provider_authentication_failure"
                return "provider_transport_failure"
            if status_code == 429:
                return "provider_rate_limit"
            if status_code in {401, 403}:
                return "provider_authentication_failure"
            if response_received is True:
                response_length = facts.get("response_length")
                if response_length == 0:
                    return "provider_response_empty"
                if facts.get("source_extraction_succeeded") is False:
                    return "provider_source_extraction_failure"
                if (
                    facts.get("source_extraction_succeeded") is True
                    and facts.get("source_contract_valid") is False
                ):
                    return "provider_response_contract_failure"

        if facts.get("worker_environment_failure") or facts.get("worker_failure_class") == "worker_environment_failure":
            return "worker_environment_failure"
        if facts.get("authentication_failure") or "authentication" in message or "unauthorized" in message:
            return "authentication_failure"
        if normalized_boundary == "provider_response" and failure_kind == "response_empty_or_extraction_failure":
            return "response_empty_or_extraction_failure"
        if normalized_boundary == "provider_response" or facts.get("schema_error"):
            return "provider_response_contract_failure"
        if normalized_boundary in {"auth", "authentication"}:
            return "authentication_failure"
        if normalized_boundary in {"authorization", "permission"}:
            return "authorization_failure"
        if normalized_boundary in {"database", "database_integrity"}:
            return "database_integrity_failure"
        if normalized_boundary == "artifact" and facts.get("root_escape"):
            return "artifact_root_escape"
        if normalized_boundary == "artifact":
            if facts.get("stl_failure"):
                return "stl_export_failure"
            if facts.get("step_failure"):
                return "step_export_failure"
            return "artifact_integrity_failure"
        if normalized_boundary in {"package", "package_generation"}:
            return "package_generation_failure"
        if normalized_boundary == "source_contract":
            if failure_kind == "python_syntax_error" or "syntax" in message or "parse" in message:
                return "python_syntax_error"
            return "source_contract_violation"
        if normalized_boundary == "execution":
            if facts.get("timed_out") or "timeout" in message:
                return "worker_timeout"
            if exception_type == "nameerror" or "nameerror" in message:
                return "python_name_error"
            if exception_type == "typeerror" or "typeerror" in message:
                return "python_type_error"
            if "selector" in message or "selector" in exception_type:
                return "cadquery_selector_error"
            if exception_type.startswith("stdfail") or "brep_api" in message or "command not done" in message:
                return "cadquery_api_error"
            if exception_type == "attributeerror" and any(
                token in message for token in ("cadquery", "workplane", "ocp")
            ):
                return "cadquery_api_error"
            if "cadquery" in message or "ocp" in message:
                return "cadquery_api_error"
            return "source_execution_error"
        if normalized_boundary == "topology":
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
        if normalized_boundary in {"semantic", "semantic_verification", "protected_facts"}:
            if facts.get("protected_fact_regression") or facts.get("regressed"):
                return "protected_fact_regression"
            if facts.get("unverifiable"):
                return "semantic_requirement_unverifiable"
            return "semantic_requirement_failed"
        return "source_execution_error"

    @staticmethod
    def earliest_stage(boundary: str, failure_class: str) -> str:
        """Map a normalized failure to the earliest canonical stage it proves."""

        class_stages = {
            "provider_transport_failure": "provider_transport",
            "provider_authentication_failure": "provider_transport",
            "provider_response_empty": "source_extraction",
            "provider_source_extraction_failure": "source_extraction",
            "provider_timeout": "provider_transport",
            "provider_rate_limit": "provider_transport",
            "authentication_failure": "provider_transport",
            "missing_provider_credentials": "provider_transport",
            "response_empty_or_extraction_failure": "source_extraction",
            "provider_response_contract_failure": "source_extraction",
            "python_syntax_error": "python_syntax",
            "source_contract_violation": "source_contract",
            "python_name_error": "build_execution",
            "python_type_error": "build_execution",
            "cadquery_api_error": "build_execution",
            "cadquery_selector_error": "build_execution",
            "worker_workspace_initialization_failure": "worker_workspace",
            "worker_environment_failure": "worker_workspace",
            "worker_timeout": "build_execution",
            "empty_shape": "topology",
            "invalid_shape": "topology",
            "solid_count_mismatch": "topology",
            "unsupported_shape": "topology",
            "semantic_requirement_failed": "semantic_measurement",
            "semantic_requirement_unverifiable": "semantic_measurement",
            "protected_fact_regression": "semantic_policy",
            "stl_export_failure": "artifact_export",
            "step_export_failure": "artifact_export",
            "artifact_integrity_failure": "package_generation",
            "package_generation_failure": "package_generation",
            "preview_render_failure": "preview_rendering",
        }
        if failure_class in class_stages:
            return class_stages[failure_class]
        return {
            "provider_response": "provider_transport",
            "source_contract": "source_contract",
            "execution": "build_execution",
            "topology": "topology",
            "semantic": "semantic_measurement",
            "protected_facts": "semantic_policy",
            "artifact": "artifact_export",
        }.get(str(boundary).lower(), "build_execution")

    def route(self, observation: FailureObservation) -> RecoveryDecision:
        policy = self._policy_for(observation)
        evidence = dict(observation.evidence)
        progress = dict(observation.progress)
        terminal_reason: str | None = None

        if observation.attempt_ordinal > policy.maximum_attempts:
            terminal_reason = "repair_ceiling_exhausted"
        elif max(
            int(progress.get("consecutive_no_progress", 0) or 0),
            int(evidence.get("consecutive_no_progress", 0) or 0),
        ) >= 2:
            terminal_reason = "two_consecutive_repairs_without_objective_progress"
        elif (
            evidence.get("same_source_hash") is True
            and evidence.get("same_error_state") is not False
        ):
            terminal_reason = "same_source_hash_repeated"
        elif evidence.get("same_error_state") is True:
            terminal_reason = "same_error_state_repeated"
        elif policy.recoverability == "terminal":
            terminal_reason = policy.terminal_conditions[0] if policy.terminal_conditions else "policy_terminal"

        terminal = terminal_reason is not None or policy.recoverability == "terminal"
        action = "require_review" if terminal_reason and policy.recoverability != "terminal" else policy.action
        if policy.recoverability == "terminal":
            action = policy.action

        return RecoveryDecision(
            observed_stage=observation.observed_stage,
            failure_class=observation.failure_class,
            first_incorrect_owner=policy.owner,
            recoverability=("terminal" if terminal else policy.recoverability),
            recommended_action=action,
            repair_level=policy.repair_level if not terminal_reason else None,
            attempt_ordinal=observation.attempt_ordinal,
            evidence=evidence,
            progress=progress,
            restart_stage=policy.restart_stage,
            invalidates=policy.invalidates,
            terminal=terminal,
            terminal_reason=terminal_reason,
            evidence_inputs=policy.evidence_inputs,
            terminal_conditions=policy.terminal_conditions,
        )

    @staticmethod
    def _policy_for(observation: FailureObservation) -> RecoveryPolicy:
        policy = RECOVERY_POLICIES.get(observation.failure_class)
        if observation.failure_class == "semantic_requirement_unverifiable":
            requirement_policy = observation.evidence.get("policy")
            if requirement_policy == "review_required":
                return _policy(
                    owner="review",
                    action="require_review",
                    maximum_attempts=1,
                    progress_requirement="review obligation is explicitly acknowledged",
                    restart_stage="candidate_review",
                    evidence_inputs=("requirement_policy", "review_obligation"),
                    terminal_conditions=("review obligation is not acknowledged",),
                    invalidates=("package", "preview"),
                    recoverability="reviewable",
                )
            if requirement_policy == "informational":
                return _policy(
                    owner="review",
                    action="require_review",
                    maximum_attempts=1,
                    progress_requirement="informational evidence is recorded",
                    restart_stage="candidate_review",
                    evidence_inputs=("requirement_policy",),
                    terminal_conditions=(),
                    invalidates=(),
                    recoverability="reviewable",
                )
        if policy is not None:
            return policy
        return _policy(
            owner="application",
            action="terminal_external_blocker",
            maximum_attempts=0,
            progress_requirement="failure is classified by an explicit policy",
            restart_stage=observation.observed_stage,
            evidence_inputs=("failure_class", "safe_diagnostic"),
            terminal_conditions=("unclassified failure",),
            invalidates=(),
            recoverability="terminal",
        )
