from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import build_ai_provider
from app.core.config import settings
from app.models.gemini_benchmark import (
    GeminiBenchmarkExperiment,
    GeminiBenchmarkMembership,
    GeminiBenchmarkModel,
    GeminiBenchmarkRun,
)
from app.models.project import Project
from app.schemas.gemini_benchmark import (
    GeminiBenchmarkClaimCreate,
    GeminiBenchmarkCompletionCreate,
    GeminiBenchmarkExperimentCreate,
    GeminiBenchmarkFinishCreate,
    GeminiBenchmarkExperimentRead,
    GeminiBenchmarkMembershipRead,
    GeminiBenchmarkModelAvailabilityCreate,
    GeminiBenchmarkModelRead,
    GeminiBenchmarkReportRead,
    GeminiBenchmarkRunRead,
)
from app.schemas.project import ProjectCreate
from app.services.debug_batches.identity import capture_batch_identity
from app.services.gemini_consistency.reporting import GeminiConsistencyReportingService
from app.services.projects.service import ProjectService


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GeminiConsistencyService:
    def __init__(self, *, db: Session, data_dir: Path) -> None:
        self.db = db
        self.data_dir = data_dir

    def create(self, payload: GeminiBenchmarkExperimentCreate) -> GeminiBenchmarkExperiment:
        identity = capture_batch_identity(
            db=self.db,
            data_dir=self.data_dir,
            frontend_build_identity=payload.frontend_build_identity,
        )
        experiment = GeminiBenchmarkExperiment(
            label=payload.label,
            corpus_version=payload.corpus_version,
            corpus_hash=payload.corpus_hash,
            mode=payload.mode,
            requested_runs=payload.runs,
            provider=identity.provider,
            git_head=identity.git_head,
            migration_head=identity.migration_head,
            prompt_versions_json=json.dumps(identity.prompt_versions, sort_keys=True),
            configuration_hash=identity.configuration_hash,
            build_identities_json=json.dumps(identity.build_identities, sort_keys=True),
            model_settings_json=json.dumps(
                {
                    "runner": payload.model_settings,
                    "configured_stage_policy": identity.stage_model_policy,
                },
                sort_keys=True,
            ),
            state="created",
            report_root=str(Path("debug-sessions") / "gemini-consistency"),
        )
        self.db.add(experiment)
        self.db.flush()
        report_root = self.data_dir / "debug-sessions" / "gemini-consistency" / experiment.id
        report_root.mkdir(parents=True, exist_ok=True)
        experiment.report_root = str(Path("debug-sessions") / "gemini-consistency" / experiment.id / "reports")
        run_identity = {
            "git_head": identity.git_head,
            "migration_head": identity.migration_head,
            "provider": identity.provider,
            "configured_default_model": identity.configured_default_model,
            "model_policy": identity.stage_model_policy,
            "prompt_versions": identity.prompt_versions,
            "configuration_hash": identity.configuration_hash,
            "build_identities": identity.build_identities,
        }
        for position, requested_model in enumerate(payload.models):
            model_config = GeminiBenchmarkModel(
                experiment_id=experiment.id,
                requested_model=requested_model,
                availability_state="unverified",
                settings_json=json.dumps(payload.model_settings, sort_keys=True),
                position=position,
            )
            self.db.add(model_config)
            self.db.flush()
            for run_index in range(1, payload.runs + 1):
                self.db.add(
                    GeminiBenchmarkRun(
                        experiment_id=experiment.id,
                        model_config_id=model_config.id,
                        run_index=run_index,
                        stable_run_key=f"{experiment.id}:{requested_model}:{run_index}",
                        state="created",
                        identity_json=json.dumps(
                            {**run_identity, "requested_model": requested_model, "run_index": run_index},
                            sort_keys=True,
                        ),
                    )
                )
        self.db.commit()
        self.db.refresh(experiment)
        return experiment

    def get(self, experiment_id: str) -> GeminiBenchmarkExperiment | None:
        return self.db.get(GeminiBenchmarkExperiment, experiment_id)

    def record_model_availability(
        self, experiment_id: str, payload: GeminiBenchmarkModelAvailabilityCreate
    ) -> GeminiBenchmarkModel:
        model = self.db.scalar(
            select(GeminiBenchmarkModel)
            .where(GeminiBenchmarkModel.experiment_id == experiment_id)
            .where(GeminiBenchmarkModel.requested_model == payload.requested_model)
        )
        if model is None:
            raise LookupError("benchmark model not found")
        model.actual_model = payload.actual_model
        model.availability_state = payload.availability_state
        self.db.commit()
        self.db.refresh(model)
        return model

    def read(self, experiment: GeminiBenchmarkExperiment) -> GeminiBenchmarkExperimentRead:
        return GeminiBenchmarkExperimentRead(
            id=experiment.id,
            label=experiment.label,
            corpus_version=experiment.corpus_version,
            corpus_hash=experiment.corpus_hash,
            mode=experiment.mode,
            requested_runs=experiment.requested_runs,
            provider=experiment.provider,
            git_head=experiment.git_head,
            migration_head=experiment.migration_head,
            prompt_versions=json.loads(experiment.prompt_versions_json),
            configuration_hash=experiment.configuration_hash,
            build_identities=json.loads(experiment.build_identities_json),
            model_settings=json.loads(experiment.model_settings_json),
            state=experiment.state,
            started_at=experiment.started_at,
            finished_at=experiment.finished_at,
            report_root=experiment.report_root,
            models=[
                GeminiBenchmarkModelRead(
                    id=model.id,
                    requested_model=model.requested_model,
                    actual_model=model.actual_model,
                    availability_state=model.availability_state,
                    settings=json.loads(model.settings_json),
                    position=model.position,
                )
                for model in experiment.models
            ],
            runs=[
                GeminiBenchmarkRunRead(
                    id=run.id,
                    model_config_id=run.model_config_id,
                    run_index=run.run_index,
                    stable_run_key=run.stable_run_key,
                    state=run.state,
                    identity=json.loads(run.identity_json),
                    report_path=run.report_path,
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                )
                for run in sorted(experiment.runs, key=lambda item: (item.model_config_id, item.run_index))
            ],
        )

    def claim(
        self,
        *,
        experiment_id: str,
        run_id: str,
        case_id: str,
        payload: GeminiBenchmarkClaimCreate,
    ) -> GeminiBenchmarkMembership:
        run = self.db.get(GeminiBenchmarkRun, run_id)
        if run is None or run.experiment_id != experiment_id:
            raise LookupError("benchmark run not found")
        if run.state in {"cancelled", "completed"}:
            raise ValueError("benchmark run is not accepting new cases")
        existing = self.db.scalar(
            select(GeminiBenchmarkMembership)
            .where(GeminiBenchmarkMembership.run_id == run_id)
            .where(GeminiBenchmarkMembership.corpus_case_id == case_id)
        )
        if existing is not None:
            return existing
        stable_project_key = f"{run.stable_run_key}:{case_id}"
        project_service = ProjectService(db=self.db, data_dir=self.data_dir)
        try:
            project = project_service.create_project(
                ProjectCreate(name=payload.title, original_intent=payload.original_intent),
                commit=False,
            )
            membership = GeminiBenchmarkMembership(
                run_id=run.id,
                corpus_case_id=case_id,
                position=payload.position,
                stable_project_key=stable_project_key,
                project_id=project.id,
                state="claimed",
                started_at=utcnow(),
            )
            self.db.add(membership)
            run.state = "running"
            self.db.commit()
            self.db.refresh(membership)
            return membership
        except IntegrityError as exc:
            self.db.rollback()
            existing = self.db.scalar(
                select(GeminiBenchmarkMembership)
                .where(GeminiBenchmarkMembership.run_id == run_id)
                .where(GeminiBenchmarkMembership.corpus_case_id == case_id)
            )
            if existing is not None:
                return existing
            raise ValueError("benchmark case claim conflicted with another submission") from exc

    def complete(
        self,
        *,
        experiment_id: str,
        run_id: str,
        case_id: str,
        payload: GeminiBenchmarkCompletionCreate,
    ) -> GeminiBenchmarkMembership:
        membership = self.db.scalar(
            select(GeminiBenchmarkMembership)
            .join(GeminiBenchmarkRun)
            .where(GeminiBenchmarkRun.experiment_id == experiment_id)
            .where(GeminiBenchmarkMembership.run_id == run_id)
            .where(GeminiBenchmarkMembership.corpus_case_id == case_id)
        )
        if membership is None:
            raise LookupError("benchmark membership not found")
        if membership.state in {"completed", "failed", "cancelled", "incomplete"}:
            return membership
        membership.state = payload.state
        membership.clarification_rounds = payload.clarification_rounds
        membership.retry_count = payload.retry_count
        membership.outcome_category = payload.outcome_category
        membership.outcome_state = payload.outcome_state
        membership.final_outcome = payload.final_outcome
        membership.metrics_json = json.dumps(payload.metrics, sort_keys=True)
        membership.evidence_path = payload.evidence_path
        membership.completed_at = utcnow()
        self.db.commit()
        self.db.refresh(membership)
        return membership

    def finish(self, experiment_id: str, payload: GeminiBenchmarkFinishCreate) -> GeminiBenchmarkExperiment:
        experiment = self.db.get(GeminiBenchmarkExperiment, experiment_id)
        if experiment is None:
            raise LookupError("benchmark experiment not found")
        if experiment.state in {"completed", "failed", "cancelled"}:
            return experiment
        experiment.state = payload.state
        experiment.finished_at = utcnow()
        self.db.commit()
        self.db.refresh(experiment)
        return experiment

    def finish_run(self, experiment_id: str, run_id: str, payload: GeminiBenchmarkFinishCreate) -> GeminiBenchmarkRun:
        run = self.db.get(GeminiBenchmarkRun, run_id)
        if run is None or run.experiment_id != experiment_id:
            raise LookupError("benchmark run not found")
        if run.state in {"completed", "failed", "cancelled"}:
            return run
        run.state = payload.state
        run.finished_at = utcnow()
        self.db.commit()
        self.db.refresh(run)
        return run

    def membership_read(self, membership: GeminiBenchmarkMembership) -> GeminiBenchmarkMembershipRead:
        return GeminiBenchmarkMembershipRead(
            id=membership.id,
            run_id=membership.run_id,
            corpus_case_id=membership.corpus_case_id,
            position=membership.position,
            stable_project_key=membership.stable_project_key,
            project_id=membership.project_id,
            state=membership.state,
            clarification_rounds=membership.clarification_rounds,
            retry_count=membership.retry_count,
            outcome_category=membership.outcome_category,
            outcome_state=membership.outcome_state,
            final_outcome=membership.final_outcome,
            metrics=json.loads(membership.metrics_json),
            evidence_path=membership.evidence_path,
            started_at=membership.started_at,
            completed_at=membership.completed_at,
        )

    def report(self, experiment_id: str) -> GeminiBenchmarkReportRead:
        experiment = self.get(experiment_id)
        if experiment is None:
            raise LookupError("benchmark experiment not found")
        memberships = list(
            self.db.scalars(
                select(GeminiBenchmarkMembership)
                .join(GeminiBenchmarkRun)
                .where(GeminiBenchmarkRun.experiment_id == experiment_id)
            )
        )
        generated = GeminiConsistencyReportingService(db=self.db, data_dir=self.data_dir).generate(experiment_id)
        report_root = generated.get("report_root")
        report_paths = [
            str(Path(report_root, name).relative_to(self.data_dir))
            for name in ("pilot-summary.md", "benchmark-summary.md", "model-comparison.md", "run-consistency.md", "failure-signatures.md")
            if report_root and (Path(report_root) / name).is_file()
        ]
        return GeminiBenchmarkReportRead(
            experiment_id=experiment_id,
            state=experiment.state,
            membership_count=len(memberships),
            completed_count=sum(item.state == "completed" for item in memberships),
            report_paths=report_paths or [item.evidence_path for item in memberships if item.evidence_path],
        )

    async def discover_models(self) -> list[dict[str, Any]]:
        provider = build_ai_provider(settings)
        if not hasattr(provider, "list_available_models"):
            raise ValueError("configured provider does not support Gemini model discovery")
        return await provider.list_available_models()
