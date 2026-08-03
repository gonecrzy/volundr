from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import json
from typing import Any


WORKER_STAGES = frozenset({"cad_execution", "worker", "topology_validation"})
ACTIVE_WORKFLOW_STATUSES = frozenset({"pending", "queued", "running"})
INTERRUPTED_WORKFLOW_STATUSES = frozenset({"cancelled", "interrupted", "aborted"})
UNFINISHED_ATTEMPT_STATUSES = frozenset({"pending", "started", "running", "compiling"})
FAILED_ATTEMPT_STATUSES = frozenset({"failed", "blocked"})


@dataclass(frozen=True)
class ProjectOutcome:
    lifecycle_state: str
    category: str
    final_outcome: str
    worker_reached: bool
    valid_geometry_produced: bool


OUTCOME_LABELS = {
    "in_progress": "In progress",
    "interrupted": "Interrupted",
    "accepted": "Accepted",
    "accepted_with_warnings": "Accepted with warnings",
    "candidate_created": "Candidate created",
    "post_worker_topology_block": "Blocked after worker",
    "post_worker_verification_block": "Blocked after worker",
    "worker_runtime_failure": "Blocked after worker",
    "worker_completed_without_valid_geometry": "Blocked after worker",
    "provider_content_failure": "Blocked before worker",
    "provider_transport_failure": "Blocked before worker",
    "blocked_before_provider": "Blocked before provider",
    "not_started": "Not started",
}


def _output_is_valid(output: Any) -> bool:
    if getattr(output, "execution_state", None) != "succeeded" or not getattr(output, "stl_path", None):
        return False
    topology_payload = getattr(output, "topology_metadata_json", None)
    if not topology_payload:
        return True
    try:
        topology = json.loads(topology_payload)
    except (TypeError, json.JSONDecodeError):
        return False
    return topology.get("valid", True) is not False


def resolve_project_outcome(
    project: Any,
    workflows: Sequence[Any],
    attempts: Sequence[Any],
    events: Sequence[Any],
    revisions: Sequence[Any],
    revision_outputs: Sequence[Any],
) -> ProjectOutcome:
    """Resolve one final project outcome for every debug-batch consumer.

    The supplied event sequence must be in authoritative persisted order. A
    downstream candidate event cannot override an earlier worker or topology
    blocker, and artifacts alone cannot create a candidate outcome.
    """

    lifecycle_state = classify_project_lifecycle(project, workflows, attempts, events, revisions)
    worker_reached = any(getattr(event, "stage", None) in WORKER_STAGES for event in events)
    valid_revision_ids = {
        getattr(revision, "id", None)
        for revision in revisions
        if getattr(revision, "status", None) == "succeeded"
        and any(
            getattr(output, "revision_id", None) == getattr(revision, "id", None)
            for output in revision_outputs
        )
        and all(
            _output_is_valid(output)
            for output in revision_outputs
            if getattr(output, "revision_id", None) == getattr(revision, "id", None)
        )
    }
    valid_geometry_produced = bool(valid_revision_ids)

    if lifecycle_state == "working_version_created":
        active_revision = next(
            (
                revision
                for revision in revisions
                if getattr(revision, "id", None) == getattr(project, "active_revision_id", None)
            ),
            None,
        )
        category = "accepted" if getattr(active_revision, "is_accepted", False) else "candidate_created"
    elif lifecycle_state == "in_progress":
        category = "in_progress"
    elif lifecycle_state == "interrupted":
        category = "interrupted"
    elif worker_reached:
        category = None
        for event in events:
            if not getattr(event, "blocking", False):
                continue
            stage = getattr(event, "stage", None)
            event_type = str(getattr(event, "event_type", ""))
            rule_id = str(getattr(event, "rule_id", "") or "")
            if stage in {"cad_execution", "worker"}:
                category = "worker_runtime_failure"
                break
            if stage == "topology_validation" and not (
                event_type.startswith("functional.") or rule_id.startswith("functional.")
            ):
                category = "post_worker_topology_block"
                break
            if (
                stage in {"candidate_classification", "verification", "artifact_consistency"}
                or event_type.startswith("functional.")
                or rule_id.startswith("functional.")
            ):
                category = "post_worker_verification_block"
                break
        if category is None:
            category = "candidate_created" if valid_geometry_produced else "worker_completed_without_valid_geometry"
    else:
        if any(getattr(attempt, "status", None) in FAILED_ATTEMPT_STATUSES for attempt in attempts):
            category = "provider_content_failure" if any(
                getattr(attempt, "raw_output_path", None) for attempt in attempts
            ) else "provider_transport_failure"
        elif any(
            getattr(event, "blocking", False)
            and getattr(event, "stage", None) in {"requirements", "clarification"}
            for event in events
        ):
            category = "blocked_before_provider"
        else:
            category = "not_started"

    return ProjectOutcome(
        lifecycle_state=lifecycle_state,
        category=category,
        final_outcome=OUTCOME_LABELS.get(category, "Integrity failure"),
        worker_reached=worker_reached,
        valid_geometry_produced=valid_geometry_produced,
    )


