from __future__ import annotations

import asyncio
import json
from app.services.gemini_consistency.provider_contract_correction import (
    clarification_outcome,
    corrected_content_denominator,
    earliest_blocker,
    evaluate_bounded_repair,
    evaluate_requirements_correction,
    furthest_valid_stage,
    holdout_configuration_audit,
    repair_packet_validity,
    select_settings_from_content,
    source_contract_passed,
    worker_reach_semantics,
)
from scripts.run_gemini_provider_contract_foundation import _generation_config
from pathlib import Path

import httpx

import scripts.run_gemini_provider_contract_correction as correction
from scripts.run_gemini_provider_contract_correction import _settings_selection, stage_prompt_selection


def _record(profile: str, result: str, *, status_code: int = 200) -> dict:
    return {
        "settings_profile": profile,
        "intrinsic_quality": {"result": result},
        "status_code": status_code,
        "success": result not in {"transport_failure", "quota_failure"},
        "complete": result not in {"transport_failure", "quota_failure"},
    }


def test_transport_failures_are_excluded_from_content_denominators() -> None:
    result = corrected_content_denominator([_record("S1-profile-b", "pass") for _ in range(11)] + [_record("S1-profile-b", "transport_failure", status_code=504)])

    assert result["content_passes"] == 11
    assert result["content_bearing_responses"] == 11
    assert result["content_pass_rate"] == 1.0
    assert result["transport_failures"] == 1


def test_transport_completion_cannot_select_settings_winner() -> None:
    s0 = corrected_content_denominator([_record("S0-current-explicit", "pass") for _ in range(12)])
    s1 = corrected_content_denominator([_record("S1-profile-b", "pass") for _ in range(11)] + [_record("S1-profile-b", "transport_failure", status_code=504)])

    decision = select_settings_from_content({"S0-current-explicit": s0, "S1-profile-b": s1})

    assert decision["content_denominators"] == {"S0-current-explicit": 12, "S1-profile-b": 11}
    assert decision["decision"] in {"S0-current-explicit", "settings_tie_requires_larger_holdout"}
    assert decision["transport_failures"] == {"S0-current-explicit": 0, "S1-profile-b": 1}


def test_historical_holdout_is_labeled_by_actual_h0_configuration() -> None:
    record = {"thinking_profile": "H0-current-stage-specific", "generation_config": {"thinkingConfig": {"thinkingLevel": "MINIMAL"}}}

    audit = holdout_configuration_audit(record, selected_thinking_profile="H1-provider-default")

    assert audit["classification"] == "holdout_h0_current_stage_specific"
    assert audit["selected_configuration_valid"] is False


def test_h1_provider_default_omits_thinking_configuration() -> None:
    assert "thinkingConfig" not in _generation_config("S0-current-explicit", "H1-provider-default", "requirements", "T0-current")


def test_repair_packet_without_source_is_invalid() -> None:
    packet = {"frozen_facts": {"invalid_slot_ids": ["2"]}, "intrinsic_expectations": {"repair_boundary": "result assignment only"}}

    result = repair_packet_validity(packet)

    assert result["valid"] is False
    assert result["classification"] == "invalid_test_packet_missing_repair_source"


def test_repair_summary_without_payload_fails() -> None:
    packet = {
        "frozen_facts": {"invalid_slot_ids": ["2"], "completed_slot_ids": ["1"], "protected_dimensions": {"diameter": 8}},
        "intrinsic_expectations": {"repair_boundary": "result assignment only"},
        "repair_source": {"slots": [{"slot_id": "1", "statements": ["body = body"], "result_symbol": "body"}, {"slot_id": "2", "statements": ["shape = body"], "result_symbol": "shape"}]},
    }

    result = evaluate_bounded_repair(packet, {"repair_complete": True, "repaired_fields": ["result_assignment"], "preserved_fields": ["1"], "rejected_changes": []})

    assert result["result"] == "fail_incomplete"


def test_bounded_repair_requires_actual_payload_and_preserves_completed_item() -> None:
    packet = {
        "frozen_facts": {"invalid_slot_ids": ["2"], "completed_slot_ids": ["1"], "protected_dimensions": {"diameter": 8}},
        "intrinsic_expectations": {"repair_boundary": "result assignment only"},
        "repair_source": {"slots": [{"slot_id": "1", "statements": ["body = body"], "result_symbol": "body"}, {"slot_id": "2", "statements": ["shape = body"], "result_symbol": "shape"}]},
    }
    response = {"repair_complete": True, "repaired_items": [{"item_type": "geometry_slot", "slot_id": "2", "result_symbol": "body", "statements": ["body = body"]}], "preserved_item_ids": ["1"], "rejected_changes": []}

    result = evaluate_bounded_repair(packet, response)

    assert result["result"] == "pass"


