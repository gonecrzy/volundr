from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.gemini_consistency.buildability_reanalysis import (
    MAX_ROLLING_REQUESTS,
    QUALITY_FLOOR_RESULTS,
    RollingWindowRateLimiter,
    authoritative_packet_expectations,
    apply_profile_b_generation_config,
    buildability_scorecard,
    evaluate_quality_floor,
    preserve_historical_reports,
    qualify_stable_foundation,
    rescore_phase1_records,
    repeatability_metrics,
    write_manual_review_bundle,
)


def test_authoritative_packet_02_expectations_are_not_provider_derived() -> None:
    expectations = authoritative_packet_expectations()
    packet = expectations["packet-02"]

    assert packet["capacity"] == 2
    assert packet["tray_dimensions_mm"] == {"width": 276, "depth": 184, "thickness": 44}
    assert packet["loading_orientation"] == "vertical_top"
    assert packet["required_features"] == {
        "carrying_handle",
        "bottom_drainage",
        "two_retention_strap_slots",
        "mostly_open_side_walls",
    }


def test_authoritative_packet_03_expected_slot_ids_are_exactly_one_through_four() -> None:
    assert authoritative_packet_expectations()["packet-03"]["expected_slot_ids"] == ["1", "2", "3", "4"]


def test_empty_nested_objects_fail_the_quality_floor() -> None:
    result = evaluate_quality_floor("packet-02", {
        "schema_version": "compact-cad-plan-v1",
        "components": [{}],
        "features": [{}],
        "relationships": [],
        "printable_outputs": [{}],
        "plan_ready": True,
    })

    assert result["result"] == "fail_structurally_empty"
    assert result["structural_emptiness_findings"]


def test_empty_ready_plan_fails_even_when_json_shape_is_valid() -> None:
    result = evaluate_quality_floor("packet-02", {
        "schema_version": "compact-cad-plan-v1",
        "components": [],
        "features": [],
        "relationships": [],
        "printable_outputs": [],
        "plan_ready": True,
    })

    assert result["result"] == "fail_structurally_empty"


def test_empty_geometry_slots_fail_the_quality_floor() -> None:
    result = evaluate_quality_floor("packet-03", {
        "schema_version": "volundr-geometry-slots-v1",
        "slots": [{"slot_id": 1, "statements": [], "result_symbol": ""}],
    })

    assert result["result"] == "fail_structurally_empty"


def test_geometry_floor_accepts_equivalent_radius_and_derived_wall_thickness() -> None:
    result = evaluate_quality_floor("packet-03", {
        "schema_version": "volundr-geometry-slots-v1",
        "slots": [
            {"slot_id": 1, "statements": ["rect_flange = rect(100, 60).extrude(12)"], "result_symbol": "shape"},
            {"slot_id": 2, "statements": ["transition = rect(100, 60).loft(circle(35), length=85)"], "result_symbol": "shape"},
            {"slot_id": 3, "statements": ["circle_flange = circle(45).extrude(12)"], "result_symbol": "shape"},
            {"slot_id": 4, "statements": ["inner = rect(94, 54).loft(circle(32)); shape = shape.cut(inner)"], "result_symbol": "shape"},
        ],
    })

    assert result["result"] == "pass"


def test_invented_critical_phone_fit_fails_but_safe_assumption_does_not() -> None:
    invented = evaluate_quality_floor("packet-01", {
        "clarification_required": False,
        "generation_ready": True,
        "critical_dimensions": [{"id": "phone_width", "value": 78, "unit": "mm", "source": "user"}],
        "functional_requirements": [
            {"id": "portrait", "description": "portrait", "source": "user"},
            {"id": "landscape", "description": "landscape", "source": "user"},
            {"id": "charging", "description": "charging port access", "source": "user"},
        ],
    })
    safe = evaluate_quality_floor("packet-01", {
        "clarification_required": True,
        "generation_ready": False,
        "assumptions": [{"id": "phone_fit", "source": "ai_assumption", "value": "unknown"}],
        "clarification_questions": [{"id": "phone_dimensions", "question": "What is the phone width?"}],
        "functional_requirements": [
            {"id": "portrait", "description": "portrait", "source": "user"},
            {"id": "landscape", "description": "landscape", "source": "user"},
            {"id": "charging", "description": "charging port access", "source": "user"},
        ],
    })

    assert invented["result"] == "fail_invented_critical_meaning"
    assert safe["result"] in {"pass", "pass_with_safe_normalization"}


def test_profile_b_can_qualify_at_baseline_acceptance_ceiling() -> None:
    summaries = {
        "profile-a-current": {"quality_floor_passes": 6, "accepted_runs": 6, "semantic_quality": 0.80, "semantic_consistency_packets": 0},
        "profile-b-sampling": {"quality_floor_passes": 6, "accepted_runs": 6, "semantic_quality": 0.79, "semantic_consistency_packets": 3},
    }

    decision = qualify_stable_foundation(summaries, baseline_profile_id="profile-a-current")

    assert decision["qualifying_profiles"] == ["profile-b-sampling"]
    assert decision["criteria"]["profile-b-sampling"]["acceptance_noninferior"] is True


