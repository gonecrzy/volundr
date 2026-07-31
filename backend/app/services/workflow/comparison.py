from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.workflow import WorkflowEvent, WorkflowRun


class WorkflowRunComparisonService:
    def __init__(self, *, db: Session) -> None:
        self.db = db

    def compare(self, baseline_workflow_run_id: str, candidate_workflow_run_id: str) -> dict[str, Any]:
        baseline = self.db.get(WorkflowRun, baseline_workflow_run_id)
        candidate = self.db.get(WorkflowRun, candidate_workflow_run_id)
        if baseline is None or candidate is None:
            raise ValueError("workflow run not found")
        baseline_events = self._events_for_run(baseline)
        candidate_events = self._events_for_run(candidate)
        changes: list[dict[str, Any]] = []
        regressions: list[dict[str, Any]] = []
        improvements: list[dict[str, Any]] = []

        self._compare_count(
            changes,
            metric="provider_call_count",
            baseline=self._count_events(baseline_events, "provider.request_prepared"),
            candidate=self._count_events(candidate_events, "provider.request_prepared"),
        )
        baseline_repairs = self._repair_count(baseline_events)
        candidate_repairs = self._repair_count(candidate_events)
        self._compare_count(changes, metric="repair_count", baseline=baseline_repairs, candidate=candidate_repairs)
        if candidate_repairs < baseline_repairs:
            improvements.append(
                {
                    "metric": "repair_count",
                    "baseline": baseline_repairs,
                    "candidate": candidate_repairs,
                    "basis": "fewer repair-stage events with the same deterministic workflow instrumentation",
                    "confidence": "probable",
                }
            )

        baseline_parameters = self._parameter_values(baseline_events)
        candidate_parameters = self._parameter_values(candidate_events)
        for parameter_id, baseline_value in baseline_parameters.items():
            if parameter_id not in candidate_parameters:
                regressions.append(
                    {
                        "metric": "parameter_value",
                        "entity_id": parameter_id,
                        "baseline": baseline_value,
                        "candidate": None,
                        "basis": "parameter disappeared from candidate trace",
                        "confidence": "confirmed",
                    }
                )
                continue
            candidate_value = candidate_parameters[parameter_id]
            if candidate_value != baseline_value:
                change = {
                    "metric": "parameter_value",
                    "entity_id": parameter_id,
                    "baseline": baseline_value,
                    "candidate": candidate_value,
                    "basis": "explicit/protected parameter value changed between traces",
                    "confidence": "confirmed",
                }
                if candidate.workflow_type == "configuration_change":
                    change["classification"] = "intended_parameter_change"
                    changes.append(change)
                else:
                    regressions.append(change)
        baseline_state = self._candidate_state(baseline_events)
        candidate_state = self._candidate_state(candidate_events)
        if baseline_state != candidate_state:
            changes.append(
                {
                    "metric": "candidate_state",
                    "baseline": baseline_state,
                    "candidate": candidate_state,
                    "classification": "changed",
                }
            )
        return {
            "baseline_workflow_run_id": baseline.id,
            "candidate_workflow_run_id": candidate.id,
            "changes": changes,
            "regressions": regressions,
            "improvements": improvements,
        }

    def _events_for_run(self, run: WorkflowRun) -> list[WorkflowEvent]:
        return list(
            self.db.scalars(
                select(WorkflowEvent)
                .where(WorkflowEvent.workflow_run_id == run.id)
                .order_by(
                    WorkflowEvent.sequence_number.asc(),
                    WorkflowEvent.recorded_at.asc(),
                )
            )
        )

    def _count_events(self, events: list[WorkflowEvent], event_type: str) -> int:
        return sum(1 for event in events if event.event_type == event_type)

    def _repair_count(self, events: list[WorkflowEvent]) -> int:
        return sum(
            1
            for event in events
            if event.stage in {"contract_repair", "execution_repair", "scope_correction"}
            and event.event_type.endswith((".failed", ".succeeded", ".resolved"))
        )

    def _compare_count(
        self,
        changes: list[dict[str, Any]],
        *,
        metric: str,
        baseline: int,
        candidate: int,
    ) -> None:
        if baseline == candidate:
            return
        changes.append(
            {
                "metric": metric,
                "baseline": baseline,
                "candidate": candidate,
                "classification": "changed",
            }
        )

    def _parameter_values(self, events: list[WorkflowEvent]) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for event in events:
            if event.entity_type != "parameter" or not event.entity_id:
                continue
            metadata = json.loads(event.metadata_json or "{}")
            value_source = metadata.get("value_source")
            if value_source not in {
                "explicit_user_value",
                "protected_parameter",
                "product_default",
                "parameter_default",
                "submitted_parameter",
            }:
                continue
            detected = json.loads(event.detected_json) if event.detected_json is not None else None
            expected = json.loads(event.expected_json) if event.expected_json is not None else None
            values[event.entity_id] = detected if detected is not None else expected
        return values

    def _candidate_state(self, events: list[WorkflowEvent]) -> str | None:
        state = None
        for event in events:
            if event.event_type != "candidate.classified":
                continue
            metadata = json.loads(event.metadata_json or "{}")
            state = metadata.get("review_state") or metadata.get("status") or state
        return state
