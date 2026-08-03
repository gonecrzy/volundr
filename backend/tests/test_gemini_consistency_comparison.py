from app.services.gemini_consistency.comparison import (
    classify_field,
    compare_evidence,
    controlled_comparison,
    failure_signature,
    semantic_equal,
)


def test_semantic_equivalence_handles_numeric_tolerance_and_id_lists() -> None:
    left = {
        "dimensions": {"width": 100.0, "height": 40.0},
        "outputs": [{"id": "body", "count": 1}, {"id": "lid", "count": 1}],
    }
    right = {
        "dimensions": {"height": 40.0004, "width": 100.0004},
        "outputs": [{"id": "lid", "count": 1}, {"id": "body", "count": 1}],
    }

    assert semantic_equal(left, right)
    assert classify_field(left, right) == "semantically_equivalent"


def test_classification_distinguishes_failures_and_material_changes() -> None:
    assert classify_field(None, {"status": "ok"}) == "one_sided_failure"
    assert classify_field(
        {"status": "failed"},
        {"status": "failed"},
        failure_a="worker_timeout",
        failure_b="worker_timeout",
    ) == "both_failed_same_signature"
    assert classify_field(
        {"status": "failed"},
        {"status": "failed"},
        failure_a="worker_timeout",
        failure_b="provider_schema_error",
    ) == "both_failed_different_signature"
    assert classify_field({"output_count": 1}, {"output_count": 2}) == "materially_inconsistent"


def test_failure_signature_is_normalized_without_raw_secret_material() -> None:
    signature = failure_signature(
        {
            "outcome_category": "worker_failure",
            "error": "Authorization: Bearer secret-value",
            "workspace": {"artifact_integrity": {"missing_count": 2}},
        }
    )

    assert signature == "missing_artifacts"
    assert "secret-value" not in signature


def test_failure_signature_reports_provider_failure_from_authoritative_attempts() -> None:
    signature = failure_signature(
        {
            "outcome_category": "completed",
            "chat_responses": [
                {
                    "response": {
                        "blocked_attempt": {
                            "failure_class": "provider_failure",
                        }
                    }
                }
            ],
            "generation_attempts": [
                {"status": "failed", "failure_class": "provider_failure"}
            ],
        }
    )

    assert signature == "provider_failure"


def test_controlled_comparison_reports_every_identity_mismatch() -> None:
    first = {
        "git_head": "abc",
        "migration_head": "0035",
        "provider": "gemini_api",
        "model_policy": {"temperature": 0.2},
        "prompt_versions": {"requirements": "v1"},
        "configuration_hash": "config-a",
        "build_identities": {"backend": {"git_sha": "abc"}},
    }
    second = {**first, "configuration_hash": "config-b", "build_identities": {"backend": {"git_sha": "def"}}}

    result = controlled_comparison(first, second)

    assert result.controlled is False
    assert {item["field"] for item in result.mismatches} == {"configuration_hash", "build_identities"}


def test_compare_evidence_scores_each_workflow_dimension_separately() -> None:
    left = {"requirements": {"a": 1}, "planning": {"b": 2}, "execution": {"c": 3}, "outcome": {"d": 4}}
    right = {"requirements": {"a": 1}, "planning": {"b": 3}, "execution": {"c": 3}, "outcome": {"d": 4}}

    comparison = compare_evidence(left, right)

    assert set(comparison["scores"]) == {"response_structure", "requirements", "planning", "execution", "outcome"}
    assert comparison["scores"]["requirements"]["score"] == 1.0
    assert comparison["scores"]["planning"]["score"] < 1.0
