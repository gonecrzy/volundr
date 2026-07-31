from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.workflow import WorkflowDiagnosis, WorkflowEvent, WorkflowRun


class WorkflowDiagnosisService:
    def __init__(self, *, db: Session) -> None:
        self.db = db

    def diagnose(self, workflow_run_id: str) -> WorkflowDiagnosis:
        run = self.db.get(WorkflowRun, workflow_run_id)
        if run is None:
            raise ValueError("workflow run not found")
        root_id = run.root_workflow_run_id or run.id
        events = list(
            self.db.scalars(
                select(WorkflowEvent)
                .join(WorkflowRun, WorkflowEvent.workflow_run_id == WorkflowRun.id)
                .where(WorkflowEvent.root_workflow_run_id == root_id)
                .order_by(
                    WorkflowRun.started_at.asc(),
                    WorkflowEvent.workflow_run_id.asc(),
                    WorkflowEvent.sequence_number.asc(),
                    WorkflowEvent.recorded_at.asc(),
                )
            )
        )
        root_event, confidence, basis = self._root_event(events)
        downstream_effects = self._downstream_effects(events, root_event)
        repairs = self._repairs(events)
        diagnosis = WorkflowDiagnosis(
            workflow_run_id=workflow_run_id,
            schema_version=run.diagnosis_version,
            root_cause_json=json.dumps(
                self._root_cause_payload(root_event, confidence, basis),
                sort_keys=True,
                default=str,
            ),
            repairs_json=json.dumps(repairs, sort_keys=True, default=str),
            downstream_effects_json=json.dumps(downstream_effects, sort_keys=True, default=str),
            final_outcome=run.status,
            basis_json=json.dumps(basis, sort_keys=True, default=str),
        )
        self.db.add(diagnosis)
        self.db.commit()
        self.db.refresh(diagnosis)
        return diagnosis

    def _root_event(
        self,
        events: list[WorkflowEvent],
    ) -> tuple[WorkflowEvent | None, str, dict[str, Any]]:
        resolved_event_ids = {
            event.caused_by_event_id
            for event in events
            if event.caused_by_event_id
            and (
                event.event_type.endswith(".succeeded")
                or event.event_type.endswith(".resolved")
            )
        }
        blocking = [
            event
            for event in events
            if event.blocking and event.id not in resolved_event_ids
        ]
        if not blocking:
            return None, "unknown", {"reason": "no_blocking_events"}
        explicit_root = next((event for event in blocking if event.is_root_failure), None)
        if explicit_root is not None:
            return explicit_root, "confirmed", {"reason": "event_marked_root_failure"}
        caused_ids = {event.caused_by_event_id for event in blocking if event.caused_by_event_id}
        linked_cause = next((event for event in blocking if event.id in caused_ids), None)
        if linked_cause is not None:
            return linked_cause, "confirmed", {"reason": "explicit_caused_by_event_link"}
        uncaused_blocking = [event for event in blocking if event.id not in caused_ids and not event.is_downstream_symptom]
        if uncaused_blocking:
            event = uncaused_blocking[0]
            confidence = "confirmed" if any(item.caused_by_event_id == event.id for item in blocking) else "probable"
            return event, confidence, {
                "reason": "blocking_event_has_downstream_links"
                if confidence == "confirmed"
                else "earliest_unlinked_blocking_event",
            }
        return blocking[0], "possible", {"reason": "sequence_order_fallback"}

    def _root_cause_payload(
        self,
        event: WorkflowEvent | None,
        confidence: str,
        basis: dict[str, Any],
    ) -> dict[str, Any]:
        if event is None:
            return {
                "stage": None,
                "rule_id": None,
                "event_id": None,
                "artifact_id": None,
                "summary": "No blocking event was recorded.",
                "confidence": confidence,
                "basis": basis,
            }
        event.is_root_failure = True
        self.db.flush()
        return {
            "stage": event.stage,
            "rule_id": event.rule_id,
            "event_id": event.id,
            "artifact_id": event.source_artifact_id,
            "summary": event.message,
            "confidence": confidence,
            "basis": basis,
        }

    def _downstream_effects(
        self,
        events: list[WorkflowEvent],
        root_event: WorkflowEvent | None,
    ) -> list[dict[str, Any]]:
        if root_event is None:
            return []
        effects: list[dict[str, Any]] = []
        for event in events:
            if event.id == root_event.id:
                continue
            if event.caused_by_event_id == root_event.id or (
                event.sequence_number > root_event.sequence_number
                and event.blocking
                and event.stage in {"candidate_classification", "artifact_consistency", "topology_validation"}
            ):
                event.is_downstream_symptom = True
                effects.append(
                    {
                        "stage": event.stage,
                        "rule_id": event.rule_id,
                        "event_id": event.id,
                        "confidence": "confirmed"
                        if event.caused_by_event_id == root_event.id
                        else "possible",
                    }
                )
        self.db.flush()
        return effects

    def _repairs(self, events: list[WorkflowEvent]) -> list[dict[str, Any]]:
        repairs: list[dict[str, Any]] = []
        for event in events:
            if event.stage not in {"contract_repair", "execution_repair", "scope_correction"}:
                continue
            outcome = "unknown"
            if event.event_type.endswith(".succeeded") or event.event_type.endswith(".resolved"):
                outcome = "resolved"
            elif event.event_type.endswith(".failed"):
                outcome = "failed"
            repairs.append({"stage": event.stage, "outcome": outcome, "event_id": event.id})
        return repairs
