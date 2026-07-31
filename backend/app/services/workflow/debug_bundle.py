from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.workflow import WorkflowArtifact, WorkflowEvent, WorkflowRun
from app.services.workflow.diagnosis import WorkflowDiagnosisService
from app.services.workflow.redaction import RedactionError, RedactionService
from app.services.workflow.stage_trace import WorkflowStageTraceService


SENSITIVE_ARTIFACT_TYPES = {
    "raw_provider_response",
    "provider_request_metadata",
    "rendered_prompt",
}
LARGE_GEOMETRY_SUFFIXES = {".stl", ".step", ".stp", ".brep"}


class WorkflowDebugBundleService:
    def __init__(self, *, db: Session, data_dir: Path) -> None:
        self.db = db
        self.data_dir = data_dir
        self.redactor = RedactionService()

    def build_bundle(self, workflow_run_id: str, *, include_geometry: bool = False) -> Path:
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
        artifacts = list(
            self.db.scalars(
                select(WorkflowArtifact)
                .where(WorkflowArtifact.root_workflow_run_id == root_id)
                .order_by(WorkflowArtifact.created_at.asc())
            )
        )
        diagnosis = WorkflowDiagnosisService(db=self.db).diagnose(run.id)
        trace_service = WorkflowStageTraceService(db=self.db)
        report = {
            "schema_version": "workflow-redaction-report-v1",
            "artifacts_inspected": [],
            "fields_removed": [],
            "fields_replaced": [],
            "sensitive_artifacts_excluded": [],
            "redaction_status": "confirmed",
        }
        bundle_dir = self.data_dir / "workflow-debug-bundles"
        bundle_dir.mkdir(parents=True, exist_ok=True)
        bundle_path = bundle_dir / f"workflow-debug-{run.id}.zip"
        root = f"workflow-debug-{run.id}"
        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            self._write_json(archive, f"{root}/run-summary.json", self._run_summary(run))
            self._write_json(
                archive,
                f"{root}/diagnosis.json",
                {
                    "schema_version": diagnosis.schema_version,
                    "workflow_run_id": diagnosis.workflow_run_id,
                    "root_cause": diagnosis.root_cause,
                    "repairs": diagnosis.repairs,
                    "downstream_effects": diagnosis.downstream_effects,
                    "final_outcome": diagnosis.final_outcome,
                },
            )
            archive.writestr(
                f"{root}/event-log.ndjson",
                "\n".join(json.dumps(self._event_payload(event), sort_keys=True, default=str) for event in events)
                + ("\n" if events else ""),
            )
            self._write_json(archive, f"{root}/stage-trace.json", trace_service.build_trace(run.id))
            archive.writestr(f"{root}/stage-trace.md", trace_service.build_markdown(run.id))
            self._write_json(
                archive,
                f"{root}/artifacts.json",
                [self._artifact_payload(artifact) for artifact in artifacts],
            )
            archive.writestr(f"{root}/README.md", self._readme(run, diagnosis.root_cause))
            for artifact in artifacts:
                self._include_artifact(
                    archive=archive,
                    root=root,
                    artifact=artifact,
                    include_geometry=include_geometry,
                    report=report,
                )
            self._write_json(archive, f"{root}/redaction-report.json", report)
        self._assert_archive_redacted(bundle_path)
        return bundle_path

    def _include_artifact(
        self,
        *,
        archive: zipfile.ZipFile,
        root: str,
        artifact: WorkflowArtifact,
        include_geometry: bool,
        report: dict[str, Any],
    ) -> None:
        report["artifacts_inspected"].append(
            {
                "artifact_id": artifact.id,
                "artifact_type": artifact.artifact_type,
                "path": artifact.path,
            }
        )
        source_path = self._artifact_path(artifact)
        if source_path is None or not source_path.exists() or not source_path.is_file():
            return
        if source_path.suffix.lower() in LARGE_GEOMETRY_SUFFIXES and not include_geometry:
            report["sensitive_artifacts_excluded"].append(
                {"artifact_id": artifact.id, "reason": "large_geometry_excluded_by_default"}
            )
            return
        data = source_path.read_bytes()
        if self._looks_text(source_path):
            text = data.decode("utf-8", errors="replace")
            if artifact.artifact_type in SENSITIVE_ARTIFACT_TYPES and not artifact.redacted:
                text, replacements = self.redactor.redact_text(text)
                if replacements:
                    report["fields_replaced"].append(
                        {
                            "artifact_id": artifact.id,
                            "artifact_type": artifact.artifact_type,
                            "patterns": replacements,
                        }
                    )
            self.redactor.assert_text_redacted(text)
            archive.writestr(
                f"{root}/artifacts/{artifact.stage}/{artifact.role}-{source_path.name}",
                text,
            )
        else:
            if artifact.artifact_type in SENSITIVE_ARTIFACT_TYPES and not artifact.redacted:
                raise RedactionError(f"sensitive binary artifact is not confirmed redacted: {artifact.id}")
            archive.write(
                source_path,
                f"{root}/artifacts/{artifact.stage}/{artifact.role}-{source_path.name}",
            )

    def _artifact_path(self, artifact: WorkflowArtifact) -> Path | None:
        path = Path(artifact.path)
        if path.is_absolute():
            return path
        return self.data_dir / path

    def _looks_text(self, path: Path) -> bool:
        return path.suffix.lower() in {".json", ".txt", ".log", ".md", ".py", ".ndjson"}

    def _assert_archive_redacted(self, bundle_path: Path) -> None:
        with zipfile.ZipFile(bundle_path) as archive:
            for name in archive.namelist():
                if Path(name).suffix.lower() not in {".json", ".txt", ".log", ".md", ".py", ".ndjson"}:
                    continue
                self.redactor.assert_text_redacted(
                    archive.read(name).decode("utf-8", errors="replace")
                )

    def _run_summary(self, run: WorkflowRun) -> dict[str, Any]:
        return {
            "schema_version": "workflow-run-summary-v1",
            "workflow_run_id": run.id,
            "project_id": run.project_id,
            "workflow_type": run.workflow_type,
            "parent_workflow_run_id": run.parent_workflow_run_id,
            "root_workflow_run_id": run.root_workflow_run_id,
            "correlation_id": run.correlation_id,
            "status": run.status,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "logging_mode": run.logging_mode,
            "event_schema_version": run.event_schema_version,
            "diagnosis_version": run.diagnosis_version,
            "redaction_version": run.redaction_version,
            "application_commit": run.application_commit,
            "worker_version": run.worker_version,
            "provider": run.provider,
            "model": run.model,
            "prompt_versions": json.loads(run.prompt_versions_json),
        }

    def _event_payload(self, event: WorkflowEvent) -> dict[str, Any]:
        return {
            "schema_version": "workflow-event-v1",
            "event_id": event.id,
            "workflow_run_id": event.workflow_run_id,
            "root_workflow_run_id": event.root_workflow_run_id,
            "correlation_id": event.correlation_id,
            "project_id": event.project_id,
            "sequence_number": event.sequence_number,
            "occurred_at": event.occurred_at,
            "recorded_at": event.recorded_at,
            "stage": event.stage,
            "event_type": event.event_type,
            "severity": event.severity,
            "blocking": event.blocking,
            "message": event.message,
            "rule_id": event.rule_id,
            "entity_type": event.entity_type,
            "entity_id": event.entity_id,
            "source_artifact_id": event.source_artifact_id,
            "caused_by_event_id": event.caused_by_event_id,
            "is_root_failure": event.is_root_failure,
            "is_downstream_symptom": event.is_downstream_symptom,
            "metadata": json.loads(event.metadata_json),
        }

    def _artifact_payload(self, artifact: WorkflowArtifact) -> dict[str, Any]:
        return {
            "artifact_id": artifact.id,
            "workflow_run_id": artifact.workflow_run_id,
            "stage": artifact.stage,
            "artifact_type": artifact.artifact_type,
            "role": artifact.role,
            "path": artifact.path,
            "sha256": artifact.sha256,
            "size_bytes": artifact.size_bytes,
            "media_type": artifact.media_type,
            "created_at": artifact.created_at,
            "redacted": artifact.redacted,
            "redaction_status": artifact.redaction_status,
            "supersedes_artifact_id": artifact.supersedes_artifact_id,
            "metadata": json.loads(artifact.artifact_metadata_json),
        }

    def _readme(self, run: WorkflowRun, root_cause: dict[str, Any]) -> str:
        return (
            f"# Workflow Debug Bundle\n\n"
            f"Workflow type: {run.workflow_type}\n\n"
            f"Final result: {run.status}\n\n"
            f"First failure: {root_cause.get('summary') or 'none recorded'}\n\n"
            f"Provider/model: {run.provider or 'unknown'} / {run.model or 'unknown'}\n"
        )

    def _write_json(self, archive: zipfile.ZipFile, name: str, payload: Any) -> None:
        data = json.dumps(payload, indent=2, sort_keys=True, default=str)
        self.redactor.assert_text_redacted(data)
        archive.writestr(name, data)