def test_bounded_repair_accepts_declarations_of_rejected_changes() -> None:
    packet = {
        "frozen_facts": {"invalid_slot_ids": ["2"], "completed_slot_ids": ["1"], "required_result_symbol": "body"},
        "intrinsic_expectations": {"repair_boundary": "result assignment only"},
        "repair_source": {"slots": [{"slot_id": "1", "statements": ["body = body"], "result_symbol": "body"}, {"slot_id": "2", "statements": ["shape = body"], "result_symbol": "shape"}]},
    }
    response = {"repaired_items": [{"slot_id": "2", "result_symbol": "body", "statements": ["body = body"]}], "preserved_item_ids": ["1"], "rejected_changes": ["changing completed slot 1"]}

    assert evaluate_bounded_repair(packet, response)["result"] == "pass"


def test_bounded_repair_rejects_payload_that_keeps_invalid_source_symbol() -> None:
    packet = {
        "frozen_facts": {"invalid_slot_ids": ["2"], "completed_slot_ids": ["1"], "required_result_symbol": "body"},
        "intrinsic_expectations": {"repair_boundary": "result assignment only"},
        "repair_source": {"slots": [{"slot_id": "1", "statements": ["body = body"], "result_symbol": "body"}, {"slot_id": "2", "statements": ["shape = body"], "result_symbol": "shape"}]},
    }
    response = {"repaired_items": [{"slot_id": "2", "result_symbol": "body", "statements": ["shape = body"]}], "preserved_item_ids": ["1"], "rejected_changes": []}

    assert evaluate_bounded_repair(packet, response)["result"] == "fail_conflicting"


def test_missing_fit_defaults_are_not_accepted_as_real_dimensions() -> None:
    packet = {
        "frozen_facts": {"cable_diameter": "missing"},
        "intrinsic_expectations": {"must_request": ["cable diameter"]},
    }
    response = {"clarification_required": False, "generation_ready": True, "clarification_questions": [], "requirements": [{"description": "cable diameter", "value": 10, "unit": "mm", "source": "default"}]}

    assert corrected_content_denominator([{"intrinsic_quality": {"result": "fail_invented_critical_meaning"}}])["content_passes"] == 0
    assert packet["frozen_facts"]["cable_diameter"] == "missing"


def test_correct_missing_fit_clarification_is_not_a_profile_failure() -> None:
    packet = {"frozen_facts": {"cable_diameter": "missing"}, "intrinsic_expectations": {"must_request": ["cable diameter"]}}
    response = {"clarification_required": True, "generation_ready": False, "clarification_questions": ["What is the cable diameter?"]}

    assert evaluate_requirements_correction(packet, response)["result"] == "pass"
    assert clarification_outcome(facts=packet["frozen_facts"], response=response, answer_submitted=False, resumed=False) == "clarification_not_answered"


def test_missing_fit_terms_allow_normal_word_order_in_questions() -> None:
    packet = {"frozen_facts": {"cable_diameter": "missing"}, "intrinsic_expectations": {"must_request": ["cable diameter"]}}
    response = {"clarification_required": True, "generation_ready": False, "clarification_questions": [{"question": "What is the diameter of the cable?"}]}

    assert evaluate_requirements_correction(packet, response)["result"] == "pass"


def test_worker_runtime_exception_implies_reach_but_not_cad_success() -> None:
    result = worker_reach_semantics({
        "source_contract_passed": True,
        "source_submitted": True,
        "worker": {"status": "runtime_failed", "runtime_error": "CadQuery exception"},
    })

    assert result["worker_ready_valid_source"] is True
    assert result["worker_reached"] is True
    assert result["worker_runtime_failed"] is True
    assert result["worker_completed"] is False


def test_earliest_blocker_and_furthest_stage_are_deterministic() -> None:
    stages = [
        {"stage": "geometry", "reached": True, "passed": False, "blocker": "source_contract"},
        {"stage": "requirements", "reached": True, "passed": False, "blocker": "clarification_required"},
        {"stage": "plan", "reached": True, "passed": True},
    ]

    assert earliest_blocker(stages=stages) == "clarification_required"
    assert furthest_valid_stage(stages=stages) == "plan"


def test_settings_replacement_deduplicates_the_failed_logical_operation() -> None:
    failed_id = "old:s1:geometry:rep-1"
    old = [{"settings_profile": "S1-profile-b", "logical_operation_id": failed_id, "success": False, "complete": False, "status_code": 504, "intrinsic_quality": {"result": "transport_failure"}}]
    old.extend(_record("S1-profile-b", "pass") | {"logical_operation_id": f"old:s1:{index}"} for index in range(11))
    replacement = _record("S1-profile-b", "pass") | {"logical_operation_id": "replacement:s1:geometry:rep-1", "replacement_of_logical_operation_id": failed_id, "complete": True}

    decision = _settings_selection(old, replacement)

    summary = decision["summaries"]["S1-profile-b"]
    assert summary["logical_operations"] == 12
    assert summary["complete"] is True
    assert summary["content_bearing_responses"] == 12
    assert decision["historical_transport_failures_excluded"]["S1-profile-b"] == 1


