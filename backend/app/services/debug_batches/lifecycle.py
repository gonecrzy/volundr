from __future__ import annotations

from collections.abc import Sequence
from typing import Any


WORKER_STAGES = frozenset({"cad_execution", "worker", "topology_validation"})
ACTIVE_WORKFLOW_STATUSES = frozenset({"pending", "queued", "running"})
INTERRUPTED_WORKFLOW_STATUSES = frozenset({"cancelled", "interrupted", "aborted"})
UNFINISHED_ATTEMPT_STATUSES = frozenset({"pending", "started", "running", "compiling"})
FAILED_ATTEMPT_STATUSES = frozenset({"failed", "blocked"})


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
        "no_activity": "No activity",
        "in_progress": "In progress",
        "interrupted": "Interrupted",
        "blocked_before_worker": "Blocked before worker",
        "blocked_after_worker": "Blocked after worker",
        "working_version_created": "Working version created",
    }.get(state, "Integrity failure")
