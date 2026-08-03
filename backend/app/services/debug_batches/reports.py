from __future__ import annotations

import json
import shutil
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.debug_batch import DebugBatch, DebugBatchMembership
from app.models.export_record import ExportRecord
from app.models.generation_attempt import GenerationAttempt
from app.models.project import Project
from app.models.project_message import ProjectMessage
from app.models.revision import Revision
from app.models.workflow import WorkflowArtifact, WorkflowEvent, WorkflowRun
from app.services.workflow.redaction import RedactionService


TEXT_SUFFIXES = {".json", ".txt", ".log", ".md", ".py", ".ndjson", ".toml", ".yaml", ".yml"}
EVIDENCE_CONTRACT_VERSION = "debug-batch-v1"


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _row_payload(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    payload: dict[str, Any] = {}
    for column in row.__table__.columns:
        value = _json_value(getattr(row, column.name))
        if column.name.endswith("_json") and isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                pass
        payload[column.name] = value
    return payload


class DebugBatchReportService:
    def __init__(self, *, db: Session, data_dir: Path) -> None:
        self.db = db
        self.data_dir = data_dir
        self.redactor = RedactionService()

    def generate(self, batch_id: str) -> dict[str, Any]:
        batch = self.db.get(DebugBatch, batch_id)
        if batch is None:
            raise LookupError("debug batch not found")
        root = self.data_dir / "debug-sessions" / batch.id
        root.mkdir(parents=True, exist_ok=True)
        for folder in ("screenshots", "comparison", "selected-regression-candidates", "projects"):
            (root / folder).mkdir(parents=True, exist_ok=True)

        integrity: dict[str, Any] = {"schema_version": "debug-batch-integrity-v1", "findings": []}
        redaction: dict[str, Any] = {
            "schema_version": "debug-batch-redaction-v1",
            "redaction_version": self.redactor.version,
            "fields_replaced": [],
            "status": "confirmed",
        }
        project_summaries: list[dict[str, Any]] = []
        memberships = list(
            self.db.scalars(
                select(DebugBatchMembership)
                .where(DebugBatchMembership.batch_id == batch.id)
                .order_by(DebugBatchMembership.position.asc())
            )
        )
        for membership in memberships:
            project = self.db.get(Project, membership.project_id)
            project_summaries.append(
                self._materialize_project(
                    root=root,
                    membership=membership,
                    project=project,
                    integrity=integrity,
                    redaction=redaction,
                )
            )

        session_payload = {
            "schema_version": EVIDENCE_CONTRACT_VERSION,
            "batch": _row_payload(batch),
            "member_project_ids": [membership.project_id for membership in memberships],
            "membership_count": len(memberships),
        }
        self._write_json(root / "session.json", session_payload, redaction)

        outcomes = Counter(summary["final_outcome"] for summary in project_summaries)
        report = {
            "schema_version": "debug-batch-report-v1",
            "batch_id": batch.id,
            "label": batch.label,
            "funnel": self._funnel(project_summaries),
            "routes": Counter(summary.get("route") for summary in project_summaries if summary.get("route")),
            "outcomes": dict(outcomes),
            "failure_distribution": dict(
                Counter(
                    finding.get("category", "unknown")
                    for summary in project_summaries
                    for finding in summary.get("findings", [])
                )
            ),
            "provider_behavior": self._provider_behavior(project_summaries),
            "user_facing_behavior": self._user_facing_behavior(project_summaries),
            "repeated_signatures": self._repeated_signatures(project_summaries),
            "integrity_findings": integrity["findings"],
            "projects": project_summaries,
        }
        self._write_json(root / "report.json", report, redaction)
        self._write_text(root / "report.md", self._markdown_report(batch, report), redaction)
        self._write_text(root / "codex-review.md", self._codex_review_instruction(batch), redaction)
        self._write_json(root / "redaction-report.json", redaction, redaction)
        self._write_json(root / "integrity-report.json", integrity, redaction)

        batch.report_path = str(root / "report.md")
        batch.report_generation_state = "generated"
        batch.redaction_status = "confirmed"
        batch.integrity_status = "findings" if integrity["findings"] else "confirmed"
        self.db.commit()
        return {
            "root_path": str(root),
            "report_path": str(root / "report.md"),
            "report": report,
            "integrity": integrity,
            "redaction": redaction,
        }

    def build_archive(self, batch_id: str) -> Path:
        batch = self.db.get(DebugBatch, batch_id)
        if batch is None:
            raise LookupError("debug batch not found")
        root = self.data_dir / "debug-sessions" / batch.id
        if not (root / "report.json").exists():
            self.generate(batch_id)
        archive_path = self.data_dir / "debug-sessions" / f"{batch.id}.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in root.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(root.parent))
        return archive_path

    def _materialize_project(
        self,
        *,
        root: Path,
        membership: DebugBatchMembership,
        project: Project | None,
        integrity: dict[str, Any],
        redaction: dict[str, Any],
    ) -> dict[str, Any]:
        project_root = root / "projects" / membership.project_id
        project_root.mkdir(parents=True, exist_ok=True)
        if project is None:
            finding = {
                "kind": "missing_project",
                "project_id": membership.project_id,
                "position": membership.position,
            }
            integrity["findings"].append(finding)
            summary = {
                "project_id": membership.project_id,
                "project_name": None,
                "position": membership.position,
                "final_outcome": "Infrastructure failure",
                "integrity_findings": [finding],
                "findings": [],
            }
            self._write_json(project_root / "summary.json", summary, redaction)
            self._write_text(project_root / "summary.md", self._summary_markdown(summary), redaction)
            return summary

        workflows = list(
            self.db.scalars(
                select(WorkflowRun)
                .where(WorkflowRun.project_id == project.id)
                .order_by(WorkflowRun.started_at.asc(), WorkflowRun.id.asc())
            )
        )
        workflow_ids = [workflow.id for workflow in workflows]
        events = list(
            self.db.scalars(
                select(WorkflowEvent)
                .where(WorkflowEvent.project_id == project.id)
                .order_by(WorkflowEvent.recorded_at.asc(), WorkflowEvent.sequence_number.asc())
            )
        )
        artifacts = list(
            self.db.scalars(
                select(WorkflowArtifact)
                .where(WorkflowArtifact.project_id == project.id)
                .order_by(WorkflowArtifact.created_at.asc(), WorkflowArtifact.id.asc())
            )
        )
        messages = list(
            self.db.scalars(
                select(ProjectMessage)
                .where(ProjectMessage.project_id == project.id)
                .order_by(ProjectMessage.created_at.asc(), ProjectMessage.id.asc())
            )
        )
        attempts = list(
            self.db.scalars(
                select(GenerationAttempt)
                .where(GenerationAttempt.project_id == project.id)
                .order_by(GenerationAttempt.attempt_number.asc(), GenerationAttempt.id.asc())
            )
        )
        revisions = list(
            self.db.scalars(
                select(Revision)
                .where(Revision.project_id == project.id)
                .order_by(Revision.revision_number.asc(), Revision.id.asc())
            )
        )
        exports = list(
            self.db.scalars(
                select(ExportRecord)
                .where(ExportRecord.project_id == project.id)
                .order_by(ExportRecord.created_at.asc(), ExportRecord.id.asc())
            )
        )

        for name, rows in {
            "conversation.json": [_row_payload(row) for row in messages],
            "workflows.json": [_row_payload(row) for row in workflows],
            "events.json": [_row_payload(row) for row in events],
            "attempts.json": [_row_payload(row) for row in attempts],
            "revisions.json": [_row_payload(row) for row in revisions],
            "exports.json": [_row_payload(row) for row in exports],
        }.items():
            self._write_json(project_root / name, rows, redaction)

        for artifact in artifacts:
            self._materialize_artifact(
                project_root=project_root,
                artifact=artifact,
                integrity=integrity,
                redaction=redaction,
            )

        active_workflow = next((workflow for workflow in reversed(workflows) if workflow.status == "running"), None)
        final_outcome = self._outcome(project, workflows, events, attempts)
        summary = {
            "project_id": project.id,
            "project_name": project.name,
            "position": membership.position,
            "original_intent": project.original_intent,
            "current_working_revision_id": project.active_revision_id,
            "workflow_ids": workflow_ids,
            "active_workflow_status": active_workflow.status if active_workflow else None,
            "route": self._route(events),
            "worker_reached": any(event.stage in {"cad_execution", "worker", "topology_validation"} for event in events),
            "attempt_count": len(attempts),
            "retry_count": max(0, len(attempts) - 1),
            "final_outcome": final_outcome,
            "findings": [
                {"category": event.stage, "event_type": event.event_type, "message": event.message}
                for event in events
                if event.blocking
            ],
            "integrity_findings": [
                finding for finding in integrity["findings"] if finding.get("project_id") == project.id
            ],
        }
        self._write_json(project_root / "summary.json", summary, redaction)
        self._write_text(project_root / "summary.md", self._summary_markdown(summary), redaction)
        return summary

    def _materialize_artifact(
        self,
        *,
        project_root: Path,
        artifact: WorkflowArtifact,
        integrity: dict[str, Any],
        redaction: dict[str, Any],
    ) -> None:
        source = Path(artifact.path)
        if not source.is_absolute():
            source = self.data_dir / source
        if not source.exists() or not source.is_file():
            integrity["findings"].append(
                {
                    "kind": "missing_artifact",
                    "project_id": artifact.project_id,
                    "artifact_id": artifact.id,
                    "artifact_type": artifact.artifact_type,
                    "path": source.name,
                }
            )
            return
        family = self._artifact_family(artifact.artifact_type)
        destination = project_root / family / f"{artifact.role}-{source.name}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix.lower() in TEXT_SUFFIXES:
            text = source.read_text(encoding="utf-8", errors="replace")
            redacted_text, replacements = self.redactor.redact_text(text)
            if replacements:
                redaction["fields_replaced"].append(
                    {"artifact_id": artifact.id, "artifact_type": artifact.artifact_type, "patterns": replacements}
                )
            self.redactor.assert_text_redacted(redacted_text)
            destination.write_text(redacted_text, encoding="utf-8")
        else:
            shutil.copyfile(source, destination)

    def _artifact_family(self, artifact_type: str) -> str:
        normalized = artifact_type.lower()
        for prefix in ("prompt", "geometry", "worker", "revision", "export", "snapshot", "frontend"):
            if prefix in normalized:
                return f"{prefix}s"
        if "requirement" in normalized:
            return "requirements"
        if "plan" in normalized or "brief" in normalized:
            return "planning"
        return "findings"

    def _outcome(
        self,
        project: Project,
        workflows: list[WorkflowRun],
        events: list[WorkflowEvent],
        attempts: list[GenerationAttempt],
    ) -> str:
        if any(workflow.status == "running" for workflow in workflows):
            return "In progress"
        if project.active_revision_id:
            return "Working version created"
        if any(event.blocking and event.stage in {"requirements", "clarification"} for event in events):
            return "Blocked before worker"
        if any(event.blocking for event in events) or any(attempt.status in {"failed", "blocked"} for attempt in attempts):
            return "Blocked after worker" if any(event.stage in {"cad_execution", "worker"} for event in events) else "Blocked before worker"
        return "Not started"

    def _route(self, events: list[WorkflowEvent]) -> str | None:
        for event in events:
            metadata = json.loads(event.metadata_json) if event.metadata_json else {}
            route = metadata.get("route")
            if route:
                return str(route)
        return None

    def _funnel(self, summaries: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "projects_created": len(summaries),
            "requirements_completed": sum(bool(item.get("workflow_ids")) for item in summaries),
            "clarifications_requested": 0,
            "planning_completed": sum(bool(item.get("current_working_revision_id")) for item in summaries),
            "geometry_generated": sum(bool(item.get("current_working_revision_id")) for item in summaries),
            "source_contract_passed": 0,
            "worker_reached": sum(bool(item.get("worker_reached")) for item in summaries),
            "valid_geometry_produced": sum(item.get("final_outcome") == "Working version created" for item in summaries),
            "snapshots_produced": 0,
            "current_working_version_promoted": sum(bool(item.get("current_working_revision_id")) for item in summaries),
            "exports_created": 0,
        }

    def _provider_behavior(self, summaries: list[dict[str, Any]]) -> dict[str, Any]:
        return {"project_count": len(summaries), "calls_by_stage": {}, "retries": sum(item.get("retry_count", 0) for item in summaries)}

    def _user_facing_behavior(self, summaries: list[dict[str, Any]]) -> dict[str, Any]:
        return {"duplicate_messages": 0, "missing_assistant_outcomes": 0, "frontend_errors": 0}

    def _repeated_signatures(self, summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        signatures = Counter(
            f"{finding.get('category')}:{finding.get('event_type')}"
            for summary in summaries
            for finding in summary.get("findings", [])
        )
        return [{"signature": signature, "project_count": count} for signature, count in signatures.items() if count > 1]

    def _markdown_report(self, batch: DebugBatch, report: dict[str, Any]) -> str:
        lines = [f"# Debug batch: {batch.label}", "", "## Summary", "", f"Projects: {len(report['projects'])}", ""]
        lines.append("## Projects")
        lines.append("")
        for project in report["projects"]:
            lines.append(
                f"- **{project.get('project_name') or project['project_id']}** — {project['final_outcome']} "
                f"(worker reached: {'yes' if project.get('worker_reached') else 'no'})"
            )
        lines.extend(["", "## Integrity", "", f"Findings: {len(report['integrity_findings'])}"])
        return "\n".join(lines) + "\n"

    def _summary_markdown(self, summary: dict[str, Any]) -> str:
        return (
            f"# {summary.get('project_name') or summary['project_id']}\n\n"
            f"Outcome: {summary['final_outcome']}\n\n"
            f"Worker reached: {'yes' if summary.get('worker_reached') else 'no'}\n"
        )

    def _codex_review_instruction(self, batch: DebugBatch) -> str:
        return f"""# Codex review instruction: {batch.label}

Review only the local redacted evidence for this batch. Confirm Git, migration,
provider, model, prompt, configuration, frontend, backend, and worker identity.
Inspect every project individually: conversation, requirements, Plan, prompt
context, source, worker evidence, findings, frontend evidence, snapshots,
exports, and final state. Identify the stopping stage for every attempt.

Classify findings as user ambiguity, legitimate clarification, requirement or
semantic-normalization defect, Plan/provider interoperability, safe
normalization, provider variability, source/coordinate/Python/CadQuery defect,
worker/infrastructure defect, topology/geometry defect, verification gap,
artifact/export defect, frontend state/wording defect, or isolated anomaly.
Identify repeated signatures and misleading frontend states. Do not propose a
generic code change from one strange provider response unless integrity,
security, Current-version, or export risk exists. Recommend narrow generic
corrections and identify real responses suitable for frozen regression
fixtures. Make no implementation changes during review.

The monitor-wall-mount (monitor mount) project is geometry/workflow evaluation only; retain its
physical engineering and test-review warning and never imply load-bearing
safety from geometry success.
"""

    def _write_json(self, path: Path, payload: Any, redaction: dict[str, Any]) -> None:
        redacted = self.redactor._redact_value(payload)
        self.redactor.assert_json_redacted(redacted)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(redacted, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8")

    def _write_text(self, path: Path, value: str, redaction: dict[str, Any]) -> None:
        redacted, replacements = self.redactor.redact_text(value)
        if replacements:
            redaction["fields_replaced"].append({"path": str(path.name), "patterns": replacements})
        self.redactor.assert_text_redacted(redacted)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(redacted, encoding="utf-8")
