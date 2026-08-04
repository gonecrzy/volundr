import json
from pathlib import Path

from app.services.gemini_consistency.interaction_capture import (
    ImmutableInteractionCapture,
    StudyContext,
)


def test_study_provider_call_is_written_once_with_identity_and_redaction(tmp_path: Path) -> None:
    capture = ImmutableInteractionCapture(
        tmp_path,
        StudyContext(
            study_id="gemini-flash-lite-study-01",
            round="baseline",
            repetition=1,
            case_id="case-001",
            project_id="project-001",
            user_operation_id="operation-001",
        ),
    )

    call_id, path = capture.record_call(
        stage="requirements",
        prompt_mode="requirements",
        requested_model="gemini-3.5-flash-lite",
        actual_model="gemini-3.5-flash-lite",
        rendered_prompt="api_key=secret-value\nCreate a phone stand.",
        request_payload={"generationConfig": {"temperature": 0.2}},
        response_payload={"text": "{\"ok\": true}"},
        raw_text='{"ok": true}',
        status_code=200,
        provider_metadata={"request_id": "request-001"},
        usage_metadata={"totalTokenCount": 12},
        latency_ms=42,
    )

    assert call_id
    assert path.is_file()
    assert "baseline/repetition-01/projects/case-001/project-001/provider-calls" in str(path)
    first_bytes = path.read_bytes()
    document = json.loads(first_bytes)
    assert document["fixture_version"] == "gemini-live-response-v1"
    assert document["provider_call_id"] == call_id
    assert document["request"]["requested_model"] == "gemini-3.5-flash-lite"
    assert document["response"]["raw_text"] == '{"ok": true}'
    assert "secret-value" not in path.read_text()

    # The same call ID can never replace its original bytes.
    assert capture.write_existing(call_id, {"changed": True}) is False
    assert path.read_bytes() == first_bytes


def test_provider_failure_is_captured_without_counting_as_cad_quality(tmp_path: Path) -> None:
    capture = ImmutableInteractionCapture(
        tmp_path,
        StudyContext("study", "baseline", 2, "case-002", "project-002", "operation-002"),
    )

    _, path = capture.record_call(
        stage="geometry_slots",
        prompt_mode="geometry_slots",
        requested_model="gemini-3.5-flash-lite",
        actual_model=None,
        rendered_prompt="prompt",
        request_payload={"generationConfig": {}},
        response_payload=None,
        raw_text=None,
        status_code=429,
        provider_metadata={"retry_after": 60},
        usage_metadata=None,
        latency_ms=100,
        error_category="provider_quota_exhausted",
    )

    document = json.loads(path.read_text())
    assert document["response"]["error_category"] == "provider_quota_exhausted"
    assert document["processing"]["accepted"] is False
