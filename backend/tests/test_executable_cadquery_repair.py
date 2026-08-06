import json
from pathlib import Path

import pytest

from app.services.executable_cadquery.repair import (
    AUTOMATIC_PROVIDER_OPERATION_BUDGET,
    build_executable_cadquery_repair_envelope,
    classify_executable_failure,
    compare_executable_progress,
    decide_executable_repair,
)
from app.services.validated_cadquery_workflow import safe_diagnostic


BASE_INPUT = {
    "generation_session_id": "session-1",
    "logical_operation_id": "operation-2",
    "parent_operation_id": "operation-1",
    "repair_ordinal": 1,
    "previous_source": "complete source",
    "previous_source_hash": "source-hash",
    "previous_result_hash": "result-hash",
    "design_contract": {"schema_version": "executable-cadquery-design-contract-v1"},
    "provider_attempt": {"attempt_id": "attempt-2", "status_code": 200},
    "worker_result": {"phase": "execution", "output_ids": ["mounting_bracket"]},
    "topology_result": {"valid": True, "detected_solid_count": 1},
    "semantic_result": {"passed": ["body_dimensions"], "failed": ["pocket"]},
    "protected_facts": [{"requirement_id": "body_dimensions", "authoritative_value": 80}],
    "repair_history": [{"repair_level": "L0", "source_hash": "old-hash"}],
}

SNAPSHOT_DIR = Path(__file__).parent / "snapshots" / "executable_cadquery_repair"


def _snapshot_payload(envelope: dict) -> dict:
    """Keep snapshots focused on the durable envelope shape and identifiers."""

    return {
        "schema_version": envelope["schema_version"],
        "repair_level": envelope["repair_level"],
        "generation_session_id": envelope["generation_session_id"],
        "logical_operation_id": envelope["logical_operation_id"],
        "parent_operation_id": envelope["parent_operation_id"],
        "repair_ordinal": envelope["repair_ordinal"],
        "canonical_output_ids": envelope["canonical_output_ids"],
        "previous_source_hash": envelope["previous_source_hash"],
        "previous_result_hash": envelope["previous_result_hash"],
        "requested_delta": envelope["requested_delta"],
    }


@pytest.mark.parametrize("level", ["L0", "L1", "L2", "L3", "L4"])
def test_repair_envelope_is_versioned_and_level_specific(level: str) -> None:
    envelope = build_executable_cadquery_repair_envelope(
        **BASE_INPUT,
        repair_level=level,
        requested_delta="Increase the pocket while preserving the body.",
    )

    assert envelope["schema_version"] == "executable-cadquery-repair-envelope-v1"
    assert envelope["repair_level"] == level
    assert envelope["generation_session_id"] == "session-1"
    assert envelope["canonical_output_ids"] == ["mounting_bracket"]
    rendered = json.dumps(envelope, sort_keys=True)
    assert "Traceback" not in rendered
    assert "/root/" not in rendered
    assert "api_key" not in rendered.lower()
    assert "canonical_source_skeleton" in rendered
    assert "workplane" in rendered.lower()
    assert "fillet(" not in rendered.lower()


@pytest.mark.parametrize("level", ["L0", "L1", "L2", "L3", "L4"])
def test_repair_envelope_matches_snapshot(level: str) -> None:
    envelope = build_executable_cadquery_repair_envelope(
        **BASE_INPUT,
        repair_level=level,
        requested_delta="Increase the pocket while preserving the body.",
    )

    snapshot_path = SNAPSHOT_DIR / f"{level}.json"
    assert snapshot_path.exists()
    expected = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert _snapshot_payload(envelope) == expected


