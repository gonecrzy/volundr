from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.workflow import WorkflowArtifact, WorkflowEvent, WorkflowRun
from app.services.workflow.redaction import RedactionService
from app.services.workflow.stages import (
    TERMINAL_WORKFLOW_STATUSES,
    WORKFLOW_DIAGNOSIS_VERSION,
    WORKFLOW_EVENT_SCHEMA_VERSION,
    WORKFLOW_REDACTION_VERSION,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowRecorder:
    def __init__(self, *, db: Session, data_dir: Path) -> None:
        self.db = db
        self.data_dir = data_dir
        self.redactor = RedactionService()

    def start_run(
        self,
        *,
        project_id: str,
        workflow_type: str,
        parent_workflow_run_id: str | None = None,
        root_workflow_run_id: str | None = None,
        correlation_id: str | None = None,
        logging_mode: str = "standard",
        provider: str | None = None,
        model: str | None = None,
        prompt_versions: dict[str, str] | None = None,
        application_commit: str | None = None,
        worker_version: str | None = None,
        metadata: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> WorkflowRun:
        parent = self.db.get(WorkflowRun, parent_workflow_run_id) if parent_workflow_run_id else None
        inherited_root_id = root_workflow_run_id or (parent.root_workflow_run_id if parent else None)
        inherited_correlation_id = correlation_id or (parent.correlation_id if parent else str(uuid4()))
        run = WorkflowRun(
            project_id=project_id,
            workflow_type=workflow_type,
            parent_workflow_run_id=parent_workflow_run_id,
            root_workflow_run_id=inherited_root_id,
            correlation_id=inherited_correlation_id,
            status="running",
            logging_mode=logging_mode,
            event_schema_version=WORKFLOW_EVENT_SCHEMA_VERSION,
            diagnosis_version=WORKFLOW_DIAGNOSIS_VERSION,
            redaction_version=WORKFLOW_REDACTION_VERSION,
            application_commit=application_commit,
            worker_version=worker_version,
            provider=provider,
            model=model,
            prompt_versions_json=json.dumps(prompt_versions or {}, sort_keys=True),
            workflow_metadata_json=json.dumps(metadata or {}, sort_keys=True, default=str),
        )
        self.db.add(run)
        self.db.flush()
        if run.root_workflow_run_id is None:
            run.root_workflow_run_id = run.id
        if commit:
            self.db.commit()
            self.db.refresh(run)
        else:
            self.db.flush()
        return run

    def complete_run(self, run: WorkflowRun | str, *, status: str, commit: bool = True) -> WorkflowRun:
        stored = self._run(run)
        if status not in TERMINAL_WORKFLOW_STATUSES:
            raise ValueError("workflow run status is not terminal")
        stored.status = status
        stored.completed_at = utcnow()
        stored.updated_at = stored.completed_at
        if commit:
            self.db.commit()
            self.db.refresh(stored)
        else:
            self.db.flush()
        return stored

    def record_event(
        self,
        run: WorkflowRun | str,
        *,
        stage: str,
        event_type: str,
        severity: str,
        message: str,
        blocking: bool = False,
        rule_id: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        expected: Any = None,
        detected: Any = None,
        source_artifact_id: str | None = None,
        caused_by_event_id: str | None = None,
        is_root_failure: bool = False,
        is_downstream_symptom: bool = False,
        deduplication_key: str | None = None,
        occurred_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
        generation_attempt_id: str | None = None,
        design_specification_id: str | None = None,
        design_plan_id: str | None = None,
        revision_id: str | None = None,
        revision_output_id: str | None = None,
        revision_plan_id: str | None = None,
        configuration_change_id: str | None = None,
        worker_job_id: str | None = None,
        provider_request_id: str | None = None,
        commit: bool = True,
    ) -> WorkflowEvent:
        stored_run = self._run(run)
        for _attempt in range(3):
            if deduplication_key:
                existing = self.db.scalar(
                    select(WorkflowEvent)
                    .where(WorkflowEvent.workflow_run_id == stored_run.id)
                    .where(WorkflowEvent.deduplication_key == deduplication_key)
                )
                if existing is not None:
                    return existing
            sequence_number = int(
                self.db.scalar(
                    select(func.max(WorkflowEvent.sequence_number)).where(
                        WorkflowEvent.workflow_run_id == stored_run.id
                    )
                )
                or 0
            ) + 1
            redacted_metadata = self.redactor.redact_mapping(metadata or {}, artifact_type="event_metadata")
            event = WorkflowEvent(
                workflow_run_id=stored_run.id,
                root_workflow_run_id=stored_run.root_workflow_run_id,
                correlation_id=stored_run.correlation_id,
                project_id=stored_run.project_id,
                generation_attempt_id=generation_attempt_id,
                design_specification_id=design_specification_id,
                design_plan_id=design_plan_id,
                revision_id=revision_id,
                revision_output_id=revision_output_id,
                revision_plan_id=revision_plan_id,
                configuration_change_id=configuration_change_id,
                worker_job_id=worker_job_id,
                provider_request_id=provider_request_id,
                sequence_number=sequence_number,
                occurred_at=occurred_at or utcnow(),
                recorded_at=utcnow(),
                stage=stage,
                event_type=event_type,
                severity=severity,
                blocking=blocking,
                message=message,
                rule_id=rule_id,
                entity_type=entity_type,
                entity_id=entity_id,
                expected_json=json.dumps(expected, sort_keys=True, default=str)
                if expected is not None
                else None,
                detected_json=json.dumps(detected, sort_keys=True, default=str)
                if detected is not None
                else None,
                source_artifact_id=source_artifact_id,
                caused_by_event_id=caused_by_event_id,
                is_root_failure=is_root_failure,
                is_downstream_symptom=is_downstream_symptom,
                deduplication_key=deduplication_key,
                metadata_json=json.dumps(redacted_metadata, sort_keys=True, default=str),
            )
            self.db.add(event)
            try:
                if commit:
                    self.db.commit()
                    self.db.refresh(event)
                else:
                    self.db.flush()
                return event
            except IntegrityError:
                self.db.rollback()
                if deduplication_key:
                    existing = self.db.scalar(
                        select(WorkflowEvent)
                        .where(WorkflowEvent.workflow_run_id == stored_run.id)
                        .where(WorkflowEvent.deduplication_key == deduplication_key)
                    )
                    if existing is not None:
                        return existing
        raise RuntimeError("workflow event could not be recorded after sequence retry")

    def record_artifact(
        self,
        run: WorkflowRun | str,
        *,
        stage: str,
        artifact_type: str,
        role: str,
        path: Path,
        media_type: str | None = None,
        redacted: bool,
        supersedes_artifact_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WorkflowArtifact:
        stored_run = self._run(run)
        sha256 = None
        size_bytes = None
        if path.exists() and path.is_file():
            size_bytes = path.stat().st_size
            sha256 = self._file_sha256(path)
        artifact = WorkflowArtifact(
            workflow_run_id=stored_run.id,
            root_workflow_run_id=stored_run.root_workflow_run_id,
            correlation_id=stored_run.correlation_id,
            project_id=stored_run.project_id,
            stage=stage,
            artifact_type=artifact_type,
            role=role,
            path=self._relative(path),
            sha256=sha256,
            size_bytes=size_bytes,
            media_type=media_type or self._guess_media_type(path),
            redacted=redacted,
            redaction_status="confirmed" if redacted else "not_required",
            supersedes_artifact_id=supersedes_artifact_id,
            artifact_metadata_json=json.dumps(metadata or {}, sort_keys=True, default=str),
        )
        self.db.add(artifact)
        self.db.commit()
        self.db.refresh(artifact)
        return artifact

    def classify_stale_runs(self, *, max_running_seconds: int) -> int:
        cutoff = utcnow() - timedelta(seconds=max_running_seconds)
        runs = list(
            self.db.scalars(
                select(WorkflowRun)
                .where(WorkflowRun.status == "running")
                .where(WorkflowRun.updated_at <= cutoff)
            )
        )
        for run in runs:
            run.status = "abandoned"
            run.completed_at = utcnow()
            run.updated_at = run.completed_at
            self.record_event(
                run,
                stage="frontend_workflow",
                event_type="workflow.abandoned",
                severity="warning",
                blocking=True,
                message="Workflow was left running and classified abandoned.",
                deduplication_key=f"workflow-abandoned-{run.id}",
            )
        self.db.commit()
        return len(runs)

    def _run(self, run: WorkflowRun | str) -> WorkflowRun:
        if isinstance(run, WorkflowRun):
            return run
        stored = self.db.get(WorkflowRun, run)
        if stored is None:
            raise ValueError("workflow run not found")
        return stored

    def _relative(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.data_dir))
        except ValueError:
            return str(path)

    def _file_sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _guess_media_type(self, path: Path) -> str | None:
        suffix = path.suffix.lower()
        if suffix == ".json":
            return "application/json"
        if suffix in {".txt", ".log", ".md"}:
            return "text/plain"
        if suffix == ".py":
            return "text/x-python"
        if suffix == ".ndjson":
            return "application/x-ndjson"
        if suffix == ".png":
            return "image/png"
        return None
