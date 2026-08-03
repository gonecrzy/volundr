from types import SimpleNamespace

from app.services.debug_batches.lifecycle import resolve_project_outcome


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