@pytest.mark.parametrize(
    ("boundary", "evidence", "expected"),
    [
        ("provider_response", {"schema_error": "missing source"}, "provider_response_contract_failure"),
        ("source_contract", {"message": "invalid Python syntax"}, "python_syntax_error"),
        ("source_contract", {"message": "unsafe import os"}, "source_contract_violation"),
        ("execution", {"exception_type": "NameError"}, "python_name_error"),
        ("execution", {"exception_type": "TypeError"}, "python_type_error"),
        ("execution", {"exception_type": "SelectorError"}, "cadquery_selector_error"),
        ("execution", {"timed_out": True}, "worker_timeout"),
        ("execution", {"worker_failure_class": "worker_environment_failure"}, "worker_environment_failure"),
        ("topology", {"empty": True}, "empty_shape"),
        ("topology", {"valid": False, "detected_solid_count": 2}, "solid_count_mismatch"),
        ("semantic", {"failed": ["pocket"]}, "semantic_requirement_failed"),
        ("semantic", {"unverifiable": ["fillet"]}, "semantic_requirement_unverifiable"),
        ("protected_facts", {"regressed": ["body_dimensions"]}, "protected_fact_regression"),
    ],
)
def test_failure_taxonomy_is_normalized(boundary: str, evidence: dict, expected: str) -> None:
    assert classify_executable_failure(boundary, evidence) == expected


def test_provider_authentication_failures_do_not_enter_source_repair() -> None:
    assert classify_executable_failure(
        "provider_response",
        {"message": "The provider authentication check failed."},
    ) == "authentication_failure"
    assert classify_executable_failure(
        "provider_response",
        {"message": "primary Gemini credential is not configured"},
    ) == "missing_provider_credentials"


def test_l1_progress_accepts_later_phase_and_additional_output() -> None:
    comparison = compare_executable_progress(
        "L1",
        previous={"phase_index": 1, "completed_output_ids": []},
        current={"phase_index": 2, "completed_output_ids": ["mounting_bracket"]},
    )

    assert comparison["measurable_progress"] is True
    assert comparison["progress_reasons"] == ["later_execution_phase", "additional_required_output"]


def test_l3_progress_requires_fewer_failures_without_protected_regression() -> None:
    comparison = compare_executable_progress(
        "L3",
        previous={"failed_requirement_ids": ["body", "pocket"], "passed_requirement_ids": ["holes"]},
        current={"failed_requirement_ids": ["pocket"], "passed_requirement_ids": ["holes", "body"]},
    )

    assert comparison["measurable_progress"] is True
    assert "failed_obligation_count_decreased" in comparison["progress_reasons"]


def test_stop_policy_rejects_repeated_hash_or_same_error_and_enforces_level_budgets() -> None:
    assert AUTOMATIC_PROVIDER_OPERATION_BUDGET == 9
    repeated_hash = decide_executable_repair(
        repair_level="L1",
        repair_ordinal=1,
        source_hash="same",
        previous_source_hash="same",
        failure_class="python_name_error",
        previous_failure_class="python_name_error",
        progress={"measurable_progress": False},
    )
    assert repeated_hash["decision"] == "stop"
    assert repeated_hash["stop_reason"] == "repeated_source_hash"

    exhausted = decide_executable_repair(
        repair_level="L1",
        repair_ordinal=2,
        source_hash="new",
        previous_source_hash="old",
        failure_class="python_name_error",
        previous_failure_class="python_name_error",
        progress={"measurable_progress": True},
    )
    assert exhausted["decision"] == "stop"
    assert exhausted["stop_reason"] == "repair_budget_exhausted"