def test_stage_selection_does_not_authorize_holdout_without_repair_prompt() -> None:
    selection = stage_prompt_selection(Path("/root/volundr"), {"selected_prompt": "T2-requirements-missing-fit-v1"}, {"selected_prompt": None})

    assert selection["selected"] is False
    assert selection["stages"]["requirements"]["selected_prompt"] == "T2-requirements-missing-fit-v1"
    assert selection["stages"]["repair"]["selected_prompt"] is None


def test_clarification_answered_is_distinct_from_requested() -> None:
    assert clarification_outcome(facts={"width": "missing"}, response={"clarification_required": True}, answer_submitted=True, resumed=True) == "clarification_answered"


def test_clarification_answer_failure_is_distinct_from_missing_answer() -> None:
    assert clarification_outcome(facts={"width": "missing"}, response={"clarification_required": True}, answer_submitted=True, resumed=False) == "clarification_answer_failed"


def test_incorrect_clarification_request_is_classified() -> None:
    assert clarification_outcome(facts={"width": "missing"}, response={"clarification_required": False}, answer_submitted=False, resumed=False) == "clarification_required_incorrectly"


def test_clarification_not_required_is_classified() -> None:
    assert clarification_outcome(facts={"width": 78}, response={"clarification_required": False}, answer_submitted=False, resumed=False) == "clarification_not_required"


def test_source_contract_pass_is_detected_from_generation_chain() -> None:
    assert source_contract_passed({"chain": {"stages": [{"source_contract_passed_hard_checks": True}]}}) is True


def test_submitted_source_without_contract_is_not_worker_ready() -> None:
    result = worker_reach_semantics({"source_submitted": True, "source_contract_passed": False})

    assert result["worker_reached"] is True
    assert result["worker_ready_valid_source"] is False


def test_worker_runtime_failure_is_not_worker_completion() -> None:
    result = worker_reach_semantics({"worker": {"status": "runtime_failed", "runtime_error": "CadQuery exception"}})

    assert result["worker_reached"] is True
    assert result["worker_completed"] is False
    assert result["worker_runtime_failed"] is True


def test_h1_generation_config_omits_thinking_for_repair() -> None:
    assert "thinkingConfig" not in _generation_config("S0-current-explicit", "H1-provider-default", "repair", "T2-repair-bounded-payload-v1")


def test_transport_denominator_marks_quota_as_excluded() -> None:
    result = corrected_content_denominator([_record("S0-current-explicit", "quota_failure", status_code=429)])

    assert result["content_bearing_responses"] == 0
    assert result["quota_failures"] == 1
    assert result["transport_excluded_from_content"] is True


def test_retry_policy_waits_once_for_hard_429_and_transport() -> None:
    assert correction.retry_wait_seconds(429, 0) == 30.0
    assert correction.retry_wait_seconds(429, 1) is None
    assert correction.retry_wait_seconds(504, 0) == 10.0
    assert correction.retry_wait_seconds(504, 1) is None
    assert correction.retry_wait_seconds(400, 0) is None


def test_correction_call_retries_429_once_without_third_attempt(monkeypatch) -> None:
    packet = correction.repair_packets_v2()[2]
    responses = [httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED"}}), httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED"}}), httpx.Response(200)]

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(correction.asyncio, "sleep", no_sleep)

    class Limiter:
        def __init__(self):
            self.events = []

        async def acquire(self):
            return {"call_start_monotonic": float(len(self.events)), "prior_rolling_window_count": len(self.events), "sleep_seconds": None}

    async def run():
        async def handler(_: httpx.Request) -> httpx.Response:
            return responses.pop(0)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://example.test") as client:
            return await correction._call_provider_no_hard_429(client=client, limiter=Limiter(), logical_operation_id="retry-test", packet=packet, settings_profile="S0-current-explicit", thinking_profile="H1-provider-default", prompt_profile="T3-repair-executable-replacement-v1", prompt="frozen", generation_config={}, key="secondary-test")

    result = asyncio.run(run())
    assert [item["status_code"] for item in result["attempts"]] == [429, 429]
    assert len(responses) == 1
    assert all(item["logical_operation_id"] == "retry-test" for item in result["attempts"])


def test_h1_repair_generation_config_omits_thinking_config() -> None:
    config = correction._generation_config("S0-current-explicit", "H1-provider-default", "repair", "T3-repair-executable-replacement-v1")
    assert "thinkingConfig" not in config
