import json
from types import SimpleNamespace

import pytest

from app.services.executable_cadquery.recovery import (
    CANONICAL_STAGES,
    RECOVERY_ACTIONS,
    RECOVERY_POLICIES,
    RECOVERY_POLICY_VERSION,
    FailureObservation,
    RecoveryRouter,
)
from app.services.executable_cadquery.workflow import ExecutableCadQueryWorkflowService


def test_policy_registry_covers_known_recovery_classes_without_geometry_generation() -> None:
    expected = {
        "provider_timeout",
        "python_syntax_error",
        "source_contract_violation",
        "cadquery_api_error",
        "worker_workspace_initialization_failure",
        "invalid_shape",
        "solid_count_mismatch",
        "semantic_requirement_failed",
        "semantic_requirement_unverifiable",
        "stl_export_failure",
        "step_export_failure",
        "preview_render_failure",
        "response_empty_or_extraction_failure",
        "source_execution_error",
        "topology_validation_failure",
        "unsupported_shape",
        "authorization_failure",
        "database_integrity_failure",
        "artifact_root_escape",
    }

    assert expected <= RECOVERY_POLICIES.keys()
    assert set(CANONICAL_STAGES) >= {
        "provider_transport",
        "source_contract",
        "worker_workspace",
        "build_execution",
        "topology",
        "semantic_measurement",
        "artifact_export",
        "preview_rendering",
    }
    assert {
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
    } <= RECOVERY_ACTIONS


def test_router_classifies_cadquery_api_failure_as_geometry_execution_repair() -> None:
    decision = RecoveryRouter().route(
        FailureObservation(
            observed_stage="build_execution",
            failure_class="cadquery_api_error",
            evidence={"exception_type": "TypeError"},
            attempt_ordinal=1,
        )
    )

    assert decision.observed_stage == "build_execution"
    assert decision.first_incorrect_owner == "geometry"
    assert decision.recoverability == "retryable"
    assert decision.recommended_action == "gemini_execution_repair"
    assert decision.repair_level == "L1"
    assert decision.restart_stage == "source_extraction"
    assert decision.terminal is False


def test_router_routes_artifact_export_failure_without_provider_repair() -> None:
    decision = RecoveryRouter().route(
        FailureObservation(
            observed_stage="artifact_export",
            failure_class="stl_export_failure",
            evidence={"valid_shape": True, "step_available": True},
            attempt_ordinal=1,
        )
    )

    assert decision.first_incorrect_owner == "artifact_pipeline"
    assert decision.recommended_action == "rerun_export"
    assert decision.repair_level is None
    assert decision.restart_stage == "artifact_export"
    assert decision.invalidates == ("package_generation", "preview_rendering")
    assert decision.terminal is False


def test_router_routes_missing_package_to_existing_package_service() -> None:
    decision = RecoveryRouter().route(
        FailureObservation(
            observed_stage="package_generation",
            failure_class="package_generation_failure",
            evidence={"package_available": False},
            attempt_ordinal=1,
        )
    )

    assert decision.first_incorrect_owner == "package_service"
    assert decision.recommended_action == "retry_stage"
    assert decision.restart_stage == "package_generation"
    assert decision.invalidates == ("preview_rendering",)


def test_router_keeps_machine_verifier_coverage_defect_out_of_gemini_repair() -> None:
    decision = RecoveryRouter().route(
        FailureObservation(
            observed_stage="semantic_measurement",
            failure_class="semantic_requirement_unverifiable",
            evidence={"policy": "machine_required", "measurement_available": False},
            attempt_ordinal=1,
        )
    )

    assert decision.first_incorrect_owner == "application"
    assert decision.recommended_action == "application_owned_fix"
    assert decision.repair_level is None
    assert decision.terminal is False


def test_router_marks_review_required_geometry_as_nonterminal_review() -> None:
    decision = RecoveryRouter().route(
        FailureObservation(
            observed_stage="semantic_policy",
            failure_class="semantic_requirement_unverifiable",
            evidence={"policy": "review_required", "measurement_available": False},
            attempt_ordinal=1,
        )
    )

    assert decision.first_incorrect_owner == "review"
    assert decision.recommended_action == "require_review"
    assert decision.recoverability == "reviewable"
    assert decision.terminal is False


def test_router_stops_after_two_no_progress_repairs() -> None:
    decision = RecoveryRouter().route(
        FailureObservation(
            observed_stage="topology",
            failure_class="invalid_shape",
            evidence={"consecutive_no_progress": 2},
            attempt_ordinal=2,
        )
    )

    assert decision.terminal is True
    assert decision.terminal_reason == "two_consecutive_repairs_without_objective_progress"
    assert decision.recommended_action == "require_review"


def test_router_stops_unknown_failures_as_explicit_external_blockers() -> None:
    decision = RecoveryRouter().route(
        FailureObservation(
            observed_stage="worker_workspace",
            failure_class="unclassified_failure",
            evidence={"message": "unknown"},
            attempt_ordinal=1,
        )
    )

    assert decision.first_incorrect_owner == "application"
    assert decision.recoverability == "terminal"
    assert decision.recommended_action == "terminal_external_blocker"
    assert decision.terminal is True


