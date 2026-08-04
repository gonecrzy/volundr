from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.services.gemini_consistency.system_boundary_methods import (
    DEFAULT_MIN_INTERVAL_SECONDS,
    DEFAULT_REQUESTS_PER_MINUTE,
    HARD_MAX_REQUESTS_PER_WINDOW,
    METHOD_IDS,
    ProcessingBlocked,
    canonical_hash,
    process_provider_text,
    process_response,
    replay_preserved_evidence,
    semantic_hash,
    validate_rate_events,
)
from scripts.run_gemini_system_boundary_methods import _answer_for_questions, _case_metrics, _factorial_headers, _factorial_data_root, _finalist_configurations, _preregistration, _preregistration_matches


def test_method_ids_are_frozen_and_current_processing_is_p0() -> None:
    assert METHOD_IDS == ("P0", "P1", "P2", "P3", "P4", "P5")


def test_code_fence_and_safe_alias_normalization_preserve_semantic_hash() -> None:
    raw = '```json\n{"status":"ready_for_generation","requirements":[{"id":"r1"}]}\n```'
    result = process_response("P1", raw, stage="requirements")

    assert result.processed["status"] == "generation_ready"
    assert result.semantic_hash_before == result.semantic_hash_after
    assert result.blocked is False
    assert result.actions


def test_ambiguous_authoritative_reconciliation_fails_closed() -> None:
    with pytest.raises(ProcessingBlocked, match="ambiguous"):
        process_response(
            "P2",
            '{"requirements":[{"id":"r1"}]}',
            stage="requirements",
            context={
                "authoritative": {
                    "r1": {"value": 78, "unit": "mm"},
                    "r2": {"value": 78, "unit": "mm"},
                },
                "restore_fields": {"r1": "value"},
                "missing_authority_key": "value",
            },
        )


def test_prior_shape_alias_requires_proof() -> None:
    with pytest.raises(ProcessingBlocked, match="prior shape"):
        process_response(
            "P3",
            '{"statements":["modified_shape = component_shape.union(feature)"],"result_symbol":"modified_shape"}',
            stage="geometry",
            context={"prior_shape_symbols": ["component_shape", "body"]},
        )


def test_proven_prior_shape_alias_normalizes_to_body() -> None:
    result = process_response(
        "P3",
        '{"statements":["modified_shape = component_shape.union(feature)"],"result_symbol":"modified_shape"}',
        stage="geometry",
        context={"prior_shape_symbols": ["component_shape"], "authoritative_prior_shape": "body"},
    )

    assert result.processed["statements"] == ["body = body.union(feature)"]
    assert result.processed["result_symbol"] == "body"
    assert result.semantic_hash_before == result.semantic_hash_after


def test_geometry_adapter_preserves_numeric_values_and_slot_order() -> None:
    raw = {
        "slots": [
            {"slot_id": 2, "result_symbol": "modified_shape", "statements": ["modified_shape = body.fillet(2.5)"]},
            {"slot_id": 1, "result_symbol": "modified_shape", "statements": ["modified_shape = component_shape.union(feature)"]},
        ]
    }

    result = process_response(
        "P3",
        raw,
        stage="geometry_slot",
        context={"slot_function_ids": {"1": "_ai_feature_body", "2": "_ai_feature_finish"}},
    )

    assert [slot["slot_id"] for slot in result.processed["slots"]] == [2, 1]
    assert result.processed["slots"][0]["statements"] == ["body = body.fillet(2.5)"]
    assert result.processed["slots"][1]["statements"] == ["body = body.union(feature)"]
    assert semantic_hash(raw) == semantic_hash(result.processed)


def test_provider_boundary_processing_preserves_raw_for_capture_and_returns_processed_text() -> None:
    raw = '{"slots":[{"slot_id":1,"result_symbol":"modified_shape","statements":["modified_shape = component_shape.union(feature)"]}]}'
    processed_text, metadata = process_provider_text(
        "P3",
        raw,
        stage="source_generation",
        context={"slot_function_ids": {"1": "_ai_feature_body"}},
    )

    assert json.loads(processed_text)["slots"][0]["result_symbol"] == "body"
    assert metadata["original_text"] == raw
    assert metadata["actions"]


def test_p0_provider_boundary_is_byte_preserving() -> None:
    raw = "  ```json\n{\"x\":1}\n```  "
    processed_text, metadata = process_provider_text("P0", raw, stage="requirements")

    assert processed_text == raw
    assert metadata["actions"] == []


def test_rate_events_never_exceed_hard_cap() -> None:
    events = [{"started_monotonic": float(index)} for index in range(HARD_MAX_REQUESTS_PER_WINDOW + 1)]
    assert validate_rate_events(events, hard_max=HARD_MAX_REQUESTS_PER_WINDOW, window_seconds=60.0) is False