def test_l0_allows_three_repairs_only_while_source_contract_progresses() -> None:
    first = {
        "extracted_source_hash": "source-1",
        "diagnostic_signature": "try_statement_forbidden|10|4",
        "violation_count": 1,
        "syntax_valid": True,
        "source_contract_valid": False,
        "no_violation_decrease_streak": 0,
    }
    second = {
        "extracted_source_hash": "source-2",
        "diagnostic_signature": "top_level_if_forbidden|12|0",
        "violation_count": 1,
        "syntax_valid": True,
        "source_contract_valid": False,
        "no_violation_decrease_streak": 1,
    }

    comparison = compare_executable_progress("L0", previous=first, current=second)
    assert comparison["measurable_progress"] is True
    assert "extracted_source_hash_changed" in comparison["progress_reasons"]
    assert "diagnostic_code_changed" in comparison["progress_reasons"]
    assert decide_executable_repair(
        repair_level="L0",
        repair_ordinal=1,
        source_hash="source-2",
        previous_source_hash="source-1",
        failure_class="source_contract_violation",
        previous_failure_class="source_contract_violation",
        progress=comparison,
    )["decision"] == "repair"

    for ordinal in (0, 1, 2):
        assert decide_executable_repair(
            repair_level="L0",
            repair_ordinal=ordinal,
            source_hash=f"source-{ordinal + 1}",
            previous_source_hash=f"source-{ordinal}",
            failure_class="source_contract_violation",
            previous_failure_class="source_contract_violation",
            progress={"measurable_progress": True},
        )["decision"] == "repair"
    assert decide_executable_repair(
        repair_level="L0",
        repair_ordinal=3,
        source_hash="source-4",
        previous_source_hash="source-3",
        failure_class="source_contract_violation",
        previous_failure_class="source_contract_violation",
        progress={"measurable_progress": True},
    )["stop_reason"] == "repair_budget_exhausted"

    repeated = compare_executable_progress("L0", previous=second, current=second)
    assert repeated["measurable_progress"] is False
    assert decide_executable_repair(
        repair_level="L0",
        repair_ordinal=2,
        source_hash="source-2",
        previous_source_hash="source-2",
        failure_class="source_contract_violation",
        previous_failure_class="source_contract_violation",
        progress=repeated,
    )["stop_reason"] == "repeated_source_hash"


def test_l0_envelope_contains_dialect_skeleton_and_full_contract() -> None:
    envelope = build_executable_cadquery_repair_envelope(
        **BASE_INPUT,
        repair_level="L0",
        previous_provider_response="complete prior response",
        previous_normalized_error="top-level if statements are not allowed",
    )

    assert envelope["source_dialect"]["version"] == "cadquery-v1-source-dialect"
    assert envelope["source_dialect_hash"]
    assert envelope["canonical_source_skeleton"]
    assert envelope["canonical_source_skeleton_hash"]
    assert envelope["design_contract"]["schema_version"] == "executable-cadquery-design-contract-v1"
    assert envelope["prior_provider_response"] == "complete prior response"


def test_protected_fact_regression_is_immediate_stop() -> None:
    decision = decide_executable_repair(
        repair_level="L3",
        repair_ordinal=1,
        source_hash="new",
        previous_source_hash="old",
        failure_class="protected_fact_regression",
        previous_failure_class="semantic_requirement_failed",
        progress={"measurable_progress": True, "protected_fact_regression": True},
    )

    assert decision == {
        "decision": "stop",
        "stop_reason": "protected_fact_regression",
        "progress_result": "regressed",
    }


def test_l0_repair_contains_exact_prior_response_and_normalized_error() -> None:
    prior_response = "Here is the complete module:\n```python\npass\n```"
    normalized_error = "response_empty_or_extraction_failure: prose outside the single Python module"

    envelope = build_executable_cadquery_repair_envelope(
        **BASE_INPUT,
        repair_level="L0",
        previous_provider_response=prior_response,
        previous_normalized_error=normalized_error,
    )

    assert envelope["prior_provider_response"] == prior_response
    assert envelope["prior_normalized_error"] == normalized_error


def test_normalized_repair_evidence_redacts_credentials_and_host_paths() -> None:
    normalized = safe_diagnostic(
        "GEMINI_API_KEY_2=secret-value failed at /root/private/model.py"
    )

    assert "secret-value" not in normalized
    assert "GEMINI_API_KEY_2" not in normalized
    assert "/root/private/model.py" not in normalized

    envelope = build_executable_cadquery_repair_envelope(
        **BASE_INPUT,
        repair_level="L0",
        previous_normalized_error="GEMINI_API_KEY_2=secret-value at /root/private/model.py",
    )
    rendered = json.dumps(envelope, sort_keys=True)
    assert "secret-value" not in rendered
    assert "/root/private/model.py" not in rendered
