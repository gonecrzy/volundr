from scripts.run_executable_cadquery_recovery_wave import _first_failure, _review_failure


def test_worker_execution_failure_precedes_later_topology_in_replay() -> None:
    failure_class, evidence, boundary = _first_failure(
        outputs=[
            {
                "output_id": "support",
                "topology_status": "invalid_shape",
                "expected_solid_count": 1,
                "detected_solid_count": None,
            }
        ],
        semantic={"failed": [], "unverifiable": []},
        package_available=False,
        package_valid=False,
        worker_result={
            "diagnostics": {
                "active_phase": "build_function",
                "failure_operation": "chamfer",
                "failure_exception_type": "StdFail_NotDone",
                "failure_message": "Traceback (most recent call last): /work/jobs/model.py BRep_API: command not done",
            }
        },
    )

    assert failure_class == "cadquery_api_error"
    assert boundary == "execution"
    assert evidence["failure_operation"] == "chamfer"
    assert "Traceback" not in evidence["message"]
    assert "/work/jobs" not in evidence["message"]


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
