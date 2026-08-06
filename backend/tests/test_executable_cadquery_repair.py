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
    assert "workplane" not in rendered.lower()
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
        ("topology", {"empty": True}, "empty_shape"),
        ("topology", {"valid": False, "detected_solid_count": 2}, "solid_count_mismatch"),
        ("semantic", {"failed": ["pocket"]}, "semantic_requirement_failed"),
        ("semantic", {"unverifiable": ["fillet"]}, "semantic_requirement_unverifiable"),
        ("protected_facts", {"regressed": ["body_dimensions"]}, "protected_fact_regression"),
    ],
)
def test_failure_taxonomy_is_normalized(boundary: str, evidence: dict, expected: str) -> None:
    assert classify_executable_failure(boundary, evidence) == expected


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
    assert AUTOMATIC_PROVIDER_OPERATION_BUDGET == 7
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