def test_semantic_repair_invalidates_all_downstream_evidence() -> None:
    decision = RecoveryRouter().route(
        FailureObservation(
            observed_stage="semantic_measurement",
            failure_class="semantic_requirement_failed",
            evidence={"measurement_available": True},
            attempt_ordinal=1,
        )
    )

    assert decision.restart_stage == "source_contract"
    assert decision.invalidates == (
        "worker",
        "topology",
        "semantic_measurement",
        "semantic_policy",
        "artifacts",
        "package",
        "preview",
    )


def test_recovery_decision_is_a_durable_side_effect_free_record() -> None:
    observation = FailureObservation(
        observed_stage="artifact_export",
        failure_class="stl_export_failure",
        evidence={"valid_shape": True, "step_hash": "step-hash"},
        attempt_ordinal=1,
        progress={"measurable_progress": False},
    )
    decision = RecoveryRouter().route(observation)
    record = decision.to_record()

    assert record == {
        "schema_version": "executable-cadquery-recovery-decision-v1",
        "policy_version": RECOVERY_POLICY_VERSION,
        "observation": {
            "observed_stage": "artifact_export",
            "failure_class": "stl_export_failure",
            "evidence": {"valid_shape": True, "step_hash": "step-hash"},
            "attempt_ordinal": 1,
            "progress": {"measurable_progress": False},
        },
        "first_incorrect_owner": "artifact_pipeline",
        "recoverability": "retryable",
        "recommended_action": "rerun_export",
        "repair_level": None,
        "restart_stage": "artifact_export",
        "invalidates": ["package_generation", "preview_rendering"],
        "terminal": False,
        "terminal_reason": None,
        "evidence_inputs": ["shape_identity", "step_hash", "export_diagnostic"],
        "terminal_conditions": ["export failure repeats", "artifact integrity failure"],
    }


def test_router_owns_failure_normalization_and_earliest_stage_mapping() -> None:
    failure_class = RecoveryRouter.classify_failure(
        "artifact",
        {"stl_failure": True, "message": "export failed after valid shape"},
    )

    assert failure_class == "stl_export_failure"
    assert RecoveryRouter.earliest_stage("artifact", failure_class) == "artifact_export"


@pytest.mark.parametrize(
    ("evidence", "expected"),
    [
        (
            {
                "response_received": False,
                "exception_type": "ConnectTimeout",
                "normalized_transport_error": "provider transport timeout",
            },
            "provider_transport_failure",
        ),
        (
            {
                "response_received": True,
                "status_code": 429,
                "rate_limit_429_classification": "http_429",
            },
            "provider_rate_limit",
        ),
        (
            {"response_received": True, "status_code": 403},
            "provider_authentication_failure",
        ),
        (
            {"response_received": True, "response_length": 0},
            "provider_response_empty",
        ),
        (
            {
                "response_received": True,
                "response_length": 24,
                "source_extraction_succeeded": False,
            },
            "provider_source_extraction_failure",
        ),
        (
            {
                "response_received": True,
                "response_length": 128,
                "source_extraction_succeeded": True,
                "source_contract_valid": False,
            },
            "provider_response_contract_failure",
        ),
    ],
)
def test_provider_taxonomy_requires_response_evidence(evidence, expected) -> None:
    assert RecoveryRouter.classify_failure("provider_response", evidence) == expected


def test_provider_contract_failure_without_response_is_transport_failure() -> None:
    assert RecoveryRouter.classify_failure(
        "provider_response",
        {"response_received": False, "exception_type": "RuntimeError"},
    ) == "provider_transport_failure"


def test_provider_transport_owner_is_not_geometry_or_provider_response() -> None:
    decision = RecoveryRouter().route(
        FailureObservation(
            observed_stage="provider_transport",
            failure_class="provider_transport_failure",
            evidence={"response_received": False},
        )
    )

    assert decision.first_incorrect_owner == "provider_transport"
    assert decision.observed_stage == "provider_transport"


def test_router_does_not_hide_worker_failure_as_geometry_failure() -> None:
    failure_class = RecoveryRouter.classify_failure(
        "execution",
        {"worker_failure_class": "worker_environment_failure"},
    )

    assert failure_class == "worker_environment_failure"
    assert RECOVERY_POLICIES[failure_class].owner == "application"


def test_workflow_persists_recovery_decision_before_execution(tmp_path) -> None:
    observation = FailureObservation(
        observed_stage="artifact_export",
        failure_class="stl_export_failure",
        evidence={"valid_shape": True},
        attempt_ordinal=1,
    )
    decision = RecoveryRouter().route(observation)
    workflow = SimpleNamespace(provenance_json="{}", diagnostics_json="{}")

    ExecutableCadQueryWorkflowService(db=None, data_dir=tmp_path)._persist_recovery_decision(
        workflow,
        decision,
    )

    provenance = json.loads(workflow.provenance_json)
    diagnostics = json.loads(workflow.diagnostics_json)
    assert provenance["recovery_decisions"] == [decision.to_record()]
    assert diagnostics["latest_recovery_decision"] == decision.to_record()


def test_workflow_updates_recovery_execution_after_re_evaluation() -> None:
    workflow = SimpleNamespace(
        provenance_json=json.dumps({"recovery_executions": [{"action": "rerun_export"}]})
    )

    ExecutableCadQueryWorkflowService._replace_last_recovery_execution(
        workflow,
        {"action": "rerun_export", "reevaluation": {"status": "passed"}},
    )

    provenance = json.loads(workflow.provenance_json)
    assert provenance["recovery_executions"] == [
        {"action": "rerun_export", "reevaluation": {"status": "passed"}}
    ]
