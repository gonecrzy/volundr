from pathlib import Path

from app.services.gemini_integration.capture import (
    IntegrationEvidenceStore,
    build_combined_bundle,
)


def test_capture_store_is_idempotent_and_records_every_attempt(tmp_path: Path) -> None:
    store = IntegrationEvidenceStore(
        tmp_path,
        study_id="gemini-provider-contract-integration-01",
    )
    attempt = {
        "study_id": "gemini-provider-contract-integration-01",
        "operation_id": "operation-001",
        "attempt_id": "attempt-001",
        "stage": "requirements",
        "request": {"generationConfig": {"candidateCount": 1}},
        "response": {"text": "{}"},
    }

    first = store.record_provider_attempt(attempt)
    second = store.record_provider_attempt(attempt)
    bundle = build_combined_bundle(store)

    assert first == second
    assert len(bundle["provider_attempts"]) == 1
    assert bundle["provider_attempts"][0]["attempt_id"] == "attempt-001"
    assert bundle["schema_version"] == "volundr-provider-contract-integration-v1"

