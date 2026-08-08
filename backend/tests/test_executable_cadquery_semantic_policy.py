from __future__ import annotations

from app.services.executable_cadquery.semantic_policy import (
    derive_concept_state,
    derive_candidate_policy,
    evaluate_semantic_policy,
)


def _requirement(
    requirement_id: str,
    *,
    verification_policy: str = "final_mesh_bounds",
    policy: str | None = None,
) -> dict:
    value = {
        "requirement_id": requirement_id,
        "expected": {"value": 10.0},
        "tolerance": 0.25,
        "verification_policy": verification_policy,
    }
    if policy is not None:
        value["policy"] = policy
    return value


def _output(*, state: str = "completed", topology: str = "valid", artifact: bool = True) -> dict:
    return {
        "output_id": "primary",
        "required": True,
        "state": state,
        "generation_status": "completed",
        "worker_status": "completed",
        "topology_status": topology,
        "artifact_available": artifact,
    }


def _passing_semantics(requirements: list[dict]) -> dict:
    return {
        "status": "passed",
        "findings": [
            {
                "requirement_id": item["requirement_id"],
                "status": "passed",
                "measurements": {"value": 10.0},
                "evidence_source": "final_mesh",
            }
            for item in requirements
        ],
    }


def test_machine_required_missing_measurement_is_unsupported_verifier() -> None:
    requirement = _requirement("wall_thickness")

    result = evaluate_semantic_policy(
        {"status": "passed", "findings": []},
        {"requirements": [requirement]},
    )

    assert result["status"] == "unsupported_verifier"
    assert result["unsupported_verifier"] == ["wall_thickness"]
    assert result["unverifiable"] == ["wall_thickness"]
    assert result["review_required"] == []
    finding = result["findings"][0]
    assert finding["policy"] == "machine_required"
    assert finding["result"] == "unsupported_verifier"
    assert finding["measurement_available"] is False
    assert finding["evidence_source"] == "none"


def test_only_explicit_review_policy_can_create_review_obligation() -> None:
    requirement = _requirement("surface_finish", policy="review_required")

    result = evaluate_semantic_policy(
        {"status": "passed", "findings": []},
        {"requirements": [requirement]},
    )

    assert result["status"] == "review_required"
    assert result["review_required"] == ["surface_finish"]
    assert result["unsupported_verifier"] == []
    assert result["findings"][0]["result"] == "review_required"


def test_frozen_contract_classification_alias_creates_review_obligation() -> None:
    requirement = _requirement("surface_finish")
    requirement["classification"] = "review_required"

    result = evaluate_semantic_policy(
        {"status": "passed", "findings": []},
        {"requirements": [requirement]},
    )

    assert result["status"] == "review_required"
    assert result["review_required"] == ["surface_finish"]
    assert result["unsupported_verifier"] == []
    assert result["findings"][0]["policy"] == "review_required"


def test_frozen_contract_informational_classification_is_nonblocking() -> None:
    requirement = _requirement("design_choice")
    requirement["classification"] = "informational"

    result = evaluate_semantic_policy(
        {"status": "passed", "findings": []},
        {"requirements": [requirement]},
    )

    assert result["status"] == "passed"
    assert result["review_required"] == []
    assert result["unsupported_verifier"] == []
    assert result["findings"][0]["policy"] == "informational"
    assert result["findings"][0]["result"] == "informational"


def test_machine_required_explicitly_missing_measurement_cannot_pass() -> None:
    requirement = _requirement("wall_thickness")

    result = evaluate_semantic_policy(
        {
            "status": "passed",
            "findings": [
                {
                    "requirement_id": "wall_thickness",
                    "status": "passed",
                    "measurement_available": False,
                }
            ],
        },
        {"requirements": [requirement]},
    )

    assert result["status"] == "unsupported_verifier"
    assert result["findings"][0]["result"] == "unsupported_verifier"


def test_missing_finding_cannot_preserve_a_passing_result() -> None:
    requirements = [_requirement("body_dimensions"), _requirement("wall_thickness")]

    result = evaluate_semantic_policy(
        {
            "status": "passed",
            "findings": [
                {
                    "requirement_id": "body_dimensions",
                    "status": "passed",
                    "measurements": {"value": 10.0},
                }
            ],
        },
        {"requirements": requirements},
    )

    assert result["status"] == "unsupported_verifier"
    assert result["passed"] == ["body_dimensions"]
    assert result["unsupported_verifier"] == ["wall_thickness"]


def test_candidate_ready_for_review_is_derived_from_persisted_evidence() -> None:
    requirements = [_requirement("body_dimensions")]
    semantic = evaluate_semantic_policy(_passing_semantics(requirements), {"requirements": requirements})

    result = derive_candidate_policy(
        outputs=[_output()],
        semantic_verification=semantic,
    )

    assert result["state"] == "candidate_ready_for_review"
    assert result["blockers"] == []
    assert result["review_obligations"] == ["independent_final_review"]


def test_candidate_fully_verified_requires_independent_pass() -> None:
    requirements = [_requirement("body_dimensions")]
    semantic = evaluate_semantic_policy(_passing_semantics(requirements), {"requirements": requirements})

    result = derive_candidate_policy(
        outputs=[_output()],
        semantic_verification=semantic,
        independent_review={"verdict": "PASS"},
    )

    assert result["state"] == "candidate_fully_verified"
    assert result["blockers"] == []
    assert result["review_obligations"] == []


