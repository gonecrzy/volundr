from __future__ import annotations

import copy
import json

import pytest

from app.services.gemini_consistency.interaction_capture import (
    ImmutableInteractionCapture,
    StudyContext,
)
from app.services.workflow.redaction import RedactionService
from app.services.gemini_consistency.profile_ablation import (
    PHASE1_CALL_LIMIT,
    PHASE2_CASE_IDS,
    AblationProfile,
    FrozenPacket,
    build_profiles,
    build_request_payload,
    balanced_execution_order,
    phase1_decision,
    phase2_plan,
    semantic_response_key,
    validate_phase1_budget,
)


def _packet() -> FrozenPacket:
    return FrozenPacket(
        packet_id="packet-01",
        originating_study="gemini-flash-lite-study-01",
        round_name="baseline",
        case_id="case-001",
        repetition=1,
        original_provider_call_id="original-call",
        stage="requirements",
        prompt_mode="requirements",
        rendered_prompt="AUTHORITATIVE CONTEXT\n{\"x\": 1}\nTASK\nReturn JSON only.",
        original_request_payload={
            "contents": [{"role": "user", "parts": [{"text": "original"}]}],
            "generationConfig": {
                "temperature": 0.2,
                "topP": 0.95,
                "maxOutputTokens": 8192,
                "thinkingConfig": {"thinkingLevel": "MINIMAL"},
            },
        },
        original_response={"candidates": []},
        expected_semantic_record={"required_ids": ["req-1"]},
        original_blocker="provenance",
        selection_reason="test fixture",
        packet_hash="packet-hash",
    )


def test_profiles_change_only_the_declared_dimensions() -> None:
    packet = _packet()
    profiles = {profile.profile_id: profile for profile in build_profiles()}
    current = build_request_payload(packet, profiles["profile-a-current"])

    sampling = build_request_payload(packet, profiles["profile-b-sampling"])
    assert sampling["contents"] == current["contents"]
    assert sampling["generationConfig"]["seed"] == 1701
    assert "temperature" not in sampling["generationConfig"]
    assert "topP" not in sampling["generationConfig"]
    assert "responseMimeType" not in sampling["generationConfig"]

    concise = build_request_payload(packet, profiles["profile-c-concise-prompt"])
    assert concise["generationConfig"] == current["generationConfig"]
    assert concise["contents"] != current["contents"]
    assert concise["contents"][0]["parts"][0]["text"].endswith(
        "Do not include explanations outside the response contract."
    )

    structured = build_request_payload(packet, profiles["profile-d-structured-output"])
    assert structured["contents"] == current["contents"]
    structured_base = {
        key: value
        for key, value in structured["generationConfig"].items()
        if key not in {"responseMimeType", "responseSchema"}
    }
    assert structured_base == current["generationConfig"]
    assert structured["generationConfig"]["responseMimeType"] == "application/json"
    assert isinstance(structured["generationConfig"]["responseSchema"], dict)


def test_profile_e_contains_only_the_declared_combination() -> None:
    packet = _packet()
    profiles = {profile.profile_id: profile for profile in build_profiles()}
    current = build_request_payload(packet, profiles["profile-a-current"])
    combined = build_request_payload(packet, profiles["profile-e-recommended-combined"])
    config = combined["generationConfig"]

    assert combined["contents"] != current["contents"]
    assert config["seed"] == 1701
    assert config["candidateCount"] == 1
    assert config["thinkingConfig"] == {"thinkingLevel": "MINIMAL"}
    assert config["responseMimeType"] == "application/json"
    assert "temperature" not in config
    assert "topP" not in config
    assert "topK" not in config


def test_execution_order_is_balanced_and_budgeted() -> None:
    order = balanced_execution_order()
    assert len(order) == PHASE1_CALL_LIMIT
    assert len(set(order)) == PHASE1_CALL_LIMIT
    assert {item[0] for item in order} == {"packet-01", "packet-02", "packet-03"}
    assert {item[1] for item in order} == {
        "profile-a-current",
        "profile-b-sampling",
        "profile-c-concise-prompt",
        "profile-d-structured-output",
        "profile-e-recommended-combined",
    }
    validate_phase1_budget(order)


def test_packet_and_response_identity_are_immutable_and_volatile_insensitive() -> None:
    packet = _packet()
    payload = {"id": "response-1", "created_at": "2026-08-04T00:00:00Z", "value": 2}
    changed = copy.deepcopy(payload)
    changed["id"] = "response-2"
    changed["created_at"] = "2026-08-05T00:00:00Z"
    assert semantic_response_key(payload) == semantic_response_key(changed)
    assert packet.packet_hash == "packet-hash"


def test_phase2_requires_a_qualifying_profile_and_freezes_cases() -> None:
    with pytest.raises(ValueError, match="qualifying"):
        phase2_plan({"qualifies": False, "profile_id": "profile-e-recommended-combined"})

    plan = phase2_plan({"qualifies": True, "profile_id": "profile-e-recommended-combined"})
    assert plan["case_ids"] == list(PHASE2_CASE_IDS)
    assert plan["arms"] == ["current-production", "winning-experimental"]
    assert plan["operations"] == 10


def test_advancement_requires_provenance_and_protected_identity_safety() -> None:
    decision = phase1_decision(
        baseline_profile_id="profile-a-current",
        profile_results={
            "profile-a-current": {"accepted_runs": 0, "semantic_consistency_packets": 0},
            "profile-b-sampling": {
                "accepted_runs": 2,
                "semantic_consistency_packets": 2,
                "provenance_regression": True,
                "protected_identity_regression": False,
            },
        },
    )
    assert decision["qualifying_profiles"] == []


def test_immutable_capture_records_experiment_identity(tmp_path) -> None:
    capture = ImmutableInteractionCapture(
        tmp_path,
        StudyContext(
            study_id="profile-ablation-01",
            round="phase-1",
            repetition=1,
            case_id="packet-01",
            project_id="profile-a-current",
            user_operation_id="operation-1",
        ),
    )
    call_id, path = capture.record_call(
        stage="requirements",
        prompt_mode="requirements",
        requested_model="gemini-3.5-flash-lite",
        actual_model="gemini-3.5-flash-lite",
        rendered_prompt="return json",
        request_payload={"generationConfig": {"maxOutputTokens": 8192}},
        response_payload={"candidates": []},
        raw_text="{}",
        status_code=200,
        provider_metadata={},
        usage_metadata={},
        latency_ms=1,
        experiment_metadata={"profile_id": "profile-a-current", "packet_hash": "hash"},
    )
    document = json.loads(path.read_text())
    assert document["experiment"]["profile_id"] == "profile-a-current"
    assert document["experiment"]["packet_hash"] == "hash"
    assert document["request"]["generation_settings"]["maxOutputTokens"] == 8192
    assert call_id


def test_ablation_reports_preserve_token_metrics_during_redaction(tmp_path) -> None:
    safe, _ = RedactionService().redact_evidence_value(
        {"tokens": 42, "total_tokens": 42, "api_key": "secret"},
        data_root=tmp_path,
        evidence_root=tmp_path,
    )
    assert safe["tokens"] == 42
    assert safe["total_tokens"] == 42
    assert safe["api_key"] == "[REDACTED]"
