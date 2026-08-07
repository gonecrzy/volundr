from scripts.run_executable_cadquery_recovery_wave import _review_failure


def test_measured_blind_review_failure_reenters_semantic_recovery() -> None:
    failure_class, evidence, boundary = _review_failure(
        {
            "requirements": [
                {
                    "requirement_id": "single_external_fillet",
                    "evidence_type": "measured",
                    "verdict": "violated",
                }
            ],
            "discrepancies": ["fillet count mismatch"],
        }
    )

    assert failure_class == "semantic_requirement_failed"
    assert boundary == "semantic"
    assert evidence["failed_requirement_ids"] == ["single_external_fillet"]
    assert evidence["measurement_available"] is True