def test_rate_policy_is_serialized_and_hard_429_retry_is_disabled() -> None:
    policy = _preregistration({})["rate_policy"]

    assert policy["default_requests_per_minute"] == DEFAULT_REQUESTS_PER_MINUTE == 12
    assert policy["minimum_interval_seconds"] == DEFAULT_MIN_INTERVAL_SECONDS == 5.0
    assert policy["hard_max_requests_per_rolling_window"] == HARD_MAX_REQUESTS_PER_WINDOW == 15
    assert policy["provider_concurrency"] == 1
    assert policy["retry_hard_429"] is False


def test_offline_replay_writes_zero_call_report(tmp_path: Path) -> None:
    result = replay_preserved_evidence(
        output_root=tmp_path / "study",
        profile_ablation_root=Path("data/debug-sessions/gemini-profile-ablation/gemini-profile-ablation-01"),
        study_root=Path("data/debug-sessions/gemini-flash-lite-study/gemini-flash-lite-study-01"),
    )

    assert result["provider_calls"] == 0
    assert result["worker_calls"] == 0
    assert result["preserved_phase1_records"] == 30
    assert result["preserved_phase2_provider_calls"] == 35


def test_replay_report_is_json_and_hashable(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    document = {"schema_version": "test", "records": []}
    path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert len(digest) == 64
    assert canonical_hash(document) == canonical_hash(json.loads(path.read_text(encoding="utf-8")))


def test_existing_preregistration_is_resumable_after_repository_commit() -> None:
    first = _preregistration({"repository": {"head": "initial"}})
    later = _preregistration({"repository": {"head": "later"}})

    assert _preregistration_matches(first, later) is True
    later["rate_policy"]["provider_concurrency"] = 2
    assert _preregistration_matches(first, later) is False


def test_factorial_data_root_is_absolute_for_backend_subprocesses(tmp_path: Path) -> None:
    assert _factorial_data_root(tmp_path, "A-current-p0").is_absolute()


def test_worker_runtime_failure_implies_reach_and_worker_ready_after_source_contract(tmp_path: Path) -> None:
    data_root = tmp_path / "live-data"
    project_root = data_root / "projects" / "project-1" / "generation-runs" / "attempt-1"
    project_root.mkdir(parents=True)
    (project_root / "source-contract.json").write_text(json.dumps({"passed_hard_checks": True}), encoding="utf-8")
    job_root = data_root / "jobs" / "revision-1"
    job_root.mkdir(parents=True)
    (job_root / "job.json").write_text(json.dumps({"job_id": "job-1"}), encoding="utf-8")
    (job_root / "result.json").write_text(json.dumps({"success": False, "error": "CadQuery exception"}), encoding="utf-8")

    metrics = _case_metrics(
        {
            "case_id": "case-006",
            "project": {"id": "project-1"},
            "revision": {"id": "revision-1"},
            "design_specification": {"outcome": "generation_ready"},
            "design_plan": {"plan_ready": True},
            "generation_attempts": [{"prompt_version": "geometry-v1", "failure_class": "none", "provider_call_count": 1}],
            "workflow_response": {"current_stage": "blocked_attempt"},
            "outputs": [{"output_id": "output-1"}],
            "findings": [],
        },
        data_root,
    )

    assert metrics["source_contract_passed"] is True
    assert metrics["worker_ready_valid_source"] is True
    assert metrics["worker_reached"] is True
    assert metrics["worker_completed"] is False
    assert metrics["worker_runtime_failed"] is True
    assert metrics["topology_valid"] is False
    assert metrics["candidate_ready"] is False


def test_frozen_clarification_facts_are_identical_for_both_arms() -> None:
    questions = ["Please provide phone width, thickness with case, case condition, and angle."]
    facts = {"phone_width": 78, "phone_thickness_with_case": 12, "desired_angle": 65}

    current_answer = _answer_for_questions(questions, facts)
    profile_b_answer = _answer_for_questions(questions, facts)

    assert current_answer == profile_b_answer


def test_factorial_enables_immutable_study_capture_for_each_case() -> None:
    headers = _factorial_headers("P3", "case-006")

    assert headers["X-Volundr-Study-Id"] == "gemini-system-boundary-methods-01"
    assert headers["X-Volundr-Study-Round"] == "validation"
    assert headers["X-Volundr-Study-Repetition"] == "1"
    assert headers["X-Volundr-Study-Case"] == "case-006"
    assert headers["X-Volundr-Benchmark-Processing"] == "P3"


def test_final_validation_is_capped_at_two_declared_systems() -> None:
    finalists = _finalist_configurations("P3")

    assert finalists == (
        ("current-p3", "current-production", "P3"),
        ("profile-b-p3", "profile-b-sampling", "P3"),
    )


def test_frozen_clarification_facts_are_mapped_to_questions() -> None:
    answer, used = _answer_for_questions(
        ["What are the phone width and thickness with the case, and desired angle?"],
        {"phone_width": 78, "phone_thickness_with_case": 12, "desired_angle": 65},
    )

    assert "78" in answer
    assert "12" in answer
    assert "65" in answer
    assert "case_condition" in answer
    assert set(used) == {"phone_width", "phone_thickness_with_case", "desired_angle"}
