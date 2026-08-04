from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.services.gemini_consistency.system_boundary_methods import (
    HARD_MAX_REQUESTS_PER_WINDOW,
    METHOD_IDS,
    ProcessingBlocked,
    canonical_hash,
    process_provider_text,
    process_response,
    replay_preserved_evidence,
    validate_rate_events,
)
from scripts.run_gemini_system_boundary_methods import _preregistration, _preregistration_matches


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
