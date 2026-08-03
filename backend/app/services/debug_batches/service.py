from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.debug_batch import DebugBatch, DebugBatchMembership
from app.models.generation_attempt import GenerationAttempt
from app.models.project import Project
from app.models.project_message import ProjectMessage
from app.models.revision import Revision
from app.models.revision_output import RevisionOutput
from app.models.workflow import WorkflowEvent, WorkflowRun
from app.schemas.debug_batch import DebugBatchRead, DebugBatchStart
from app.services.debug_batches.identity import capture_batch_identity
from app.services.debug_batches.lifecycle import resolve_project_outcome


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DebugBatchService:
    def __init__(self, *, db: Session, data_dir: Path) -> None:
        self.db = db
        self.data_dir = data_dir

    def start(self, payload: DebugBatchStart) -> DebugBatch:
        if self.db.scalar(
            select(DebugBatch.id).where(DebugBatch.state.in_(["active", "finishing"])).limit(1)
        ) is not None:
            raise ValueError("another debug batch is already active")
        if self.db.scalar(select(DebugBatch.id).where(DebugBatch.label == payload.label).where(DebugBatch.state == "active")):
            raise ValueError("an active debug batch already uses this label")
        baseline = None
        if payload.baseline_batch_id:
            baseline = self.db.get(DebugBatch, payload.baseline_batch_id)
            if baseline is None or baseline.state != "frozen":
                raise ValueError("baseline batch must be frozen")
        identity = capture_batch_identity(
            db=self.db,
            data_dir=self.data_dir,
            frontend_build_identity=payload.frontend_build_identity,
        )
        batch = DebugBatch(
            label=payload.label,
            notes=payload.notes,
            target_project_count=payload.target_project_count,
            baseline_batch_id=baseline.id if baseline else None,
            state="active",
            git_head=identity.git_head,
            branch=identity.branch,
            migration_head=identity.migration_head,
            application_version=identity.application_version,
            frontend_build_identity=identity.frontend_build_identity,
            backend_build_identity=identity.backend_build_identity,
            worker_build_identity=identity.worker_build_identity,
            build_identities_json=json.dumps(identity.build_identities, sort_keys=True),
            identity_complete=identity.identity_complete,
            provider=identity.provider,
            configured_default_model=identity.configured_default_model,
            stage_model_policy_json=json.dumps(identity.stage_model_policy, sort_keys=True),
            actual_provider_models_json=json.dumps(identity.actual_provider_models, sort_keys=True),
            prompt_versions_json=json.dumps(identity.prompt_versions, sort_keys=True),
            configuration_hash=identity.configuration_hash,
            evidence_contract_version="debug-batch-v1",
            comparison_status=(
                "pending_identity"
                if baseline and not (baseline.identity_complete and identity.identity_complete)
                else "pending"
                if baseline
                else "not_applicable"
            ),
            redaction_status="pending",
            integrity_status="pending",
        )
        self.db.add(batch)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ValueError("another debug batch is already active") from exc
        self.db.refresh(batch)
        return batch

    def attach_new_project(self, project: Project) -> DebugBatchMembership | None:
        batch = self.db.scalar(
            select(DebugBatch)
            .where(DebugBatch.state == "active")
            .order_by(DebugBatch.started_at.asc(), DebugBatch.id.asc())
            .limit(1)
        )
        if batch is None:
            return None
        existing = self.db.scalar(
            select(DebugBatchMembership).where(DebugBatchMembership.project_id == project.id)
        )
        if existing is not None:
            return existing
        max_position = self.db.scalar(
            select(func.max(DebugBatchMembership.position)).where(DebugBatchMembership.batch_id == batch.id)
        )
        position = int(max_position if max_position is not None else -1) + 1
        membership = DebugBatchMembership(batch_id=batch.id, project_id=project.id, position=position)
        self.db.add(membership)
        self.db.flush()
        return membership

    def finish(self, batch_id: str) -> DebugBatch:
        batch = self.db.get(DebugBatch, batch_id)
        if batch is None:
            raise LookupError("debug batch not found")
        if batch.state == "frozen":
            return batch
        if batch.state not in {"active", "finishing", "failed"}:
            raise ValueError("debug batch cannot be finished from its current state")
        batch.state = "finishing"
        batch.report_generation_state = "running"
        self.db.commit()
        try:
            from app.services.debug_batches.reports import DebugBatchReportService

            DebugBatchReportService(db=self.db, data_dir=self.data_dir).generate(batch.id)
        except Exception:
            failed = self.db.get(DebugBatch, batch.id)
            if failed is not None:
                failed.state = "failed"
                failed.report_generation_state = "failed"
                self.db.commit()
            raise
        frozen = self.db.get(DebugBatch, batch.id)
        if frozen is None:  # pragma: no cover - report generation retains the row
            raise LookupError("debug batch disappeared during report generation")
        frozen.state = "frozen"
        frozen.finished_at = frozen.finished_at or utcnow()
        self.db.commit()
        self.db.refresh(frozen)
        return frozen

    def get(self, batch_id: str) -> DebugBatch | None:
        return self.db.get(DebugBatch, batch_id)

    def read(self, batch: DebugBatch) -> DebugBatchRead:
        memberships = []
        for membership in sorted(batch.memberships, key=lambda item: item.position):
            project = self.db.get(Project, membership.project_id)
            status = self._project_status(project)
            memberships.append(
                {
                    "project_id": membership.project_id,
                    "position": membership.position,
                    "project_name": project.name if project else None,
                    "missing": project is None,
                    **status,
                }
            )
        return DebugBatchRead(
            id=batch.id,
            label=batch.label,
            notes=batch.notes,
            target_project_count=batch.target_project_count,
            baseline_batch_id=batch.baseline_batch_id,
            state=batch.state,
            git_head=batch.git_head,
            branch=batch.branch,
            migration_head=batch.migration_head,
            application_version=batch.application_version,
            frontend_build_identity=batch.frontend_build_identity,
            backend_build_identity=batch.backend_build_identity,
            worker_build_identity=batch.worker_build_identity,
            provider=batch.provider,
            configured_default_model=batch.configured_default_model,
            stage_model_policy=json.loads(batch.stage_model_policy_json),
            actual_provider_models=json.loads(batch.actual_provider_models_json),
            prompt_versions=json.loads(batch.prompt_versions_json),
            configuration_hash=batch.configuration_hash,
            started_at=batch.started_at,
            finished_at=batch.finished_at,
            report_path=batch.report_path,
            report_generation_state=batch.report_generation_state,
            evidence_contract_version=batch.evidence_contract_version,
            comparison_status=batch.comparison_status,
            redaction_status=batch.redaction_status,
            integrity_status=batch.integrity_status,
            build_identities=json.loads(batch.build_identities_json),
            identity_complete=batch.identity_complete,
            memberships=memberships,
        )

    def _project_status(self, project: Project | None) -> dict[str, object]:
        if project is None:
            return {
                "lifecycle_state": "interrupted",
                "workflow_phase": "Infrastructure failure",
                "worker_reached": False,
                "current_working_revision_id": None,
                "attempt_count": 0,
                "retry_count": 0,
                "provider_call_count": 0,
                "provider_retry_count": 0,
                "content_repair_count": 0,
                "generation_attempt_count": 0,
                "workflow_stage_attempt_count": 0,
                "user_operation_count": 0,
                "outcome_category": "infrastructure_failure",
                "final_outcome": "Infrastructure failure",
            }
        workflows = list(
            self.db.scalars(
                select(WorkflowRun)
                .where(WorkflowRun.project_id == project.id)
                .order_by(WorkflowRun.updated_at.asc(), WorkflowRun.id.asc())
            )
        )
        events = list(
            self.db.scalars(
                select(WorkflowEvent)
                .where(WorkflowEvent.project_id == project.id)
                .order_by(WorkflowEvent.recorded_at.asc(), WorkflowEvent.id.asc())
            )
        )
        attempts = list(
            self.db.scalars(
                select(GenerationAttempt)
                .where(GenerationAttempt.project_id == project.id)
                .order_by(GenerationAttempt.attempt_number.asc())
            )
        )
        messages = list(
            self.db.scalars(
                select(ProjectMessage)
                .where(ProjectMessage.project_id == project.id)
                .order_by(ProjectMessage.created_at.asc(), ProjectMessage.id.asc())
            )
        )
        revisions = list(
            self.db.scalars(
                select(Revision)
                .where(Revision.project_id == project.id)
                .order_by(Revision.revision_number.asc(), Revision.id.asc())
            )
        )
        revision_outputs = list(
            self.db.scalars(
                select(RevisionOutput)
                .join(Revision, RevisionOutput.revision_id == Revision.id)
                .where(Revision.project_id == project.id)
                .order_by(RevisionOutput.created_at.asc(), RevisionOutput.id.asc())
            )
        )
        outcome = resolve_project_outcome(
            project,
            workflows,
            attempts,
            events,
            revisions,
            revision_outputs,
        )
        lifecycle_state = outcome.lifecycle_state
        worker_reached = outcome.worker_reached
        active = lifecycle_state == "in_progress"
        if active:
            phase = "Waiting for clarification" if any(
                "clarif" in event.stage or "clarif" in event.event_type for event in events[-2:]
            ) else outcome.final_outcome
        else:
            phase = outcome.final_outcome
        provider_call_count = sum(attempt.provider_call_count for attempt in attempts)
        provider_retry_count = sum(attempt.provider_retry_count for attempt in attempts)
        content_repair_count = sum(attempt.content_repair_count for attempt in attempts)
        workflow_stage_attempt_count = len({(event.stage, event.generation_attempt_id) for event in events})
        return {
            "lifecycle_state": lifecycle_state,
            "workflow_phase": phase,
            "worker_reached": worker_reached,
            "current_working_revision_id": project.active_revision_id,
            "attempt_count": len(attempts),
            "retry_count": provider_retry_count,
            "provider_call_count": provider_call_count,
            "provider_retry_count": provider_retry_count,
            "content_repair_count": content_repair_count,
            "generation_attempt_count": len(attempts),
            "workflow_stage_attempt_count": workflow_stage_attempt_count,
            "user_operation_count": sum(message.role == "user" for message in messages),
            "outcome_category": outcome.category,
            "final_outcome": phase,
        }
