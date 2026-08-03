from types import SimpleNamespace

from app.services.debug_batches.lifecycle import resolve_project_outcome
from app.services.projects.output_outcomes import resolve_output_outcome


def _project(*, active_revision_id: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(id="project", active_revision_id=active_revision_id)


def _workflow() -> SimpleNamespace:
    return SimpleNamespace(status="failed")


def _attempt() -> SimpleNamespace:
    return SimpleNamespace(status="failed")


def _event(
    *,
    stage: str,
    event_type: str,
    blocking: bool = False,
    sequence_number: int = 1,
    rule_id: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        stage=stage,
        event_type=event_type,
        blocking=blocking,
        sequence_number=sequence_number,
        rule_id=rule_id,
    )


def _revision(*, status: str = "failed", review_state: str = "blocked") -> SimpleNamespace:
    return SimpleNamespace(id="revision", status=status, review_state=review_state)


def _output(
    *,
    execution_state: str,
    stl_path: str | None = None,
    topology_valid: bool | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        revision_id="revision",
        execution_state=execution_state,
        stl_path=stl_path,
        topology_metadata_json=(
            '{"valid": true}' if topology_valid is True else '{"valid": false}' if topology_valid is False else None
        ),
    )


def test_worker_failure_is_authoritative_before_downstream_topology() -> None:
    outcome = resolve_project_outcome(
        _project(),
        [_workflow()],
        [_attempt()],
        [
            _event(stage="cad_execution", event_type="worker.failed", blocking=True, sequence_number=1),
            _event(stage="topology_validation", event_type="topology.failed", blocking=True, sequence_number=2),
        ],
        [_revision()],
        [_output(execution_state="failed", topology_valid=False)],
    )

    assert outcome.category == "worker_runtime_failure"
    assert outcome.final_outcome == "Blocked after worker"


def test_artifacts_do_not_make_a_blocked_required_output_a_candidate() -> None:
    outcome = resolve_project_outcome(
        _project(),
        [_workflow()],
        [_attempt()],
        [
            _event(stage="worker", event_type="worker.completed", sequence_number=1),
            _event(
                stage="candidate_classification",
                event_type="candidate.classified",
                blocking=True,
                sequence_number=2,
            ),
        ],
        [_revision(status="succeeded")],
        [_output(execution_state="blocked", stl_path="model.stl", topology_valid=True)],
    )

    assert outcome.category == "post_worker_verification_block"
    assert outcome.final_outcome == "Blocked after worker"


def test_feature_verification_block_wins_over_valid_geometry() -> None:
    outcome = resolve_project_outcome(
        _project(),
        [_workflow()],
        [_attempt()],
        [
            _event(stage="worker", event_type="worker.completed", sequence_number=1),
            _event(
                stage="topology_validation",
                event_type="functional.verification.completed",
                blocking=True,
                sequence_number=2,
                rule_id="functional.feature_missing",
            ),
        ],
        [_revision(status="succeeded")],
        [_output(execution_state="succeeded", stl_path="model.stl", topology_valid=True)],
    )

    assert outcome.category == "post_worker_verification_block"
    assert outcome.final_outcome == "Blocked after worker"


def test_pre_worker_blocking_artifact_finding_is_source_blocked() -> None:
    outcome = resolve_project_outcome(
        _project(),
        [_workflow()],
        [_attempt()],
        [],
        [],
        [],
        [
            SimpleNamespace(
                revision_id=None,
                category="design_artifact_consistency",
                rule_id="design_artifact.requirement_trace_ambiguous",
                is_blocking=True,
            )
        ],
    )

    assert outcome.outcome_state == "source_blocked"
    assert outcome.category == "provider_transport_failure"
    assert outcome.final_outcome == "Blocked before worker"


def test_requirement_verification_block_is_not_classified_as_candidate_block() -> None:
    output = SimpleNamespace(
        revision_id="revision",
        output_id="part",
        required=True,
        execution_state="succeeded",
        stl_path="model.stl",
        step_path="model.step",
        brep_path="model.brep",
        stl_hash="stl-hash",
        step_hash="step-hash",
        brep_hash="brep-hash",
        expected_solid_count=1,
        detected_solid_count=1,
        topology_metadata_json='{"valid": true, "detected_solid_count": 1}',
    )
    outcome = resolve_project_outcome(
        _project(),
        [_workflow()],
        [_attempt()],
        [
            _event(stage="worker", event_type="worker.completed", sequence_number=1),
            _event(
                stage="candidate_classification",
                event_type="candidate.classified",
                blocking=True,
                sequence_number=2,
                rule_id="candidate.blocked",
            ),
        ],
        [_revision(status="succeeded")],
        [output],
        [
            SimpleNamespace(
                revision_id="revision",
                category="requirement",
                rule_id="requirement.req_one_piece",
                is_blocking=True,
            )
        ],
    )

    assert outcome.outcome_state == "verification_blocked"
    assert outcome.category == "post_worker_verification_block"


def _valid_output(output_id: str = "part") -> dict:
    return {
        "output_id": output_id,
        "required": True,
        "expected_solid_count": 1,
        "allow_disconnected_solids": False,
        "required_artifact_formats": ["stl", "step", "brep"],
    }


def _registered_output(output_id: str = "part", *, state: str = "ready", valid: bool = True) -> dict:
    return {
        **_valid_output(output_id),
        "execution_state": state,
        "stl_path": f"revisions/r/{output_id}.stl",
        "stl_hash": "stl-hash",
        "step_path": f"revisions/r/{output_id}.step",
        "step_hash": "step-hash",
        "brep_path": f"revisions/r/{output_id}.brep",
        "brep_hash": "brep-hash",
        "topology_metadata": {
            "valid": valid,
            "expected_solid_count": 1,
            "detected_solid_count": 1 if valid else 2,
        },
    }


def test_canonical_output_resolver_reconciles_stale_manifest_state() -> None:
    outcome = resolve_output_outcome(
        expected_outputs=[_valid_output()],
        worker_status="succeeded",
        registered_artifacts=[_registered_output(state="blocked")],
        artifact_readiness_findings=[
            {
                "rule_id": "design_artifact.manifest_required_output_not_ready",
                "is_blocking": True,
            }
        ],
    )

    assert outcome.state == "valid_geometry_unverified"
    assert outcome.is_candidate_eligible is True
    assert outcome.integrity_findings[0]["rule_id"] == "integrity.stale_output_manifest_state"


def test_canonical_output_resolver_distinguishes_artifact_and_topology_blocks() -> None:
    incomplete = resolve_output_outcome(
        expected_outputs=[_valid_output()],
        worker_status="succeeded",
        registered_artifacts=[{**_registered_output(), "step_path": None, "step_hash": None}],
    )
    invalid = resolve_output_outcome(
        expected_outputs=[_valid_output()],
        worker_status="succeeded",
        registered_artifacts=[_registered_output(valid=False)],
    )

    assert incomplete.state == "incomplete_artifacts"
    assert invalid.state == "invalid_topology"


def test_canonical_output_resolver_consumes_final_feature_evidence_blocker() -> None:
    outcome = resolve_output_outcome(
        expected_outputs=[_valid_output()],
        worker_status="succeeded",
        registered_artifacts=[_registered_output()],
        verification_findings=[
            {"rule_id": "feature.verification_blocked", "is_blocking": True}
        ],
    )

    assert outcome.state == "verification_blocked"
    assert outcome.verification_status == "blocked"