def test_profile_b_live_override_changes_sampling_only() -> None:
    config = {"temperature": 0.2, "topP": 0.95, "topK": 40, "maxOutputTokens": 8192}

    overridden = apply_profile_b_generation_config(config)

    assert overridden["maxOutputTokens"] == 8192
    assert overridden["candidateCount"] == 1
    assert overridden["seed"] == 1701
    assert "temperature" not in overridden
    assert "topP" not in overridden
    assert "topK" not in overridden


def test_semantic_noninferiority_margin_is_applied() -> None:
    summaries = {
        "profile-a-current": {"quality_floor_passes": 6, "accepted_runs": 6, "semantic_quality": 0.80, "semantic_consistency_packets": 0},
        "profile-b-sampling": {"quality_floor_passes": 6, "accepted_runs": 6, "semantic_quality": 0.779, "semantic_consistency_packets": 3},
    }

    decision = qualify_stable_foundation(summaries, baseline_profile_id="profile-a-current")

    assert decision["qualifying_profiles"] == []
    assert decision["criteria"]["profile-b-sampling"]["semantic_noninferior"] is False


def test_semantic_and_byte_repeatability_are_reported_separately() -> None:
    metrics = repeatability_metrics([
        {"packet_id": "packet-01", "semantic_key": "same", "raw_hash": "a", "quality_floor": {"result": "pass"}},
        {"packet_id": "packet-01", "semantic_key": "same", "raw_hash": "b", "quality_floor": {"result": "pass"}},
    ])

    assert metrics == {"semantic_consistent_packets": 1, "byte_identical_packets": 0, "eligible_packets": 1}


def test_buildability_dimensions_are_independent() -> None:
    score = buildability_scorecard([
        {"profile_id": "profile-b-sampling", "packet_id": "packet-01", "repetition": 1, "quality_floor": {"result": "pass"}, "corrected_semantic_score": 1.0, "semantic_key": "same", "raw_hash": "a", "actual_model": "gemini-3.5-flash-lite", "total_tokens": 10, "latency_ms": 20},
        {"profile_id": "profile-b-sampling", "packet_id": "packet-01", "repetition": 2, "quality_floor": {"result": "pass"}, "corrected_semantic_score": 1.0, "semantic_key": "same", "raw_hash": "b", "actual_model": "gemini-3.5-flash-lite", "total_tokens": 10, "latency_ms": 30},
    ])

    assert score["semantic_stability"] == 1.0
    assert score["structural_stability"] == 1.0
    assert score["efficiency"] > 0
    assert "buildability_score" in score


def test_offline_rescoring_does_not_need_a_provider_client() -> None:
    root = Path(__file__).parents[2] / "data/debug-sessions/gemini-profile-ablation/gemini-profile-ablation-01"
    result = rescore_phase1_records(root)

    assert len(result["records"]) == 30
    assert result["provider_calls"] == 0
    assert set(result["quality_floor_results"]) <= set(QUALITY_FLOOR_RESULTS)


def test_profile_b_offline_floor_counts_all_six_existing_responses() -> None:
    root = Path(__file__).parents[2] / "data/debug-sessions/gemini-profile-ablation/gemini-profile-ablation-01"

    result = rescore_phase1_records(root)

    assert result["profile_summaries"]["profile-b-sampling"]["quality_floor_passes"] == 6
    assert result["profile_summaries"]["profile-b-sampling"]["identity_stability"] == 1.0


def test_manual_review_bundle_embeds_all_thirty_records_and_raw_response(tmp_path: Path) -> None:
    result = {"records": [{"record": index, "raw_response_text": "{}", "parsed_response": {}} for index in range(30)], "profile_summaries": [], "comparisons": [], "decision": {}}
    output = tmp_path / "all-responses-manual-review.json"

    write_manual_review_bundle(output, study={}, repository={}, packets=[], profiles=[], phase1=result, phase2={"run": False, "reason": "offline qualification pending"}, historical_decision={"decision": "old"}, final_recommendation={})

    document = json.loads(output.read_text())
    assert document["schema_version"] == "gemini-profile-ablation-manual-review-v1"
    assert len(document["phase_1"]["records"]) == 30
    assert document["phase_1"]["records"][0]["raw_response_text"] == "{}"


def test_historical_reports_are_copied_without_overwriting_existing_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    (source / "final-decision.json").write_text('{"decision":"old"}\n')
    destination.mkdir()
    (destination / "final-decision.json").write_text('{"decision":"preserved"}\n')

    preserve_historical_reports(source, destination)

    assert json.loads((destination / "final-decision.json").read_text())["decision"] == "preserved"
    assert (destination / "final-decision.json.copy").is_file()


def test_rate_limiter_blocks_the_sixteenth_request_in_a_rolling_minute() -> None:
    now = [100.0]
    sleeps: list[float] = []
    def sleep(duration: float) -> None:
        sleeps.append(duration)
        now[0] += duration

    limiter = RollingWindowRateLimiter(max_requests=MAX_ROLLING_REQUESTS, interval_seconds=60.0, min_interval_seconds=0.0, clock=lambda: now[0], sleep=sleep)

    for _ in range(MAX_ROLLING_REQUESTS):
        limiter.acquire()
    limiter.acquire()

    assert sleeps and sleeps[-1] >= 60.0
    assert limiter.report()["max_requests_per_rolling_window"] == 15
    assert RollingWindowRateLimiter().min_interval_seconds >= 5.0