def test_reviewer_pass_cannot_override_deterministic_candidate_blocker() -> None:
    requirements = [_requirement("body_dimensions")]
    semantic = evaluate_semantic_policy(
        {
            "status": "failed",
            "findings": [
                {
                    "requirement_id": "body_dimensions",
                    "status": "failed",
                    "measurements": {"value": 12.0},
                }
            ],
        },
        {"requirements": requirements},
    )

    result = derive_candidate_policy(
        outputs=[_output()],
        semantic_verification=semantic,
        independent_review={"verdict": "PASS"},
    )

    assert result["state"] == "candidate_blocked"
    assert "body_dimensions" in result["blockers"]
    assert result["review_obligations"] == []


def test_review_pass_cannot_create_fully_verified_candidate_without_package() -> None:
    requirements = [_requirement("body_dimensions")]
    semantic = evaluate_semantic_policy(_passing_semantics(requirements), {"requirements": requirements})

    result = derive_candidate_policy(
        outputs=[_output()],
        semantic_verification=semantic,
        artifacts={"package_required": True, "package_available": False},
        independent_review={"verdict": "PASS"},
    )

    assert result["state"] == "candidate_blocked"
    assert result["blockers"] == ["package_missing"]


def test_explicit_review_requirement_stays_ready_for_review() -> None:
    requirement = _requirement("surface_finish", policy="review_required")
    semantic = evaluate_semantic_policy(
        {"status": "passed", "findings": []},
        {"requirements": [requirement]},
    )

    result = derive_candidate_policy(
        outputs=[_output()],
        semantic_verification=semantic,
        independent_review={"verdict": "UNCERTAIN"},
    )

    assert result["state"] == "candidate_ready_for_review"
    assert "surface_finish" in result["review_obligations"]
    assert "independent_final_review" in result["review_obligations"]


def test_valid_artifact_with_unsupported_semantics_is_concept_available_but_candidate_blocked() -> None:
    requirement = _requirement("unmeasured_interface")
    semantic = evaluate_semantic_policy({"status": "passed", "findings": []}, {"requirements": [requirement]})

    concept = derive_concept_state(outputs=[_output()], semantic_verification=semantic)
    candidate = derive_candidate_policy(outputs=[_output()], semantic_verification=semantic)

    assert concept["state"] == "concept_available"
    assert concept["concept_state"] == "concept_available"
    assert concept["revision_capable"] is True
    assert candidate["state"] == "candidate_blocked"
    assert "unmeasured_interface" in candidate["blockers"]


def test_review_obligation_does_not_make_a_valid_concept_unavailable() -> None:
    requirement = _requirement("surface_finish", policy="review_required")
    semantic = evaluate_semantic_policy({"status": "passed", "findings": []}, {"requirements": [requirement]})

    concept = derive_concept_state(outputs=[_output()], semantic_verification=semantic)
    candidate = derive_candidate_policy(outputs=[_output()], semantic_verification=semantic)

    assert concept["state"] == "concept_available"
    assert candidate["state"] == "candidate_ready_for_review"


def test_fully_verified_candidate_also_has_concept_available_state() -> None:
    requirement = _requirement("body_dimensions")
    semantic = evaluate_semantic_policy(_passing_semantics([requirement]), {"requirements": [requirement]})

    concept = derive_concept_state(outputs=[_output()], semantic_verification=semantic)
    candidate = derive_candidate_policy(
        outputs=[_output()],
        semantic_verification=semantic,
        independent_review={"verdict": "PASS"},
    )

    assert concept["state"] == "concept_available"
    assert candidate["state"] == "candidate_fully_verified"


def test_clarification_before_generation_is_concept_unavailable() -> None:
    result = derive_concept_state(outputs=[], semantic_verification=None, clarification_required=True)

    assert result["state"] == "concept_unavailable"
    assert result["concept_state"] == "concept_unavailable"
    assert result["revision_capable"] is False
    assert "clarification_required" in result["blockers"]


def test_source_failure_invalid_topology_and_missing_artifact_are_concept_unavailable() -> None:
    semantic = {"status": "unsupported_verifier"}

    source_failure = derive_concept_state(
        outputs=[_output(state="not_generated")], semantic_verification=semantic
    )
    invalid_topology = derive_concept_state(
        outputs=[_output(topology="failed")], semantic_verification=semantic
    )
    missing_artifact = derive_concept_state(
        outputs=[_output(artifact=False)], semantic_verification=semantic
    )

    assert source_failure["state"] == "concept_unavailable"
    assert invalid_topology["state"] == "concept_unavailable"
    assert missing_artifact["state"] == "concept_unavailable"


def test_multi_output_identity_blocker_does_not_erase_valid_concept_artifact() -> None:
    semantic = {
        "status": "failed",
        "failed": ["required_output_count"],
        "findings": [],
    }

    concept = derive_concept_state(outputs=[_output()], semantic_verification=semantic)
    candidate = derive_candidate_policy(outputs=[_output()], semantic_verification=semantic)

    assert concept["state"] == "concept_available"
    assert candidate["state"] == "candidate_blocked"
    assert "required_output_count" in candidate["blockers"]


def test_artifact_integrity_failure_is_fail_closed_for_concept_availability() -> None:
    output = _output()
    output["artifact_integrity"] = False

    result = derive_concept_state(outputs=[output], semantic_verification={"status": "passed"})

    assert result["state"] == "concept_unavailable"
    assert "output:primary:artifact_integrity" in result["blockers"]
