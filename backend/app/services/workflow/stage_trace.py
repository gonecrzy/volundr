from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.workflow import WorkflowArtifact, WorkflowEvent, WorkflowRun


class WorkflowStageTraceService:
    def __init__(self, *, db: Session) -> None:
        self.db = db

    def build_trace(self, workflow_run_id: str) -> dict[str, Any]:
        run = self.db.get(WorkflowRun, workflow_run_id)
        if run is None:
            raise ValueError("workflow run not found")
        events = self._events_for_family(run)
        artifacts = self._artifacts_for_family(run)
        traces: dict[tuple[str, str], dict[str, Any]] = {}
        for event in events:
            if not event.entity_id:
                continue
            key = (event.entity_type or "unknown", event.entity_id)
            trace = traces.setdefault(
                key,
                {
                    "entity_type": key[0],
                    "entity_id": key[1],
                    "stages": [],
                    "status": "consistent",
                    "first_drift": None,
                },
            )
            expected = self._json_value(event.expected_json)
            detected = self._json_value(event.detected_json)
            metadata = json.loads(event.metadata_json or "{}")
            value = detected if detected is not None else expected
            stage_entry = {
                "stage": event.stage,
                "value": value,
                "source": metadata.get("value_source") or metadata.get("source") or "recorded_event",
                "event_id": event.id,
                "rule_id": event.rule_id,
            }
            trace["stages"].append(stage_entry)
            if expected is not None and detected is not None and expected != detected and trace["first_drift"] is None:
                trace["status"] = "drift_detected"
                trace["first_drift"] = {
                    "stage": event.stage,
                    "event_id": event.id,
                    "expected": expected,
                    "detected": detected,
                    "rule_id": event.rule_id,
                }
        for artifact in artifacts:
            if artifact.sha256 is None:
                continue
            entity_type = "source_hash" if artifact.artifact_type == "cadquery_source" else "artifact_hash"
            entity_id = artifact.role
            key = (entity_type, entity_id)
            trace = traces.setdefault(
                key,
                {
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "stages": [],
                    "status": "observed",
                    "first_drift": None,
                },
            )
            trace["stages"].append(
                {
                    "stage": artifact.stage,
                    "value": artifact.sha256,
                    "source": "artifact_sha256",
                    "artifact_id": artifact.id,
                    "path": artifact.path,
                }
            )
        return {
            "schema_version": "stage-trace-v1",
            "workflow_run_id": run.id,
            "root_workflow_run_id": run.root_workflow_run_id or run.id,
            "traces": list(traces.values()),
        }

    def build_markdown(self, workflow_run_id: str) -> str:
        trace = self.build_trace(workflow_run_id)
        lines = [
            "| Item | Type | Status | Stages | First drift |",
            "| --- | --- | --- | --- | --- |",
        ]
        for item in trace["traces"]:
            stages = " -> ".join(str(stage["stage"]) for stage in item["stages"])
            first_drift = item["first_drift"]["stage"] if item.get("first_drift") else ""
            lines.append(
                f"| {item['entity_id']} | {item['entity_type']} | {item['status']} | {stages} | {first_drift} |"
            )
        return "\n".join(lines) + "\n"

    def _events_for_family(self, run: WorkflowRun) -> list[WorkflowEvent]:
        root_id = run.root_workflow_run_id or run.id
        return list(
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

    def _artifacts_for_family(self, run: WorkflowRun) -> list[WorkflowArtifact]:
        root_id = run.root_workflow_run_id or run.id
        return list(
            self.db.scalars(
                select(WorkflowArtifact)
                .where(WorkflowArtifact.root_workflow_run_id == root_id)
                .order_by(WorkflowArtifact.created_at.asc())
            )
        )

    def _json_value(self, value: str | None) -> Any:
        if value is None:
            return None
        return json.loads(value)