def resolve_project_outcome_from_db(db: Any, project_id: str) -> ProjectOutcome | None:
    """Load the persisted project chain and resolve it through one code path."""

    from sqlalchemy import select

    from app.models.generation_attempt import GenerationAttempt
    from app.models.project import Project
    from app.models.revision import Revision
    from app.models.revision_output import RevisionOutput
    from app.models.workflow import WorkflowEvent, WorkflowRun

    project = db.get(Project, project_id)
    if project is None:
        return None
    workflows = list(
        db.scalars(
            select(WorkflowRun)
            .where(WorkflowRun.project_id == project.id)
            .order_by(WorkflowRun.started_at.asc(), WorkflowRun.id.asc())
        )
    )
    events = list(
        db.scalars(
            select(WorkflowEvent)
            .where(WorkflowEvent.project_id == project.id)
            .order_by(WorkflowEvent.recorded_at.asc(), WorkflowEvent.id.asc())
        )
    )
    attempts = list(
        db.scalars(
            select(GenerationAttempt)
            .where(GenerationAttempt.project_id == project.id)
            .order_by(GenerationAttempt.attempt_number.asc(), GenerationAttempt.id.asc())
        )
    )
    revisions = list(
        db.scalars(
            select(Revision)
            .where(Revision.project_id == project.id)
            .order_by(Revision.revision_number.asc(), Revision.id.asc())
        )
    )
    revision_outputs = list(
        db.scalars(
            select(RevisionOutput)
            .join(Revision, RevisionOutput.revision_id == Revision.id)
            .where(Revision.project_id == project.id)
            .order_by(RevisionOutput.created_at.asc(), RevisionOutput.id.asc())
        )
    )
    return resolve_project_outcome(project, workflows, attempts, events, revisions, revision_outputs)


def classify_project_lifecycle(
    project: Any,
    workflows: Sequence[Any],
    attempts: Sequence[Any],
    events: Sequence[Any],
    revisions: Sequence[Any],
) -> str:
    """Classify the complete persisted project chain without inferring activity.

    The state is intentionally narrower than the report's human-facing labels.
    In particular, a terminal workflow with a non-terminal generation attempt
    is interrupted: it has evidence of work, but no accepted terminal result.
    """

    if getattr(project, "active_revision_id", None):
        return "working_version_created"

    if any(getattr(workflow, "status", None) in ACTIVE_WORKFLOW_STATUSES for workflow in workflows):
        return "in_progress"

    worker_reached = any(getattr(event, "stage", None) in WORKER_STAGES for event in events)
    unfinished_attempt = any(
        getattr(attempt, "status", None) in UNFINISHED_ATTEMPT_STATUSES for attempt in attempts
    )
    interrupted_workflow = any(
        getattr(workflow, "status", None) in INTERRUPTED_WORKFLOW_STATUSES for workflow in workflows
    )
    activity_exists = bool(workflows or attempts or events or revisions)
    if unfinished_attempt or interrupted_workflow:
        return "interrupted"

    if worker_reached:
        return "blocked_after_worker"

    has_blocking_event = any(bool(getattr(event, "blocking", False)) for event in events)
    has_failed_attempt = any(
        getattr(attempt, "status", None) in FAILED_ATTEMPT_STATUSES for attempt in attempts
    )
    if has_blocking_event or has_failed_attempt:
        return "blocked_before_worker"

    if activity_exists:
        return "interrupted"
    return "no_activity"


def lifecycle_label(state: str) -> str:
    return {
        # Keep the existing API/report wording while exposing the canonical
        # lifecycle_state separately.
        "no_activity": "Not started",
        "in_progress": "In progress",
        "interrupted": "Interrupted",
        "blocked_before_worker": "Blocked before worker",
        "blocked_after_worker": "Blocked after worker",
        "working_version_created": "Working version created",
    }.get(state, "Integrity failure")
