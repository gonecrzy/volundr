from __future__ import annotations

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
    worker_reach_semantics,
)
from scripts.run_gemini_provider_contract_foundation import _generation_config


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
