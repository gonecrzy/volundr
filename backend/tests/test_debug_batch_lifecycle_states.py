from datetime import datetime, timezone

from app.models.generation_attempt import GenerationAttempt
from app.models.project import Project
from app.models.revision import Revision
from app.models.workflow import WorkflowEvent, WorkflowRun
from app.services.debug_batches.lifecycle import classify_project_lifecycle


def _project(*, active_revision_id: str | None = None) -> Project:
    return Project(
        name="Fixture",
        slug="fixture",
        original_intent="Build a fixture",
        active_revision_id=active_revision_id,
    )


def _workflow(*, status: str) -> WorkflowRun:
    return WorkflowRun(
        project_id="project",
        workflow_type="initial_generation",
        correlation_id="correlation",
        status=status,
    )


def _attempt(*, status: str) -> GenerationAttempt:
    return GenerationAttempt(
        project_id="project",
        attempt_number=1,
        provider_id="gemini_api",
        provider_settings_json="{}",
        prompt_version="test",
        ruleset_version="test",
        request_payload_path="request.json",
        prompt_path="prompt.txt",
        status=status,
    )


def _event(*, stage: str, blocking: bool = False) -> WorkflowEvent:
    return WorkflowEvent(
        workflow_run_id="workflow",
        correlation_id="correlation",
        project_id="project",
        sequence_number=1,
        occurred_at=datetime.now(timezone.utc),
        recorded_at=datetime.now(timezone.utc),
        stage=stage,
        event_type="test.event",
        blocking=blocking,
        message="test",
    )


def test_classifies_project_with_no_chain_activity_as_no_activity() -> None:
    assert classify_project_lifecycle(_project(), [], [], [], []) == "no_activity"


def test_classifies_running_workflow_as_in_progress() -> None:
    assert classify_project_lifecycle(_project(), [_workflow(status="running")], [], [], []) == "in_progress"


def test_classifies_terminal_workflow_with_started_attempt_as_interrupted() -> None:
    assert classify_project_lifecycle(_project(), [_workflow(status="failed")], [_attempt(status="started")], [], []) == "interrupted"


def test_classifies_failed_attempt_before_worker_as_blocked_before_worker() -> None:
    assert classify_project_lifecycle(_project(), [_workflow(status="failed")], [_attempt(status="failed")], [_event(stage="source_generation", blocking=True)], []) == "blocked_before_worker"


def test_classifies_worker_failure_as_blocked_after_worker() -> None:
    assert classify_project_lifecycle(_project(), [_workflow(status="failed")], [_attempt(status="failed")], [_event(stage="cad_execution", blocking=True)], []) == "blocked_after_worker"


def test_classifies_active_revision_as_working_version_created() -> None:
    revision = Revision(id="revision", project_id="project", revision_number=1, status="succeeded")
    assert classify_project_lifecycle(_project(active_revision_id="revision"), [], [], [], [revision]) == "working_version_created"
