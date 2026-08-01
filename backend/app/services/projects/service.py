import ast
import asyncio
import difflib
import hashlib
import json
import re
import shutil
import subprocess
import time
import zipfile
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from typing import Any

import trimesh
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.clarification_answer import ClarificationAnswer
from app.models.clarification_question import ClarificationQuestion
from app.models.configuration_change import ConfigurationChange, ConfigurationPreset
from app.models.design_artifact_consistency import DesignArtifactConsistencyResult
from app.models.design_plan import (
    DesignPlan,
    DesignPlanClarificationAnswer,
    DesignPlanClarificationQuestion,
)
from app.models.design_specification import DesignSpecification
from app.models.geometric_analysis_result import GeometricAnalysisResult
from app.models.generation_attempt import GenerationAttempt
from app.models.project import Project, utcnow as project_utcnow
from app.models.project_message import ProjectMessage
from app.models.revision import Revision
from app.models.revision_output import RevisionOutput
from app.models.revision_plan import (
    ComponentRevisionSummary,
    RevisionComplianceResult,
    RevisionPlan,
    RevisionPlanClarificationAnswer,
    RevisionPlanClarificationQuestion,
    RevisionSuccessResult,
)
from app.models.source_validation_result import SourceValidationResult
from app.models.validation_finding import ValidationFinding
from app.models.workflow import (
    FrontendWorkflowEvent,
    WorkflowArtifact,
    WorkflowDiagnosis,
    WorkflowEvent,
    WorkflowRun,
)
from app.schemas.project import (
    ClarificationAnswersCreate,
    ClarificationQuestionRead,
    ConfigurationChangeCreate,
    ConfigurationChangeRead,
    ConfigurationOverrideManifestRead,
    ConfigurationParameterRead,
    ConfigurationPresetCreate,
    ConfigurationPresetRead,
    ConfigurationValidationState,
    ComponentRevisionSummaryRead,
    DesignArtifactConsistencyRead,
    DesignSpecificationPayload,
    DesignSpecificationRead,
    DesignPlanClarificationQuestionRead,
    DesignPlanOutcome,
    DesignPlanPayload,
    DesignPlanRead,
    DesignPlanReviewState,
    GenerationCreate,
    GeometricAnalysisRead,
    GeometricFindingRead,
    ManualRevisionCreate,
    MeshMetadataRead,
    ProjectCreate,
    ProjectLibraryRead,
    ProjectMessageRead,
    ProjectWorkspaceRead,
    ProjectSave,
    ProjectUpdate,
    RevisionRead,
    RevisionOutputRead,
    RevisionComplianceResultRead,
    RevisionPlanClarificationQuestionRead,
    RevisionPlanCreate,
    RevisionPlanOutcome,
    RevisionPlanPayload,
    RevisionPlanRead,
    RevisionPlanReviewState,
    RevisionSuccessResultRead,
    ValidationFindingRead,
    ValidationSummaryRead,
    RequirementExtractionCreate,
    RequirementImportance,
    RequirementOutcome,
    RequirementSource,
)
from app.schemas.printability import PrintabilityProfile, PrintabilityResult
from app.services.ai.provider import (
    AiProvider,
    DesignPlanRequest,
    ModelGenerationRequest,
    RequirementExtractionRequest,
    RevisionPlanRequest,
)
from app.services.ai.source_extraction import (
    SourceExtractionError,
    extract_python_source,
)
from app.services.cad.cadquery_contract import CadQueryContractError, validate_cadquery_source
from app.services.cad.cadquery_source_authority import (
    CadQuerySourceAuthorityError,
    authority_from_generation_context,
    validate_cadquery_source_authority,
)
from app.services.cad.geometry_bodies import (
    GEOMETRY_BODIES_SCHEMA_VERSION,
    GeometryBodyError,
    assemble_geometry_bodies,
    build_geometry_function_inventory,
)
from app.services.cad.patterns import normalize_pattern_specs, validate_pattern_specs
from app.services.cad.source_scaffold import (
    SCAFFOLD_VERSION,
    ScaffoldSourceError,
    extract_geometry_functions,
    render_cadquery_scaffold,
    validate_scaffold_source,
)
from app.services.cad.worker_client import FilesystemCadWorkerRunner
from app.services.cad.source_metadata import (
    SourceMapping,
    SourceMetadata,
    SourceModuleFingerprint,
    SourceOutputMapping,
    SourceParameterMapping,
    evaluate_constants,
)
from app.services.generation.failure_taxonomy import FailureClass
from app.services.functional.intent import (
    resolve_retention_proposals,
    validate_functional_plan,
    validate_revision_success_criteria,
)
from app.services.projects.design_artifact_consistency import (
    certify_design_artifact_consistency,
    consistency_failure_message,
)
from app.services.projects.plan_provenance import (
    normalize_plan_provenance,
    validate_plan_provenance,
)
from app.services.projects.plan_constraints import explicit_control_requests, normalize_plan_constraints
from app.services.projects.requirement_ledger import (
    RequirementLedgerStore,
    active_requirements,
    requirement_delta_for_message,
)
from app.services.workflow.observability import WorkflowRecorder
from app.services.requirements.trace import (
    RequirementTraceError,
    build_explicit_requirement_inventory,
    inventory_from_design_specification,
    merge_resolved_requirements,
    requirement_trace_payload,
    validate_design_plan_trace,
    validate_design_specification_trace,
    validate_execution_parameters,
    validate_requirement_extraction_trace,
    validate_source_parameter_trace,
)
from app.services.geometry.invariants import (
    GeometricAnalysisContext,
    GeometricFinding,
    GeometryAnalyzerRegistry,
    mesh_hash,
)
from app.services.geometry.functional import (
    FunctionalGeometryContext,
    FunctionalGeometryVerifierRegistry,
)
from app.services.geometry.requirement_compliance import evaluate_requirement_compliance
from app.services.mesh.inspect import MeshMetadata, _as_mesh
from app.services.printability.inspector import inspect_printability
from app.services.workflow.observability import WorkflowRecorder

DRAFT_RETENTION_DAYS = 14
ARCHIVED_RETENTION_DAYS = 60
AI_SOURCE_TYPES = frozenset({"ai_initial", "ai_revision", "ai_repair"})
OPEN_CANDIDATE_STATES = frozenset({"ready", "ready_with_warnings", "blocked"})
ACCEPTABLE_CANDIDATE_STATES = frozenset({"ready", "ready_with_warnings"})
OUTPUT_READY_STATES = frozenset({"ready", "ready_with_warnings", "blocked"})
PRINTABLE_OUTPUT_TYPES = frozenset(
    {"printable_component", "repeated_printable_component", "optional_printable_component"}
)
RETRYABLE_OUTPUT_ERRORS = frozenset({"cadquery_process", "cadquery_timeout", "worker_failure", "artifact_write"})
BLOCKING_RULE_IDS = frozenset(
    {
        "mesh.empty_or_zero_volume",
        "orientation.below_build_plate",
        "orientation.above_build_plate",
        "profile.build_volume",
    }
)
BLOCKING_CRITICAL_RULE_IDS = frozenset(
    {
        "feature.minimum_thickness",
        "feature.small_features_gaps_holes",
    }
)
REQUIREMENTS_PROMPT_VERSION = "requirements-v1"
DESIGN_SPEC_SCHEMA_VERSION = "1.0"
DESIGN_PLAN_PROMPT_VERSION = "design-plan-v6"
CADQUERY_GENERATION_PROMPT_VERSION = "cadquery-generation-v1"
CADQUERY_GEOMETRY_BODY_PROMPT_VERSION = "cadquery-geometry-body-v6"
CADQUERY_GEOMETRY_BODY_REPAIR_PROMPT_VERSION = "cadquery-geometry-body-repair-v6"
DESIGN_PLAN_SCHEMA_VERSION = "1.0"
REVISION_PLAN_PROMPT_VERSION = "revision-planning-v1"
CADQUERY_REVISION_PROMPT_VERSION = "cadquery-revision-v1"
REVISION_PLAN_SCHEMA_VERSION = "revision-plan-v1"
DEFAULT_REQUIREMENT_PROFILE = {
    "version": "volundr-defaults-v1",
    "units": "mm",
    "default_nozzle_diameter_mm": 0.4,
    "default_layer_height_mm": 0.2,
    "general_functional_wall_thickness_mm": 3.0,
    "minimum_preferred_functional_wall_thickness_mm": 1.6,
    "general_removable_fit_clearance_per_side_mm": [0.30, 0.50],
    "general_close_fit_clearance_per_side_mm": [0.15, 0.25],
    "default_small_edge_chamfer_mm": [0.5, 1.0],
    "supports_assumed_allowed": False,
}


class _StoppedWithRevision(Exception):
    def __init__(self, revision: RevisionRead) -> None:
        self.revision = revision


class ProjectService:
    def __init__(
        self,
        *,
        db: Session,
        data_dir: Path | None = None,
        cad_runner: Any | None = None,
        ai_provider: AiProvider | None = None,
    ) -> None:
        self.db = db
        self.data_dir = data_dir or settings.data_dir
        self.cad_runner = cad_runner or FilesystemCadWorkerRunner()
        self.ai_provider = ai_provider

    def create_project(self, payload: ProjectCreate) -> Project:
        project = Project(
            name=payload.name.strip(),
            slug=self._unique_slug(payload.name),
            original_intent=payload.original_intent.strip(),
        )
        self.db.add(project)
        self.db.flush()
        self._record_message(
            project_id=project.id,
            revision_id=None,
            role="user",
            content=project.original_intent,
        )
        self._record_message(
            project_id=project.id,
            revision_id=None,
            role="system_event",
            content="Project created",
        )
        self.db.commit()
        self.db.refresh(project)
        return project

    def create_draft_project(self) -> Project:
        self.cleanup_expired_drafts()
        draft_id = self._next_draft_id()
        project = Project(
            name=f"Draft {draft_id}",
            slug=self._unique_slug(f"draft-{draft_id}"),
            original_intent="",
            status="draft",
        )
        self.db.add(project)
        self.db.flush()
        self._record_message(
            project_id=project.id,
            revision_id=None,
            role="system_event",
            content="Draft workspace created",
        )
        self.db.commit()
        self.db.refresh(project)
        return project

    def save_project(self, project_id: str, payload: ProjectSave) -> Project | None:
        project = self.db.get(Project, project_id)
        if project is None:
            return None
        project.name = payload.name.strip()
        project.slug = self._unique_slug(project.name, exclude_project_id=project.id)
        project.original_intent = payload.original_intent.strip()
        if project.status == "draft":
            project.status = "active"
            self._record_message(
                project_id=project.id,
                revision_id=None,
                role="system_event",
                content="Draft workspace saved",
            )
        self.db.commit()
        self.db.refresh(project)
        return project

    def list_projects(self) -> list[Project]:
        self.cleanup_expired_projects()
        return list(
            self.db.scalars(
                select(Project)
                .where(Project.status == "active")
                .order_by(Project.created_at.desc())
            )
        )

    def list_project_library(self) -> list[ProjectLibraryRead]:
        projects = self.list_projects()
        results: list[ProjectLibraryRead] = []
        for project in projects:
            revisions = list(
                self.db.scalars(
                    select(Revision)
                    .where(Revision.project_id == project.id)
                    .order_by(Revision.revision_number.desc())
                )
            )
            latest = revisions[0] if revisions else None
            current = self.db.get(Revision, project.active_revision_id) if project.active_revision_id else None
            active_workflow = self.db.scalar(
                select(WorkflowRun)
                .where(WorkflowRun.project_id == project.id)
                .where(WorkflowRun.status == "running")
                .order_by(WorkflowRun.updated_at.desc())
            )
            count_revision = current or latest
            part_count = (
                int(
                    self.db.scalar(
                        select(func.count(RevisionOutput.id)).where(RevisionOutput.revision_id == count_revision.id)
                    )
                    or 0
                )
                if count_revision is not None
                else 0
            )
            warning_count = (
                int(
                    self.db.scalar(
                        select(func.count(ValidationFinding.id))
                        .where(ValidationFinding.revision_id == count_revision.id)
                        .where(ValidationFinding.is_blocking.is_(False))
                        .where(ValidationFinding.finding_state == "open")
                    )
                    or 0
                )
                if count_revision is not None
                else 0
            )
            results.append(
                ProjectLibraryRead(
                    **{
                        "id": project.id,
                        "name": project.name,
                        "slug": project.slug,
                        "original_intent": project.original_intent,
                        "status": project.status,
                        "active_revision_id": project.active_revision_id,
                        "created_at": project.created_at,
                        "updated_at": project.updated_at,
                        "archived_at": project.archived_at,
                        "latest_revision_id": latest.id if latest else None,
                        "active_workflow_status": active_workflow.status if active_workflow else None,
                        "printable_part_count": part_count,
                        "unresolved_warning_count": warning_count,
                        "preview_revision_id": (current or latest).id if (current or latest) else None,
                    },
                )
            )
        return results

    def cleanup_expired_projects(self) -> int:
        return self.cleanup_expired_drafts() + self.cleanup_expired_archived_projects()

    def cleanup_expired_drafts(self) -> int:
        cutoff = project_utcnow() - timedelta(days=DRAFT_RETENTION_DAYS)
        expired_drafts = list(
            self.db.scalars(
                select(Project).where(
                    Project.status == "draft",
                    Project.updated_at < cutoff,
                )
            )
        )
        expired_draft_ids = [project.id for project in expired_drafts]
        for project in expired_drafts:
            self._delete_project_records(project)
        if expired_drafts:
            self.db.commit()
            for project_id in expired_draft_ids:
                self._delete_project_files(project_id)
        return len(expired_drafts)

    def cleanup_expired_archived_projects(self) -> int:
        cutoff = project_utcnow() - timedelta(days=ARCHIVED_RETENTION_DAYS)
        expired_archived_projects = list(
            self.db.scalars(
                select(Project).where(
                    Project.status == "archived",
                    Project.archived_at.is_not(None),
                    Project.archived_at < cutoff,
                )
            )
        )
        expired_project_ids = [project.id for project in expired_archived_projects]
        for project in expired_archived_projects:
            self._delete_project_records(project)
        if expired_archived_projects:
            self.db.commit()
            for project_id in expired_project_ids:
                self._delete_project_files(project_id)
        return len(expired_archived_projects)

    def get_project(self, project_id: str) -> Project | None:
        return self.db.get(Project, project_id)

    def get_workspace(self, project_id: str) -> ProjectWorkspaceRead | None:
        project = self.db.get(Project, project_id)
        if project is None:
            return None

        WorkflowRecorder(db=self.db, data_dir=self.data_dir).classify_stale_runs(
            max_running_seconds=settings.workflow_stale_seconds,
        )
        messages = self.list_project_messages(project_id) or []
        revisions = self.list_revisions(project_id)
        active_workflow = self.db.scalar(
            select(WorkflowRun)
            .where(WorkflowRun.project_id == project_id)
            .where(WorkflowRun.status == "running")
            .order_by(WorkflowRun.updated_at.desc(), WorkflowRun.started_at.desc())
        )
        active_revision = self.db.get(Revision, project.active_revision_id) if project.active_revision_id else None
        required_paths: list[str] = []
        missing_paths: list[str] = []
        for revision in self.db.scalars(
            select(Revision)
            .where(Revision.project_id == project_id, Revision.status == "succeeded")
        ):
            for output in revision.outputs:
                for relative_path in (output.stl_path, output.step_path, output.brep_path):
                    if not relative_path:
                        continue
                    required_paths.append(relative_path)
                    if not (self.data_dir / relative_path).is_file():
                        missing_paths.append(relative_path)
        ledger = RequirementLedgerStore(self.db).load(project_id)
        return ProjectWorkspaceRead(
            project=project,
            messages=messages,
            revisions=revisions,
            active_requirements=active_requirements(ledger),
            current_working_revision_id=(
                active_revision.id
                if active_revision is not None and active_revision.is_accepted and active_revision.status == "succeeded"
                else None
            ),
            active_workflow=(
                {
                    "id": active_workflow.id,
                    "project_id": active_workflow.project_id,
                    "workflow_type": active_workflow.workflow_type,
                    "status": active_workflow.status,
                    "correlation_id": active_workflow.correlation_id,
                    "started_at": active_workflow.started_at,
                    "updated_at": active_workflow.updated_at,
                }
                if active_workflow is not None
                else None
            ),
            artifact_integrity={
                "checked_count": len(required_paths),
                "missing_count": len(missing_paths),
                "missing_paths": missing_paths,
                "status": "missing" if missing_paths else "ok",
            },
        )

    def get_active_revision(self, project_id: str) -> RevisionRead | None:
        project = self.db.get(Project, project_id)
        if project is None or project.active_revision_id is None:
            return None
        revision = self.db.get(Revision, project.active_revision_id)
        if revision is None or revision.review_state != "accepted":
            return None
        return self._revision_read(revision)

    def list_project_messages(self, project_id: str) -> list[ProjectMessageRead] | None:
        if self.db.get(Project, project_id) is None:
            return None
        messages = self.db.scalars(
            select(ProjectMessage)
            .where(ProjectMessage.project_id == project_id)
            .order_by(ProjectMessage.created_at.asc())
        )
        return [ProjectMessageRead.model_validate(message) for message in messages]

    def update_project(self, project_id: str, payload: ProjectUpdate) -> Project | None:
        project = self.db.get(Project, project_id)
        if project is None:
            return None
        if payload.name is not None:
            next_name = payload.name.strip()
            if next_name != project.name:
                project.name = next_name
                project.slug = self._unique_slug(next_name, exclude_project_id=project.id)
        if payload.original_intent is not None:
            project.original_intent = payload.original_intent.strip()
        self.db.commit()
        self.db.refresh(project)
        return project

    def archive_project(self, project_id: str) -> Project | None:
        project = self.db.get(Project, project_id)
        if project is None:
            return None
        project.status = "archived"
        project.archived_at = project_utcnow()
        self._record_message(
            project_id=project.id,
            revision_id=None,
            role="system_event",
            content="Project archived",
        )
        self.db.commit()
        self.db.refresh(project)
        return project

    def delete_project(self, project_id: str) -> bool:
        project = self.db.get(Project, project_id)
        if project is None:
            return False
        deleted_project_id = project.id
        workflow_run_ids = list(
            self.db.scalars(select(WorkflowRun.id).where(WorkflowRun.project_id == deleted_project_id))
        )
        self._delete_project_records(project)
        self.db.commit()
        self._delete_project_files(deleted_project_id)
        self._delete_workflow_debug_bundles(workflow_run_ids)
        return True

    def list_revisions(self, project_id: str) -> list[RevisionRead]:
        revisions = self.db.scalars(
            select(Revision)
            .where(Revision.project_id == project_id)
            .order_by(Revision.revision_number.asc())
        )
        return [self._revision_read(revision) for revision in revisions]

    def list_candidates(self, project_id: str) -> list[RevisionRead] | None:
        if self.db.get(Project, project_id) is None:
            return None
        revisions = self.db.scalars(
            select(Revision)
            .where(
                Revision.project_id == project_id,
                Revision.status == "succeeded",
                Revision.review_state.in_(OPEN_CANDIDATE_STATES),
            )
            .order_by(Revision.revision_number.asc())
        )
        return [self._revision_read(revision) for revision in revisions]

    def get_candidate(self, revision_id: str) -> RevisionRead | None:
        revision = self.db.get(Revision, revision_id)
        if revision is None or revision.review_state not in OPEN_CANDIDATE_STATES:
            return None
        return self._revision_read(revision)

    def list_validation_findings(self, revision_id: str) -> list[ValidationFindingRead] | None:
        if self.db.get(Revision, revision_id) is None:
            return None
        findings = self.db.scalars(
            select(ValidationFinding)
            .where(ValidationFinding.revision_id == revision_id)
            .order_by(ValidationFinding.created_at.asc(), ValidationFinding.rule_id.asc())
        )
        return [ValidationFindingRead.model_validate(finding) for finding in findings]

    def list_revision_outputs(self, revision_id: str) -> list[RevisionOutputRead] | None:
        revision = self.db.get(Revision, revision_id)
        if revision is None:
            return None
        outputs = list(
            self.db.scalars(
                select(RevisionOutput)
                .where(RevisionOutput.revision_id == revision_id)
                .order_by(RevisionOutput.created_at.asc(), RevisionOutput.output_id.asc())
            )
        )
        return [self._revision_output_read(output) for output in outputs]

    def get_revision_output(self, output_artifact_id: str) -> RevisionOutputRead | None:
        output = self.db.get(RevisionOutput, output_artifact_id)
        if output is None:
            return None
        return self._revision_output_read(output)

    def list_revision_output_findings(
        self,
        output_artifact_id: str,
    ) -> list[ValidationFindingRead] | None:
        if self.db.get(RevisionOutput, output_artifact_id) is None:
            return None
        findings = self.db.scalars(
            select(ValidationFinding)
            .where(ValidationFinding.revision_output_id == output_artifact_id)
            .order_by(ValidationFinding.created_at.asc(), ValidationFinding.rule_id.asc())
        )
        return [ValidationFindingRead.model_validate(finding) for finding in findings]

    def list_generation_attempt_findings(
        self,
        attempt_id: str,
    ) -> list[ValidationFindingRead] | None:
        if self.db.get(GenerationAttempt, attempt_id) is None:
            return None
        findings = self.db.scalars(
            select(ValidationFinding)
            .where(ValidationFinding.generation_attempt_id == attempt_id)
            .order_by(ValidationFinding.created_at.asc(), ValidationFinding.rule_id.asc())
        )
        return [ValidationFindingRead.model_validate(finding) for finding in findings]

    def get_geometric_analysis(self, revision_id: str) -> GeometricAnalysisRead | None:
        result = self.db.scalar(
            select(GeometricAnalysisResult)
            .where(GeometricAnalysisResult.revision_id == revision_id)
            .order_by(GeometricAnalysisResult.created_at.desc())
        )
        if result is None:
            return None
        result_path = self.data_dir / result.result_path
        if not result_path.exists():
            return None
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        return GeometricAnalysisRead(
            id=result.id,
            revision_id=result.revision_id,
            revision_output_id=result.revision_output_id,
            design_specification_id=result.design_specification_id,
            analysis_version=result.analysis_version,
            tolerance_profile_version=result.tolerance_profile_version,
            mesh_hash=result.mesh_hash,
            source_hash=result.source_hash,
            analysis_ms=result.analysis_ms,
            created_at=result.created_at,
            findings=[
                GeometricFindingRead.model_validate(finding)
                for finding in payload.get("findings", [])
            ],
        )

    def get_revision_output_geometric_analysis(
        self,
        output_artifact_id: str,
    ) -> GeometricAnalysisRead | None:
        result = self.db.scalar(
            select(GeometricAnalysisResult)
            .where(GeometricAnalysisResult.revision_output_id == output_artifact_id)
            .order_by(GeometricAnalysisResult.created_at.desc())
        )
        if result is None:
            return None
        result_path = self.data_dir / result.result_path
        if not result_path.exists():
            return None
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        return GeometricAnalysisRead(
            id=result.id,
            revision_id=result.revision_id,
            revision_output_id=result.revision_output_id,
            design_specification_id=result.design_specification_id,
            analysis_version=result.analysis_version,
            tolerance_profile_version=result.tolerance_profile_version,
            mesh_hash=result.mesh_hash,
            source_hash=result.source_hash,
            analysis_ms=result.analysis_ms,
            created_at=result.created_at,
            findings=[
                GeometricFindingRead.model_validate(finding)
                for finding in payload.get("findings", [])
            ],
        )

    def accept_candidate(self, revision_id: str) -> RevisionRead | None:
        revision = self.db.get(Revision, revision_id)
        if revision is None:
            return None
        if revision.review_state not in ACCEPTABLE_CANDIDATE_STATES:
            raise ValueError("candidate state does not permit acceptance")
        if revision.cad_backend == "cadquery" and revision.design_plan_id is not None:
            self._require_revision_base_ready(revision, purpose="candidate acceptance")
        if self._has_blocking_findings(revision.id):
            raise ValueError("candidate has unresolved blocking validation findings")
        project = self.db.get(Project, revision.project_id)
        if project is None:
            return None
        parent_run = self._workflow_run_for_revision(revision.id)
        workflow_run = self._start_child_workflow_run(
            project_id=project.id,
            workflow_type="candidate_acceptance",
            parent=parent_run,
        )
        now = project_utcnow()
        revision.review_state = "accepted"
        revision.is_accepted = True
        revision.accepted_at = now
        project.active_revision_id = revision.id
        self._record_message(
            project_id=project.id,
            revision_id=revision.id,
            role="system_event",
            content=f"Accepted R{revision.revision_number}",
        )
        self._record_workflow_event(
            workflow_run,
            stage="acceptance",
            event_type="candidate.accepted",
            severity="summary",
            message=f"Accepted R{revision.revision_number}.",
            deduplication_key=f"candidate-accepted-{revision.id}",
            revision_id=revision.id,
        )
        self._workflow_recorder().complete_run(workflow_run, status="completed")
        if parent_run is not None:
            self._workflow_recorder().complete_run(parent_run, status="completed")
        self.db.commit()
        self.db.refresh(revision)
        return self._revision_read(revision)

    def _cadquery_runner(self) -> Any:
        return self.cad_runner

    def _workflow_recorder(self) -> WorkflowRecorder:
        return WorkflowRecorder(db=self.db, data_dir=self.data_dir)

    def _latest_root_workflow_run(self, project_id: str) -> WorkflowRun | None:
        return self.db.scalar(
            select(WorkflowRun)
            .where(WorkflowRun.project_id == project_id)
            .where(WorkflowRun.root_workflow_run_id == WorkflowRun.id)
            .where(WorkflowRun.status == "running")
            .order_by(WorkflowRun.started_at.desc())
        )

    def _workflow_run_for_revision(self, revision_id: str) -> WorkflowRun | None:
        matched_run = self.db.scalar(
            select(WorkflowRun)
            .join(WorkflowEvent, WorkflowEvent.workflow_run_id == WorkflowRun.id)
            .where(WorkflowEvent.revision_id == revision_id)
            .order_by(WorkflowRun.started_at.asc())
        )
        if matched_run is None:
            return None
        return self.db.get(WorkflowRun, matched_run.root_workflow_run_id or matched_run.id)

    def _workflow_run_for_revision_plan(self, revision_plan_id: str) -> WorkflowRun | None:
        matched_run = self.db.scalar(
            select(WorkflowRun)
            .join(WorkflowEvent, WorkflowEvent.workflow_run_id == WorkflowRun.id)
            .where(WorkflowEvent.revision_plan_id == revision_plan_id)
            .order_by(WorkflowRun.started_at.asc())
        )
        return matched_run

    def _ensure_initial_workflow_run(self, project: Project) -> WorkflowRun:
        existing = self._latest_root_workflow_run(project.id)
        if existing is not None:
            return existing
        return self._workflow_recorder().start_run(
            project_id=project.id,
            workflow_type="initial_generation",
            logging_mode="standard",
            provider=self._provider_name(),
            model=self._provider_model(),
            prompt_versions={
                "requirements": self._requirement_prompt_template_version(),
                "design_plan": self._design_plan_prompt_template_version(),
                "cadquery": self._provider_cadquery_prompt_template_version(),
                "revision_plan": self._revision_plan_prompt_template_version(),
            },
            application_commit=self._application_commit(),
            worker_version="cad-worker-v1",
        )

    def _start_child_workflow_run(
        self,
        *,
        project_id: str,
        workflow_type: str,
        parent: WorkflowRun | None = None,
    ) -> WorkflowRun:
        parent_run = parent or self._latest_root_workflow_run(project_id)
        return self._workflow_recorder().start_run(
            project_id=project_id,
            workflow_type=workflow_type,
            parent_workflow_run_id=parent_run.id if parent_run is not None else None,
            logging_mode=parent_run.logging_mode if parent_run is not None else "standard",
            provider=self._provider_name(),
            model=self._provider_model(),
            prompt_versions=json.loads(parent_run.prompt_versions_json)
            if parent_run is not None
            else {},
            application_commit=parent_run.application_commit if parent_run is not None else self._application_commit(),
            worker_version=parent_run.worker_version if parent_run is not None else "cad-worker-v1",
        )

    def _complete_workflow_lineage(self, workflow_run: WorkflowRun, *, status: str) -> None:
        recorder = self._workflow_recorder()
        recorder.complete_run(workflow_run, status=status)
        root_id = workflow_run.root_workflow_run_id or workflow_run.id
        if root_id == workflow_run.id:
            return
        root = self.db.get(WorkflowRun, root_id)
        if root is not None and root.status == "running":
            recorder.complete_run(root, status=status)

    def _record_workflow_event(
        self,
        workflow_run: WorkflowRun | None,
        *,
        stage: str,
        event_type: str,
        severity: str = "standard",
        message: str,
        blocking: bool = False,
        rule_id: str | None = None,
        deduplication_key: str | None = None,
        caused_by_event_id: str | None = None,
        is_root_failure: bool = False,
        is_downstream_symptom: bool = False,
        entity_type: str | None = None,
        entity_id: str | None = None,
        expected: Any = None,
        detected: Any = None,
        generation_attempt_id: str | None = None,
        design_specification_id: str | None = None,
        design_plan_id: str | None = None,
        revision_id: str | None = None,
        revision_output_id: str | None = None,
        revision_plan_id: str | None = None,
        configuration_change_id: str | None = None,
        worker_job_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        if workflow_run is None:
            return None
        return self._workflow_recorder().record_event(
            workflow_run,
            stage=stage,
            event_type=event_type,
            severity=severity,
            message=message,
            blocking=blocking,
            rule_id=rule_id,
            deduplication_key=deduplication_key,
            caused_by_event_id=caused_by_event_id,
            is_root_failure=is_root_failure,
            is_downstream_symptom=is_downstream_symptom,
            entity_type=entity_type,
            entity_id=entity_id,
            expected=expected,
            detected=detected,
            generation_attempt_id=generation_attempt_id,
            design_specification_id=design_specification_id,
            design_plan_id=design_plan_id,
            revision_id=revision_id,
            revision_output_id=revision_output_id,
            revision_plan_id=revision_plan_id,
            configuration_change_id=configuration_change_id,
            worker_job_id=worker_job_id,
            metadata=metadata,
        )

    def _record_workflow_artifact(
        self,
        workflow_run: WorkflowRun | None,
        *,
        stage: str,
        artifact_type: str,
        role: str,
        relative_path: str | None,
        redacted: bool = False,
        supersedes_artifact_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        if workflow_run is None or not relative_path:
            return None
        return self._workflow_recorder().record_artifact(
            workflow_run,
            stage=stage,
            artifact_type=artifact_type,
            role=role,
            path=self.data_dir / relative_path,
            redacted=redacted,
            supersedes_artifact_id=supersedes_artifact_id,
            metadata=metadata,
        )

    def _design_plan_parameter_values(self, design_plan_payload: dict[str, Any]) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for parameter in design_plan_payload.get("parameters", []):
            if not isinstance(parameter, dict):
                continue
            parameter_id = str(parameter.get("id") or "").strip()
            if parameter_id:
                values[parameter_id] = parameter.get("value")
        return values

    def _optional_int(self, value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _optional_bool(self, value: Any) -> bool | None:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes"}:
                return True
            if normalized in {"false", "0", "no"}:
                return False
            return None
        if isinstance(value, (int, float)):
            return bool(value)
        return None

    def _apply_topology_metadata_fields(
        self,
        output: RevisionOutput,
        topology_metadata: dict[str, Any] | None,
    ) -> None:
        if topology_metadata is None:
            return
        expected_solid_count = self._optional_int(topology_metadata.get("expected_solid_count"))
        detected_solid_count = self._optional_int(topology_metadata.get("detected_solid_count"))
        allow_disconnected_solids = self._optional_bool(
            topology_metadata.get("allow_disconnected_solids")
        )
        if expected_solid_count is not None:
            output.expected_solid_count = expected_solid_count
        if detected_solid_count is not None:
            output.detected_solid_count = detected_solid_count
        if allow_disconnected_solids is not None:
            output.allow_disconnected_solids = allow_disconnected_solids

    def _persist_cadquery_output_artifacts(
        self,
        *,
        revision: Revision,
        output: RevisionOutput,
        output_result: Any,
        source: str,
        stl_dir: Path,
        step_dir: Path,
        brep_dir: Path,
        metadata_dir: Path,
        design_specification_payload: dict[str, Any] | None,
        design_specification_id: str | None,
    ) -> None:
        output.execution_state = "validating"
        stl_path = stl_dir / output.filename
        shutil.copyfile(output_result.stl_path, stl_path)
        output.stl_path = self._relative(stl_path)
        output.stl_hash = self._file_sha256(stl_path)
        if output_result.step_path is not None:
            step_path = step_dir / f"{Path(output.filename).stem}.step"
            shutil.copyfile(output_result.step_path, step_path)
            output.step_path = self._relative(step_path)
            output.step_hash = self._file_sha256(step_path)
        if output_result.brep_path is not None:
            brep_path = brep_dir / f"{Path(output.filename).stem}.brep"
            shutil.copyfile(output_result.brep_path, brep_path)
            output.brep_path = self._relative(brep_path)
            output.brep_hash = self._file_sha256(brep_path)
        if output_result.topology_metadata is not None:
            output.topology_metadata_json = json.dumps(
                output_result.topology_metadata,
                sort_keys=True,
            )
            self._apply_topology_metadata_fields(output, output_result.topology_metadata)
        if output_result.metadata is not None:
            metadata_path = metadata_dir / f"{self._safe_stem(output.output_id)}.metadata.json"
            metadata_path.write_text(
                json.dumps(asdict(output_result.metadata), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            mesh_metadata_json = json.dumps(asdict(output_result.metadata), sort_keys=True)
            output.mesh_metadata_json = mesh_metadata_json
            output.metadata_json = mesh_metadata_json
            self._persist_geometric_analysis(
                revision=revision,
                stl_path=stl_path,
                source=source,
                design_specification_payload=design_specification_payload,
                design_specification_id=design_specification_id,
                revision_output=output,
            )
            self._persist_validation_findings(revision=revision, stl_path=stl_path, revision_output=output)
        output.compile_error = output_result.compile_error
        output.execution_state = self._derive_execution_state(output.id)
        output.validation_summary_json = json.dumps(
            self._validation_summary(output.revision_id, revision_output_id=output.id).model_dump()
        )
        output.updated_at = project_utcnow()

    def _persist_assembly_output_findings(self, revision: Revision) -> None:
        outputs = list(
            self.db.scalars(
                select(RevisionOutput)
                .where(RevisionOutput.revision_id == revision.id)
                .order_by(RevisionOutput.created_at.asc(), RevisionOutput.output_id.asc())
            )
        )
        output_ids = [output.output_id for output in outputs]
        if len(output_ids) != len(set(output_ids)):
            self.db.add(
                self._assembly_finding(
                    revision.id,
                    rule_id="assembly.duplicate_output_id",
                    severity="critical",
                    blocking=True,
                    title="Duplicate printable output ID",
                    explanation="The Design Plan produced duplicate printable output IDs.",
                    suggested_correction="Regenerate the Design Plan with unique output IDs.",
                )
            )
        for output in outputs:
            if output.required and output.execution_state == "failed":
                self.db.add(
                    self._assembly_finding(
                        revision.id,
                        rule_id="assembly.required_output_failed",
                        severity="critical",
                        blocking=True,
                        title=f"Required output failed: {output.label}",
                        explanation="A required printable output did not compile successfully.",
                        suggested_correction="Retry the output if the failure is transient, or create a new generation/revision.",
                        detected_value=output.output_id,
                    )
                )
            elif not output.required and output.execution_state == "failed":
                self.db.add(
                    self._assembly_finding(
                        revision.id,
                        rule_id="assembly.optional_output_failed",
                        severity="warning",
                        blocking=False,
                        title=f"Optional output failed: {output.label}",
                        explanation="An optional printable output did not compile successfully.",
                        suggested_correction="Retry the output if needed, or continue without this optional artifact.",
                        detected_value=output.output_id,
                    )
                )
        self.db.flush()

    def _assembly_finding(
        self,
        revision_id: str,
        *,
        rule_id: str,
        severity: str,
        blocking: bool,
        title: str,
        explanation: str,
        suggested_correction: str,
        detected_value: str | None = None,
    ) -> ValidationFinding:
        return ValidationFinding(
            revision_id=revision_id,
            rule_id=rule_id,
            category="assembly",
            severity=severity,
            is_blocking=blocking,
            title=title,
            explanation=explanation,
            suggested_correction=suggested_correction,
            detected_value=detected_value,
            unit=None,
            threshold_value=None,
            orientation_dependent=False,
            affected_geometry_summary=None,
            metadata_json=json.dumps({"finding_origin": "assembly_output"}),
        )

    def _refresh_revision_output_counts(self, revision: Revision) -> None:
        outputs = list(
            self.db.scalars(select(RevisionOutput).where(RevisionOutput.revision_id == revision.id))
        )
        revision.expected_output_count = len(outputs)
        revision.required_output_count = sum(1 for output in outputs if output.required)
        revision.successful_output_count = sum(1 for output in outputs if output.execution_state in OUTPUT_READY_STATES)
        revision.blocked_output_count = sum(1 for output in outputs if output.execution_state == "blocked")
        revision.failed_output_count = sum(1 for output in outputs if output.execution_state == "failed")
        self.db.flush()

    def _derive_execution_state(self, output_artifact_id: str) -> str:
        findings = list(
            self.db.scalars(
                select(ValidationFinding).where(
                    ValidationFinding.revision_output_id == output_artifact_id
                )
            )
        )
        if any(finding.is_blocking for finding in findings):
            return "blocked"
        if findings:
            return "ready_with_warnings"
        return "ready"

    def _first_successful_output_stl(self, revision: Revision) -> str | None:
        output = self.db.scalar(
            select(RevisionOutput)
            .where(
                RevisionOutput.revision_id == revision.id,
                RevisionOutput.execution_state.in_(OUTPUT_READY_STATES),
                RevisionOutput.stl_path.is_not(None),
            )
            .order_by(RevisionOutput.required.desc(), RevisionOutput.created_at.asc())
        )
        return output.stl_path if output is not None else None

    def _write_assembly_compile_log(self, revision: Revision, log_dir: Path) -> Path:
        path = log_dir.parent / "compile.log"
        outputs = list(
            self.db.scalars(
                select(RevisionOutput)
                .where(RevisionOutput.revision_id == revision.id)
                .order_by(RevisionOutput.created_at.asc(), RevisionOutput.output_id.asc())
            )
        )
        lines = ["Multi-output compilation summary"]
        for output in outputs:
            lines.append(f"{output.output_id}: {output.execution_state}")
            if output.compile_error:
                lines.append(output.compile_error)
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def _write_revision_execution_manifest(
        self,
        *,
        revision: Revision,
        source_hash: str,
        parameter_hash: str,
        parameter_values: dict[str, Any],
    ) -> Path:
        revision_dir = self._revision_dir(revision.project_id, revision.id)
        outputs = list(
            self.db.scalars(
                select(RevisionOutput)
                .where(RevisionOutput.revision_id == revision.id)
                .order_by(RevisionOutput.created_at.asc(), RevisionOutput.output_id.asc())
            )
        )
        payload = {
            "cad_backend": revision.cad_backend,
            "source_language": revision.source_language,
            "source_contract_version": revision.source_contract_version,
            "source_hash": source_hash,
            "parameter_hash": parameter_hash,
            "parameters": parameter_values,
            "requested_output_ids": [output.output_id for output in outputs],
            "output_ids": [
                output.output_id
                for output in outputs
                if output.execution_state in OUTPUT_READY_STATES
            ],
            "outputs": [
                {
                    "output_id": output.output_id,
                    "required": output.required,
                    "success": output.execution_state in OUTPUT_READY_STATES,
                    "topology_metadata": json.loads(output.topology_metadata_json)
                    if output.topology_metadata_json
                    else None,
                    "compile_error": output.compile_error,
                    "stl_hash": output.stl_hash,
                    "step_hash": output.step_hash,
                    "brep_hash": output.brep_hash,
                }
                for output in outputs
            ],
        }
        path = revision_dir / "execution-manifest.json"
        self._write_json(path, payload)
        return path

    def reject_candidate(self, revision_id: str) -> RevisionRead | None:
        revision = self.db.get(Revision, revision_id)
        if revision is None:
            return None
        if revision.review_state not in OPEN_CANDIDATE_STATES:
            raise ValueError("candidate state does not permit rejection")
        revision.review_state = "rejected"
        revision.is_accepted = False
        revision.rejected_at = project_utcnow()
        parent_run = self._workflow_run_for_revision(revision.id) or self._latest_root_workflow_run(
            revision.project_id
        )
        workflow_run = self._start_child_workflow_run(
            project_id=revision.project_id,
            workflow_type="candidate_rejection",
            parent=parent_run,
        )
        self._record_workflow_event(
            workflow_run,
            stage="rejection",
            event_type="candidate.rejected",
            severity="summary",
            message="Candidate revision rejected by user.",
            deduplication_key=f"candidate-rejected-{revision.id}",
            revision_id=revision.id,
        )
        self._record_message(
            project_id=revision.project_id,
            revision_id=revision.id,
            role="system_event",
            content=f"Rejected R{revision.revision_number}",
        )
        self.db.commit()
        self._workflow_recorder().complete_run(workflow_run, status="completed")
        if parent_run is not None:
            self._workflow_recorder().complete_run(parent_run, status="completed")
        self.db.refresh(revision)
        return self._revision_read(revision)

    def dismiss_validation_finding(
        self,
        finding_id: str,
        reason: str | None = None,
    ) -> ValidationFindingRead | None:
        finding = self.db.get(ValidationFinding, finding_id)
        if finding is None:
            return None
        if finding.is_blocking:
            raise ValueError("blocking validation findings cannot be dismissed")
        finding.finding_state = "dismissed"
        finding.dismissal_reason = reason.strip() if reason and reason.strip() else None
        finding.dismissed_at = project_utcnow()
        self.db.commit()
        self.db.refresh(finding)
        return ValidationFindingRead.model_validate(finding)

    async def extract_requirements(
        self,
        project_id: str,
        payload: RequirementExtractionCreate,
    ) -> DesignSpecificationRead | None:
        project = self.db.get(Project, project_id)
        if project is None:
            return None
        if self.ai_provider is None:
            raise RuntimeError("AI provider is not configured")
        workflow_run = self._ensure_initial_workflow_run(project)
        self._record_workflow_event(
            workflow_run,
            stage="project_request",
            event_type="project_request.submitted",
            severity="summary",
            message="Project request submitted for requirement extraction.",
            deduplication_key=f"project-request-{project.id}-{payload.user_instruction}",
        )
        inventory = build_explicit_requirement_inventory(payload.user_instruction)
        defaults = dict(DEFAULT_REQUIREMENT_PROFILE)
        defaults["explicit_requirements"] = {
            item["requirement_id"]: {
                "value": item["value"],
                "unit": item.get("unit"),
                "source": item["source"],
                "authority": item["authority"],
                "protected": item["protected"],
            }
            for item in inventory
        }
        request = RequirementExtractionRequest(
            project_name=project.name,
            original_intent=project.original_intent,
            user_instruction=payload.user_instruction,
            defaults=defaults,
        )
        previous_specification = self._latest_design_specification(project.id)
        result = await self._run_requirement_extraction(
            project=project,
            request=request,
            superseded_specification_id=previous_specification.id if previous_specification else None,
        )
        self._record_workflow_artifact(
            workflow_run,
            stage="requirement_extraction",
            artifact_type="raw_provider_response",
            role="requirement_raw_response",
            relative_path=result.raw_response_path,
        )
        self._record_workflow_artifact(
            workflow_run,
            stage="requirement_extraction",
            artifact_type="design_specification",
            role="design_specification_version",
            relative_path=result.specification_path,
        )
        self._record_workflow_event(
            workflow_run,
            stage="requirement_extraction",
            event_type="requirement_extraction.completed",
            severity="summary",
            message="Requirement extraction completed.",
            deduplication_key=f"requirement-extraction-completed-{project.id}",
        )
        return result

    def get_current_design_specification(self, project_id: str) -> DesignSpecificationRead | None:
        if self.db.get(Project, project_id) is None:
            return None
        specification = self._latest_design_specification(project_id)
        return self._design_specification_read(specification) if specification is not None else None

    def get_design_specification(self, specification_id: str) -> DesignSpecificationRead | None:
        specification = self.db.get(DesignSpecification, specification_id)
        return self._design_specification_read(specification) if specification is not None else None

    def get_design_plan(self, design_plan_id: str) -> DesignPlanRead | None:
        plan = self.db.get(DesignPlan, design_plan_id)
        return self._design_plan_read(plan) if plan is not None else None

    def get_current_design_plan(self, project_id: str) -> DesignPlanRead | None:
        if self.db.get(Project, project_id) is None:
            return None
        plan = self._latest_design_plan(project_id)
        return self._design_plan_read(plan) if plan is not None else None

    def list_configuration_parameters(self, project_id: str) -> list[ConfigurationParameterRead] | None:
        context = self._configuration_context(project_id)
        if context is None:
            return None
        _project, base_revision, _design_plan, design_plan_payload, source, _source_hash = context
        self._require_revision_base_ready(base_revision, purpose="configuration parameter review")
        metadata = self._configuration_source_metadata(
            source=source,
            design_plan_payload=design_plan_payload,
            cad_backend=base_revision.cad_backend,
            design_specification_payload=self._revision_design_specification_payload(base_revision),
        )
        return [
            self._configuration_parameter_read(parameter, design_plan_payload, metadata)
            for parameter in design_plan_payload.get("parameters", [])
        ]

    def list_configuration_presets(self, project_id: str) -> list[ConfigurationPresetRead] | None:
        context = self._configuration_context(project_id)
        if context is None:
            return None
        _project, _base_revision, design_plan, design_plan_payload, _source, _source_hash = context
        result: list[ConfigurationPresetRead] = []
        for preset in design_plan_payload.get("presets", []):
            if not isinstance(preset, dict) or not preset.get("id"):
                continue
            result.append(
                ConfigurationPresetRead(
                    id=str(preset.get("id")),
                    project_id=project_id,
                    design_plan_id=design_plan.id,
                    preset_id=str(preset.get("id")),
                    label=str(preset.get("label") or preset.get("id")),
                    parameter_values=dict(preset.get("parameter_values") or {}),
                    source="design_plan",
                    created_at=None,
                )
            )
        project_presets = list(
            self.db.scalars(
                select(ConfigurationPreset)
                .where(ConfigurationPreset.project_id == project_id)
                .where(ConfigurationPreset.design_plan_id == design_plan.id)
                .order_by(ConfigurationPreset.created_at.asc(), ConfigurationPreset.preset_id.asc())
            )
        )
        result.extend(self._configuration_preset_read(preset) for preset in project_presets)
        return result

    def create_configuration_preset(
        self,
        project_id: str,
        payload: ConfigurationPresetCreate,
    ) -> ConfigurationPresetRead | None:
        context = self._configuration_context(project_id)
        if context is None:
            return None
        _project, base_revision, design_plan, design_plan_payload, source, _source_hash = context
        self._require_revision_base_ready(base_revision, purpose="configuration preset")
        if payload.design_plan_id is not None and payload.design_plan_id != design_plan.id:
            raise ValueError("preset Design Plan does not match the active revision")
        validation = self._resolve_configuration(
            design_plan_payload=design_plan_payload,
            source=source,
            cad_backend=base_revision.cad_backend,
            selected_preset_id=None,
            requested_values=payload.parameter_values,
            user_overrides={},
        )
        if validation["validation_state"] != ConfigurationValidationState.CONFIGURATION_READY.value:
            raise ValueError("preset values are not a valid configuration")
        preset = ConfigurationPreset(
            project_id=project_id,
            design_plan_id=design_plan.id,
            preset_id=payload.preset_id,
            label=payload.label,
            parameter_values_json=json.dumps(payload.parameter_values, sort_keys=True),
        )
        self.db.add(preset)
        self.db.commit()
        self.db.refresh(preset)
        return self._configuration_preset_read(preset)

    def preview_configuration_change(
        self,
        project_id: str,
        payload: ConfigurationChangeCreate,
    ) -> ConfigurationChangeRead | None:
        context = self._configuration_context(project_id, base_revision_id=payload.base_revision_id)
        if context is None:
            return None
        _project, base_revision, design_plan, design_plan_payload, source, source_hash = context
        self._require_revision_base_ready(base_revision, purpose="configuration preview")
        resolution = self._resolve_configuration(
            design_plan_payload=design_plan_payload,
            source=source,
            cad_backend=base_revision.cad_backend,
            selected_preset_id=payload.selected_preset_id,
            requested_values=payload.parameter_values,
            user_overrides=payload.user_overrides,
            project_id=project_id,
            design_plan_id=design_plan.id,
        )
        change = self._persist_configuration_change(
            project_id=project_id,
            base_revision=base_revision,
            design_plan=design_plan,
            reason=payload.reason,
            selected_preset_id=payload.selected_preset_id,
            source_hash=source_hash,
            resolution=resolution,
        )
        self.db.commit()
        self.db.refresh(change)
        return self._configuration_change_read(change)

    def get_configuration_change(self, configuration_change_id: str) -> ConfigurationChangeRead | None:
        change = self.db.get(ConfigurationChange, configuration_change_id)
        return self._configuration_change_read(change) if change is not None else None

    def read_configuration_override_manifest(
        self,
        configuration_change_id: str,
    ) -> ConfigurationOverrideManifestRead | None:
        change = self.db.get(ConfigurationChange, configuration_change_id)
        if change is None:
            return None
        manifest = self._configuration_override_manifest(change)
        return ConfigurationOverrideManifestRead(**manifest)

    async def generate_from_configuration_change(
        self,
        configuration_change_id: str,
    ) -> RevisionRead | None:
        change = self.db.get(ConfigurationChange, configuration_change_id)
        if change is None:
            return None
        if change.validation_state != ConfigurationValidationState.CONFIGURATION_READY.value:
            raise ValueError("configuration is not ready for generation")
        if change.generated_revision_id is not None:
            existing = self.db.get(Revision, change.generated_revision_id)
            if existing is not None:
                return self._revision_read(existing)
        base_revision = self.db.get(Revision, change.base_revision_id)
        design_plan = self.db.get(DesignPlan, change.design_plan_id)
        if base_revision is None or design_plan is None:
            raise ValueError("configuration base revision or Design Plan is missing")
        self._require_revision_base_ready(base_revision, purpose="configuration generation")
        source_path = self.resolve_revision_source(base_revision.id)
        if source_path is None:
            raise ValueError("base revision source is missing")
        source = source_path.read_text(encoding="utf-8")
        source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        if change.base_source_hash and change.base_source_hash != source_hash:
            raise ValueError("base source hash changed; configuration cannot be reproduced")
        manifest = self._configuration_override_manifest(change)
        design_plan_payload = self._read_design_plan_payload(design_plan)
        if base_revision.cad_backend != "cadquery":
            raise ValueError("configuration generation requires a CadQuery base revision")
        workflow_run = self._start_child_workflow_run(
            project_id=change.project_id,
            workflow_type="configuration_change",
            parent=self._workflow_run_for_revision(base_revision.id),
        )
        self._record_workflow_event(
            workflow_run,
            stage="configuration_execution",
            event_type="configuration_execution.started",
            severity="summary",
            message="Configuration generation started.",
            deduplication_key=f"configuration-started-{change.id}",
            configuration_change_id=change.id,
            revision_id=base_revision.id,
            metadata={
                "provider_call_count": 0,
                "base_source_hash": source_hash,
                "parameter_hash": self._configuration_parameter_hash(manifest["parameter_values"]),
            },
        )
        revision = await self._create_cadquery_revision_from_planned_source(
            project_id=change.project_id,
            source=source,
            user_instruction=f"Configuration change {change.id}",
            source_type="configuration_change",
            raw_ai_output=None,
            design_specification_id=change.design_specification_id,
            design_specification_payload=self._configured_design_specification_payload(base_revision, change),
            design_plan_id=change.design_plan_id,
            design_plan_payload=design_plan_payload,
            source_validation_result_id=None,
            parameter_values=manifest["parameter_values"],
            parameter_overrides=manifest["parameter_values"],
            parent_revision_id=base_revision.id,
            configuration_change_id=change.id,
            workflow_run=workflow_run,
        )
        if revision is None:
            self._workflow_recorder().complete_run(workflow_run, status="failed")
            return None
        generated_revision = self.db.get(Revision, revision.id)
        if generated_revision is not None:
            revision_dir = self._revision_dir(generated_revision.project_id, generated_revision.id)
            config_path = revision_dir / "configuration.json"
            overrides_path = revision_dir / "parameter-overrides.json"
            self._write_configuration_json(config_path, self._configuration_change_payload(change))
            self._write_json(overrides_path, manifest)
            change.configuration_path = self._relative(config_path)
            change.override_manifest_path = self._relative(overrides_path)
            change.generated_revision_id = generated_revision.id
            change.approved_at = project_utcnow()
            generated_revision.configuration_change_id = change.id
            if change.configuration_path:
                self._write_configuration_json(
                    self.data_dir / change.configuration_path,
                    self._configuration_change_payload(change),
                )
            if change.override_manifest_path:
                self._write_json(self.data_dir / change.override_manifest_path, self._configuration_override_manifest(change))
            self._record_workflow_artifact(
                workflow_run,
                stage="configuration_execution",
                artifact_type="configuration_change",
                role="configuration_change_record",
                relative_path=change.configuration_path,
            )
            self._record_workflow_artifact(
                workflow_run,
                stage="configuration_execution",
                artifact_type="parameter_manifest",
                role="configuration_override_manifest",
                relative_path=change.override_manifest_path,
            )
            generated_revision.output_manifest_path = self._relative(
                self._write_output_manifest(generated_revision)
            )
            self._record_message(
                project_id=change.project_id,
                revision_id=generated_revision.id,
                role="system_event",
                content=f"Generated configuration candidate R{generated_revision.revision_number}",
            )
            self.db.commit()
            self.db.refresh(generated_revision)
            self._record_workflow_event(
                workflow_run,
                stage="configuration_execution",
                event_type="configuration_execution.completed",
                severity="summary" if generated_revision.status == "succeeded" else "error",
                blocking=generated_revision.status != "succeeded",
                rule_id="configuration_execution.failed"
                if generated_revision.status != "succeeded"
                else None,
                message="Configuration generation completed.",
                deduplication_key=f"configuration-completed-{change.id}",
                configuration_change_id=change.id,
                revision_id=generated_revision.id,
                metadata={"provider_call_count": 0, "status": generated_revision.status},
            )
            self._workflow_recorder().complete_run(
                workflow_run,
                status="completed" if generated_revision.status == "succeeded" else "failed",
            )
            return self._revision_read(generated_revision)
        return revision

    def get_revision_plan(self, revision_plan_id: str) -> RevisionPlanRead | None:
        plan = self.db.get(RevisionPlan, revision_plan_id)
        return self._revision_plan_read(plan) if plan is not None else None

    def get_current_revision_plan(self, project_id: str) -> RevisionPlanRead | None:
        if self.db.get(Project, project_id) is None:
            return None
        plan = self._latest_revision_plan(project_id)
        return self._revision_plan_read(plan) if plan is not None else None

    async def create_revision_plan(
        self,
        project_id: str,
        payload: RevisionPlanCreate,
    ) -> RevisionPlanRead | None:
        project = self.db.get(Project, project_id)
        if project is None:
            return None
        if self.ai_provider is None:
            raise RuntimeError("AI provider is not configured")
        base_revision_id = payload.base_revision_id or project.active_revision_id
        if base_revision_id is None:
            raise ValueError("base revision is required for revision planning")
        base_revision = self.db.get(Revision, base_revision_id)
        if base_revision is None or base_revision.project_id != project.id:
            raise ValueError("base revision not found for project")
        if base_revision.status != "succeeded":
            raise ValueError("base revision must be successful")
        if base_revision.cad_backend != "cadquery":
            raise ValueError("structured revision generation requires a CadQuery base revision")
        if base_revision.design_plan_id is None:
            raise ValueError("structured revision planning requires a Design Plan")
        design_plan = self.db.get(DesignPlan, base_revision.design_plan_id)
        if design_plan is None or design_plan.review_state != DesignPlanReviewState.APPROVED.value:
            raise ValueError("base revision must reference an approved Design Plan")
        self._require_revision_base_ready(base_revision, purpose="revision planning")
        design_plan_payload = self._read_design_plan_payload(design_plan)
        design_specification = (
            self.db.get(DesignSpecification, base_revision.design_specification_id)
            if base_revision.design_specification_id
            else None
        )
        design_specification_payload = (
            self._read_design_specification_payload(design_specification)
            if design_specification is not None
            else None
        )
        base_source = self.read_revision_source(base_revision.id)
        if base_source is None:
            raise ValueError("base revision source is missing")
        output_manifest = self.read_output_manifest(base_revision.id)
        selected_findings = self._selected_finding_payloads(
            project_id=project.id,
            revision_id=base_revision.id,
            finding_ids=payload.targeted_finding_ids,
        )
        ledger_store = RequirementLedgerStore(self.db)
        requirement_delta, physical_observation = requirement_delta_for_message(
            payload.user_instruction
        )
        ledger = ledger_store.load(project.id)
        if requirement_delta:
            ledger = ledger_store.apply_delta(
                project_id=project.id,
                changes=requirement_delta,
                originating_message=payload.user_instruction,
                observation=physical_observation,
            )
        active_requirement_items = active_requirements(ledger)
        source_metadata = self._revision_source_metadata(
            source=base_source,
            cad_backend=base_revision.cad_backend,
            design_specification_payload=design_specification_payload,
            design_plan_payload=design_plan_payload,
            source_type=base_revision.source_type,
        ).to_json()
        request = RevisionPlanRequest(
            project_name=project.name,
            original_intent=project.original_intent,
            user_instruction=payload.user_instruction,
            reason=payload.reason,
            base_revision_id=base_revision.id,
            design_specification=design_specification_payload,
            design_plan=design_plan_payload,
            product_parameters=list(design_plan_payload.get("parameters", [])),
            dependency_edges=list(design_plan_payload.get("dependency_edges", [])),
            components=list(design_plan_payload.get("components", [])),
            features=list(design_plan_payload.get("features", [])),
            printable_outputs=list(design_plan_payload.get("printable_outputs", [])),
            output_manifest=output_manifest,
            source_metadata=source_metadata,
            selected_findings=selected_findings,
            active_requirements=active_requirement_items,
            requirement_delta=requirement_delta,
        )
        superseded = self._latest_revision_plan(project.id, base_revision_id=base_revision.id)
        return await self._run_revision_planning(
            project=project,
            base_revision=base_revision,
            design_specification=design_specification,
            design_plan=design_plan,
            request=request,
            superseded_revision_plan_id=superseded.id if superseded else None,
        )

    def approve_revision_plan(self, revision_plan_id: str) -> RevisionPlanRead | None:
        plan = self.db.get(RevisionPlan, revision_plan_id)
        if plan is None:
            return None
        if plan.review_state != RevisionPlanReviewState.PENDING_REVIEW.value:
            raise ValueError("Only pending Revision Plans can be approved")
        if self._has_newer_revision_plan(plan):
            raise ValueError("Revision Plan has been superseded")
        plan.review_state = RevisionPlanReviewState.APPROVED.value
        plan.approved_at = project_utcnow()
        self._record_message(
            project_id=plan.project_id,
            revision_id=plan.base_revision_id,
            role="system_event",
            content=f"Revision Plan v{plan.version_number} approved",
        )
        workflow_run = self._workflow_run_for_revision_plan(plan.id)
        self._record_workflow_event(
            workflow_run,
            stage="revision_planning",
            event_type="revision_plan.approved",
            severity="summary",
            message="Revision Plan approved for source generation.",
            deduplication_key=f"revision-plan-approved-{plan.id}",
            revision_id=plan.base_revision_id,
            revision_plan_id=plan.id,
            design_plan_id=plan.base_design_plan_id,
            metadata={"review_state": plan.review_state},
        )
        self.db.commit()
        self.db.refresh(plan)
        return self._revision_plan_read(plan)

    def reject_revision_plan(self, revision_plan_id: str) -> RevisionPlanRead | None:
        plan = self.db.get(RevisionPlan, revision_plan_id)
        if plan is None:
            return None
        if plan.review_state not in {
            RevisionPlanReviewState.PENDING_REVIEW.value,
            RevisionPlanReviewState.CLARIFICATION_REQUIRED.value,
        }:
            raise ValueError("Only pending or clarification Revision Plans can be rejected")
        plan.review_state = RevisionPlanReviewState.REJECTED.value
        plan.rejected_at = project_utcnow()
        self._record_message(
            project_id=plan.project_id,
            revision_id=plan.base_revision_id,
            role="system_event",
            content=f"Revision Plan v{plan.version_number} rejected",
        )
        self.db.commit()
        self.db.refresh(plan)
        return self._revision_plan_read(plan)

    def list_revision_plan_clarification_questions(
        self,
        revision_plan_id: str,
    ) -> list[RevisionPlanClarificationQuestionRead] | None:
        if self.db.get(RevisionPlan, revision_plan_id) is None:
            return None
        questions = self.db.scalars(
            select(RevisionPlanClarificationQuestion)
            .where(RevisionPlanClarificationQuestion.revision_plan_id == revision_plan_id)
            .order_by(RevisionPlanClarificationQuestion.display_order.asc())
        )
        return [RevisionPlanClarificationQuestionRead.model_validate(question) for question in questions]

    async def submit_revision_plan_clarification_answers(
        self,
        revision_plan_id: str,
        payload: ClarificationAnswersCreate,
    ) -> RevisionPlanRead | None:
        plan = self.db.get(RevisionPlan, revision_plan_id)
        if plan is None:
            return None
        if self.ai_provider is None:
            raise RuntimeError("AI provider is not configured")
        project = self.db.get(Project, plan.project_id)
        base_revision = self.db.get(Revision, plan.base_revision_id)
        design_plan = self.db.get(DesignPlan, plan.base_design_plan_id) if plan.base_design_plan_id else None
        design_specification = (
            self.db.get(DesignSpecification, plan.base_design_specification_id)
            if plan.base_design_specification_id
            else None
        )
        if project is None or base_revision is None or design_plan is None:
            raise ValueError("Revision Plan context is incomplete")
        self._require_revision_base_ready(base_revision, purpose="revision planning")
        previous_payload = self._read_revision_plan_payload(plan)
        answers: list[dict[str, Any]] = []
        questions_context: list[dict[str, Any]] = []
        for answer_payload in payload.answers:
            question = self.db.get(RevisionPlanClarificationQuestion, answer_payload.question_id)
            if question is None or question.revision_plan_id != plan.id:
                raise ValueError("clarification question not found for Revision Plan")
            answer = RevisionPlanClarificationAnswer(
                project_id=plan.project_id,
                revision_plan_id=plan.id,
                question_id=question.id,
                related_requirement_id=question.requirement_id,
                question_text=question.question,
                answer=answer_payload.answer.strip(),
            )
            self.db.add(answer)
            answers.append(
                {
                    "question_id": question.id,
                    "related_requirement_id": question.requirement_id,
                    "question": question.question,
                    "answer": answer.answer,
                }
            )
            questions_context.append(
                {
                    "id": question.id,
                    "question": question.question,
                    "reason": question.reason,
                    "related_requirement_id": question.requirement_id,
                }
            )
        self.db.commit()
        design_plan_payload = self._read_design_plan_payload(design_plan)
        design_specification_payload = (
            self._read_design_specification_payload(design_specification)
            if design_specification is not None
            else None
        )
        base_source = self.read_revision_source(base_revision.id) or ""
        source_metadata = self._cadquery_revision_source_metadata(
            base_source,
            design_plan_payload,
        ).to_json()
        ledger = RequirementLedgerStore(self.db).load(project.id)
        request = RevisionPlanRequest(
            project_name=project.name,
            original_intent=project.original_intent,
            user_instruction=plan.user_instruction,
            reason=plan.reason,
            base_revision_id=base_revision.id,
            design_specification=design_specification_payload,
            design_plan=design_plan_payload,
            product_parameters=list(design_plan_payload.get("parameters", [])),
            dependency_edges=list(design_plan_payload.get("dependency_edges", [])),
            components=list(design_plan_payload.get("components", [])),
            features=list(design_plan_payload.get("features", [])),
            printable_outputs=list(design_plan_payload.get("printable_outputs", [])),
            output_manifest=self.read_output_manifest(base_revision.id),
            source_metadata=source_metadata,
            clarification_questions=questions_context,
            clarification_answers=answers,
            previous_revision_plan=previous_payload,
            active_requirements=active_requirements(ledger),
            requirement_delta=list(previous_payload.get("requirement_delta", [])),
        )
        return await self._run_revision_planning(
            project=project,
            base_revision=base_revision,
            design_specification=design_specification,
            design_plan=design_plan,
            request=request,
            superseded_revision_plan_id=plan.id,
        )

    async def generate_from_revision_plan(self, revision_plan_id: str) -> RevisionRead | None:
        plan = self.db.get(RevisionPlan, revision_plan_id)
        if plan is None:
            return None
        if plan.review_state != RevisionPlanReviewState.APPROVED.value:
            raise ValueError("Revision Plan must be approved before source revision")
        if self._has_newer_revision_plan(plan):
            raise ValueError("Revision Plan has been superseded")
        if plan.generated_revision_id is not None:
            raise ValueError("Revision Plan has already generated a candidate")
        if self.ai_provider is None:
            raise RuntimeError("AI provider is not configured")
        project = self.db.get(Project, plan.project_id)
        base_revision = self.db.get(Revision, plan.base_revision_id)
        design_plan = self.db.get(DesignPlan, plan.revised_design_plan_id or plan.base_design_plan_id)
        design_specification = (
            self.db.get(
                DesignSpecification,
                plan.revised_design_specification_id or plan.base_design_specification_id,
            )
            if (plan.revised_design_specification_id or plan.base_design_specification_id)
            else None
        )
        if project is None or base_revision is None or design_plan is None:
            raise ValueError("Revision Plan context is incomplete")
        self._require_revision_base_ready(base_revision, purpose="component revision generation")
        base_source = self.read_revision_source(base_revision.id)
        if base_source is None:
            raise ValueError("base revision source is missing")
        revision_plan_payload = self._read_revision_plan_payload(plan)
        design_plan_payload = self._read_design_plan_payload(design_plan)
        design_specification_payload = (
            self._read_design_specification_payload(design_specification)
            if design_specification is not None
            else None
        )
        configuration_context: dict[str, Any] | None = None
        cadquery_parameter_values: dict[str, Any] | None = None
        configuration_change_id: str | None = None
        if base_revision.configuration_change_id is not None:
            change = self.db.get(ConfigurationChange, base_revision.configuration_change_id)
            if change is not None:
                configuration_change_id = change.id
                override_manifest = self._configuration_override_manifest(change)
                configuration_context = {
                    "configuration_change": self._configuration_change_payload(change),
                    "override_manifest": override_manifest,
                }
                cadquery_parameter_values = dict(override_manifest.get("parameter_values") or {})
        selected_findings = self._selected_finding_payloads(
            project_id=project.id,
            revision_id=base_revision.id,
            finding_ids=revision_plan_payload.get("targeted_findings", []),
        )
        base_source_metadata = self._revision_source_metadata(
            source=base_source,
            cad_backend=base_revision.cad_backend,
            design_specification_payload=design_specification_payload,
            design_plan_payload=design_plan_payload,
            source_type="ai_revision",
        ).to_json()
        scoped_revision_context = self._component_revision_scope_context(
            revision_plan_payload=revision_plan_payload,
            design_plan_payload=design_plan_payload,
            source_metadata=base_source_metadata,
            output_manifest=self.read_output_manifest(base_revision.id),
            selected_findings=selected_findings,
            configuration_context=configuration_context,
        )
        parent_workflow_run = self._workflow_run_for_revision_plan(plan.id)
        workflow_run = self._start_child_workflow_run(
            project_id=project.id,
            workflow_type="component_revision",
            parent=parent_workflow_run,
        )
        self._record_workflow_event(
            workflow_run,
            stage="component_revision",
            event_type="component_revision.started",
            severity="summary",
            message="Component-targeted revision generation started.",
            deduplication_key=f"component-revision-started-{plan.id}",
            revision_plan_id=plan.id,
            revision_id=base_revision.id,
            metadata={"base_revision_id": base_revision.id},
        )
        generation_request = self._generation_request(
            project=project,
            payload=GenerationCreate(
                user_instruction=plan.user_instruction,
                design_specification_id=design_specification.id if design_specification else None,
            ),
            current_source=base_source,
            design_specification=design_specification_payload,
            design_plan=design_plan_payload,
            revision_plan=revision_plan_payload,
            output_manifest=self.read_output_manifest(base_revision.id),
            selected_findings=selected_findings,
            source_metadata=base_source_metadata,
            scoped_revision_context=scoped_revision_context,
            configuration_context=configuration_context,
            active_requirement_items=active_requirements(
                RequirementLedgerStore(self.db).load(project.id)
            ),
            requirement_delta=list(revision_plan_payload.get("requirement_delta", [])),
        )
        generation_attempt = self._start_generation_attempt(
            project=project,
            request=generation_request,
            base_revision_id=base_revision.id,
            design_specification_payload=design_specification_payload,
            design_plan_payload=design_plan_payload,
        )
        self._record_workflow_event(
            workflow_run,
            stage="source_generation",
            event_type="provider.request_prepared",
            severity="summary",
            message="Revision source provider request prepared.",
            deduplication_key=f"revision-provider-request-{generation_attempt.id}",
            generation_attempt_id=generation_attempt.id,
            revision_plan_id=plan.id,
        )
        try:
            generation_result = await self._generate_source_model(generation_request)
        except asyncio.CancelledError:
            self._finish_provider_cancelled_attempt(generation_attempt)
            self._workflow_recorder().complete_run(workflow_run, status="cancelled")
            raise
        except RuntimeError as exc:
            self._finish_generation_attempt(
                generation_attempt,
                status="failed",
                failure_class=self._provider_failure_class(str(exc)),
                error_message=str(exc),
            )
            self._workflow_recorder().complete_run(workflow_run, status="failed")
            raise

        self._record_generation_result(generation_attempt, generation_result)
        self._record_workflow_artifact(
            workflow_run,
            stage="source_generation",
            artifact_type="raw_provider_response",
            role="raw_revision_source_response",
            relative_path=generation_attempt.raw_output_path,
            redacted=generation_attempt.raw_output_path is None,
        )
        try:
            revised_source = self._prepare_generated_source(
                raw_output=generation_result.raw_output,
                design_plan_payload=design_plan_payload,
                generation_contract_version=generation_request.generation_contract_version,
                attempt=generation_attempt,
                workflow_run=workflow_run,
                role="component_revision_geometry",
            )
        except (SourceExtractionError, ScaffoldSourceError) as exc:
            if isinstance(exc, GeometryBodyError):
                self._record_workflow_event(
                    workflow_run,
                    stage="source_extraction",
                    event_type="geometry_body.failed",
                    severity="error",
                    blocking=True,
                    rule_id=exc.rule_id,
                    message=str(exc),
                    deduplication_key=f"geometry-body-failed-{generation_attempt.id}",
                    generation_attempt_id=generation_attempt.id,
                    revision_plan_id=plan.id,
                    metadata=exc.details,
                )
            self._finish_generation_attempt(
                generation_attempt,
                status="failed",
                failure_class=(
                    FailureClass.GEOMETRY_BODY_FAILURE
                    if isinstance(exc, GeometryBodyError)
                    else FailureClass.SOURCE_EXTRACTION_FAILURE
                ),
                error_message=str(exc),
            )
            raise ValueError(str(exc)) from exc
        self._record_generation_extracted_source(
            generation_attempt,
            revised_source,
            source_language="python",
        )
        self._record_workflow_artifact(
            workflow_run,
            stage="source_extraction",
            artifact_type="cadquery_source",
            role="component_revised_source",
            relative_path=generation_attempt.source_path,
        )
        source_validation = self._persist_source_contract_validation(
            project=project,
            attempt=generation_attempt,
            source=revised_source,
            source_type="ai_revision",
            design_specification=design_specification,
            design_specification_payload=design_specification_payload,
            design_plan=design_plan,
            design_plan_payload=design_plan_payload,
        )
        self._record_workflow_artifact(
            workflow_run,
            stage="source_contract_validation",
            artifact_type="source_validation_result",
            role="source_contract_result",
            relative_path=source_validation.result_path,
        )
        if not source_validation.passed_hard_checks:
            message = self._source_contract_rejection_message(source_validation)
            self._record_workflow_event(
                workflow_run,
                stage="source_contract_validation",
                event_type="source_contract.failed",
                severity="error",
                blocking=True,
                rule_id="source_contract.hard_rejection",
                message=message,
                deduplication_key=f"revision-source-contract-failed-{source_validation.id}",
                generation_attempt_id=generation_attempt.id,
                revision_plan_id=plan.id,
            )
            self._finish_generation_attempt(
                generation_attempt,
                status="failed",
                failure_class=FailureClass.SOURCE_CONTRACT_HARD_REJECTION,
                error_message=message,
            )
            self._workflow_recorder().complete_run(workflow_run, status="failed")
            raise ValueError(message)
        self._record_workflow_event(
            workflow_run,
            stage="source_contract_validation",
            event_type="source_contract.passed",
            severity="summary",
            message="Revision source contract passed.",
            deduplication_key=f"revision-source-contract-passed-{source_validation.id}",
            generation_attempt_id=generation_attempt.id,
            revision_plan_id=plan.id,
        )
        compliance = self._persist_revision_compliance_result(
            project=project,
            revision_plan=plan,
            generation_attempt=generation_attempt,
            base_source=base_source,
            revised_source=revised_source,
            revision_plan_payload=revision_plan_payload,
            design_specification_payload=design_specification_payload,
            design_plan_payload=design_plan_payload,
            configuration_context=configuration_context,
            cad_backend=base_revision.cad_backend,
        )
        self._record_workflow_artifact(
            workflow_run,
            stage="revision_scope_validation",
            artifact_type="revision_compliance_result",
            role="scope_compliance_result",
            relative_path=compliance.result_path,
        )
        if not compliance.passed:
            first_scope_finding = next(
                (
                    finding
                    for finding in (self._read_json_file(compliance.result_path) or {}).get("findings", [])
                    if isinstance(finding, dict) and finding.get("is_blocking")
                ),
                {},
            )
            self._record_workflow_event(
                workflow_run,
                stage="revision_scope_validation",
                event_type="revision_scope.failed",
                severity="error",
                blocking=True,
                rule_id=str(first_scope_finding.get("rule_id") or "revision.scope_exceeded"),
                message="Revised source exceeded the approved Revision Plan scope.",
                deduplication_key=f"revision-scope-failed-{compliance.id}",
                generation_attempt_id=generation_attempt.id,
                revision_plan_id=plan.id,
                metadata={"compliance_result_id": compliance.id},
            )
            self._finish_generation_attempt(
                generation_attempt,
                status="failed",
                failure_class=FailureClass.REVISION_REGRESSION,
                error_message="Revised source exceeded approved Revision Plan scope",
            )
            try:
                (
                    revised_source,
                    raw_ai_output,
                    generation_attempt,
                    source_validation,
                    compliance,
                ) = await self._attempt_scope_correction(
                    project=project,
                    base_revision=base_revision,
                    revision_plan=plan,
                    failed_source=revised_source,
                    revision_plan_payload=revision_plan_payload,
                    design_specification=design_specification,
                    design_specification_payload=design_specification_payload,
                    design_plan=design_plan,
                    design_plan_payload=design_plan_payload,
                    output_manifest=self.read_output_manifest(base_revision.id),
                    selected_findings=selected_findings,
                    scoped_revision_context=scoped_revision_context,
                    configuration_context=configuration_context,
                    compliance_findings=compliance,
                    cad_backend=base_revision.cad_backend,
                    workflow_run=workflow_run,
                )
            except ValueError as exc:
                self._record_workflow_event(
                    workflow_run,
                    stage="scope_correction",
                    event_type="scope_correction.failed",
                    severity="error",
                    blocking=True,
                    rule_id="revision.scope_exceeded",
                    message="Scope correction did not produce an approved revision.",
                    deduplication_key=f"scope-correction-failed-{plan.id}",
                    revision_plan_id=plan.id,
                    metadata={"error": str(exc)},
                )
                self._workflow_recorder().complete_run(workflow_run, status="failed")
                raise
            self._record_workflow_artifact(
                workflow_run,
                stage="scope_correction",
                artifact_type="cadquery_source",
                role="scope_corrected_source",
                relative_path=generation_attempt.source_path,
            )
            generation_result_raw_output = raw_ai_output
        else:
            generation_result_raw_output = generation_result.raw_output
        candidate = await self._create_cadquery_revision_from_planned_source(
            project_id=project.id,
            source=revised_source,
            user_instruction=plan.user_instruction,
            source_type="ai_revision",
            raw_ai_output=generation_result_raw_output,
            design_specification_id=design_specification.id if design_specification else None,
            design_specification_payload=design_specification_payload,
            design_plan_id=design_plan.id,
            design_plan_payload=design_plan_payload,
            source_validation_result_id=source_validation.id,
            parameter_values=cadquery_parameter_values or self._cadquery_source_parameter_values(revised_source),
            parameter_overrides=cadquery_parameter_values,
            parent_revision_id=base_revision.id,
            configuration_change_id=configuration_change_id,
            workflow_run=workflow_run,
        )
        if candidate is None:
            self._finish_generation_attempt(
                generation_attempt,
                status="failed",
                failure_class=FailureClass.UNKNOWN_FAILURE,
                error_message="revision candidate was not created",
            )
            self._workflow_recorder().complete_run(workflow_run, status="failed")
            return None
        if candidate.status != "succeeded":
            self._finish_generation_attempt(
                generation_attempt,
                status="failed",
                failure_class=FailureClass.DESIGN_ARTIFACT_INCONSISTENT
                if self._has_design_artifact_consistency_blockers(candidate.id)
                else FailureClass.CADQUERY_COMPILE_FAILURE,
                error_message=candidate.error_message,
                resulting_revision_id=candidate.id,
            )
            self.db.commit()
            self._workflow_recorder().complete_run(workflow_run, status="failed")
            return candidate
        plan.generated_revision_id = candidate.id
        compliance.revision_id = candidate.id
        self._persist_revision_success_results(
            project=project,
            revision_plan=plan,
            generation_attempt_id=generation_attempt.id,
            revision_id=candidate.id,
            source=revised_source,
            revision_plan_payload=revision_plan_payload,
            cad_backend=base_revision.cad_backend,
        )
        component_summary = self._persist_component_revision_summary(
            project=project,
            revision_plan=plan,
            generation_attempt=generation_attempt,
            base_revision=base_revision,
            revision_id=candidate.id,
            base_source=base_source,
            revised_source=revised_source,
            revision_plan_payload=revision_plan_payload,
            design_plan_payload=design_plan_payload,
            compliance_result=compliance,
        )
        self._record_workflow_artifact(
            workflow_run,
            stage="output_preservation",
            artifact_type="component_revision_summary",
            role="output_preservation_result",
            relative_path=component_summary.summary_path,
        )
        consistency_result = self._latest_design_artifact_consistency(candidate.id)
        if consistency_result is not None:
            self._record_workflow_artifact(
                workflow_run,
                stage="artifact_consistency",
                artifact_type="design_consistency_result",
                role="design_consistency_result",
                relative_path=consistency_result.result_path,
            )
        component_summary_payload = self._read_json_file(component_summary.summary_path) or {}
        targeted_outputs = component_summary_payload.get("targeted_outputs", [])
        protected_outputs = component_summary_payload.get("protected_outputs", [])
        self._finish_generation_attempt(
            generation_attempt,
            status="succeeded",
            failure_class=FailureClass.NONE,
            resulting_revision_id=candidate.id,
        )
        self.db.commit()
        self._record_workflow_event(
            workflow_run,
            stage="component_revision",
            event_type="component_revision.completed",
            severity="summary",
            message="Component-targeted revision generation completed.",
            deduplication_key=f"component-revision-completed-{plan.id}",
            revision_plan_id=plan.id,
            revision_id=candidate.id,
            metadata={
                "targeted_outputs": [
                    {
                        "output_id": item.get("output_id"),
                        "change_state": item.get("change_state"),
                    }
                    for item in targeted_outputs
                    if isinstance(item, dict)
                ],
                "protected_outputs": [
                    {
                        "output_id": item.get("output_id"),
                        "preservation_state": item.get("preservation_state"),
                    }
                    for item in protected_outputs
                    if isinstance(item, dict)
                ],
                "output_count": candidate.expected_output_count,
            },
        )
        self._workflow_recorder().complete_run(workflow_run, status="completed")
        revision = self.db.get(Revision, candidate.id)
        if revision is not None:
            revision.review_state = self._derive_review_state(revision.id)
            self.db.commit()
            self.db.refresh(revision)
            return self._revision_read(revision)
        return candidate

    def get_revision_compliance_result(
        self,
        revision_plan_id: str,
    ) -> RevisionComplianceResultRead | None:
        result = self.db.scalar(
            select(RevisionComplianceResult)
            .where(RevisionComplianceResult.revision_plan_id == revision_plan_id)
            .order_by(RevisionComplianceResult.created_at.desc())
        )
        if result is None:
            return None
        payload = self._read_json_file(result.result_path) or {}
        return RevisionComplianceResultRead(
            id=result.id,
            project_id=result.project_id,
            revision_plan_id=result.revision_plan_id,
            generation_attempt_id=result.generation_attempt_id,
            revision_id=result.revision_id,
            base_source_hash=result.base_source_hash,
            revised_source_hash=result.revised_source_hash,
            passed=result.passed,
            validation_ms=result.validation_ms,
            created_at=result.created_at,
            findings=list(payload.get("findings", [])),
            metadata=dict(payload.get("metadata", {})),
        )

    def list_revision_success_results(
        self,
        revision_plan_id: str,
    ) -> list[RevisionSuccessResultRead] | None:
        if self.db.get(RevisionPlan, revision_plan_id) is None:
            return None
        rows = self.db.scalars(
            select(RevisionSuccessResult)
            .where(RevisionSuccessResult.revision_plan_id == revision_plan_id)
            .order_by(RevisionSuccessResult.created_at.asc(), RevisionSuccessResult.target_id.asc())
        )
        return [self._revision_success_result_read(row) for row in rows]

    async def _attempt_scope_correction(
        self,
        *,
        project: Project,
        base_revision: Revision,
        revision_plan: RevisionPlan,
        failed_source: str,
        revision_plan_payload: dict[str, Any],
        design_specification: DesignSpecification | None,
        design_specification_payload: dict[str, Any] | None,
        design_plan: DesignPlan,
        design_plan_payload: dict[str, Any],
        output_manifest: dict[str, Any] | None,
        selected_findings: list[dict[str, Any]],
        scoped_revision_context: dict[str, Any],
        configuration_context: dict[str, Any] | None,
        compliance_findings: RevisionComplianceResult,
        cad_backend: str,
        workflow_run: WorkflowRun | None = None,
    ) -> tuple[str, str, GenerationAttempt, SourceValidationResult, RevisionComplianceResult]:
        payload = self._read_json_file(compliance_findings.result_path) or {}
        correction_request = self._generation_request(
            project=project,
            payload=GenerationCreate(
                user_instruction=revision_plan.user_instruction,
                design_specification_id=design_specification.id if design_specification else None,
            ),
            current_source=failed_source,
            scope_diagnostics=json.dumps(payload.get("findings", []), indent=2, sort_keys=True),
            design_specification=design_specification_payload,
            design_plan=design_plan_payload,
            revision_plan=revision_plan_payload,
            output_manifest=output_manifest,
            selected_findings=selected_findings,
            scoped_revision_context=scoped_revision_context,
            configuration_context=configuration_context,
        )
        correction_attempt = self._start_generation_attempt(
            project=project,
            request=correction_request,
            base_revision_id=base_revision.id,
            design_specification_payload=design_specification_payload,
            design_plan_payload=design_plan_payload,
        )
        try:
            correction_result = await self._generate_source_model(correction_request)
        except asyncio.CancelledError:
            self._finish_provider_cancelled_attempt(correction_attempt)
            raise
        except RuntimeError as exc:
            self._finish_generation_attempt(
                correction_attempt,
                status="failed",
                failure_class=self._provider_failure_class(str(exc)),
                error_message=str(exc),
            )
            raise
        self._record_generation_result(correction_attempt, correction_result)
        try:
            corrected_source = self._prepare_generated_source(
                raw_output=correction_result.raw_output,
                design_plan_payload=design_plan_payload,
                generation_contract_version=correction_request.generation_contract_version,
                attempt=correction_attempt,
                workflow_run=workflow_run,
                role="scope_correction_geometry",
            )
        except (SourceExtractionError, ScaffoldSourceError) as exc:
            self._finish_generation_attempt(
                correction_attempt,
                status="failed",
                failure_class=(
                    FailureClass.GEOMETRY_BODY_FAILURE
                    if isinstance(exc, GeometryBodyError)
                    else FailureClass.SOURCE_EXTRACTION_FAILURE
                ),
                error_message=str(exc),
            )
            raise ValueError(str(exc)) from exc
        self._record_generation_extracted_source(
            correction_attempt,
            corrected_source,
            source_language="python",
        )
        corrected_validation = self._persist_source_contract_validation(
            project=project,
            attempt=correction_attempt,
            source=corrected_source,
            source_type="ai_revision",
            design_specification=design_specification,
            design_specification_payload=design_specification_payload,
            design_plan=design_plan,
            design_plan_payload=design_plan_payload,
        )
        if not corrected_validation.passed_hard_checks:
            message = self._source_contract_rejection_message(corrected_validation)
            self._finish_generation_attempt(
                correction_attempt,
                status="failed",
                failure_class=FailureClass.SOURCE_CONTRACT_HARD_REJECTION,
                error_message=message,
            )
            raise ValueError(message)
        corrected_compliance = self._persist_revision_compliance_result(
            project=project,
            revision_plan=revision_plan,
            generation_attempt=correction_attempt,
            base_source=self.read_revision_source(base_revision.id) or "",
            revised_source=corrected_source,
            revision_plan_payload=revision_plan_payload,
            design_specification_payload=design_specification_payload,
            design_plan_payload=design_plan_payload,
            configuration_context=configuration_context,
            cad_backend=cad_backend,
        )
        if not corrected_compliance.passed:
            message = "Revised source rejected before compile by Revision Plan compliance"
            self._finish_generation_attempt(
                correction_attempt,
                status="failed",
                failure_class=FailureClass.REVISION_REGRESSION,
                error_message=message,
            )
            raise ValueError(message)
        return (
            corrected_source,
            correction_result.raw_output,
            correction_attempt,
            corrected_validation,
            corrected_compliance,
        )

    def get_component_revision_summary_by_plan(
        self,
        revision_plan_id: str,
    ) -> ComponentRevisionSummaryRead | None:
        row = self.db.scalar(
            select(ComponentRevisionSummary)
            .where(ComponentRevisionSummary.revision_plan_id == revision_plan_id)
            .order_by(ComponentRevisionSummary.created_at.desc())
        )
        return self._component_revision_summary_read(row) if row is not None else None

    def get_component_revision_summary_by_revision(
        self,
        revision_id: str,
    ) -> ComponentRevisionSummaryRead | None:
        row = self.db.scalar(
            select(ComponentRevisionSummary)
            .where(ComponentRevisionSummary.revision_id == revision_id)
            .order_by(ComponentRevisionSummary.created_at.desc())
        )
        return self._component_revision_summary_read(row) if row is not None else None

    def get_component_revision_scope(self, revision_plan_id: str) -> dict[str, Any] | None:
        plan = self.db.get(RevisionPlan, revision_plan_id)
        if plan is None:
            return None
        base_revision = self.db.get(Revision, plan.base_revision_id)
        design_plan = self.db.get(DesignPlan, plan.revised_design_plan_id or plan.base_design_plan_id)
        if base_revision is None or design_plan is None:
            return None
        source = self.read_revision_source(base_revision.id)
        if source is None:
            return None
        plan_payload = self._read_revision_plan_payload(plan)
        design_plan_payload = self._read_design_plan_payload(design_plan)
        metadata = self._cadquery_revision_source_metadata(source, design_plan_payload).to_json()
        configuration_context = None
        if base_revision.configuration_change_id is not None:
            change = self.db.get(ConfigurationChange, base_revision.configuration_change_id)
            if change is not None:
                configuration_context = {
                    "configuration_change": self._configuration_change_payload(change),
                    "override_manifest": self._configuration_override_manifest(change),
                }
        return self._component_revision_scope_context(
            revision_plan_payload=plan_payload,
            design_plan_payload=design_plan_payload,
            source_metadata=metadata,
            output_manifest=self.read_output_manifest(base_revision.id),
            selected_findings=[],
            configuration_context=configuration_context,
        )

    def _component_revision_summary_read(
        self,
        row: ComponentRevisionSummary,
    ) -> ComponentRevisionSummaryRead:
        payload = self._read_json_file(row.summary_path) or {}
        return ComponentRevisionSummaryRead(
            id=row.id,
            project_id=row.project_id,
            revision_plan_id=row.revision_plan_id,
            revision_id=row.revision_id,
            base_revision_id=row.base_revision_id,
            generation_attempt_id=row.generation_attempt_id,
            base_source_hash=row.base_source_hash,
            revised_source_hash=row.revised_source_hash,
            equivalence_profile_version=row.equivalence_profile_version,
            created_at=row.created_at,
            summary=payload,
        )

    async def create_design_plan_from_specification(
        self,
        specification_id: str,
    ) -> DesignPlanRead | None:
        specification = self.db.get(DesignSpecification, specification_id)
        if specification is None:
            return None
        if specification.outcome != RequirementOutcome.GENERATION_READY.value:
            raise ValueError("Design Specification must be generation_ready before planning")
        if self._has_newer_design_specification(specification):
            raise ValueError("Design Specification has been superseded")
        if self.ai_provider is None:
            raise RuntimeError("AI provider is not configured")
        project = self.db.get(Project, specification.project_id)
        if project is None:
            return None

        parent_run = self._ensure_initial_workflow_run(project)
        workflow_run = self._start_child_workflow_run(
            project_id=project.id,
            workflow_type="design_plan_creation",
            parent=parent_run,
        )
        self._record_workflow_event(
            workflow_run,
            stage="design_plan_generation",
            event_type="design_plan_generation.started",
            severity="summary",
            message="Design Plan generation started.",
            deduplication_key=f"design-plan-generation-started-{specification.id}",
        )
        superseded_plan = self._latest_design_plan(project.id, specification_id=specification.id)
        ledger_store = RequirementLedgerStore(self.db)
        ledger = ledger_store.ensure_from_specification(
            project_id=project.id,
            specification=self._read_design_specification_payload(specification),
            originating_message=specification.user_instruction,
        )
        request = DesignPlanRequest(
            project_name=project.name,
            original_intent=project.original_intent,
            user_instruction=specification.user_instruction,
            design_specification=self._read_design_specification_payload(specification),
            defaults=DEFAULT_REQUIREMENT_PROFILE,
            active_requirements=active_requirements(ledger),
        )
        try:
            result = await self._run_design_planning(
                project=project,
                specification=specification,
                request=request,
                superseded_design_plan_id=superseded_plan.id if superseded_plan else None,
            )
        except asyncio.CancelledError:
            self._record_workflow_event(
                workflow_run,
                stage="design_plan_validation",
                event_type="design_plan.validation.cancelled",
                severity="warning",
                blocking=True,
                rule_id="design_plan.cancelled",
                message="Design Plan generation was cancelled before approval.",
                deduplication_key=f"design-plan-validation-cancelled-{specification.id}",
                is_root_failure=True,
            )
            self._complete_workflow_lineage(workflow_run, status="cancelled")
            raise
        except Exception as exc:
            error_message = str(exc)
            cause = exc.__cause__
            while cause is not None:
                cause_message = str(cause)
                if cause_message.startswith("Functional Design Plan validation failed:"):
                    error_message = cause_message
                    break
                cause = cause.__cause__
            rule_id = "design_plan.generation_failed"
            stage = "design_plan_generation"
            event_type = "design_plan_generation.failed"
            if error_message.startswith("Functional Design Plan validation failed:"):
                stage = "design_plan_validation"
                event_type = "design_plan.validation.failed"
                rule_id = error_message.split(":", 1)[1].split(";", 1)[0].strip() or rule_id
            self._record_workflow_event(
                workflow_run,
                stage=stage,
                event_type=event_type,
                severity="error",
                blocking=True,
                rule_id=rule_id,
                message=error_message,
                deduplication_key=f"design-plan-failed-{specification.id}",
                is_root_failure=True,
            )
            self._complete_workflow_lineage(workflow_run, status="failed")
            raise
        self._record_workflow_artifact(
            workflow_run,
            stage="design_plan_generation",
            artifact_type="raw_provider_response",
            role="design_plan_raw_response",
            relative_path=result.raw_response_path,
        )
        self._record_workflow_artifact(
            workflow_run,
            stage="design_plan_generation",
            artifact_type="design_plan",
            role="design_plan_version",
            relative_path=result.plan_path,
        )
        self._record_workflow_event(
            workflow_run,
            stage="design_plan_generation",
            event_type="design_plan_generation.completed",
            severity="summary",
            message="Design Plan generation completed.",
            deduplication_key=f"design-plan-generation-completed-{specification.id}",
        )
        self._workflow_recorder().complete_run(workflow_run, status="completed")
        return result

    def approve_design_plan(self, design_plan_id: str) -> DesignPlanRead | None:
        plan = self.db.get(DesignPlan, design_plan_id)
        if plan is None:
            return None
        if plan.review_state != DesignPlanReviewState.PENDING_REVIEW.value:
            raise ValueError("Only pending Design Plans can be approved")
        if self._has_newer_design_plan(plan):
            raise ValueError("Design Plan has been superseded")
        plan.review_state = DesignPlanReviewState.APPROVED.value
        plan.approved_at = project_utcnow()
        self._record_message(
            project_id=plan.project_id,
            revision_id=None,
            role="system_event",
            content=f"Design Plan v{plan.version_number} approved",
        )
        self.db.commit()
        self.db.refresh(plan)
        return self._design_plan_read(plan)

    def reject_design_plan(self, design_plan_id: str) -> DesignPlanRead | None:
        plan = self.db.get(DesignPlan, design_plan_id)
        if plan is None:
            return None
        if plan.review_state not in {
            DesignPlanReviewState.PENDING_REVIEW.value,
            DesignPlanReviewState.CLARIFICATION_REQUIRED.value,
        }:
            raise ValueError("Only pending or clarification Design Plans can be rejected")
        plan.review_state = DesignPlanReviewState.REJECTED.value
        plan.rejected_at = project_utcnow()
        self._record_message(
            project_id=plan.project_id,
            revision_id=None,
            role="system_event",
            content=f"Design Plan v{plan.version_number} rejected",
        )
        self.db.commit()
        self.db.refresh(plan)
        return self._design_plan_read(plan)

    def list_design_plan_clarification_questions(
        self,
        design_plan_id: str,
    ) -> list[DesignPlanClarificationQuestionRead] | None:
        if self.db.get(DesignPlan, design_plan_id) is None:
            return None
        questions = self.db.scalars(
            select(DesignPlanClarificationQuestion)
            .where(DesignPlanClarificationQuestion.design_plan_id == design_plan_id)
            .order_by(DesignPlanClarificationQuestion.display_order.asc())
        )
        return [DesignPlanClarificationQuestionRead.model_validate(question) for question in questions]

    async def submit_design_plan_clarification_answers(
        self,
        design_plan_id: str,
        payload: ClarificationAnswersCreate,
    ) -> DesignPlanRead | None:
        plan = self.db.get(DesignPlan, design_plan_id)
        if plan is None:
            return None
        if plan.review_state != DesignPlanReviewState.CLARIFICATION_REQUIRED.value:
            raise ValueError("Design Plan is not waiting for clarification")
        if self.ai_provider is None:
            raise RuntimeError("AI provider is not configured")
        project = self.db.get(Project, plan.project_id)
        specification = self.db.get(DesignSpecification, plan.design_specification_id)
        if project is None or specification is None:
            raise ValueError("Design Plan context is incomplete")

        previous_payload = self._read_design_plan_payload(plan)
        answers: list[dict[str, Any]] = []
        questions_context: list[dict[str, Any]] = []
        for answer_payload in payload.answers:
            question = self.db.get(DesignPlanClarificationQuestion, answer_payload.question_id)
            if question is None or question.design_plan_id != plan.id:
                raise ValueError("clarification question not found for Design Plan")
            answer = DesignPlanClarificationAnswer(
                project_id=plan.project_id,
                design_plan_id=plan.id,
                question_id=question.id,
                related_plan_field=question.related_plan_field,
                question_text=question.question,
                answer=answer_payload.answer.strip(),
            )
            self.db.add(answer)
            answers.append(
                {
                    "question_id": question.id,
                    "related_plan_field": question.related_plan_field,
                    "question": question.question,
                    "answer": answer.answer,
                }
            )
            questions_context.append(
                {
                    "id": question.id,
                    "question": question.question,
                    "reason": question.reason,
                    "related_plan_field": question.related_plan_field,
                }
            )
        self.db.commit()

        request = DesignPlanRequest(
            project_name=project.name,
            original_intent=project.original_intent,
            user_instruction=specification.user_instruction,
            design_specification=self._read_design_specification_payload(specification),
            previous_design_plan=previous_payload,
            clarification_questions=questions_context,
            clarification_answers=answers,
            defaults=DEFAULT_REQUIREMENT_PROFILE,
            active_requirements=active_requirements(
                RequirementLedgerStore(self.db).load(project.id)
            ),
        )
        return await self._run_design_planning(
            project=project,
            specification=specification,
            request=request,
            superseded_design_plan_id=plan.id,
        )

    async def generate_from_design_plan(
        self,
        design_plan_id: str,
    ) -> RevisionRead | None:
        plan = self.db.get(DesignPlan, design_plan_id)
        if plan is None:
            return None
        if plan.review_state != DesignPlanReviewState.APPROVED.value:
            raise ValueError("Design Plan must be approved before CAD generation")
        if self._has_newer_design_plan(plan):
            raise ValueError("Design Plan has been superseded")
        specification = self.db.get(DesignSpecification, plan.design_specification_id)
        if specification is None:
            raise ValueError("Design Specification not found for Design Plan")
        payload = GenerationCreate(
            user_instruction=specification.user_instruction,
            design_specification_id=specification.id,
        )
        return await self.generate_initial_revision(
            specification.project_id,
            payload,
            design_plan=plan,
        )

    def list_clarification_questions(
        self,
        specification_id: str,
    ) -> list[ClarificationQuestionRead] | None:
        if self.db.get(DesignSpecification, specification_id) is None:
            return None
        questions = self.db.scalars(
            select(ClarificationQuestion)
            .where(ClarificationQuestion.design_specification_id == specification_id)
            .order_by(ClarificationQuestion.display_order.asc())
        )
        return [ClarificationQuestionRead.model_validate(question) for question in questions]

    async def submit_clarification_answers(
        self,
        specification_id: str,
        payload: ClarificationAnswersCreate,
    ) -> DesignSpecificationRead | None:
        specification = self.db.get(DesignSpecification, specification_id)
        if specification is None:
            return None
        if self.ai_provider is None:
            raise RuntimeError("AI provider is not configured")

        previous_payload = self._read_design_specification_payload(specification)
        answers: list[dict[str, Any]] = []
        for answer_payload in payload.answers:
            question = self.db.get(ClarificationQuestion, answer_payload.question_id)
            if question is None or question.design_specification_id != specification.id:
                raise ValueError("clarification question not found for specification")
            answer = ClarificationAnswer(
                project_id=specification.project_id,
                question_id=question.id,
                design_specification_id=specification.id,
                related_requirement_id=question.requirement_id,
                question_text=question.question,
                answer=answer_payload.answer.strip(),
            )
            self.db.add(answer)
            answers.append(
                {
                    "question_id": question.id,
                    "related_requirement_id": question.requirement_id,
                    "question": question.question,
                    "answer": answer.answer,
                }
            )
        self.db.commit()

        project = self.db.get(Project, specification.project_id)
        if project is None:
            return None
        workflow_run = self._start_child_workflow_run(
            project_id=project.id,
            workflow_type="requirement_clarification",
        )
        self._record_workflow_event(
            workflow_run,
            stage="requirement_clarification",
            event_type="requirement_clarification.answers_submitted",
            severity="summary",
            message="Clarification answers submitted for requirement review.",
            deduplication_key=f"requirement-clarification-answers-{specification.id}",
            design_specification_id=specification.id,
        )
        request = RequirementExtractionRequest(
            project_name=project.name,
            original_intent=project.original_intent,
            user_instruction=specification.user_instruction,
            previous_specification=previous_payload,
            clarification_questions=[
                {
                    "id": question.id,
                    "related_requirement_id": question.requirement_id,
                    "question": question.question,
                    "reason": question.reason,
                }
                for question in specification.clarification_questions
            ],
            clarification_answers=answers,
            defaults=DEFAULT_REQUIREMENT_PROFILE,
        )
        result = await self._run_requirement_extraction(
            project=project,
            request=request,
            superseded_specification_id=specification.id,
        )
        self._record_workflow_artifact(
            workflow_run,
            stage="requirement_extraction",
            artifact_type="raw_provider_response",
            role="clarification_requirement_raw_response",
            relative_path=result.raw_response_path,
        )
        self._record_workflow_artifact(
            workflow_run,
            stage="requirement_extraction",
            artifact_type="design_specification",
            role="clarified_design_specification_version",
            relative_path=result.specification_path,
        )
        self._record_workflow_event(
            workflow_run,
            stage="requirement_extraction",
            event_type="requirement_clarification.completed",
            severity="summary",
            message="Clarification answers produced an updated requirements version.",
            deduplication_key=f"requirement-clarification-completed-{result.id}",
            design_specification_id=result.id,
        )
        self._workflow_recorder().complete_run(workflow_run, status="completed")
        self.db.commit()
        return result

    async def generate_from_design_specification(
        self,
        specification_id: str,
    ) -> RevisionRead | None:
        specification = self.db.get(DesignSpecification, specification_id)
        if specification is None:
            return None
        payload = GenerationCreate(
            user_instruction=specification.user_instruction,
            design_specification_id=specification.id,
        )
        design_plan = self._latest_design_plan(
            specification.project_id,
            specification_id=specification.id,
        )
        if design_plan is None or design_plan.review_state != DesignPlanReviewState.APPROVED.value:
            raise ValueError("Approved Design Plan is required before CAD generation")
        return await self.generate_initial_revision(
            specification.project_id,
            payload,
            design_plan=design_plan,
        )

    async def create_manual_revision(
        self,
        project_id: str,
        payload: ManualRevisionCreate,
    ) -> RevisionRead | None:
        return await self._create_cadquery_revision_from_planned_source(
            project_id=project_id,
            source=payload.source,
            user_instruction=payload.user_instruction,
            source_type="manual_edit",
            raw_ai_output=None,
            design_specification_id=None,
            design_specification_payload=None,
            design_plan_id=None,
            design_plan_payload=self._cadquery_manual_design_plan_payload(payload.source),
            source_validation_result_id=None,
            parameter_values=self._cadquery_source_parameter_values(payload.source),
            auto_accept=True,
        )

    async def generate_initial_revision(
        self,
        project_id: str,
        payload: GenerationCreate,
        *,
        design_plan: DesignPlan | None = None,
    ) -> RevisionRead | None:
        project = self.db.get(Project, project_id)
        if project is None:
            return None
        if self.ai_provider is None:
            raise RuntimeError("AI provider is not configured")

        current_source = None
        source_type = "ai_initial"
        design_specification = None
        design_specification_payload = None
        design_plan_payload = None
        if payload.design_specification_id is not None:
            design_specification = self.db.get(DesignSpecification, payload.design_specification_id)
            if design_specification is None or design_specification.project_id != project.id:
                raise ValueError("Design Specification not found for project")
            if design_specification.outcome != RequirementOutcome.GENERATION_READY.value:
                raise ValueError("Design Specification must be generation_ready before CAD generation")
            if self._has_newer_design_specification(design_specification):
                raise ValueError("Design Specification has been superseded")
            design_specification_payload = self._read_design_specification_payload(design_specification)
            if design_plan is not None:
                if design_plan.design_specification_id != design_specification.id:
                    raise ValueError("Design Plan does not belong to Design Specification")
                design_plan_payload = self._read_design_plan_payload(design_plan)
        if project.active_revision_id is not None:
            current_source = self.read_revision_source(project.active_revision_id)
            if current_source is None:
                raise RuntimeError("active revision source is missing")
            source_type = "ai_revision"
            if design_specification_payload is None:
                latest_specification = self._latest_design_specification(project.id)
                if latest_specification is not None:
                    design_specification = latest_specification
                    design_specification_payload = self._read_design_specification_payload(
                        latest_specification
                    )
        elif design_specification is None:
            raise ValueError("Design Specification is required before initial AI generation")
        if design_plan is None or design_plan_payload is None:
            raise ValueError("Approved Design Plan is required before CAD generation")

        parent_run = self._ensure_initial_workflow_run(project)
        workflow_run = self._start_child_workflow_run(
            project_id=project.id,
            workflow_type="source_generation",
            parent=parent_run,
        )
        self._record_workflow_event(
            workflow_run,
            stage="source_generation",
            event_type="source_generation.started",
            severity="summary",
            message="CadQuery source generation started.",
            deduplication_key=f"source-generation-started-{project.id}-{design_plan.id}",
        )
        generation_request = self._generation_request(
            project=project,
            payload=payload,
            current_source=current_source,
            design_specification=design_specification_payload,
            design_plan=design_plan_payload,
        )
        generation_attempt = self._start_generation_attempt(
            project=project,
            request=generation_request,
            base_revision_id=project.active_revision_id,
            design_specification_payload=design_specification_payload,
            design_plan_payload=design_plan_payload,
        )
        self._record_workflow_event(
            workflow_run,
            stage="source_generation",
            event_type="provider.request_prepared",
            severity="standard",
            message="Provider request prepared for CadQuery source generation.",
            deduplication_key=f"provider-request-prepared-{generation_attempt.id}",
            generation_attempt_id=generation_attempt.id,
        )
        try:
            generation_result = await self._generate_source_model(generation_request)
        except asyncio.CancelledError:
            self._finish_provider_cancelled_attempt(generation_attempt)
            self._complete_workflow_lineage(workflow_run, status="cancelled")
            raise
        except RuntimeError as exc:
            self._finish_generation_attempt(
                generation_attempt,
                status="failed",
                failure_class=self._provider_failure_class(str(exc)),
                error_message=str(exc),
            )
            self._complete_workflow_lineage(workflow_run, status="failed")
            raise

        try:
            source, raw_ai_output, active_attempt, source_validation = (
                await self._extract_validate_or_repair_source(
                    project=project,
                    payload=payload,
                    generation_attempt=generation_attempt,
                    generation_result=generation_result,
                    source_type=source_type,
                    design_specification=design_specification,
                    design_specification_payload=design_specification_payload,
                    design_plan=design_plan,
                    design_plan_payload=design_plan_payload,
                    generation_contract_version=generation_request.generation_contract_version,
                    workflow_run=workflow_run,
                )
            )
        except _StoppedWithRevision as exc:
            self._complete_workflow_lineage(workflow_run, status="failed")
            return exc.revision
        except asyncio.CancelledError:
            self._complete_workflow_lineage(workflow_run, status="cancelled")
            raise
        except Exception:
            self._complete_workflow_lineage(workflow_run, status="failed")
            raise
        initial_revision = await self._create_cadquery_revision_from_planned_source(
            project_id=project_id,
            source=source,
            user_instruction=payload.user_instruction,
            source_type=source_type,
            raw_ai_output=raw_ai_output,
            design_specification_id=design_specification.id if design_specification else None,
            design_specification_payload=design_specification_payload,
            design_plan_id=design_plan.id,
            design_plan_payload=design_plan_payload,
            source_validation_result_id=source_validation.id,
            workflow_run=workflow_run,
        )
        if initial_revision is None or initial_revision.status == "succeeded":
            self._finish_generation_attempt(
                active_attempt,
                status="succeeded" if initial_revision is not None else "failed",
                failure_class=FailureClass.NONE
                if initial_revision is not None
                else FailureClass.UNKNOWN_FAILURE,
                resulting_revision_id=initial_revision.id if initial_revision is not None else None,
            )
            self._workflow_recorder().complete_run(
                workflow_run,
                status="completed" if initial_revision is not None else "failed",
            )
            return initial_revision

        self._finish_generation_attempt(
            active_attempt,
            status="failed",
            failure_class=FailureClass.DESIGN_ARTIFACT_INCONSISTENT
            if self._has_design_artifact_consistency_blockers(initial_revision.id)
            else FailureClass.CADQUERY_COMPILE_FAILURE,
            error_message=initial_revision.error_message,
            resulting_revision_id=initial_revision.id,
        )
        if self._has_design_artifact_consistency_blockers(initial_revision.id):
            self._complete_workflow_lineage(workflow_run, status="failed")
            return initial_revision

        repair_request = self._generation_request(
            project=project,
            payload=payload,
            current_source=source,
            compiler_diagnostics=initial_revision.error_message,
            design_specification=design_specification_payload,
            design_plan=design_plan_payload,
        )
        repair_attempt = self._start_generation_attempt(
            project=project,
            request=repair_request,
            base_revision_id=project.active_revision_id,
            design_specification_payload=design_specification_payload,
            design_plan_payload=design_plan_payload,
        )
        try:
            repair_result = await self._generate_source_model(repair_request)
        except asyncio.CancelledError:
            self._finish_provider_cancelled_attempt(repair_attempt)
            self._complete_workflow_lineage(workflow_run, status="cancelled")
            raise
        except RuntimeError as exc:
            self._finish_generation_attempt(
                repair_attempt,
                status="failed",
                failure_class=self._provider_failure_class(str(exc)),
                error_message=str(exc),
            )
            self._complete_workflow_lineage(workflow_run, status="failed")
            raise

        self._record_generation_result(repair_attempt, repair_result)
        try:
            repaired_source = self._prepare_generated_source(
                raw_output=repair_result.raw_output,
                design_plan_payload=design_plan_payload,
                generation_contract_version=repair_request.generation_contract_version,
                attempt=repair_attempt,
                workflow_run=workflow_run,
                role="execution_repair_geometry",
            )
        except (SourceExtractionError, ScaffoldSourceError) as exc:
            failed_repair = self._create_failed_ai_revision(
                project=project,
                user_instruction=payload.user_instruction,
                source_type="ai_repair",
                raw_ai_output=repair_result.raw_output,
                error_message=str(exc),
            )
            self._finish_generation_attempt(
                repair_attempt,
                status="failed",
                failure_class=(
                    FailureClass.GEOMETRY_BODY_FAILURE
                    if isinstance(exc, GeometryBodyError)
                    else FailureClass.SOURCE_EXTRACTION_FAILURE
                ),
                error_message=str(exc),
                resulting_revision_id=failed_repair.id,
            )
            self._complete_workflow_lineage(workflow_run, status="failed")
            return failed_repair

        self._record_generation_extracted_source(repair_attempt, repaired_source)
        repair_source_validation = self._persist_source_contract_validation(
            project=project,
            attempt=repair_attempt,
            source=repaired_source,
            source_type="ai_repair",
            design_specification=design_specification,
            design_specification_payload=design_specification_payload,
            design_plan=design_plan,
            design_plan_payload=design_plan_payload,
        )
        if not repair_source_validation.passed_hard_checks:
            error_message = self._source_contract_rejection_message(repair_source_validation)
            self._finish_generation_attempt(
                repair_attempt,
                status="failed",
                failure_class=FailureClass.SOURCE_CONTRACT_HARD_REJECTION,
                error_message=error_message,
            )
            self._complete_workflow_lineage(workflow_run, status="failed")
            return initial_revision
        repair_revision = await self._create_cadquery_revision_from_planned_source(
            project_id=project_id,
            source=repaired_source,
            user_instruction=payload.user_instruction,
            source_type="ai_repair",
            raw_ai_output=repair_result.raw_output,
            design_specification_id=design_specification.id if design_specification else None,
            design_specification_payload=design_specification_payload,
            design_plan_id=design_plan.id,
            design_plan_payload=design_plan_payload,
            source_validation_result_id=repair_source_validation.id,
            workflow_run=workflow_run,
        )
        self._finish_generation_attempt(
            repair_attempt,
            status="succeeded" if repair_revision and repair_revision.status == "succeeded" else "failed",
            failure_class=FailureClass.NONE
            if repair_revision and repair_revision.status == "succeeded"
            else FailureClass.DESIGN_ARTIFACT_INCONSISTENT
            if repair_revision and self._has_design_artifact_consistency_blockers(repair_revision.id)
            else FailureClass.CADQUERY_COMPILE_FAILURE,
            error_message=None
            if repair_revision and repair_revision.status == "succeeded"
            else repair_revision.error_message if repair_revision else "repair revision was not created",
            resulting_revision_id=repair_revision.id if repair_revision else None,
        )
        status = "completed" if repair_revision is not None and repair_revision.status == "succeeded" else "failed"
        self._complete_workflow_lineage(workflow_run, status=status)
        return repair_revision

    async def _extract_validate_or_repair_source(
        self,
        *,
        project: Project,
        payload: GenerationCreate,
        generation_attempt: GenerationAttempt,
        generation_result,
        source_type: str,
        design_specification: DesignSpecification | None,
        design_specification_payload: dict[str, Any] | None,
        design_plan: DesignPlan | None = None,
        design_plan_payload: dict[str, Any] | None = None,
        generation_contract_version: str = "v1",
        workflow_run: WorkflowRun | None = None,
    ) -> tuple[str, str, GenerationAttempt, SourceValidationResult]:
        self._record_generation_result(generation_attempt, generation_result)
        self._record_workflow_artifact(
            workflow_run,
            stage="provider_response",
            artifact_type="raw_provider_response",
            role="initial_raw_response",
            relative_path=generation_attempt.raw_output_path,
            redacted=False,
        )
        active_role = "initial_generated_source"
        try:
            source = self._prepare_generated_source(
                raw_output=generation_result.raw_output,
                design_plan_payload=design_plan_payload,
                generation_contract_version=generation_contract_version,
                attempt=generation_attempt,
                workflow_run=workflow_run,
                role="initial_geometry",
            )
        except GeometryBodyError as exc:
            self._record_workflow_event(
                workflow_run,
                stage="source_extraction",
                event_type="geometry_body.failed",
                severity="error",
                blocking=True,
                rule_id=exc.rule_id,
                message=str(exc),
                deduplication_key=f"geometry-body-failed-{generation_attempt.id}",
                generation_attempt_id=generation_attempt.id,
                metadata=exc.details,
            )
            self._finish_generation_attempt(
                generation_attempt,
                status="failed",
                failure_class=FailureClass.GEOMETRY_BODY_FAILURE,
                error_message=str(exc),
            )
            repaired = await self._attempt_geometry_body_repair(
                project=project,
                payload=payload,
                failed_attempt=generation_attempt,
                failed_response=generation_result,
                diagnostics=exc,
                design_specification=design_specification,
                design_specification_payload=design_specification_payload,
                design_plan=design_plan,
                design_plan_payload=design_plan_payload,
                workflow_run=workflow_run,
            )
            if repaired is None:
                failed_revision = self._create_failed_ai_revision(
                    project=project,
                    user_instruction=payload.user_instruction,
                    source_type=source_type,
                    raw_ai_output=generation_result.raw_output,
                    error_message=str(exc),
                )
                generation_attempt.resulting_revision_id = failed_revision.id
                self.db.commit()
                raise _StoppedWithRevision(failed_revision) from exc
            source, generation_result, generation_attempt = repaired
            active_role = "geometry_body_repaired_source"
        except (SourceExtractionError, ScaffoldSourceError) as exc:
            failed_revision = self._create_failed_ai_revision(
                project=project,
                user_instruction=payload.user_instruction,
                source_type=source_type,
                raw_ai_output=generation_result.raw_output,
                error_message=str(exc),
            )
            self._finish_generation_attempt(
                generation_attempt,
                status="failed",
                failure_class=(
                    FailureClass.GEOMETRY_BODY_FAILURE
                    if isinstance(exc, GeometryBodyError)
                    else FailureClass.SOURCE_EXTRACTION_FAILURE
                ),
                error_message=str(exc),
                resulting_revision_id=failed_revision.id,
            )
            raise _StoppedWithRevision(failed_revision) from exc

        self._record_generation_extracted_source(
            generation_attempt,
            source,
            source_language="python",
        )
        initial_source_artifact = self._record_workflow_artifact(
            workflow_run,
            stage="source_extraction",
            artifact_type="cadquery_source",
            role=active_role,
            relative_path=generation_attempt.source_path,
            redacted=False,
        )
        source_validation = self._persist_source_contract_validation(
            project=project,
            attempt=generation_attempt,
            source=source,
            source_type=source_type,
            design_specification=design_specification,
            design_specification_payload=design_specification_payload,
            design_plan=design_plan,
            design_plan_payload=design_plan_payload,
        )
        if source_validation.passed_hard_checks:
            self._record_workflow_event(
                workflow_run,
                stage="source_contract_validation",
                event_type="source_contract.passed",
                severity="summary",
                message="CadQuery source contract passed.",
                deduplication_key=f"source-contract-passed-{generation_attempt.id}",
                generation_attempt_id=generation_attempt.id,
                metadata={"source_validation_result_id": source_validation.id},
            )
            return source, generation_result.raw_output, generation_attempt, source_validation

        contract_diagnostics = self._source_contract_rejection_message(source_validation)
        source_failure_event = self._record_workflow_event(
            workflow_run,
            stage="source_contract_validation",
            event_type="source_contract.failed",
            severity="error",
            blocking=True,
            rule_id="source_contract.failed",
            message=contract_diagnostics,
            deduplication_key=f"source-contract-failed-{generation_attempt.id}",
            generation_attempt_id=generation_attempt.id,
            metadata={"source_validation_result_id": source_validation.id},
        )
        self._finish_generation_attempt(
            generation_attempt,
            status="failed",
            failure_class=FailureClass.SOURCE_CONTRACT_HARD_REJECTION,
            error_message=contract_diagnostics,
        )

        repair_request = self._generation_request(
            project=project,
            payload=payload,
            current_source=source,
            contract_diagnostics=contract_diagnostics,
            design_specification=design_specification_payload,
            design_plan=design_plan_payload,
        )
        repair_attempt = self._start_generation_attempt(
            project=project,
            request=repair_request,
            base_revision_id=project.active_revision_id,
            design_specification_payload=design_specification_payload,
            design_plan_payload=design_plan_payload,
        )
        repair_workflow_run = None
        if workflow_run is not None:
            repair_workflow_run = self._start_child_workflow_run(
                project_id=project.id,
                workflow_type="contract_repair",
                parent=self.db.get(WorkflowRun, workflow_run.root_workflow_run_id)
                if workflow_run.root_workflow_run_id
                else workflow_run,
            )
            self._record_workflow_event(
                repair_workflow_run,
                stage="contract_repair",
                event_type="contract_repair.started",
                severity="summary",
                message="Contract repair started.",
                deduplication_key=f"contract-repair-started-{repair_attempt.id}",
                caused_by_event_id=source_failure_event.id if source_failure_event is not None else None,
                generation_attempt_id=repair_attempt.id,
            )
        try:
            repair_result = await self._generate_source_model(repair_request)
        except asyncio.CancelledError:
            self._finish_provider_cancelled_attempt(repair_attempt)
            if repair_workflow_run is not None:
                self._workflow_recorder().complete_run(repair_workflow_run, status="cancelled")
            raise
        except RuntimeError as exc:
            self._finish_generation_attempt(
                repair_attempt,
                status="failed",
                failure_class=self._provider_failure_class(str(exc)),
                error_message=str(exc),
            )
            if repair_workflow_run is not None:
                self._workflow_recorder().complete_run(repair_workflow_run, status="failed")
            raise

        self._record_generation_result(repair_attempt, repair_result)
        self._record_workflow_artifact(
            repair_workflow_run or workflow_run,
            stage="provider_response",
            artifact_type="raw_provider_response",
            role="contract_repair_raw_response",
            relative_path=repair_attempt.raw_output_path,
            redacted=False,
        )
        try:
            repaired_source = self._prepare_generated_source(
                raw_output=repair_result.raw_output,
                design_plan_payload=design_plan_payload,
                generation_contract_version=repair_request.generation_contract_version,
                attempt=repair_attempt,
                workflow_run=repair_workflow_run or workflow_run,
                role="contract_repair_geometry",
            )
        except (SourceExtractionError, ScaffoldSourceError) as exc:
            self._finish_generation_attempt(
                repair_attempt,
                status="failed",
                failure_class=(
                    FailureClass.GEOMETRY_BODY_FAILURE
                    if isinstance(exc, GeometryBodyError)
                    else FailureClass.SOURCE_EXTRACTION_FAILURE
                ),
                error_message=str(exc),
            )
            if repair_workflow_run is not None:
                self._workflow_recorder().complete_run(repair_workflow_run, status="failed")
            raise ValueError(str(exc)) from exc

        self._record_generation_extracted_source(
            repair_attempt,
            repaired_source,
            source_language="python",
        )
        self._record_workflow_artifact(
            repair_workflow_run or workflow_run,
            stage="contract_repair",
            artifact_type="cadquery_source",
            role="contract_repaired_source",
            relative_path=repair_attempt.source_path,
            redacted=False,
            supersedes_artifact_id=initial_source_artifact.id
            if initial_source_artifact is not None
            else None,
        )
        repaired_validation = self._persist_source_contract_validation(
            project=project,
            attempt=repair_attempt,
            source=repaired_source,
            source_type="ai_repair",
            design_specification=design_specification,
            design_specification_payload=design_specification_payload,
            design_plan=design_plan,
            design_plan_payload=design_plan_payload,
        )
        if not repaired_validation.passed_hard_checks:
            error_message = self._source_contract_rejection_message(repaired_validation)
            self._record_workflow_event(
                repair_workflow_run or workflow_run,
                stage="contract_repair",
                event_type="contract_repair.failed",
                severity="error",
                blocking=True,
                rule_id="source_contract.failed",
                message=error_message,
                deduplication_key=f"contract-repair-failed-{repair_attempt.id}",
                generation_attempt_id=repair_attempt.id,
            )
            self._finish_generation_attempt(
                repair_attempt,
                status="failed",
                failure_class=FailureClass.SOURCE_CONTRACT_HARD_REJECTION,
                error_message=error_message,
            )
            if repair_workflow_run is not None:
                self._workflow_recorder().complete_run(repair_workflow_run, status="failed")
            raise ValueError(error_message)

        self._record_workflow_event(
            repair_workflow_run or workflow_run,
            stage="contract_repair",
            event_type="contract_repair.succeeded",
            severity="summary",
            message="Contract repair produced source that passed hard checks.",
            deduplication_key=f"contract-repair-succeeded-{repair_attempt.id}",
            caused_by_event_id=source_failure_event.id if source_failure_event is not None else None,
            generation_attempt_id=repair_attempt.id,
        )
        if repair_workflow_run is not None:
            self._workflow_recorder().complete_run(repair_workflow_run, status="completed")
        return repaired_source, repair_result.raw_output, repair_attempt, repaired_validation

    def _generation_request(
        self,
        *,
        project: Project,
        payload: GenerationCreate,
        current_source: str | None = None,
        contract_diagnostics: str | None = None,
        compiler_diagnostics: str | None = None,
        scope_diagnostics: str | None = None,
        design_specification: dict[str, Any] | None = None,
        design_plan: dict[str, Any] | None = None,
        revision_plan: dict[str, Any] | None = None,
        output_manifest: dict[str, Any] | None = None,
        selected_findings: list[dict[str, Any]] | None = None,
        source_metadata: dict[str, Any] | None = None,
        scoped_revision_context: dict[str, Any] | None = None,
        configuration_context: dict[str, Any] | None = None,
        geometry_body_diagnostics: str | None = None,
        active_requirement_items: list[dict[str, Any]] | None = None,
        requirement_delta: list[dict[str, Any]] | None = None,
    ) -> ModelGenerationRequest:
        source_authority = authority_from_generation_context(
            design_plan_payload=design_plan,
            revision_plan_payload=revision_plan,
        )
        return ModelGenerationRequest(
            project_name=project.name,
            original_intent=project.original_intent,
            user_instruction=payload.user_instruction,
            current_source=current_source,
            contract_diagnostics=contract_diagnostics,
            compiler_diagnostics=compiler_diagnostics,
            scope_diagnostics=scope_diagnostics,
            design_specification=design_specification,
            design_plan=design_plan,
            revision_plan=revision_plan,
            output_manifest=output_manifest,
            selected_findings=selected_findings or [],
            source_metadata=source_metadata,
            scoped_revision_context=scoped_revision_context,
            configuration_context=configuration_context,
            source_authority=source_authority,
            geometry_body_diagnostics=geometry_body_diagnostics,
            active_requirements=active_requirement_items
            if active_requirement_items is not None
            else active_requirements(RequirementLedgerStore(self.db).load(project.id)),
            requirement_delta=(
                list(requirement_delta)
                if requirement_delta is not None
                else requirement_delta_for_message(payload.user_instruction)[0]
            ),
            generation_contract_version=self._provider_generation_contract_version(),
        )

    async def _generate_source_model(self, request: ModelGenerationRequest):
        generator = getattr(self.ai_provider, "generate_cadquery_model", None)
        if not callable(generator):
            raise RuntimeError("AI provider does not support CadQuery generation")
        return await generator(request)

    def _provider_generation_contract_version(self) -> str:
        version = getattr(self.ai_provider, "cadquery_generation_contract_version", None)
        if callable(version):
            return str(version())
        return "v1"

    def _prepare_generated_source(
        self,
        *,
        raw_output: str,
        design_plan_payload: dict[str, Any] | None,
        generation_contract_version: str,
        attempt: GenerationAttempt,
        workflow_run: WorkflowRun | None,
        role: str,
    ) -> str:
        if generation_contract_version != SCAFFOLD_VERSION:
            return self._extract_generated_source(raw_output)
        if not design_plan_payload:
            raise ScaffoldSourceError("scaffold generation requires an approved Design Plan")
        inventory = build_geometry_function_inventory(design_plan_payload)
        assembly = assemble_geometry_bodies(raw_output, inventory)
        geometry_functions = assembly.functions
        rendered = render_cadquery_scaffold(design_plan_payload, geometry_functions)
        run_dir = self._generation_attempt_dir(attempt.project_id, attempt.id)
        parsed_path = run_dir / "geometry-bodies.json"
        original_path = run_dir / "geometry-bodies-original.json"
        geometry_path = run_dir / "geometry-bodies.py"
        self._write_json(parsed_path, assembly.payload)
        self._write_json(
            original_path,
            {
                "schema_version": GEOMETRY_BODIES_SCHEMA_VERSION,
                "functions": [
                    {
                        "function_id": function_id,
                        "statements": assembly.original_body_lines[function_id],
                        "result_symbol": assembly.result_symbols[function_id],
                    }
                    for function_id in assembly.original_body_lines
                ],
            },
        )
        geometry_path.write_text(
            "\n\n".join(geometry_functions[name] for name in rendered.expected_geometry_functions) + "\n",
            encoding="utf-8",
        )
        scaffold_manifest_path = run_dir / "scaffold-manifest.json"
        self._write_json(
            scaffold_manifest_path,
            {
                "schema_version": SCAFFOLD_VERSION,
                "geometry_body_schema_version": GEOMETRY_BODIES_SCHEMA_VERSION,
                "scaffold_hash": rendered.scaffold_hash,
                "expected_geometry_functions": list(rendered.expected_geometry_functions),
                "function_body_hashes": assembly.function_body_hashes,
                "derived_parameter_manifest": rendered.derived_parameter_manifest,
                "pattern_manifest": rendered.pattern_manifest,
                "parameter_effect_manifest": rendered.parameter_effect_manifest,
                "assembled_source_hash": self._sha256(rendered.source),
                "role": role,
            },
        )
        stage = "source_extraction" if role == "initial_geometry" else "contract_repair"
        self._record_workflow_artifact(
            workflow_run,
            stage=stage,
            artifact_type="cadquery_geometry_body_json",
            role=f"{role}_parsed_geometry_bodies",
            relative_path=self._relative(parsed_path),
            redacted=False,
        )
        self._record_workflow_artifact(
            workflow_run,
            stage=stage,
            artifact_type="cadquery_geometry_body_original",
            role=f"{role}_original_body_statements",
            relative_path=self._relative(original_path),
            redacted=False,
        )
        self._record_workflow_artifact(
            workflow_run,
            stage=stage,
            artifact_type="cadquery_geometry_bodies",
            role=role,
            relative_path=self._relative(geometry_path),
            redacted=False,
        )
        self._record_workflow_artifact(
            workflow_run,
            stage=stage,
            artifact_type="cadquery_scaffold_manifest",
            role=f"{role}_scaffold_manifest",
            relative_path=self._relative(scaffold_manifest_path),
            redacted=False,
        )
        return rendered.source

    def _extract_generated_source(self, raw_output: str) -> str:
        return extract_python_source(raw_output)

    async def _attempt_geometry_body_repair(
        self,
        *,
        project: Project,
        payload: GenerationCreate,
        failed_attempt: GenerationAttempt,
        failed_response: Any,
        diagnostics: GeometryBodyError,
        design_specification: DesignSpecification | None,
        design_specification_payload: dict[str, Any] | None,
        design_plan: DesignPlan | None,
        design_plan_payload: dict[str, Any] | None,
        workflow_run: WorkflowRun | None,
    ) -> tuple[str, Any, GenerationAttempt] | None:
        """Try one structured body repair without reopening scaffold authority."""

        repair_request = self._generation_request(
            project=project,
            payload=payload,
            current_source=failed_response.raw_output,
            design_specification=design_specification_payload,
            design_plan=design_plan_payload,
            geometry_body_diagnostics=json.dumps(
                {"rule_id": diagnostics.rule_id, "message": str(diagnostics), "details": diagnostics.details},
                sort_keys=True,
            ),
        )
        repair_attempt = self._start_generation_attempt(
            project=project,
            request=repair_request,
            base_revision_id=project.active_revision_id,
            design_specification_payload=design_specification_payload,
            design_plan_payload=design_plan_payload,
        )
        repair_workflow_run = None
        if workflow_run is not None:
            root = self.db.get(WorkflowRun, workflow_run.root_workflow_run_id) if workflow_run.root_workflow_run_id else workflow_run
            repair_workflow_run = self._start_child_workflow_run(
                project_id=project.id,
                workflow_type="contract_repair",
                parent=root or workflow_run,
            )
            self._record_workflow_event(
                repair_workflow_run,
                stage="contract_repair",
                event_type="geometry_body.repair_started",
                severity="summary",
                message="Structured geometry-body repair started.",
                deduplication_key=f"geometry-body-repair-started-{repair_attempt.id}",
                caused_by_event_id=None,
                generation_attempt_id=repair_attempt.id,
                metadata={"rule_id": diagnostics.rule_id, "failed_attempt_id": failed_attempt.id},
            )
        try:
            repair_result = await self._generate_source_model(repair_request)
        except asyncio.CancelledError:
            self._finish_provider_cancelled_attempt(repair_attempt)
            if repair_workflow_run is not None:
                self._workflow_recorder().complete_run(repair_workflow_run, status="cancelled")
            raise
        except RuntimeError as exc:
            self._finish_generation_attempt(
                repair_attempt,
                status="failed",
                failure_class=self._provider_failure_class(str(exc)),
                error_message=str(exc),
            )
            if repair_workflow_run is not None:
                self._workflow_recorder().complete_run(repair_workflow_run, status="failed")
            return None

        self._record_generation_result(repair_attempt, repair_result)
        self._record_workflow_artifact(
            repair_workflow_run or workflow_run,
            stage="provider_response",
            artifact_type="raw_provider_response",
            role="geometry_body_repair_raw_response",
            relative_path=repair_attempt.raw_output_path,
            redacted=False,
        )
        try:
            repaired_source = self._prepare_generated_source(
                raw_output=repair_result.raw_output,
                design_plan_payload=design_plan_payload,
                generation_contract_version=repair_request.generation_contract_version,
                attempt=repair_attempt,
                workflow_run=repair_workflow_run or workflow_run,
                role="geometry_body_repair",
            )
        except GeometryBodyError as exc:
            self._finish_generation_attempt(
                repair_attempt,
                status="failed",
                failure_class=FailureClass.GEOMETRY_BODY_FAILURE,
                error_message=str(exc),
            )
            if repair_workflow_run is not None:
                self._record_workflow_event(
                    repair_workflow_run,
                    stage="contract_repair",
                    event_type="geometry_body.repair_failed",
                    severity="error",
                    blocking=True,
                    rule_id=exc.rule_id,
                    message=str(exc),
                    deduplication_key=f"geometry-body-repair-failed-{repair_attempt.id}",
                    generation_attempt_id=repair_attempt.id,
                )
                self._workflow_recorder().complete_run(repair_workflow_run, status="failed")
            return None

        self._record_generation_extracted_source(repair_attempt, repaired_source)
        self._record_workflow_artifact(
            repair_workflow_run or workflow_run,
            stage="contract_repair",
            artifact_type="cadquery_source",
            role="geometry_body_repaired_source",
            relative_path=repair_attempt.source_path,
            redacted=False,
        )
        if repair_workflow_run is not None:
            self._record_workflow_event(
                repair_workflow_run,
                stage="contract_repair",
                event_type="geometry_body.repair_succeeded",
                severity="summary",
                message="Structured geometry-body repair produced an assembled source.",
                deduplication_key=f"geometry-body-repair-succeeded-{repair_attempt.id}",
                generation_attempt_id=repair_attempt.id,
            )
            self._workflow_recorder().complete_run(repair_workflow_run, status="completed")
        return repaired_source, repair_result, repair_attempt

    def _routing_for_request(self, request: Any) -> dict[str, Any]:
        resolver = getattr(self.ai_provider, "routing_for_request", None)
        if callable(resolver):
            decision = resolver(request)
            as_dict = getattr(decision, "as_dict", None)
            if callable(as_dict):
                return as_dict()
            if isinstance(decision, dict):
                return dict(decision)
        model = self._provider_model()
        return {
            "prompt_mode": "provider_managed",
            "provider": self._provider_name(),
            "selected_model": model,
            "policy_version": "provider-managed",
            "routing_reason": "provider_managed",
            "fallback_chain": [model] if model else [],
        }

    def _start_generation_attempt(
        self,
        *,
        project: Project,
        request: ModelGenerationRequest,
        base_revision_id: str | None,
        design_specification_payload: dict[str, Any] | None = None,
        design_plan_payload: dict[str, Any] | None = None,
    ) -> GenerationAttempt:
        routing = self._routing_for_request(request)
        attempt = GenerationAttempt(
            project_id=project.id,
            base_revision_id=base_revision_id,
            attempt_number=self._next_generation_attempt_number(project.id),
            provider_id=self._provider_name(),
            model_id=routing.get("selected_model") or self._provider_model(),
            provider_settings_json=json.dumps(self._provider_settings(), sort_keys=True),
            routing_metadata_json=json.dumps(routing, sort_keys=True),
            prompt_version=self._prompt_template_version(request),
            ruleset_version=self._ruleset_version(),
            request_payload_path="",
            prompt_path="",
            status="started",
            failure_class=FailureClass.NONE.value,
        )
        attempt.cad_backend = "cadquery"
        attempt.source_language = "python"
        attempt.source_contract_version = "cadquery-v1"
        self.db.add(attempt)
        self.db.flush()

        run_dir = self._generation_attempt_dir(project.id, attempt.id)
        run_dir.mkdir(parents=True, exist_ok=True)
        request_path = run_dir / "request.json"
        prompt_path = run_dir / "prompt.txt"
        design_spec_path = run_dir / "design-spec.json"
        design_plan_path = run_dir / "design-plan.json"
        chain_path = run_dir / "chain.json"

        self._write_json(request_path, asdict(request))
        prompt_path.write_text(self._render_prompt(request), encoding="utf-8")
        self._write_json(
            design_spec_path,
            design_specification_payload or self._cadquery_design_spec_placeholder(request),
        )
        if design_plan_payload is not None:
            self._write_json(design_plan_path, design_plan_payload)
        self._write_json(chain_path, self._attempt_chain(attempt, status="started"))

        attempt.request_payload_path = self._relative(request_path)
        attempt.prompt_path = self._relative(prompt_path)
        attempt.design_spec_path = self._relative(design_spec_path)
        attempt.design_plan_path = self._relative(design_plan_path) if design_plan_payload is not None else None
        attempt.intermediate_artifacts_path = self._relative(chain_path)
        self._update_attempt_chain(attempt, status="started")
        self.db.commit()
        self.db.refresh(attempt)
        return attempt

    def _record_generation_result(self, attempt: GenerationAttempt, generation_result) -> None:
        run_dir = self._generation_attempt_dir(attempt.project_id, attempt.id)
        raw_output_path = run_dir / "raw-output.txt"
        raw_output_path.write_text(generation_result.raw_output, encoding="utf-8")
        attempt.provider_id = generation_result.provider
        attempt.model_id = generation_result.provider_model
        usage_metadata = getattr(generation_result, "usage_metadata", None)
        attempt.provider_usage_json = json.dumps(usage_metadata, sort_keys=True) if usage_metadata else None
        attempt.provider_request_id = getattr(generation_result, "provider_request_id", None)
        result_routing = getattr(generation_result, "routing_metadata", None)
        if isinstance(result_routing, dict) and result_routing:
            stored_routing = json.loads(attempt.routing_metadata_json or "{}")
            stored_routing.update(result_routing)
            attempt.routing_metadata_json = json.dumps(stored_routing, sort_keys=True)
        attempt.provider_latency_ms = getattr(generation_result, "provider_latency_ms", None)
        attempt.raw_output_path = self._relative(raw_output_path)
        attempt.output_hash = self._sha256(generation_result.raw_output)
        self._update_attempt_chain(attempt, status=attempt.status)
        self.db.commit()

    def _record_generation_extracted_source(
        self,
        attempt: GenerationAttempt,
        source: str,
        *,
        source_language: str = "python",
    ) -> None:
        run_dir = self._generation_attempt_dir(attempt.project_id, attempt.id)
        source_path = run_dir / "extracted-source.py"
        source_path.write_text(source, encoding="utf-8")
        attempt.source_path = self._relative(source_path)
        attempt.source_hash = self._sha256(source)
        attempt.cad_backend = "cadquery"
        attempt.source_language = "python"
        attempt.source_contract_version = "cadquery-v1"
        self._update_attempt_chain(attempt, status=attempt.status)
        self.db.commit()

    def _finish_generation_attempt(
        self,
        attempt: GenerationAttempt,
        *,
        status: str,
        failure_class: FailureClass,
        error_message: str | None = None,
        resulting_revision_id: str | None = None,
    ) -> None:
        attempt.status = status
        attempt.failure_class = failure_class.value
        attempt.error_message = error_message
        attempt.resulting_revision_id = resulting_revision_id
        attempt.completed_at = project_utcnow()
        self._update_attempt_chain(attempt, status=status, error_message=error_message)
        self.db.commit()

    def _finish_provider_cancelled_attempt(self, attempt: GenerationAttempt) -> None:
        self._finish_generation_attempt(
            attempt,
            status="failed",
            failure_class=FailureClass.PROVIDER_TIMEOUT,
            error_message="request was cancelled while waiting for the AI provider",
        )

    def _provider_failure_class(self, error_message: str) -> FailureClass:
        if "timed out" in error_message.lower() or "timeout" in error_message.lower():
            return FailureClass.PROVIDER_TIMEOUT
        return FailureClass.PROVIDER_FAILURE

    async def _run_requirement_extraction(
        self,
        *,
        project: Project,
        request: RequirementExtractionRequest,
        superseded_specification_id: str | None = None,
    ) -> DesignSpecificationRead:
        attempt = self._start_requirement_attempt(project=project, request=request)
        try:
            extractor = getattr(self.ai_provider, "extract_requirements")
            extraction_result = await extractor(request)
        except asyncio.CancelledError:
            self._finish_provider_cancelled_attempt(attempt)
            raise
        except RuntimeError as exc:
            self._finish_generation_attempt(
                attempt,
                status="failed",
                failure_class=self._provider_failure_class(str(exc)),
                error_message=str(exc),
            )
            raise

        self._record_generation_result(attempt, extraction_result)
        try:
            parsed_payload = self._parse_design_specification_payload(
                extraction_result.raw_output,
                project_id=project.id,
                generation_attempt_id=attempt.id,
            )
        except (ValueError, ValidationError) as exc:
            self._finish_generation_attempt(
                attempt,
                status="failed",
                failure_class=FailureClass.DESIGN_SPEC_INVALID,
                error_message=str(exc),
            )
            if request.schema_repair_of_raw_output is not None:
                raise RuntimeError("requirement extraction returned invalid Design Specification") from exc
            repair_request = RequirementExtractionRequest(
                project_name=request.project_name,
                original_intent=request.original_intent,
                user_instruction=request.user_instruction,
                previous_specification=request.previous_specification,
                clarification_questions=request.clarification_questions,
                clarification_answers=request.clarification_answers,
                schema_repair_of_raw_output=extraction_result.raw_output,
                schema_validation_error=str(exc),
                defaults=request.defaults,
            )
            return await self._run_requirement_extraction(
                project=project,
                request=repair_request,
                superseded_specification_id=superseded_specification_id,
            )
        inventory = build_explicit_requirement_inventory(request.user_instruction)
        requirement_stage: dict[str, Any] | None = None
        specification_stage: dict[str, Any] | None = None
        if inventory:
            parsed_payload, requirement_stage = validate_requirement_extraction_trace(
                parsed_payload,
                inventory,
            )
            parsed_payload, specification_stage = validate_design_specification_trace(
                parsed_payload,
                inventory,
            )
            parsed_payload["outcome"] = self._derive_requirement_outcome(parsed_payload).value
            parsed_payload["clarification_required"] = (
                parsed_payload["outcome"] == RequirementOutcome.CLARIFICATION_REQUIRED.value
            )
            parsed_payload["generation_ready"] = (
                parsed_payload["outcome"] == RequirementOutcome.GENERATION_READY.value
            )
            self._persist_requirement_trace(
                attempt=attempt,
                inventory=inventory,
                stages=[
                    stage
                    for stage in (requirement_stage, specification_stage)
                    if stage is not None
                ],
            )

        specification = self._persist_design_specification(
            project=project,
            attempt=attempt,
            request=request,
            payload=parsed_payload,
            raw_response_path=attempt.raw_output_path,
            superseded_specification_id=superseded_specification_id,
        )
        self._finish_generation_attempt(
            attempt,
            status="succeeded",
            failure_class=FailureClass.NONE,
        )
        return self._design_specification_read(specification)

    def _persist_requirement_trace(
        self,
        *,
        attempt: GenerationAttempt,
        inventory: list[dict[str, Any]],
        stages: list[dict[str, Any]],
    ) -> str:
        run_dir = self._generation_attempt_dir(attempt.project_id, attempt.id)
        trace_path = run_dir / "requirement-trace.json"
        self._write_json(
            trace_path,
            requirement_trace_payload(
                inventory=inventory,
                resolved_requirements=merge_resolved_requirements(inventory),
                stages=stages,
            ),
        )
        return self._relative(trace_path)

    async def _run_design_planning(
        self,
        *,
        project: Project,
        specification: DesignSpecification,
        request: DesignPlanRequest,
        superseded_design_plan_id: str | None = None,
    ) -> DesignPlanRead:
        attempt = self._start_design_plan_attempt(project=project, request=request)
        try:
            planner = getattr(self.ai_provider, "create_design_plan")
            planning_result = await planner(request)
        except asyncio.CancelledError:
            self._finish_provider_cancelled_attempt(attempt)
            raise
        except RuntimeError as exc:
            self._finish_generation_attempt(
                attempt,
                status="failed",
                failure_class=self._provider_failure_class(str(exc)),
                error_message=str(exc),
            )
            raise

        self._record_generation_result(attempt, planning_result)
        try:
            parsed_payload = self._parse_design_plan_payload(
                planning_result.raw_output,
                project_id=project.id,
                design_specification_id=specification.id,
                generation_attempt_id=attempt.id,
                design_specification_payload=request.design_specification,
                request_context=" ".join(
                    value for value in (request.original_intent, request.user_instruction) if value
                ),
            )
        except (ValueError, ValidationError) as exc:
            self._finish_generation_attempt(
                attempt,
                status="failed",
                failure_class=FailureClass.DESIGN_PLAN_INVALID,
                error_message=str(exc),
            )
            if request.schema_repair_of_raw_output is not None:
                raise RuntimeError("planning returned invalid Design Plan") from exc
            repair_request = DesignPlanRequest(
                project_name=request.project_name,
                original_intent=request.original_intent,
                user_instruction=request.user_instruction,
                design_specification=request.design_specification,
                previous_design_plan=request.previous_design_plan,
                clarification_questions=request.clarification_questions,
                clarification_answers=request.clarification_answers,
                schema_repair_of_raw_output=planning_result.raw_output,
                schema_validation_error=str(exc),
                defaults=request.defaults,
                active_requirements=request.active_requirements,
                requirement_delta=request.requirement_delta,
            )
            return await self._run_design_planning(
                project=project,
                specification=specification,
                request=repair_request,
                superseded_design_plan_id=superseded_design_plan_id,
            )

        plan = self._persist_design_plan(
            project=project,
            specification=specification,
            attempt=attempt,
            payload=parsed_payload,
            raw_response_path=attempt.raw_output_path,
            superseded_design_plan_id=superseded_design_plan_id,
        )
        self._finish_generation_attempt(
            attempt,
            status="succeeded",
            failure_class=FailureClass.NONE,
        )
        return self._design_plan_read(plan)

    async def _run_revision_planning(
        self,
        *,
        project: Project,
        base_revision: Revision,
        design_specification: DesignSpecification | None,
        design_plan: DesignPlan,
        request: RevisionPlanRequest,
        superseded_revision_plan_id: str | None = None,
    ) -> RevisionPlanRead:
        workflow_run = self._start_child_workflow_run(
            project_id=project.id,
            workflow_type="revision_planning",
        )
        attempt = self._start_revision_plan_attempt(
            project=project,
            base_revision_id=base_revision.id,
            request=request,
        )
        self._record_workflow_event(
            workflow_run,
            stage="revision_planning",
            event_type="revision_plan_generation.started",
            severity="summary",
            message="Revision Plan generation started.",
            deduplication_key=f"revision-plan-started-{attempt.id}",
            generation_attempt_id=attempt.id,
            revision_id=base_revision.id,
            design_plan_id=design_plan.id,
            metadata={"base_revision_id": base_revision.id},
        )
        self._record_workflow_artifact(
            workflow_run,
            stage="revision_planning",
            artifact_type="provider_request_metadata",
            role="revision_plan_request",
            relative_path=attempt.request_payload_path,
        )
        self._record_workflow_artifact(
            workflow_run,
            stage="revision_planning",
            artifact_type="rendered_prompt",
            role="revision_plan_prompt",
            relative_path=attempt.prompt_path,
        )
        try:
            planner = getattr(self.ai_provider, "create_revision_plan")
            planning_result = await planner(request)
        except asyncio.CancelledError:
            self._finish_provider_cancelled_attempt(attempt)
            raise
        except RuntimeError as exc:
            self._finish_generation_attempt(
                attempt,
                status="failed",
                failure_class=self._provider_failure_class(str(exc)),
                error_message=str(exc),
            )
            self._workflow_recorder().complete_run(workflow_run, status="failed")
            raise

        self._record_generation_result(attempt, planning_result)
        self._record_workflow_artifact(
            workflow_run,
            stage="revision_planning",
            artifact_type="raw_provider_response",
            role="revision_plan_provider_response",
            relative_path=attempt.raw_output_path,
        )
        try:
            parsed_payload = self._parse_revision_plan_payload(
                planning_result.raw_output,
                project_id=project.id,
                base_revision_id=base_revision.id,
                base_design_specification_id=design_specification.id
                if design_specification is not None
                else None,
                base_design_plan_id=design_plan.id,
                generation_attempt_id=attempt.id,
                design_plan_payload=self._read_design_plan_payload(design_plan),
                active_requirements=request.active_requirements,
                requirement_delta=request.requirement_delta,
            )
        except (ValueError, ValidationError) as exc:
            self._finish_generation_attempt(
                attempt,
                status="failed",
                failure_class=FailureClass.REVISION_REGRESSION,
                error_message=str(exc),
            )
            self._workflow_recorder().complete_run(workflow_run, status="failed")
            if request.schema_repair_of_raw_output is not None:
                raise RuntimeError("revision planning returned invalid Revision Plan") from exc
            repair_request = RevisionPlanRequest(
                project_name=request.project_name,
                original_intent=request.original_intent,
                user_instruction=request.user_instruction,
                reason=request.reason,
                base_revision_id=request.base_revision_id,
                design_specification=request.design_specification,
                design_plan=request.design_plan,
                product_parameters=request.product_parameters,
                dependency_edges=request.dependency_edges,
                components=request.components,
                features=request.features,
                printable_outputs=request.printable_outputs,
                output_manifest=request.output_manifest,
                source_metadata=request.source_metadata,
                selected_findings=request.selected_findings,
                geometric_measurements=request.geometric_measurements,
                clarification_questions=request.clarification_questions,
                clarification_answers=request.clarification_answers,
                previous_revision_plan=request.previous_revision_plan,
                schema_repair_of_raw_output=planning_result.raw_output,
                schema_validation_error=str(exc),
                active_requirements=request.active_requirements,
                requirement_delta=request.requirement_delta,
            )
            return await self._run_revision_planning(
                project=project,
                base_revision=base_revision,
                design_specification=design_specification,
                design_plan=design_plan,
                request=repair_request,
                superseded_revision_plan_id=superseded_revision_plan_id,
            )

        plan = self._persist_revision_plan(
            project=project,
            base_revision=base_revision,
            design_specification=design_specification,
            design_plan=design_plan,
            attempt=attempt,
            payload=parsed_payload,
            raw_response_path=attempt.raw_output_path,
            superseded_revision_plan_id=superseded_revision_plan_id,
        )
        self._record_workflow_artifact(
            workflow_run,
            stage="revision_planning",
            artifact_type="revision_plan",
            role="approved_revision_plan",
            relative_path=plan.plan_path,
        )
        self._record_workflow_event(
            workflow_run,
            stage="revision_planning",
            event_type="revision_plan_generation.completed",
            severity="summary",
            message="Revision Plan generated for review.",
            deduplication_key=f"revision-plan-completed-{plan.id}",
            generation_attempt_id=attempt.id,
            revision_id=base_revision.id,
            revision_plan_id=plan.id,
            design_plan_id=design_plan.id,
            metadata={"review_state": plan.review_state},
        )
        self._finish_generation_attempt(
            attempt,
            status="succeeded",
            failure_class=FailureClass.NONE,
        )
        self._workflow_recorder().complete_run(workflow_run, status="completed")
        return self._revision_plan_read(plan)

    def _start_revision_plan_attempt(
        self,
        *,
        project: Project,
        base_revision_id: str,
        request: RevisionPlanRequest,
    ) -> GenerationAttempt:
        routing = self._routing_for_request(request)
        attempt = GenerationAttempt(
            project_id=project.id,
            base_revision_id=base_revision_id,
            attempt_number=self._next_generation_attempt_number(project.id),
            provider_id=self._provider_name(),
            model_id=routing.get("selected_model") or self._provider_model(),
            provider_settings_json=json.dumps(self._provider_settings(), sort_keys=True),
            routing_metadata_json=json.dumps(routing, sort_keys=True),
            prompt_version=self._revision_plan_prompt_template_version(),
            ruleset_version=self._ruleset_version(),
            request_payload_path="",
            prompt_path="",
            status="started",
            failure_class=FailureClass.NONE.value,
        )
        self.db.add(attempt)
        self.db.flush()

        run_dir = self._generation_attempt_dir(project.id, attempt.id)
        run_dir.mkdir(parents=True, exist_ok=True)
        request_path = run_dir / "request.json"
        prompt_path = run_dir / "prompt.txt"
        design_spec_path = run_dir / "design-spec.json"
        design_plan_path = run_dir / "design-plan.json"
        chain_path = run_dir / "chain.json"

        self._write_json(request_path, asdict(request))
        prompt_path.write_text(self._render_revision_plan_prompt(request), encoding="utf-8")
        if request.design_specification is not None:
            self._write_json(design_spec_path, request.design_specification)
            attempt.design_spec_path = self._relative(design_spec_path)
        self._write_json(design_plan_path, request.design_plan)
        self._write_json(chain_path, self._attempt_chain(attempt, status="started"))

        attempt.request_payload_path = self._relative(request_path)
        attempt.prompt_path = self._relative(prompt_path)
        attempt.design_plan_path = self._relative(design_plan_path)
        attempt.intermediate_artifacts_path = self._relative(chain_path)
        self._update_attempt_chain(attempt, status="started")
        self.db.commit()
        self.db.refresh(attempt)
        return attempt

    def _start_design_plan_attempt(
        self,
        *,
        project: Project,
        request: DesignPlanRequest,
    ) -> GenerationAttempt:
        routing = self._routing_for_request(request)
        attempt = GenerationAttempt(
            project_id=project.id,
            base_revision_id=project.active_revision_id,
            attempt_number=self._next_generation_attempt_number(project.id),
            provider_id=self._provider_name(),
            model_id=routing.get("selected_model") or self._provider_model(),
            provider_settings_json=json.dumps(self._provider_settings(), sort_keys=True),
            routing_metadata_json=json.dumps(routing, sort_keys=True),
            prompt_version=self._design_plan_prompt_template_version(),
            ruleset_version=self._ruleset_version(),
            request_payload_path="",
            prompt_path="",
            status="started",
            failure_class=FailureClass.NONE.value,
        )
        self.db.add(attempt)
        self.db.flush()

        run_dir = self._generation_attempt_dir(project.id, attempt.id)
        run_dir.mkdir(parents=True, exist_ok=True)
        request_path = run_dir / "request.json"
        prompt_path = run_dir / "prompt.txt"
        design_spec_path = run_dir / "design-spec.json"
        chain_path = run_dir / "chain.json"

        self._write_json(request_path, asdict(request))
        prompt_path.write_text(self._render_design_plan_prompt(request), encoding="utf-8")
        self._write_json(design_spec_path, request.design_specification)
        self._write_json(chain_path, self._attempt_chain(attempt, status="started"))

        attempt.request_payload_path = self._relative(request_path)
        attempt.prompt_path = self._relative(prompt_path)
        attempt.design_spec_path = self._relative(design_spec_path)
        attempt.intermediate_artifacts_path = self._relative(chain_path)
        self._update_attempt_chain(attempt, status="started")
        self.db.commit()
        self.db.refresh(attempt)
        return attempt

    def _start_requirement_attempt(
        self,
        *,
        project: Project,
        request: RequirementExtractionRequest,
    ) -> GenerationAttempt:
        routing = self._routing_for_request(request)
        attempt = GenerationAttempt(
            project_id=project.id,
            base_revision_id=project.active_revision_id,
            attempt_number=self._next_generation_attempt_number(project.id),
            provider_id=self._provider_name(),
            model_id=routing.get("selected_model") or self._provider_model(),
            provider_settings_json=json.dumps(self._provider_settings(), sort_keys=True),
            routing_metadata_json=json.dumps(routing, sort_keys=True),
            prompt_version=self._requirement_prompt_template_version(),
            ruleset_version=self._ruleset_version(),
            request_payload_path="",
            prompt_path="",
            status="started",
            failure_class=FailureClass.NONE.value,
        )
        self.db.add(attempt)
        self.db.flush()

        run_dir = self._generation_attempt_dir(project.id, attempt.id)
        run_dir.mkdir(parents=True, exist_ok=True)
        request_path = run_dir / "request.json"
        prompt_path = run_dir / "prompt.txt"
        chain_path = run_dir / "chain.json"

        self._write_json(request_path, asdict(request))
        prompt_path.write_text(self._render_requirement_prompt(request), encoding="utf-8")
        self._write_json(chain_path, self._attempt_chain(attempt, status="started"))

        attempt.request_payload_path = self._relative(request_path)
        attempt.prompt_path = self._relative(prompt_path)
        attempt.intermediate_artifacts_path = self._relative(chain_path)
        self._update_attempt_chain(attempt, status="started")
        self.db.commit()
        self.db.refresh(attempt)
        return attempt

    def _parse_design_specification_payload(
        self,
        raw_output: str,
        *,
        project_id: str,
        generation_attempt_id: str,
    ) -> dict[str, Any]:
        json_text = self._extract_json_response(raw_output)
        payload = json.loads(json_text)
        payload["project_id"] = project_id
        payload["generation_attempt_id"] = generation_attempt_id
        if "schema_version" not in payload:
            payload["schema_version"] = DESIGN_SPEC_SCHEMA_VERSION
        payload = self._normalize_design_specification_payload(payload)
        validated = DesignSpecificationPayload.model_validate(payload)
        normalized = validated.model_dump(mode="json")
        outcome = self._derive_requirement_outcome(normalized)
        normalized["outcome"] = outcome.value
        normalized["clarification_required"] = outcome == RequirementOutcome.CLARIFICATION_REQUIRED
        normalized["generation_ready"] = outcome == RequirementOutcome.GENERATION_READY
        if outcome == RequirementOutcome.UNSUPPORTED_REQUEST:
            normalized["supported_scope"] = False
        return normalized

    def _normalize_design_specification_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        normalized["parameters"] = [
            self._normalize_design_parameter(item, index)
            for index, item in enumerate(normalized.get("parameters") or [])
        ]
        normalized["functional_requirements"] = [
            self._normalize_functional_requirement(item, index)
            for index, item in enumerate(normalized.get("functional_requirements") or [])
        ]
        normalized["assumptions"] = [
            self._normalize_design_assumption(item, index)
            for index, item in enumerate(normalized.get("assumptions") or [])
        ]
        normalized["missing_requirements"] = [
            self._normalize_missing_requirement(item, index)
            for index, item in enumerate(normalized.get("missing_requirements") or [])
        ]
        return normalized

    def _normalize_design_parameter(self, item: object, index: int) -> object:
        if not isinstance(item, dict):
            return item
        normalized = dict(item)
        normalized.setdefault("id", f"parameter_{index + 1}")
        normalized.setdefault("label", normalized.get("name") or self._human_label(str(normalized["id"])))
        if "value" not in normalized and "default_value" in normalized:
            normalized["value"] = normalized["default_value"]
        normalized.setdefault("source", RequirementSource.AI_ASSUMPTION.value)
        normalized.setdefault("importance", RequirementImportance.IMPORTANT.value)
        normalized.setdefault("protected", False)
        normalized.setdefault("editable", True)
        return normalized

    def _normalize_functional_requirement(self, item: object, index: int) -> object:
        if isinstance(item, str):
            description = item
            normalized: dict[str, Any] = {"description": description}
        elif isinstance(item, dict):
            normalized = dict(item)
            description = str(normalized.get("description") or normalized.get("requirement") or "")
            if description:
                normalized["description"] = description
        else:
            return item
        description = str(normalized.get("description") or f"Functional requirement {index + 1}")
        normalized.setdefault("id", self._safe_identifier(description, fallback=f"functional_requirement_{index + 1}"))
        normalized.setdefault("source", RequirementSource.USER.value)
        normalized.setdefault("importance", self._importance_from_priority(normalized.get("priority")))
        normalized.setdefault(
            "protected",
            normalized.get("importance") == RequirementImportance.CRITICAL.value,
        )
        return normalized

    def _normalize_design_assumption(self, item: object, index: int) -> object:
        if isinstance(item, str):
            description = item
            normalized: dict[str, Any] = {"description": description}
        elif isinstance(item, dict):
            normalized = dict(item)
            description = str(
                normalized.get("description")
                or normalized.get("assumption")
                or normalized.get("text")
                or ""
            )
            if description:
                normalized["description"] = description
        else:
            return item
        description = str(normalized.get("description") or f"Assumption {index + 1}")
        normalized.setdefault("id", self._safe_identifier(description, fallback=f"assumption_{index + 1}"))
        if normalized.get("source") not in {
            RequirementSource.PRODUCT_DEFAULT.value,
            RequirementSource.PRINTER_PROFILE.value,
            RequirementSource.AI_ASSUMPTION.value,
            RequirementSource.CALCULATED.value,
        }:
            normalized["source"] = RequirementSource.AI_ASSUMPTION.value
        normalized.setdefault("requires_approval", False)
        return normalized

    def _normalize_missing_requirement(self, item: object, index: int) -> object:
        if isinstance(item, str):
            return {
                "id": self._safe_identifier(item, fallback=f"missing_requirement_{index + 1}"),
                "description": item,
                "source": RequirementSource.USER.value,
                "importance": RequirementImportance.CRITICAL.value,
                "reason": item,
            }
        if isinstance(item, dict):
            normalized = dict(item)
            description = str(
                normalized.get("description")
                or normalized.get("label")
                or normalized.get("reason")
                or f"Missing requirement {index + 1}"
            )
            normalized.setdefault(
                "id",
                self._safe_identifier(description, fallback=f"missing_requirement_{index + 1}"),
            )
            normalized.setdefault("description", description)
            normalized.setdefault("source", RequirementSource.USER.value)
            normalized.setdefault("importance", RequirementImportance.CRITICAL.value)
            return normalized
        return item

    def _importance_from_priority(self, priority: object) -> str:
        if isinstance(priority, str) and priority.lower() in {"high", "critical", "required"}:
            return RequirementImportance.CRITICAL.value
        if isinstance(priority, str) and priority.lower() in {"low", "optional", "cosmetic"}:
            return RequirementImportance.OPTIONAL.value
        return RequirementImportance.IMPORTANT.value

    def _safe_identifier(self, value: str, *, fallback: str) -> str:
        identifier = re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")
        return identifier[:120] or fallback

    def _human_label(self, value: str) -> str:
        return re.sub(r"[_-]+", " ", value).strip().title() or value

    def _extract_json_response(self, raw_output: str) -> str:
        stripped = raw_output.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL)
        return fenced.group(1).strip() if fenced else stripped

    def _derive_requirement_outcome(self, payload: dict[str, Any]) -> RequirementOutcome:
        explicit = payload.get("outcome")
        if explicit:
            return RequirementOutcome(explicit)
        if not payload.get("supported_scope", True):
            return RequirementOutcome.UNSUPPORTED_REQUEST
        if payload.get("conflicts"):
            return RequirementOutcome.REQUIREMENTS_CONFLICT
        if payload.get("clarification_required") or payload.get("clarification_questions"):
            return RequirementOutcome.CLARIFICATION_REQUIRED
        if payload.get("generation_ready"):
            return RequirementOutcome.GENERATION_READY
        return RequirementOutcome.EXTRACTION_FAILED

    def _parse_design_plan_payload(
        self,
        raw_output: str,
        *,
        project_id: str,
        design_specification_id: str,
        generation_attempt_id: str,
        design_specification_payload: dict[str, Any] | None = None,
        request_context: str | None = None,
    ) -> dict[str, Any]:
        json_text = self._extract_json_response(raw_output)
        payload = json.loads(json_text)
        payload["project_id"] = project_id
        payload["design_specification_id"] = design_specification_id
        payload["generation_attempt_id"] = generation_attempt_id
        if "schema_version" not in payload:
            payload["schema_version"] = DESIGN_PLAN_SCHEMA_VERSION
        validated = DesignPlanPayload.model_validate(payload)
        normalized = validated.model_dump(mode="json", by_alias=True)
        normalized = resolve_retention_proposals(normalized)
        normalized = normalize_plan_provenance(
            normalized,
            design_specification_payload,
        )
        normalized = normalize_plan_constraints(
            normalized,
            request_context=request_context,
        )
        normalized = normalize_pattern_specs(normalized)
        validate_pattern_specs(normalized)
        outcome = self._derive_design_plan_outcome(normalized)
        normalized["outcome"] = outcome.value
        normalized["clarification_required"] = (
            outcome == DesignPlanOutcome.PLAN_CLARIFICATION_REQUIRED
        )
        normalized["plan_ready"] = outcome == DesignPlanOutcome.PLAN_READY
        provenance_findings = validate_plan_provenance(
            normalized,
            design_specification_payload,
        )
        if any(finding.get("is_blocking") for finding in provenance_findings):
            raise ValueError(
                "Design Plan provenance validation failed: "
                + "; ".join(str(finding.get("rule_id")) for finding in provenance_findings)
            )
        self._validate_design_plan_source_requirement_links(
            normalized,
            design_specification_payload=design_specification_payload,
        )
        functional_findings = validate_functional_plan(normalized)
        if any(finding.get("is_blocking") for finding in functional_findings):
            raise ValueError(
                "Functional Design Plan validation failed: "
                + "; ".join(str(finding.get("rule_id")) for finding in functional_findings)
            )
        if functional_findings:
            normalized["functional_validation_findings"] = functional_findings
        explicit_inventory = inventory_from_design_specification(design_specification_payload)
        if explicit_inventory:
            validate_design_plan_trace(normalized, explicit_inventory)
        self._validate_design_plan_dependency_edges(normalized)
        return normalized

    def _validate_design_plan_source_requirement_links(
        self,
        payload: dict[str, Any],
        *,
        design_specification_payload: dict[str, Any] | None,
    ) -> None:
        if payload.get("outcome") != DesignPlanOutcome.PLAN_READY.value:
            return
        if not design_specification_payload:
            return
        source_values = self._numeric_design_specification_values(design_specification_payload)
        violations: list[str] = []
        for parameter in payload.get("parameters", []):
            if not isinstance(parameter, dict):
                continue
            source_id = parameter.get("source_requirement_id")
            if not source_id or source_id not in source_values:
                continue
            provenance = parameter.get("provenance")
            if isinstance(provenance, dict) and provenance.get("relationship") not in {None, "direct"}:
                continue
            expected = source_values[source_id]
            detected = self._to_float(parameter.get("value"))
            if detected is None:
                violations.append(
                    f"Design Plan parameter {parameter.get('id')} is linked to numeric source "
                    f"requirement {source_id} but has a non-numeric value."
                )
                continue
            parameter_unit = parameter.get("unit")
            expected_unit = expected.get("unit")
            if parameter_unit and expected_unit and parameter_unit != expected_unit:
                violations.append(
                    f"Design Plan parameter {parameter.get('id')} unit {parameter_unit} "
                    f"does not match source requirement {source_id} unit {expected_unit}."
                )
            expected_value = expected["value"]
            tolerance = expected["tolerance"]
            if abs(detected - expected_value) > tolerance:
                violations.append(
                    f"Design Plan parameter {parameter.get('id')} value {detected:g} "
                    f"does not match source requirement {source_id} value {expected_value:g} "
                    f"within tolerance {tolerance:g}. Use a derived parameter for calculated "
                    "stack, envelope, or overall product dimensions."
                )
        if violations:
            raise ValueError("\n".join(violations))

    def _validate_design_plan_dependency_edges(self, payload: dict[str, Any]) -> None:
        if payload.get("outcome") != DesignPlanOutcome.PLAN_READY.value:
            return
        parameter_ids = {
            str(parameter.get("id"))
            for parameter in payload.get("parameters", [])
            if isinstance(parameter, dict) and parameter.get("id")
        }
        derived_ids = {
            str(parameter.get("id"))
            for parameter in payload.get("derived_parameters", [])
            if isinstance(parameter, dict) and parameter.get("id")
        }
        known_ids = parameter_ids | derived_ids
        violations: list[str] = []
        for index, edge in enumerate(payload.get("dependency_edges", []), start=1):
            if not isinstance(edge, dict):
                continue
            from_id = str(edge.get("from") or edge.get("from_") or "")
            to_id = str(edge.get("to") or "")
            if from_id and from_id not in known_ids:
                violations.append(
                    f"Design Plan dependency edge {index} references unknown source "
                    f"parameter {from_id}. Add it to parameters or derived_parameters."
                )
            if to_id and to_id not in known_ids:
                violations.append(
                    f"Design Plan dependency edge {index} references unknown target "
                    f"parameter {to_id}. Add it to derived_parameters or remove the edge. "
                    "Feature dependencies belong in feature.parameters, not dependency_edges."
                )
        if violations:
            raise ValueError("\n".join(violations))

    def _numeric_design_specification_values(
        self,
        payload: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        values: dict[str, dict[str, Any]] = {}
        for collection_name in ("critical_dimensions", "parameters"):
            for entry in payload.get(collection_name, []):
                if not isinstance(entry, dict):
                    continue
                entry_id = entry.get("id")
                value = self._to_float(entry.get("value"))
                if not entry_id or value is None:
                    continue
                tolerance = self._to_float(entry.get("tolerance"))
                values[str(entry_id)] = {
                    "value": value,
                    "unit": entry.get("unit"),
                    "tolerance": tolerance if tolerance is not None else 1e-6,
                }
        return values

    def _to_float(self, value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _derive_design_plan_outcome(self, payload: dict[str, Any]) -> DesignPlanOutcome:
        explicit = payload.get("outcome")
        if explicit:
            return DesignPlanOutcome(explicit)
        if payload.get("clarification_required") or payload.get("clarification_questions"):
            return DesignPlanOutcome.PLAN_CLARIFICATION_REQUIRED
        if payload.get("plan_ready"):
            return DesignPlanOutcome.PLAN_READY
        return DesignPlanOutcome.PLAN_FAILED

    def _parse_revision_plan_payload(
        self,
        raw_output: str,
        *,
        project_id: str,
        base_revision_id: str,
        base_design_specification_id: str | None,
        base_design_plan_id: str | None,
        generation_attempt_id: str,
        design_plan_payload: dict[str, Any] | None = None,
        active_requirements: list[dict[str, Any]] | None = None,
        requirement_delta: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        json_text = self._extract_json_response(raw_output)
        payload = json.loads(json_text)
        payload["project_id"] = project_id
        payload["base_revision_id"] = base_revision_id
        payload["base_design_specification_id"] = base_design_specification_id
        payload["base_design_plan_id"] = base_design_plan_id
        payload["generation_attempt_id"] = generation_attempt_id
        payload["schema_version"] = str(payload.get("schema_version") or REVISION_PLAN_SCHEMA_VERSION)
        validated = RevisionPlanPayload.model_validate(payload)
        normalized = validated.model_dump(mode="json")
        outcome = self._derive_revision_plan_outcome(normalized)
        normalized["outcome"] = outcome.value
        normalized["clarification_required"] = outcome == RevisionPlanOutcome.CLARIFICATION_REQUIRED
        normalized["revision_ready"] = outcome == RevisionPlanOutcome.REVISION_READY
        normalized["active_requirements"] = list(active_requirements or [])
        normalized["requirement_delta"] = list(requirement_delta or [])
        criteria_findings = validate_revision_success_criteria(
            normalized,
            plan=design_plan_payload,
        )
        if any(finding.get("is_blocking") for finding in criteria_findings):
            raise ValueError(
                "Revision success criteria validation failed: "
                + "; ".join(str(finding.get("rule_id")) for finding in criteria_findings)
            )
        return normalized

    def _derive_revision_plan_outcome(self, payload: dict[str, Any]) -> RevisionPlanOutcome:
        explicit = payload.get("outcome")
        if explicit:
            return RevisionPlanOutcome(explicit)
        if payload.get("clarification_questions"):
            return RevisionPlanOutcome.CLARIFICATION_REQUIRED
        if payload.get("requested_changes"):
            return RevisionPlanOutcome.REVISION_READY
        return RevisionPlanOutcome.PLANNING_FAILED

    def _persist_design_specification(
        self,
        *,
        project: Project,
        attempt: GenerationAttempt,
        request: RequirementExtractionRequest,
        payload: dict[str, Any],
        raw_response_path: str | None,
        superseded_specification_id: str | None,
    ) -> DesignSpecification:
        run_dir = self._generation_attempt_dir(project.id, attempt.id)
        spec_path = run_dir / "parsed-design-spec.json"
        self._write_json(spec_path, payload)
        content_hash = self._sha256(json.dumps(payload, sort_keys=True))
        attempt.design_spec_path = self._relative(spec_path)
        specification = DesignSpecification(
            project_id=project.id,
            generation_attempt_id=attempt.id,
            superseded_specification_id=superseded_specification_id,
            version_number=self._next_design_specification_version(project.id),
            schema_version=str(payload.get("schema_version", DESIGN_SPEC_SCHEMA_VERSION)),
            prompt_template_version=attempt.prompt_version,
            ruleset_version=attempt.ruleset_version,
            provider=attempt.provider_id,
            provider_model=attempt.model_id,
            user_instruction=request.user_instruction,
            raw_response_path=raw_response_path,
            specification_path=self._relative(spec_path),
            content_hash=content_hash,
            outcome=str(payload["outcome"]),
            supported_scope=bool(payload.get("supported_scope", True)),
            clarification_required=bool(payload.get("clarification_required", False)),
            generation_ready=bool(payload.get("generation_ready", False)),
        )
        self.db.add(specification)
        self.db.flush()
        for index, question_payload in enumerate(payload.get("clarification_questions", [])):
            self.db.add(
                ClarificationQuestion(
                    project_id=project.id,
                    design_specification_id=specification.id,
                    requirement_id=question_payload.get("related_requirement_id")
                    or question_payload.get("id"),
                    question=question_payload["question"],
                    reason=question_payload.get("reason"),
                    display_order=index,
                )
            )
        self.db.flush()
        self._update_attempt_chain(attempt, status=attempt.status)
        self.db.commit()
        self.db.refresh(specification)
        return specification

    def _persist_design_plan(
        self,
        *,
        project: Project,
        specification: DesignSpecification,
        attempt: GenerationAttempt,
        payload: dict[str, Any],
        raw_response_path: str | None,
        superseded_design_plan_id: str | None,
    ) -> DesignPlan:
        run_dir = self._generation_attempt_dir(project.id, attempt.id)
        plan_path = run_dir / "parsed-design-plan.json"
        self._write_json(plan_path, payload)
        content_hash = self._sha256(json.dumps(payload, sort_keys=True))
        attempt.design_plan_path = self._relative(plan_path)
        if payload["outcome"] == DesignPlanOutcome.PLAN_READY.value:
            review_state = DesignPlanReviewState.PENDING_REVIEW
        elif payload["outcome"] == DesignPlanOutcome.PLAN_CLARIFICATION_REQUIRED.value:
            review_state = DesignPlanReviewState.CLARIFICATION_REQUIRED
        else:
            review_state = DesignPlanReviewState.REJECTED
        plan = DesignPlan(
            project_id=project.id,
            design_specification_id=specification.id,
            generation_attempt_id=attempt.id,
            superseded_design_plan_id=superseded_design_plan_id,
            version_number=self._next_design_plan_version(project.id),
            schema_version=str(payload.get("schema_version", DESIGN_PLAN_SCHEMA_VERSION)),
            prompt_template_version=attempt.prompt_version,
            ruleset_version=attempt.ruleset_version,
            provider=attempt.provider_id,
            provider_model=attempt.model_id,
            raw_response_path=raw_response_path,
            plan_path=self._relative(plan_path),
            content_hash=content_hash,
            outcome=str(payload["outcome"]),
            review_state=review_state.value,
            clarification_required=bool(payload.get("clarification_required", False)),
            plan_ready=bool(payload.get("plan_ready", False)),
        )
        self.db.add(plan)
        self.db.flush()
        for index, question_payload in enumerate(payload.get("clarification_questions", [])):
            question_text = str(question_payload.get("question") or "").strip()
            if not question_text:
                continue
            self.db.add(
                DesignPlanClarificationQuestion(
                    project_id=project.id,
                    design_plan_id=plan.id,
                    related_plan_field=question_payload.get("related_plan_field")
                    or question_payload.get("plan_field")
                    or question_payload.get("id"),
                    question=question_text,
                    reason=question_payload.get("reason"),
                    display_order=index,
                )
            )
        self._update_attempt_chain(attempt, status=attempt.status)
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def _persist_revision_plan(
        self,
        *,
        project: Project,
        base_revision: Revision,
        design_specification: DesignSpecification | None,
        design_plan: DesignPlan,
        attempt: GenerationAttempt,
        payload: dict[str, Any],
        raw_response_path: str | None,
        superseded_revision_plan_id: str | None,
    ) -> RevisionPlan:
        run_dir = self._generation_attempt_dir(project.id, attempt.id)
        plan_path = run_dir / "parsed-revision-plan.json"
        base_source = self.read_revision_source(base_revision.id) or ""
        base_manifest = self.read_output_manifest(base_revision.id) or {}
        base_spec_payload = (
            self._read_design_specification_payload(design_specification)
            if design_specification is not None
            else None
        )
        base_plan_payload = self._read_design_plan_payload(design_plan)
        attempt.design_plan_path = self._relative(plan_path)
        if payload["outcome"] == RevisionPlanOutcome.REVISION_READY.value:
            review_state = RevisionPlanReviewState.PENDING_REVIEW
        elif payload["outcome"] == RevisionPlanOutcome.CLARIFICATION_REQUIRED.value:
            review_state = RevisionPlanReviewState.CLARIFICATION_REQUIRED
        else:
            review_state = RevisionPlanReviewState.REJECTED
        request_instruction = self._revision_plan_request_instruction(attempt)
        requested_controls = explicit_control_requests(base_plan_payload, request_instruction)
        if requested_controls:
            payload["requires_design_plan_version"] = True
            payload["requested_exposed_controls"] = requested_controls
        self._write_json(plan_path, payload)
        content_hash = self._sha256(json.dumps(payload, sort_keys=True))

        plan = RevisionPlan(
            project_id=project.id,
            base_revision_id=base_revision.id,
            base_design_specification_id=design_specification.id if design_specification else None,
            base_design_plan_id=design_plan.id,
            generation_attempt_id=attempt.id,
            superseded_revision_plan_id=superseded_revision_plan_id,
            version_number=self._next_revision_plan_version(project.id),
            schema_version=str(payload.get("schema_version", REVISION_PLAN_SCHEMA_VERSION)),
            prompt_template_version=attempt.prompt_version,
            ruleset_version=attempt.ruleset_version,
            provider=attempt.provider_id,
            provider_model=attempt.model_id,
            user_instruction=str(payload.get("user_instruction") or attempt.project.original_intent)
            if getattr(attempt, "project", None) is not None
            else str(payload.get("summary") or ""),
            reason=str(payload.get("reason") or "user_request"),
            raw_response_path=raw_response_path,
            plan_path=self._relative(plan_path),
            content_hash=content_hash,
            base_source_hash=self._sha256(base_source) if base_source else None,
            base_output_manifest_hash=self._sha256(json.dumps(base_manifest, sort_keys=True)),
            base_design_specification_hash=self._sha256(json.dumps(base_spec_payload, sort_keys=True))
            if base_spec_payload is not None
            else None,
            base_design_plan_hash=self._sha256(json.dumps(base_plan_payload, sort_keys=True)),
            outcome=str(payload["outcome"]),
            review_state=review_state.value,
            clarification_required=bool(payload.get("clarification_required", False)),
            revision_ready=bool(payload.get("revision_ready", False)),
        )
        plan.user_instruction = request_instruction
        self.db.add(plan)
        self.db.flush()
        for index, question_payload in enumerate(payload.get("clarification_questions", [])):
            self.db.add(
                RevisionPlanClarificationQuestion(
                    project_id=project.id,
                    revision_plan_id=plan.id,
                    requirement_id=question_payload.get("related_requirement_id")
                    or question_payload.get("id"),
                    question=question_payload["question"],
                    reason=question_payload.get("reason"),
                    display_order=index,
                )
            )
        if payload.get("requires_design_specification_version") and base_spec_payload is not None:
            revised_spec = self._persist_revision_specification_snapshot(
                project=project,
                base_specification=design_specification,
                revision_plan=plan,
                base_payload=base_spec_payload,
                revision_plan_payload=payload,
            )
            plan.revised_design_specification_id = revised_spec.id
        if payload.get("requires_design_plan_version"):
            revised_plan = self._persist_revision_design_plan_snapshot(
                project=project,
                base_plan=design_plan,
                revision_plan=plan,
                base_payload=base_plan_payload,
                revision_plan_payload=payload,
            )
            plan.revised_design_plan_id = revised_plan.id
        self.db.flush()
        self._update_attempt_chain(attempt, status=attempt.status)
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def _revision_plan_request_instruction(self, attempt: GenerationAttempt) -> str:
        if not attempt.request_payload_path:
            return ""
        payload = self._read_json_file(attempt.request_payload_path) or {}
        return str(payload.get("user_instruction") or "")

    def _update_attempt_chain(
        self,
        attempt: GenerationAttempt,
        *,
        status: str,
        error_message: str | None = None,
    ) -> None:
        if not attempt.intermediate_artifacts_path:
            return
        chain_path = self.data_dir / attempt.intermediate_artifacts_path
        self._write_json(
            chain_path,
            self._attempt_chain(attempt, status=status, error_message=error_message),
        )

    def _attempt_chain(
        self,
        attempt: GenerationAttempt,
        *,
        status: str,
        error_message: str | None = None,
    ) -> dict:
        source_validation = self.db.scalar(
            select(SourceValidationResult)
            .where(SourceValidationResult.generation_attempt_id == attempt.id)
            .order_by(SourceValidationResult.created_at.desc())
        )
        return {
            "chain_version": "generation-chain-v1",
            "attempt_id": attempt.id,
            "status": status,
            "failure_class": attempt.failure_class,
            "error_message": error_message,
            "stages": [
                {
                    "stage": "cadquery_generation",
                    "prompt_version": attempt.prompt_version,
                    "ruleset_version": attempt.ruleset_version,
                    "request_payload_path": attempt.request_payload_path,
                    "prompt_path": attempt.prompt_path,
                    "raw_output_path": attempt.raw_output_path,
                    "source_path": attempt.source_path,
                    "design_spec_path": attempt.design_spec_path,
                    "design_plan_path": attempt.design_plan_path,
                    "source_contract_result_path": source_validation.result_path
                    if source_validation is not None
                    else None,
                    "source_contract_version": source_validation.contract_version
                    if source_validation is not None
                    else None,
                    "source_contract_passed_hard_checks": source_validation.passed_hard_checks
                    if source_validation is not None
                    else None,
                    "source_hash": attempt.source_hash,
                    "output_hash": attempt.output_hash,
                }
            ],
        }

    def _cadquery_design_spec_placeholder(self, request: ModelGenerationRequest) -> dict:
        return {
            "design_specification_version": "cadquery-design-spec-placeholder-v1",
            "artifact_status": "placeholder_until_staged_requirements",
            "sources": [
                "user",
                "clarification",
                "calculated",
                "printer_profile",
                "product_default",
                "ai_assumption",
            ],
            "project_name": {"value": request.project_name, "source": "user"},
            "original_intent": {"value": request.original_intent, "source": "user"},
            "user_instruction": {"value": request.user_instruction, "source": "user"},
        }

    def _render_prompt(self, request: ModelGenerationRequest) -> str:
        build_cadquery_prompt = getattr(self.ai_provider, "build_cadquery_prompt", None)
        if callable(build_cadquery_prompt):
            return build_cadquery_prompt(request)
        return ""

    def _render_requirement_prompt(self, request: RequirementExtractionRequest) -> str:
        build_prompt = getattr(self.ai_provider, "build_requirement_prompt", None)
        if callable(build_prompt):
            return build_prompt(request)
        return ""

    def _render_design_plan_prompt(self, request: DesignPlanRequest) -> str:
        build_prompt = getattr(self.ai_provider, "build_design_plan_prompt", None)
        if callable(build_prompt):
            return build_prompt(request)
        return ""

    def _render_revision_plan_prompt(self, request: RevisionPlanRequest) -> str:
        build_prompt = getattr(self.ai_provider, "build_revision_plan_prompt", None)
        if callable(build_prompt):
            return build_prompt(request)
        return ""

    def _prompt_template_version(self, request: ModelGenerationRequest) -> str:
        if request.geometry_body_diagnostics:
            return CADQUERY_GEOMETRY_BODY_REPAIR_PROMPT_VERSION
        if request.generation_contract_version == SCAFFOLD_VERSION:
            return CADQUERY_GEOMETRY_BODY_PROMPT_VERSION
        if request.compiler_diagnostics:
            return "cadquery-execution-repair-v2"
        if request.contract_diagnostics:
            return "cadquery-contract-repair-v2"
        if request.scope_diagnostics:
            return "cadquery-scope-correction-v2"
        if request.revision_plan and request.scoped_revision_context:
            return "cadquery-component-revision-v2"
        if request.revision_plan:
            return "cadquery-revision-v1"
        version = getattr(self.ai_provider, "cadquery_prompt_template_version", None)
        if callable(version):
            return str(version())
        return "cadquery-generation-v1"

    def _provider_cadquery_prompt_template_version(self) -> str:
        version = getattr(self.ai_provider, "cadquery_prompt_template_version", None)
        if callable(version):
            return str(version())
        return CADQUERY_GENERATION_PROMPT_VERSION

    def _requirement_prompt_template_version(self) -> str:
        version = getattr(self.ai_provider, "requirement_prompt_template_version", None)
        if callable(version):
            return str(version())
        return REQUIREMENTS_PROMPT_VERSION

    def _design_plan_prompt_template_version(self) -> str:
        version = getattr(self.ai_provider, "design_plan_prompt_template_version", None)
        if callable(version):
            return str(version())
        return DESIGN_PLAN_PROMPT_VERSION

    def _revision_plan_prompt_template_version(self) -> str:
        version = getattr(self.ai_provider, "revision_plan_prompt_template_version", None)
        if callable(version):
            return str(version())
        return REVISION_PLAN_PROMPT_VERSION

    def _ruleset_version(self) -> str:
        return str(getattr(self.ai_provider, "ruleset_version", "gemini-ruleset-v1"))

    def _provider_name(self) -> str:
        return type(self.ai_provider).__name__ if self.ai_provider is not None else "unknown"

    def _provider_model(self) -> str | None:
        model = getattr(self.ai_provider, "model", None)
        return str(model) if model is not None else None

    def _provider_settings(self) -> dict:
        provider_settings = getattr(self.ai_provider, "provider_settings", None)
        if callable(provider_settings):
            return provider_settings()
        settings_payload: dict[str, str | int | None] = {}
        for name in ("model", "binary", "timeout_seconds"):
            value = getattr(self.ai_provider, name, None)
            if value is not None:
                settings_payload[name] = value
        return settings_payload

    def _application_commit(self) -> str | None:
        configured = getattr(settings, "application_commit", None)
        if configured:
            return str(configured)
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.data_dir.parent if self.data_dir.name == "data" else Path.cwd(),
                check=False,
                capture_output=True,
                text=True,
                timeout=1,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        commit = result.stdout.strip()
        return commit or None

    def _latest_design_specification(self, project_id: str) -> DesignSpecification | None:
        return self.db.scalar(
            select(DesignSpecification)
            .where(DesignSpecification.project_id == project_id)
            .order_by(DesignSpecification.version_number.desc())
        )

    def _latest_design_plan(
        self,
        project_id: str,
        *,
        specification_id: str | None = None,
    ) -> DesignPlan | None:
        query = select(DesignPlan).where(DesignPlan.project_id == project_id)
        if specification_id is not None:
            query = query.where(DesignPlan.design_specification_id == specification_id)
        return self.db.scalar(query.order_by(DesignPlan.version_number.desc()))

    def _latest_revision_plan(
        self,
        project_id: str,
        *,
        base_revision_id: str | None = None,
    ) -> RevisionPlan | None:
        query = select(RevisionPlan).where(RevisionPlan.project_id == project_id)
        if base_revision_id is not None:
            query = query.where(RevisionPlan.base_revision_id == base_revision_id)
        return self.db.scalar(query.order_by(RevisionPlan.version_number.desc()))

    def _has_newer_design_specification(self, specification: DesignSpecification) -> bool:
        latest_version = self.db.scalar(
            select(func.max(DesignSpecification.version_number)).where(
                DesignSpecification.project_id == specification.project_id
            )
        )
        return latest_version is not None and int(latest_version) > specification.version_number

    def _has_newer_design_plan(self, plan: DesignPlan) -> bool:
        latest_version = self.db.scalar(
            select(func.max(DesignPlan.version_number)).where(
                DesignPlan.project_id == plan.project_id,
                DesignPlan.design_specification_id == plan.design_specification_id,
            )
        )
        return latest_version is not None and int(latest_version) > plan.version_number

    def _has_newer_revision_plan(self, plan: RevisionPlan) -> bool:
        latest_version = self.db.scalar(
            select(func.max(RevisionPlan.version_number)).where(
                RevisionPlan.project_id == plan.project_id,
                RevisionPlan.base_revision_id == plan.base_revision_id,
            )
        )
        return latest_version is not None and int(latest_version) > plan.version_number

    def _read_design_specification_payload(
        self,
        specification: DesignSpecification,
    ) -> dict[str, Any]:
        path = self.data_dir / specification.specification_path
        return json.loads(path.read_text(encoding="utf-8"))

    def _read_design_plan_payload(
        self,
        plan: DesignPlan,
    ) -> dict[str, Any]:
        path = self.data_dir / plan.plan_path
        return json.loads(path.read_text(encoding="utf-8"))

    def _read_revision_plan_payload(
        self,
        plan: RevisionPlan,
    ) -> dict[str, Any]:
        path = self.data_dir / plan.plan_path
        return json.loads(path.read_text(encoding="utf-8"))

    def _design_specification_read(
        self,
        specification: DesignSpecification,
    ) -> DesignSpecificationRead:
        questions = list(
            self.db.scalars(
                select(ClarificationQuestion)
                .where(ClarificationQuestion.design_specification_id == specification.id)
                .order_by(ClarificationQuestion.display_order.asc())
            )
        )
        return DesignSpecificationRead(
            id=specification.id,
            project_id=specification.project_id,
            generation_attempt_id=specification.generation_attempt_id,
            superseded_specification_id=specification.superseded_specification_id,
            version_number=specification.version_number,
            schema_version=specification.schema_version,
            prompt_template_version=specification.prompt_template_version,
            ruleset_version=specification.ruleset_version,
            provider=specification.provider,
            provider_model=specification.provider_model,
            user_instruction=specification.user_instruction,
            raw_response_path=specification.raw_response_path,
            specification_path=specification.specification_path,
            content_hash=specification.content_hash,
            outcome=RequirementOutcome(specification.outcome),
            supported_scope=specification.supported_scope,
            clarification_required=specification.clarification_required,
            generation_ready=specification.generation_ready,
            created_at=specification.created_at,
            specification=self._read_design_specification_payload(specification),
            clarification_questions=[
                ClarificationQuestionRead.model_validate(question) for question in questions
            ],
        )

    def _design_plan_read(
        self,
        plan: DesignPlan,
    ) -> DesignPlanRead:
        questions = list(
            self.db.scalars(
                select(DesignPlanClarificationQuestion)
                .where(DesignPlanClarificationQuestion.design_plan_id == plan.id)
                .order_by(DesignPlanClarificationQuestion.display_order.asc())
            )
        )
        return DesignPlanRead(
            id=plan.id,
            project_id=plan.project_id,
            design_specification_id=plan.design_specification_id,
            generation_attempt_id=plan.generation_attempt_id,
            superseded_design_plan_id=plan.superseded_design_plan_id,
            version_number=plan.version_number,
            schema_version=plan.schema_version,
            prompt_template_version=plan.prompt_template_version,
            ruleset_version=plan.ruleset_version,
            provider=plan.provider,
            provider_model=plan.provider_model,
            raw_response_path=plan.raw_response_path,
            plan_path=plan.plan_path,
            content_hash=plan.content_hash,
            outcome=DesignPlanOutcome(plan.outcome),
            review_state=DesignPlanReviewState(plan.review_state),
            clarification_required=plan.clarification_required,
            plan_ready=plan.plan_ready,
            approved_at=plan.approved_at,
            rejected_at=plan.rejected_at,
            created_at=plan.created_at,
            plan=self._read_design_plan_payload(plan),
            clarification_questions=[
                DesignPlanClarificationQuestionRead.model_validate(question)
                for question in questions
            ],
        )

    def _revision_plan_read(
        self,
        plan: RevisionPlan,
    ) -> RevisionPlanRead:
        questions = list(
            self.db.scalars(
                select(RevisionPlanClarificationQuestion)
                .where(RevisionPlanClarificationQuestion.revision_plan_id == plan.id)
                .order_by(RevisionPlanClarificationQuestion.display_order.asc())
            )
        )
        return RevisionPlanRead(
            id=plan.id,
            project_id=plan.project_id,
            base_revision_id=plan.base_revision_id,
            base_design_specification_id=plan.base_design_specification_id,
            base_design_plan_id=plan.base_design_plan_id,
            generation_attempt_id=plan.generation_attempt_id,
            superseded_revision_plan_id=plan.superseded_revision_plan_id,
            generated_revision_id=plan.generated_revision_id,
            revised_design_specification_id=plan.revised_design_specification_id,
            revised_design_plan_id=plan.revised_design_plan_id,
            version_number=plan.version_number,
            schema_version=plan.schema_version,
            prompt_template_version=plan.prompt_template_version,
            ruleset_version=plan.ruleset_version,
            provider=plan.provider,
            provider_model=plan.provider_model,
            user_instruction=plan.user_instruction,
            reason=plan.reason,
            raw_response_path=plan.raw_response_path,
            plan_path=plan.plan_path,
            content_hash=plan.content_hash,
            base_source_hash=plan.base_source_hash,
            base_output_manifest_hash=plan.base_output_manifest_hash,
            base_design_specification_hash=plan.base_design_specification_hash,
            base_design_plan_hash=plan.base_design_plan_hash,
            outcome=RevisionPlanOutcome(plan.outcome),
            review_state=RevisionPlanReviewState(plan.review_state),
            clarification_required=plan.clarification_required,
            revision_ready=plan.revision_ready,
            approved_at=plan.approved_at,
            rejected_at=plan.rejected_at,
            created_at=plan.created_at,
            revision_plan=self._read_revision_plan_payload(plan),
            clarification_questions=[
                RevisionPlanClarificationQuestionRead.model_validate(question)
                for question in questions
            ],
        )

    def _persist_source_contract_validation(
        self,
        *,
        project: Project,
        attempt: GenerationAttempt,
        source: str,
        source_type: str,
        design_specification: DesignSpecification | None,
        design_specification_payload: dict[str, Any] | None,
        design_plan: DesignPlan | None = None,
        design_plan_payload: dict[str, Any] | None = None,
    ) -> SourceValidationResult:
        return self._persist_cadquery_source_contract_validation(
            project=project,
            attempt=attempt,
            source=source,
            source_type=source_type,
            design_specification=design_specification,
            design_specification_payload=design_specification_payload,
            design_plan_payload=design_plan_payload,
        )

    def _persist_cadquery_source_contract_validation(
        self,
        *,
        project: Project,
        attempt: GenerationAttempt,
        source: str,
        source_type: str,
        design_specification: DesignSpecification | None,
        design_specification_payload: dict[str, Any] | None = None,
        design_plan_payload: dict[str, Any] | None = None,
    ) -> SourceValidationResult:
        started = time.perf_counter()
        source_hash = self._sha256(source)
        hard_violations: list[dict[str, Any]] = []
        metadata: dict[str, Any] | None = None
        try:
            source_metadata = validate_cadquery_source(source, contract_version="cadquery-v1")
            hard_violations.extend(validate_scaffold_source(source))
            metadata = asdict(source_metadata)
            explicit_inventory = inventory_from_design_specification(design_specification_payload)
            if explicit_inventory:
                validate_source_parameter_trace(
                    {
                        "parameter_ids": source_metadata.parameter_ids,
                        "parameter_defaults": source_metadata.parameter_defaults,
                    },
                        explicit_inventory,
                    )
            source_authority = authority_from_generation_context(
                design_plan_payload=design_plan_payload,
            )
            if source_authority:
                validate_cadquery_source_authority(source, source_authority)
        except CadQueryContractError as exc:
            hard_violations.append(
                {
                    "rule_id": "cadquery.contract",
                    "category": "source_contract",
                    "severity": "critical",
                    "is_blocking": True,
                    "title": "CadQuery source contract violation",
                    "explanation": str(exc),
                    "suggested_correction": "Regenerate or repair the CadQuery source so it satisfies cadquery-v1.",
                }
            )
        except RequirementTraceError as exc:
            hard_violations.extend(exc.findings)
        except CadQuerySourceAuthorityError as exc:
            hard_violations.extend(exc.findings)
        validation_ms = round((time.perf_counter() - started) * 1000, 3)
        run_dir = self._generation_attempt_dir(project.id, attempt.id)
        result_path = run_dir / "source-contract.json"
        self._write_json(
            result_path,
            {
                "contract_version": "cadquery-v1",
                "validator_version": "cadquery-ast-validator-v2",
                "ruleset_version": self._ruleset_version(),
                "passed_hard_checks": not hard_violations,
                "hard_violations": hard_violations,
                "quality_findings": [],
                "specification_findings": [],
                "source_metadata": metadata or {"source_hash": source_hash},
                "validation_ms": validation_ms,
                "source_type": source_type,
            },
        )
        source_validation = SourceValidationResult(
            project_id=project.id,
            generation_attempt_id=attempt.id,
            design_specification_id=design_specification.id if design_specification else None,
            validator_id="cadquery-ast-validator",
            cad_backend="cadquery",
            source_language="python",
            contract_version="cadquery-v1",
            ruleset_version=self._ruleset_version(),
            validator_version="cadquery-ast-validator-v2",
            source_hash=source_hash,
            result_path=self._relative(result_path),
            passed_hard_checks=not hard_violations,
            validation_ms=validation_ms,
        )
        self.db.add(source_validation)
        self.db.flush()
        for violation in hard_violations:
            self.db.add(
                ValidationFinding(
                    revision_id=None,
                    generation_attempt_id=attempt.id,
                    design_specification_id=design_specification.id if design_specification else None,
                    source_validation_result_id=source_validation.id,
                    rule_id=str(violation.get("rule_id") or "cadquery.contract"),
                    category=str(violation.get("category") or "source_contract"),
                    severity=str(violation.get("severity") or "critical"),
                    is_blocking=bool(violation.get("is_blocking", True)),
                    title=str(violation.get("title") or "CadQuery source contract violation"),
                    explanation=str(violation.get("explanation") or ""),
                    suggested_correction=str(
                        violation.get("suggested_correction")
                        or "Regenerate or repair the CadQuery source so it satisfies cadquery-v1."
                    ),
                    detected_value=json.dumps(violation.get("detected_value"), sort_keys=True)
                    if violation.get("detected_value") is not None
                    else None,
                    threshold_value=json.dumps(violation.get("expected_value"), sort_keys=True)
                    if violation.get("expected_value") is not None
                    else None,
                    orientation_dependent=False,
                    metadata_json=json.dumps(
                        {
                            "finding_origin": "source_contract",
                            "parameter_id": violation.get("parameter_id"),
                            "component_id": violation.get("component_id"),
                            "feature_id": violation.get("feature_id"),
                            "output_id": violation.get("output_id"),
                            "identity_id": violation.get("identity_id"),
                            "metadata": violation.get("metadata"),
                        },
                        sort_keys=True,
                    ),
                )
            )
        self._update_attempt_chain(attempt, status=attempt.status)
        self.db.commit()
        self.db.refresh(source_validation)
        return source_validation

    def _source_contract_rejection_message(self, source_validation: SourceValidationResult) -> str:
        header = "The generated model did not implement the approved design identities."
        findings = list(
            self.db.scalars(
                select(ValidationFinding)
                .where(ValidationFinding.source_validation_result_id == source_validation.id)
                .where(ValidationFinding.is_blocking.is_(True))
                .order_by(ValidationFinding.created_at.asc(), ValidationFinding.rule_id.asc())
            )
        )
        if not findings:
            return header
        lines = [header, "The model was not executed."]
        for finding in findings[:8]:
            detail = f"{finding.rule_id} - {finding.title}"
            if finding.explanation:
                detail += f": {finding.explanation}"
            if finding.detected_value is not None or finding.threshold_value is not None:
                detail += (
                    f": expected {finding.threshold_value or 'n/a'}, "
                    f"detected {finding.detected_value or 'n/a'}"
                )
            if finding.source_line_start is not None:
                detail += f" (line {finding.source_line_start})"
            lines.append(f"- {detail}")
        if len(findings) > 8:
            lines.append(f"- {len(findings) - 8} additional blocking findings")
        return "\n".join(lines)

    def _source_validation_generation_attempt_id(
        self,
        source_validation_result_id: str | None,
    ) -> str | None:
        if source_validation_result_id is None:
            return None
        source_validation = self.db.get(SourceValidationResult, source_validation_result_id)
        return source_validation.generation_attempt_id if source_validation is not None else None

    def _persist_design_artifact_consistency(
        self,
        *,
        revision: Revision,
        source: str,
        design_specification_payload: dict[str, Any] | None,
        design_plan_payload: dict[str, Any],
        execution_parameters: dict[str, Any] | None = None,
        execution_manifest: dict[str, Any] | None = None,
        output_manifest: dict[str, Any] | None = None,
        parameter_overrides: dict[str, Any] | None = None,
        generation_attempt_id: str | None = None,
    ) -> DesignArtifactConsistencyResult:
        started = time.perf_counter()
        payload = certify_design_artifact_consistency(
            project_id=revision.project_id,
            revision_id=revision.id,
            design_specification_id=revision.design_specification_id,
            design_specification_payload=design_specification_payload,
            design_plan_id=revision.design_plan_id,
            design_plan_payload=design_plan_payload,
            source=source,
            execution_parameters=execution_parameters,
            execution_manifest=execution_manifest,
            output_manifest=output_manifest,
            parameter_overrides=parameter_overrides,
        )
        result_dir = self._revision_dir(revision.project_id, revision.id) / "metadata"
        result_dir.mkdir(parents=True, exist_ok=True)
        result_path = result_dir / "design-artifact-consistency.json"
        self._write_json(result_path, payload)
        row = DesignArtifactConsistencyResult(
            project_id=revision.project_id,
            revision_id=revision.id,
            design_specification_id=revision.design_specification_id,
            design_plan_id=revision.design_plan_id,
            generation_attempt_id=generation_attempt_id,
            schema_version=str(payload["schema_version"]),
            validator_version=str(payload["validator_version"]),
            source_hash=payload.get("source_hash"),
            parameter_hash=payload.get("parameter_hash"),
            output_manifest_hash=payload.get("output_manifest_hash"),
            result_path=self._relative(result_path),
            pre_execution_passed=bool(payload.get("pre_execution_passed")),
            post_execution_passed=bool(payload.get("post_execution_passed")),
            revision_base_ready=bool(payload.get("revision_base_ready")),
            configuration_ready=bool(payload.get("configuration_ready")),
            validation_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        self.db.add(row)
        self.db.flush()
        self._persist_design_artifact_findings(revision=revision, payload=payload)
        return row

    def _persist_design_artifact_findings(
        self,
        *,
        revision: Revision,
        payload: dict[str, Any],
    ) -> None:
        self.db.execute(
            delete(ValidationFinding).where(
                ValidationFinding.revision_id == revision.id,
                ValidationFinding.category == "design_artifact_consistency",
            )
        )
        for finding in payload.get("findings", []):
            if not isinstance(finding, dict):
                continue
            self.db.add(
                ValidationFinding(
                    revision_id=revision.id,
                    rule_id=str(finding.get("rule_id") or "design_artifact.consistency"),
                    category="design_artifact_consistency",
                    severity=str(finding.get("severity") or "critical"),
                    is_blocking=bool(finding.get("is_blocking", True)),
                    title=str(finding.get("title") or "Design artifact consistency"),
                    explanation=str(finding.get("explanation") or "Design artifacts are inconsistent."),
                    suggested_correction=str(
                        finding.get("suggested_correction")
                        or "Regenerate from the approved Design Plan."
                    ),
                    detected_value=self._value_to_text(finding.get("detected_value")),
                    unit=finding.get("unit") if isinstance(finding.get("unit"), str) else None,
                    threshold_value=self._value_to_text(finding.get("expected_value")),
                    orientation_dependent=False,
                    metadata_json=json.dumps(
                        {
                            "finding_origin": "design_artifact_consistency",
                            "phase": finding.get("phase"),
                            "parameter_id": finding.get("parameter_id"),
                            "component_id": finding.get("component_id"),
                            "feature_id": finding.get("feature_id"),
                            "output_id": finding.get("output_id"),
                        },
                        sort_keys=True,
                    ),
                )
            )
        self.db.flush()

    def _latest_design_artifact_consistency(
        self,
        revision_id: str,
    ) -> DesignArtifactConsistencyResult | None:
        return self.db.scalar(
            select(DesignArtifactConsistencyResult)
            .where(DesignArtifactConsistencyResult.revision_id == revision_id)
            .order_by(DesignArtifactConsistencyResult.created_at.desc())
        )

    def _read_design_artifact_consistency_payload(
        self,
        result: DesignArtifactConsistencyResult,
    ) -> dict[str, Any]:
        return self._read_json_file(result.result_path) or {}

    def _certify_revision_artifacts(
        self,
        revision: Revision,
    ) -> DesignArtifactConsistencyResult:
        source = self.read_revision_source(revision.id)
        if source is None:
            raise ValueError("base revision source is missing")
        design_plan_payload = self._revision_design_plan_payload(revision)
        if design_plan_payload is None:
            raise ValueError("base revision must reference an approved Design Plan")
        design_specification_payload = self._revision_design_specification_payload(revision)
        output_manifest = self.read_output_manifest(revision.id)
        execution_manifest = None
        if revision.execution_manifest_path:
            execution_manifest = self._read_json_file(revision.execution_manifest_path)
        execution_parameters = (
            execution_manifest.get("parameters")
            if isinstance(execution_manifest, dict) and isinstance(execution_manifest.get("parameters"), dict)
            else None
        )
        parameter_overrides = None
        if revision.configuration_change_id is not None:
            change = self.db.get(ConfigurationChange, revision.configuration_change_id)
            if change is not None:
                override_manifest = self._configuration_override_manifest(change)
                parameter_overrides = dict(override_manifest.get("parameter_values") or {})
        result = self._persist_design_artifact_consistency(
            revision=revision,
            source=source,
            design_specification_payload=design_specification_payload,
            design_plan_payload=design_plan_payload,
            execution_parameters=execution_parameters,
            execution_manifest=execution_manifest,
            output_manifest=output_manifest,
            parameter_overrides=parameter_overrides,
        )
        if revision.status == "succeeded":
            revision.review_state = self._derive_review_state(revision.id)
        self.db.flush()
        return result

    def _require_revision_base_ready(
        self,
        revision: Revision,
        *,
        purpose: str,
    ) -> DesignArtifactConsistencyResult:
        result = self._certify_revision_artifacts(revision)
        if not result.revision_base_ready:
            payload = self._read_design_artifact_consistency_payload(result)
            self.db.commit()
            raise ValueError(consistency_failure_message(payload))
        return result

    def _value_to_text(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value, sort_keys=True)

    def _attach_source_validation_to_revision(
        self,
        *,
        source_validation_result_id: str,
        revision_id: str,
    ) -> None:
        source_validation = self.db.get(SourceValidationResult, source_validation_result_id)
        if source_validation is not None:
            source_validation.revision_id = revision_id
        for finding in self.db.scalars(
            select(ValidationFinding).where(
                ValidationFinding.source_validation_result_id == source_validation_result_id
            )
        ):
            finding.revision_id = revision_id
        self.db.flush()

    def _persist_revision_compliance_result(
        self,
        *,
        project: Project,
        revision_plan: RevisionPlan,
        generation_attempt: GenerationAttempt,
        base_source: str,
        revised_source: str,
        revision_plan_payload: dict[str, Any],
        design_specification_payload: dict[str, Any] | None,
        design_plan_payload: dict[str, Any],
        configuration_context: dict[str, Any] | None = None,
        cad_backend: str = "cadquery",
    ) -> RevisionComplianceResult:
        started = time.perf_counter()
        base_scan = self._revision_source_metadata(
            source=base_source,
            cad_backend=cad_backend,
            design_specification_payload=design_specification_payload,
            design_plan_payload=design_plan_payload,
            source_type="ai_revision",
        )
        revised_scan = self._revision_source_metadata(
            source=revised_source,
            cad_backend=cad_backend,
            design_specification_payload=design_specification_payload,
            design_plan_payload=design_plan_payload,
            source_type="ai_revision",
        )
        findings = self._revision_compliance_findings(
            base_scan=base_scan,
            revised_scan=revised_scan,
            revision_plan_payload=revision_plan_payload,
            design_plan_payload=design_plan_payload,
            configuration_context=configuration_context,
        )
        passed = not any(finding["is_blocking"] for finding in findings)
        result_payload = {
            "schema_version": "revision-compliance-v1",
            "revision_plan_id": revision_plan.id,
            "base_source_hash": base_scan.source_hash,
            "revised_source_hash": revised_scan.source_hash,
            "passed": passed,
            "findings": findings,
            "metadata": {
                "base_modules": base_scan.module_names,
                "revised_modules": revised_scan.module_names,
                "base_outputs": sorted(base_scan.output_mappings),
                "revised_outputs": sorted(revised_scan.output_mappings),
                "base_shared_modules": sorted(base_scan.shared_module_mappings),
                "revised_shared_modules": sorted(revised_scan.shared_module_mappings),
                "base_module_fingerprints": {
                    name: asdict(fingerprint)
                    for name, fingerprint in base_scan.module_fingerprints.items()
                },
                "revised_module_fingerprints": {
                    name: asdict(fingerprint)
                    for name, fingerprint in revised_scan.module_fingerprints.items()
                },
            },
        }
        result_dir = self._revision_plan_dir(project.id, revision_plan.id)
        result_dir.mkdir(parents=True, exist_ok=True)
        result_path = result_dir / "revision-compliance.json"
        self._write_json(result_path, result_payload)
        row = RevisionComplianceResult(
            project_id=project.id,
            revision_plan_id=revision_plan.id,
            generation_attempt_id=generation_attempt.id,
            base_source_hash=base_scan.source_hash,
            revised_source_hash=revised_scan.source_hash,
            result_path=self._relative(result_path),
            passed=passed,
            validation_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        self.db.add(row)
        self.db.flush()
        return row

    def _revision_source_metadata(
        self,
        *,
        source: str,
        cad_backend: str,
        design_specification_payload: dict[str, Any] | None,
        design_plan_payload: dict[str, Any] | None,
        source_type: str,
    ) -> SourceMetadata:
        if cad_backend != "cadquery":
            raise ValueError("CadQuery source is required for revision metadata")
        return self._cadquery_revision_source_metadata(source, design_plan_payload or {})

    def _cadquery_revision_source_metadata(
        self,
        source: str,
        design_plan_payload: dict[str, Any],
    ) -> SourceMetadata:
        metadata = validate_cadquery_source(source, contract_version="cadquery-v1")
        tree = ast.parse(source)
        source_hash = self._sha256(source)
        parameter_mappings: dict[str, SourceParameterMapping] = {}
        parameter_fingerprints: dict[str, str] = {}
        for call in self._cadquery_runtime_calls(tree, "ParameterSpec"):
            parameter_id = self._cadquery_static_string_keyword(call, "id")
            if not parameter_id:
                continue
            parameter_mappings[parameter_id] = SourceParameterMapping(
                parameter_id=parameter_id,
                target_name=parameter_id,
                target_kind="ParameterSpec",
                line=getattr(call, "lineno", 1),
            )
            parameter_fingerprints[parameter_id] = self._cadquery_normalized_hash(call)

        component_mappings: dict[str, SourceMapping] = {}
        feature_mappings: dict[str, SourceMapping] = {}
        shared_module_mappings: dict[str, SourceMapping] = {}
        module_fingerprints: dict[str, SourceModuleFingerprint] = {}
        top_level_functions = self._cadquery_top_level_functions(tree)
        functions_by_name = {function.name: function for function in top_level_functions}
        for function in top_level_functions:
            ownership = self._cadquery_function_ownership(function)
            component_ids = ownership["component_ids"]
            feature_ids = ownership["feature_ids"]
            shared_helper_ids = ownership["shared_helper_ids"]
            for component_id in component_ids:
                component_mappings[component_id] = SourceMapping(
                    requirement_id=component_id,
                    marker_type="component",
                    target_name=function.name,
                    target_kind="function",
                    line=function.lineno,
                )
            for feature_id, component_id in ownership["feature_components"].items():
                feature_mappings[feature_id] = SourceMapping(
                    requirement_id=feature_id,
                    marker_type="feature",
                    target_name=function.name,
                    target_kind="function",
                    line=function.lineno,
                )
                if component_id and component_id not in component_ids:
                    component_ids.append(component_id)
            for helper_id in shared_helper_ids:
                shared_module_mappings[helper_id] = SourceMapping(
                    requirement_id=helper_id,
                    marker_type="shared_helper",
                    target_name=function.name,
                    target_kind="function",
                    line=function.lineno,
                )
            if component_ids or feature_ids or shared_helper_ids:
                called_modules = self._cadquery_called_functions(function)
                fingerprint_nodes = [function]
                fingerprint_nodes.extend(
                    functions_by_name[name]
                    for name in called_modules
                    if name.startswith("_ai_") and name in functions_by_name
                )
                module_fingerprints[function.name] = SourceModuleFingerprint(
                    module_name=function.name,
                    line=function.lineno,
                    normalized_hash=self._cadquery_normalized_hash(
                        ast.Module(body=fingerprint_nodes, type_ignores=[])
                    ),
                    called_modules=called_modules,
                    referenced_parameters=self._cadquery_referenced_parameters(function),
                    component_ids=component_ids,
                    feature_ids=feature_ids,
                    is_shared=bool(shared_helper_ids) and not component_ids and not feature_ids,
                )

        for component_id in metadata.component_ids:
            component_mappings.setdefault(
                component_id,
                SourceMapping(
                    requirement_id=component_id,
                    marker_type="component",
                    target_name="build",
                    target_kind="function",
                    line=1,
                ),
            )

        output_mappings: dict[str, SourceOutputMapping] = {}
        output_fingerprints: dict[str, str] = {}
        for call in self._cadquery_runtime_calls(tree, "PrintableOutput"):
            output_id = self._cadquery_static_string_keyword(call, "output_id")
            if not output_id:
                continue
            component_ids = self._cadquery_output_component_ids(call)
            output_module_name = f"output:{output_id}"
            output_mappings[output_id] = SourceOutputMapping(
                output_id=output_id,
                component_ids=component_ids,
                target_name=output_id,
                target_kind="PrintableOutput",
                line=getattr(call, "lineno", 1),
                module_name=output_module_name,
                filename=f"{output_id}.stl",
                required=self._cadquery_static_bool_keyword(call, "required", default=True),
            )
            output_fingerprints[output_id] = self._cadquery_normalized_hash(call)
            module_fingerprints[output_module_name] = SourceModuleFingerprint(
                module_name=output_module_name,
                line=getattr(call, "lineno", 1),
                normalized_hash=output_fingerprints[output_id],
                component_ids=component_ids,
                output_ids=[output_id],
            )

        for output_id in metadata.output_ids:
            output_mappings.setdefault(
                output_id,
                SourceOutputMapping(
                    output_id=output_id,
                    component_ids=list(metadata.output_component_ids.get(output_id, [])),
                    target_name=output_id,
                    target_kind="PrintableOutput",
                    line=1,
                    module_name=f"output:{output_id}",
                    filename=f"{output_id}.stl",
                    required=True,
                ),
            )
        for feature in design_plan_payload.get("features", []):
            feature_id = str(feature.get("id") or "")
            if not feature_id:
                continue
            if feature_id in feature_mappings:
                continue
            component_id = str(feature.get("component_id") or "")
            if component_id and component_id not in metadata.component_ids:
                continue
            feature_mappings[feature_id] = SourceMapping(
                requirement_id=feature_id,
                marker_type="feature",
                target_name=component_mappings.get(component_id, SourceMapping("", "", "build", "function", 1)).target_name
                if component_id
                else "build",
                target_kind="function",
                line=1,
            )
        return SourceMetadata(
            source_hash=source_hash,
            source_size_bytes=len(source.encode("utf-8")),
            line_count=len(source.splitlines()),
            module_names=sorted(set(["build", *module_fingerprints])),
            parameter_names=list(metadata.parameter_ids),
            feature_mappings=feature_mappings,
            component_mappings=component_mappings,
            parameter_mappings=parameter_mappings,
            output_mappings=output_mappings,
            shared_module_mappings=shared_module_mappings,
            module_fingerprints=module_fingerprints,
            parameter_fingerprints=parameter_fingerprints,
            output_fingerprints=output_fingerprints,
            assignments={
                parameter_id: self._cadquery_assignment_literal(default)
                for parameter_id, default in metadata.parameter_defaults.items()
            },
            assignment_lines={
                parameter_id: parameter_mappings.get(
                    parameter_id,
                    SourceParameterMapping(parameter_id, parameter_id, "ParameterSpec", 1),
                ).line
                for parameter_id in metadata.parameter_defaults
            },
        )

    def _cadquery_top_level_functions(self, tree: ast.Module) -> list[ast.FunctionDef]:
        return [node for node in tree.body if isinstance(node, ast.FunctionDef)]

    def _cadquery_runtime_calls(self, tree: ast.AST, call_name: str) -> list[ast.Call]:
        return [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and self._cadquery_call_name(node.func) == call_name
        ]

    def _cadquery_call_name(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    def _cadquery_function_ownership(self, node: ast.FunctionDef) -> dict[str, Any]:
        component_ids: list[str] = []
        feature_ids: list[str] = []
        feature_components: dict[str, str | None] = {}
        shared_helper_ids: list[str] = []
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Name):
                continue
            decorator_name = decorator.func.id
            decorator_id = self._cadquery_static_positional_string(decorator, 0)
            if not decorator_id:
                continue
            if decorator_name == "component":
                component_ids.append(decorator_id)
            elif decorator_name == "feature":
                feature_ids.append(decorator_id)
                feature_components[decorator_id] = self._cadquery_static_string_keyword(decorator, "component")
            elif decorator_name == "shared_helper":
                shared_helper_ids.append(decorator_id)
        return {
            "component_ids": list(dict.fromkeys(component_ids)),
            "feature_ids": list(dict.fromkeys(feature_ids)),
            "feature_components": feature_components,
            "shared_helper_ids": list(dict.fromkeys(shared_helper_ids)),
        }

    def _cadquery_normalized_hash(self, node: ast.AST) -> str:
        return self._sha256(ast.dump(node, include_attributes=False, annotate_fields=True))

    def _cadquery_called_functions(self, node: ast.AST) -> list[str]:
        names: list[str] = []
        for call in (child for child in ast.walk(node) if isinstance(child, ast.Call)):
            name = self._cadquery_call_name(call.func)
            if name:
                names.append(name)
        return sorted(set(names))

    def _cadquery_referenced_parameters(self, node: ast.AST) -> list[str]:
        names: list[str] = []
        for child in ast.walk(node):
            if (
                isinstance(child, ast.Subscript)
                and isinstance(child.value, ast.Name)
                and child.value.id == "params"
                and isinstance(child.slice, ast.Constant)
                and isinstance(child.slice.value, str)
            ):
                names.append(child.slice.value)
        return sorted(set(names))

    def _cadquery_static_positional_string(self, node: ast.Call, index: int) -> str | None:
        if len(node.args) <= index:
            return None
        value = node.args[index]
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
        return None

    def _cadquery_static_string_keyword(self, node: ast.Call, name: str) -> str | None:
        for keyword in node.keywords:
            if keyword.arg == name and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                return keyword.value.value
        return None

    def _cadquery_static_bool_keyword(self, node: ast.Call, name: str, *, default: bool) -> bool:
        for keyword in node.keywords:
            if keyword.arg == name and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, bool):
                return keyword.value.value
        return default

    def _cadquery_output_component_ids(self, node: ast.Call) -> list[str]:
        component_ids: list[str] = []
        component_id = self._cadquery_static_string_keyword(node, "component_id")
        if component_id:
            component_ids.append(component_id)
        for keyword in node.keywords:
            if keyword.arg != "component_ids" or not isinstance(keyword.value, ast.List | ast.Tuple):
                continue
            for element in keyword.value.elts:
                if isinstance(element, ast.Constant) and isinstance(element.value, str):
                    component_ids.append(element.value)
        return list(dict.fromkeys(component_ids))

    def _cadquery_source_parameter_values(self, source: str) -> dict[str, Any]:
        try:
            metadata = validate_cadquery_source(source, contract_version="cadquery-v1")
        except CadQueryContractError:
            return {}
        return dict(metadata.parameter_defaults)

    def _cadquery_execution_parameter_values(
        self,
        *,
        source: str,
        design_plan_payload: dict[str, Any],
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        values = self._cadquery_source_parameter_values(source)
        values.update(self._design_plan_parameter_values(design_plan_payload))
        if overrides is not None:
            values.update(overrides)
        try:
            metadata = validate_cadquery_source(source, contract_version="cadquery-v1")
        except CadQueryContractError:
            return values
        return {
            parameter_id: self._coerce_cadquery_parameter_value(
                value,
                parameter_type=metadata.parameter_types.get(parameter_id),
            )
            for parameter_id, value in values.items()
        }

    def _coerce_cadquery_parameter_value(self, value: Any, *, parameter_type: str | None) -> Any:
        if parameter_type == "int" and isinstance(value, float) and value.is_integer():
            return int(value)
        if parameter_type == "float" and isinstance(value, int) and not isinstance(value, bool):
            return float(value)
        return value

    def _cadquery_manual_design_plan_payload(self, source: str) -> dict[str, Any]:
        try:
            metadata = validate_cadquery_source(source, contract_version="cadquery-v1")
        except CadQueryContractError:
            return {
                "parameters": [],
                "components": [{"id": "model", "label": "Model"}],
                "features": [],
                "printable_outputs": [
                    {
                        "id": "model",
                        "label": "Model",
                        "component_id": "model",
                        "component_ids": ["model"],
                        "filename": "model.stl",
                        "quantity": 1,
                        "required": True,
                        "output_type": "printable_component",
                    }
                ],
            }
        components = [
            {"id": component_id, "label": component_id.replace("_", " ").title()}
            for component_id in metadata.component_ids
        ]
        outputs = []
        for output_id in metadata.output_ids:
            component_ids = list(metadata.output_component_ids.get(output_id) or [])
            component_id = component_ids[0] if component_ids else None
            outputs.append(
                {
                    "id": output_id,
                    "label": output_id.replace("_", " ").title(),
                    "component_id": component_id,
                    "component_ids": component_ids,
                    "filename": f"{output_id}.stl",
                    "quantity": 1,
                    "required": True,
                    "output_type": "printable_component",
                }
            )
        if not outputs:
            outputs.append(
                {
                    "id": "model",
                    "label": "Model",
                    "component_id": "model",
                    "component_ids": ["model"],
                    "filename": "model.stl",
                    "quantity": 1,
                    "required": True,
                    "output_type": "printable_component",
                }
            )
        return {
            "parameters": [
                {
                    "id": parameter_id,
                    "label": parameter_id.replace("_", " ").title(),
                    "value": metadata.parameter_defaults.get(parameter_id),
                    "editable": True,
                }
                for parameter_id in metadata.parameter_ids
            ],
            "components": components or [{"id": "model", "label": "Model"}],
            "features": [],
            "printable_outputs": outputs,
        }

    def _cadquery_assignment_literal(self, value: Any) -> str:
        if isinstance(value, bool):
            return "1" if value else "0"
        return str(value)

    def _revision_compliance_findings(
        self,
        *,
        base_scan,
        revised_scan,
        revision_plan_payload: dict[str, Any],
        design_plan_payload: dict[str, Any],
        configuration_context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        allowed_parameters = set(revision_plan_payload.get("allowed_parameter_changes", []))
        for dependency in revision_plan_payload.get("required_dependency_changes", []):
            allowed_parameters.update(str(item) for item in dependency.get("affects", []))
        protected_parameters = {
            item.get("parameter_id"): item
            for item in revision_plan_payload.get("protected_parameters", [])
            if item.get("parameter_id")
        }
        modern_requirement_contract = "exposed_controls" in design_plan_payload
        exposed_control_ids = {
            str(item.get("parameter_id"))
            for item in design_plan_payload.get("exposed_controls", []) or []
            if isinstance(item, dict) and item.get("parameter_id")
        }
        if modern_requirement_contract:
            # Ordinary revisions are judged by the active requirement ledger
            # and post-worker evidence.  Source-level preservation remains
            # strict only for controls the user explicitly exposed.
            protected_parameters = {
                parameter_id: item
                for parameter_id, item in protected_parameters.items()
                if str(parameter_id) in exposed_control_ids
            }
        plan_parameter_ids = {
            str(item.get("id"))
            for item in (
                list(design_plan_payload.get("parameters", []))
                + list(design_plan_payload.get("derived_parameters", []))
            )
            if item.get("id")
        }
        if modern_requirement_contract:
            plan_parameter_ids = exposed_control_ids
        plan_output_ids = {
            str(output.get("id"))
            for output in design_plan_payload.get("printable_outputs", [])
            if output.get("id")
        }
        base_constants = evaluate_constants(base_scan.assignments)
        revised_constants = evaluate_constants(revised_scan.assignments)
        for parameter_id, protected in protected_parameters.items():
            expected = protected.get("expected_value")
            detected = revised_constants.get(parameter_id)
            if detected is None and parameter_id in revised_scan.assignments:
                detected = revised_scan.assignments[parameter_id]
            if parameter_id not in revised_scan.assignments:
                findings.append(
                    self._revision_compliance_finding(
                        "revision.protected_parameter_removed",
                        "Protected parameter removed",
                        f"{parameter_id} is protected by the Revision Plan but is missing.",
                        parameter_id=parameter_id,
                        expected=expected,
                        detected=None,
                    )
                )
            elif expected is not None and not self._values_equal(expected, detected):
                findings.append(
                    self._revision_compliance_finding(
                        "revision.unauthorized_parameter_change",
                        "Protected parameter changed",
                        f"{parameter_id} changed outside the approved revision scope.",
                        parameter_id=parameter_id,
                        expected=expected,
                        detected=detected,
                    )
                )
        ignored: set[str] = set()
        for name in sorted(set(base_scan.assignments) & set(revised_scan.assignments)):
            if name in ignored or name in allowed_parameters:
                continue
            if name not in plan_parameter_ids and name not in protected_parameters:
                continue
            base_value = base_constants.get(name, base_scan.assignments.get(name))
            revised_value = revised_constants.get(name, revised_scan.assignments.get(name))
            if not self._values_equal(base_value, revised_value):
                findings.append(
                    self._revision_compliance_finding(
                        "revision.unauthorized_parameter_change",
                        "Unauthorized parameter changed",
                        f"{name} changed but is not listed as allowed or required by the Revision Plan.",
                        parameter_id=name,
                        expected=base_value,
                        detected=revised_value,
                    )
                )
        for parameter_id in sorted(set(base_scan.parameter_fingerprints) & set(revised_scan.parameter_fingerprints)):
            if parameter_id in allowed_parameters:
                continue
            if parameter_id not in plan_parameter_ids and parameter_id not in protected_parameters:
                continue
            if base_scan.parameter_fingerprints[parameter_id] == revised_scan.parameter_fingerprints[parameter_id]:
                continue
            findings.append(
                self._revision_compliance_finding(
                    "revision.unauthorized_parameter_definition_change",
                    "Unauthorized parameter definition changed",
                    f"{parameter_id} changed its ParameterSpec declaration outside the approved revision scope.",
                    parameter_id=parameter_id,
                    expected=base_scan.parameter_fingerprints[parameter_id],
                    detected=revised_scan.parameter_fingerprints[parameter_id],
                )
            )
        for component_id in revision_plan_payload.get("protected_components", []):
            if component_id and component_id not in revised_scan.component_mappings:
                findings.append(
                    self._revision_compliance_finding(
                        "revision.protected_component_removed",
                        "Protected component marker removed",
                        f"Component {component_id} must remain present.",
                        component_id=component_id,
                    )
                )
        for feature_id in revision_plan_payload.get("protected_features", []):
            if feature_id and feature_id not in revised_scan.feature_mappings:
                findings.append(
                    self._revision_compliance_finding(
                        "revision.protected_feature_removed",
                        "Protected feature marker removed",
                        f"Feature {feature_id} must remain present.",
                        feature_id=feature_id,
                    )
                )
        for output in design_plan_payload.get("printable_outputs", []):
            output_id = output.get("id")
            if output_id and output_id not in revised_scan.output_mappings:
                findings.append(
                    self._revision_compliance_finding(
                        "revision.required_output_removed",
                        "Planned output marker removed",
                        f"Output {output_id} is declared by the Design Plan but missing from revised source.",
                        output_id=output_id,
                    )
                )
        for output_id in revision_plan_payload.get("protected_outputs", []):
            base_mapping = base_scan.output_mappings.get(output_id)
            revised_mapping = revised_scan.output_mappings.get(output_id)
            if base_mapping is None or revised_mapping is None:
                continue
            if (
                base_mapping.module_name != revised_mapping.module_name
                or base_mapping.component_ids != revised_mapping.component_ids
            ):
                findings.append(
                    self._revision_compliance_finding(
                        "revision.unexpected_output_change",
                        "Protected output mapping changed",
                        f"Output {output_id} changed module or component mapping outside the approved scope.",
                        output_id=output_id,
                        expected=base_mapping.module_name,
                        detected=revised_mapping.module_name,
                    )
                )
        targeted_outputs = set(map(str, revision_plan_payload.get("targeted_outputs", [])))
        protected_outputs = set(map(str, revision_plan_payload.get("protected_outputs", [])))
        for output_id in sorted(set(base_scan.output_fingerprints) & set(revised_scan.output_fingerprints)):
            if output_id in targeted_outputs:
                continue
            if output_id not in protected_outputs and output_id not in plan_output_ids:
                continue
            if base_scan.output_fingerprints[output_id] == revised_scan.output_fingerprints[output_id]:
                continue
            rule_id = (
                "revision.protected_output_declaration_changed"
                if output_id in protected_outputs
                else "revision.unexpected_output_declaration_changed"
            )
            findings.append(
                self._revision_compliance_finding(
                    rule_id,
                    "Output declaration changed outside revision scope",
                    f"Output {output_id} changed its PrintableOutput declaration outside the approved revision scope.",
                    output_id=output_id,
                    expected=base_scan.output_fingerprints[output_id],
                    detected=revised_scan.output_fingerprints[output_id],
                )
            )
        findings.extend(
            self._component_scope_findings(
                base_scan=base_scan,
                revised_scan=revised_scan,
                revision_plan_payload=revision_plan_payload,
                design_plan_payload=design_plan_payload,
            )
        )
        findings.extend(
            self._interface_parameter_findings(
                base_scan=base_scan,
                revised_scan=revised_scan,
                revision_plan_payload=revision_plan_payload,
            )
        )
        findings.extend(
            self._configuration_preservation_findings(
                revised_scan=revised_scan,
                configuration_context=configuration_context,
            )
        )
        for dependency in revision_plan_payload.get("required_dependency_changes", []):
            changed = dependency.get("parameter_id")
            if not changed:
                continue
            base_value = base_constants.get(changed, base_scan.assignments.get(changed))
            revised_value = revised_constants.get(changed, revised_scan.assignments.get(changed))
            if self._values_equal(base_value, revised_value):
                continue
            for dependent in dependency.get("affects", []):
                base_dependent = base_scan.assignments.get(str(dependent))
                revised_dependent = revised_scan.assignments.get(str(dependent))
                if base_dependent == revised_dependent:
                    findings.append(
                        self._revision_compliance_finding(
                            "revision.required_dependency_not_updated",
                            "Required dependency was not updated",
                            f"{dependent} must change with {changed} according to the Revision Plan.",
                            parameter_id=str(dependent),
                            expected="changed expression or value",
                            detected=revised_dependent,
                        )
                    )
        return findings

    def _component_scope_findings(
        self,
        *,
        base_scan,
        revised_scan,
        revision_plan_payload: dict[str, Any],
        design_plan_payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        targeted_components = set(map(str, revision_plan_payload.get("targeted_components", [])))
        targeted_features = set(map(str, revision_plan_payload.get("targeted_features", [])))
        targeted_outputs = set(map(str, revision_plan_payload.get("targeted_outputs", [])))
        allowed_shared_modules = set(map(str, revision_plan_payload.get("allowed_shared_modules", [])))
        protected_components = set(map(str, revision_plan_payload.get("protected_components", [])))
        protected_features = set(map(str, revision_plan_payload.get("protected_features", [])))
        protected_outputs = set(map(str, revision_plan_payload.get("protected_outputs", [])))
        plan_component_ids = {
            str(component.get("id"))
            for component in design_plan_payload.get("components", [])
            if component.get("id")
        }
        plan_output_ids = {
            str(output.get("id"))
            for output in design_plan_payload.get("printable_outputs", [])
            if output.get("id")
        }
        allowed_modules = self._modules_for_scope(
            base_scan,
            components=targeted_components,
            features=targeted_features,
            outputs=targeted_outputs,
        ) | allowed_shared_modules
        protected_modules = self._modules_for_scope(
            base_scan,
            components=protected_components,
            features=protected_features,
            outputs=protected_outputs,
        )
        for component_id in sorted(set(revised_scan.component_mappings) - plan_component_ids):
            if component_id not in targeted_components:
                findings.append(
                    self._revision_compliance_finding(
                        "revision.undeclared_component_added",
                        "Undeclared component added",
                        f"Component {component_id} is not declared by the approved Design Plan.",
                        component_id=component_id,
                    )
                )
        for output_id in sorted(set(revised_scan.output_mappings) - plan_output_ids):
            if output_id not in targeted_outputs:
                findings.append(
                    self._revision_compliance_finding(
                        "revision.undeclared_output_added",
                        "Undeclared output added",
                        f"Output {output_id} is not declared by the approved Design Plan.",
                        output_id=output_id,
                    )
                )
        for module_name, base_fp in sorted(base_scan.module_fingerprints.items()):
            revised_fp = revised_scan.module_fingerprints.get(module_name)
            if revised_fp is None:
                rule_id = (
                    "revision.protected_component_removed"
                    if module_name in protected_modules
                    else "revision.unrelated_module_removed"
                )
                findings.append(
                    self._revision_compliance_finding(
                        rule_id,
                        "Module removed outside revision scope",
                        f"Module {module_name} was removed but is not an approved deletion.",
                        detected=None,
                        expected=module_name,
                    )
                )
                continue
            if base_fp.normalized_hash == revised_fp.normalized_hash:
                continue
            if module_name in allowed_modules:
                continue
            if base_fp.is_shared:
                findings.append(
                    self._revision_compliance_finding(
                        "revision.shared_module_change_not_allowed",
                        "Shared module changed without approval",
                        f"Shared module {module_name} changed but is not listed as an allowed shared module.",
                        expected=base_fp.normalized_hash,
                        detected=revised_fp.normalized_hash,
                    )
                )
                continue
            if module_name in protected_modules:
                findings.append(
                    self._revision_compliance_finding(
                        "revision.protected_module_changed",
                        "Protected component module changed",
                        f"Module {module_name} belongs to protected revision scope and changed structurally.",
                        expected=base_fp.normalized_hash,
                        detected=revised_fp.normalized_hash,
                    )
                )
                continue
            findings.append(
                self._revision_compliance_finding(
                    "revision.revision_scope_exceeded",
                    "Unrelated module changed",
                    f"Module {module_name} changed but is outside the approved target scope.",
                    expected=base_fp.normalized_hash,
                    detected=revised_fp.normalized_hash,
                )
            )
        for module_name, revised_fp in sorted(revised_scan.module_fingerprints.items()):
            if module_name in base_scan.module_fingerprints:
                continue
            owned_by_target = bool(
                set(revised_fp.component_ids) & targeted_components
                or set(revised_fp.feature_ids) & targeted_features
                or set(revised_fp.output_ids) & targeted_outputs
            )
            if not owned_by_target and module_name not in allowed_shared_modules:
                findings.append(
                    self._revision_compliance_finding(
                        "revision.revision_scope_exceeded",
                        "New module outside revision scope",
                        f"Module {module_name} was added outside the approved component or shared-module scope.",
                        detected=module_name,
                    )
                )
        return findings

    def _modules_for_scope(
        self,
        scan,
        *,
        components: set[str],
        features: set[str],
        outputs: set[str],
    ) -> set[str]:
        modules: set[str] = set()
        for module_name, fingerprint in scan.module_fingerprints.items():
            if (
                set(fingerprint.component_ids) & components
                or set(fingerprint.feature_ids) & features
                or set(fingerprint.output_ids) & outputs
            ):
                modules.add(module_name)
        for component_id, mapping in scan.component_mappings.items():
            if component_id in components and mapping.target_kind == "module":
                modules.add(mapping.target_name)
        for feature_id, mapping in scan.feature_mappings.items():
            if feature_id in features and mapping.target_kind == "module":
                modules.add(mapping.target_name)
        for output_id, mapping in scan.output_mappings.items():
            if output_id in outputs:
                modules.add(mapping.module_name or mapping.target_name)
        return modules

    def _interface_parameter_findings(
        self,
        *,
        base_scan,
        revised_scan,
        revision_plan_payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        base_constants = evaluate_constants(base_scan.assignments)
        revised_constants = evaluate_constants(revised_scan.assignments)
        for interface in revision_plan_payload.get("protected_interfaces", []):
            interface_id = str(interface.get("id") or "interface")
            for parameter_id in map(str, interface.get("parameters", [])):
                base_value = base_constants.get(parameter_id, base_scan.assignments.get(parameter_id))
                revised_value = revised_constants.get(parameter_id, revised_scan.assignments.get(parameter_id))
                if not self._values_equal(base_value, revised_value):
                    findings.append(
                        self._revision_compliance_finding(
                            "revision.interface_parameter_changed",
                            "Protected interface parameter changed",
                            f"{parameter_id} changed on protected interface {interface_id}.",
                            parameter_id=parameter_id,
                            expected=base_value,
                            detected=revised_value,
                        )
                    )
        return findings

    def _configuration_preservation_findings(
        self,
        *,
        revised_scan,
        configuration_context: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        if not configuration_context:
            return []
        manifest = configuration_context.get("override_manifest") or {}
        findings: list[dict[str, Any]] = []
        required_parameters = set((manifest.get("parameter_values") or {}).keys())
        for parameter_id in sorted(required_parameters):
            if not self._parameter_has_source_mapping(parameter_id, revised_scan):
                findings.append(
                    self._revision_compliance_finding(
                        "revision.configured_parameter_removed",
                        "Configured parameter removed",
                        f"{parameter_id} is active in the current configuration but missing from revised source.",
                        parameter_id=parameter_id,
                    )
                )
        return findings

    def _component_revision_scope_context(
        self,
        *,
        revision_plan_payload: dict[str, Any],
        design_plan_payload: dict[str, Any],
        source_metadata: dict[str, Any],
        output_manifest: dict[str, Any] | None,
        selected_findings: list[dict[str, Any]],
        configuration_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        targeted_components = list(map(str, revision_plan_payload.get("targeted_components", [])))
        targeted_features = list(map(str, revision_plan_payload.get("targeted_features", [])))
        targeted_outputs = list(map(str, revision_plan_payload.get("targeted_outputs", [])))
        protected_components = list(map(str, revision_plan_payload.get("protected_components", [])))
        protected_features = list(map(str, revision_plan_payload.get("protected_features", [])))
        protected_outputs = list(map(str, revision_plan_payload.get("protected_outputs", [])))
        allowed_shared_modules = list(map(str, revision_plan_payload.get("allowed_shared_modules", [])))
        module_fingerprints = source_metadata.get("module_fingerprints", {})
        def modules_for(kind: str, ids: list[str]) -> list[str]:
            result: set[str] = set()
            for module_name, fingerprint in module_fingerprints.items():
                values = fingerprint.get(f"{kind}_ids", [])
                if set(map(str, values)) & set(ids):
                    result.add(module_name)
            return sorted(result)

        return {
            "schema_version": "component-revision-scope-v1",
            "targeted_components": targeted_components,
            "targeted_features": targeted_features,
            "targeted_outputs": targeted_outputs,
            "target_modules": sorted(
                set(modules_for("component", targeted_components))
                | set(modules_for("feature", targeted_features))
                | set(modules_for("output", targeted_outputs))
            ),
            "allowed_shared_modules": allowed_shared_modules,
            "protected_components": protected_components,
            "protected_features": protected_features,
            "protected_outputs": protected_outputs,
            "protected_modules": sorted(
                set(modules_for("component", protected_components))
                | set(modules_for("feature", protected_features))
                | set(modules_for("output", protected_outputs))
            ),
            "protected_interfaces": list(revision_plan_payload.get("protected_interfaces", [])),
            "shared_parameters_allowed_to_change": list(
                revision_plan_payload.get("allowed_parameter_changes", [])
            ),
            "shared_parameters_required_unchanged": [
                item.get("parameter_id")
                for item in revision_plan_payload.get("protected_parameters", [])
                if item.get("parameter_id")
            ],
            "output_manifest_summary": output_manifest,
            "selected_findings": selected_findings,
            "active_configuration": configuration_context,
            "success_criteria": list(revision_plan_payload.get("success_criteria", [])),
            "source_metadata_summary": {
                "source_hash": source_metadata.get("source_hash"),
                "modules": source_metadata.get("module_names", []),
                "components": sorted(source_metadata.get("component_mappings", {})),
                "features": sorted(source_metadata.get("feature_mappings", {})),
                "outputs": sorted(source_metadata.get("output_mappings", {})),
                "shared_modules": sorted(source_metadata.get("shared_module_mappings", {})),
            },
        }

    def _revision_compliance_finding(
        self,
        rule_id: str,
        title: str,
        explanation: str,
        *,
        parameter_id: str | None = None,
        component_id: str | None = None,
        feature_id: str | None = None,
        output_id: str | None = None,
        expected: Any = None,
        detected: Any = None,
    ) -> dict[str, Any]:
        return {
            "rule_id": rule_id,
            "category": "revision_preservation",
            "severity": "critical",
            "is_blocking": True,
            "title": title,
            "explanation": explanation,
            "suggested_correction": "Regenerate the revision from the approved Revision Plan while preserving protected source markers and values.",
            "parameter_id": parameter_id,
            "component_id": component_id,
            "feature_id": feature_id,
            "output_id": output_id,
            "expected_value": expected,
            "detected_value": detected,
        }

    def _persist_revision_success_results(
        self,
        *,
        project: Project,
        revision_plan: RevisionPlan,
        generation_attempt_id: str | None,
        revision_id: str,
        source: str,
        revision_plan_payload: dict[str, Any],
        cad_backend: str = "cadquery",
    ) -> None:
        metadata = self._revision_source_metadata(
            source=source,
            cad_backend=cad_backend,
            design_specification_payload=None,
            design_plan_payload=None,
            source_type="ai_revision",
        )
        constants = evaluate_constants(metadata.assignments)
        outputs = {
            output.output_id: output
            for output in self.db.scalars(
                select(RevisionOutput).where(RevisionOutput.revision_id == revision_id)
            )
        }
        for criterion in revision_plan_payload.get("success_criteria", []):
            criterion_type = str(criterion.get("type") or "")
            target_id = str(criterion.get("target_id") or "")
            expected = criterion.get("expected_value")
            detected: Any = None
            state = "success_unverifiable"
            explanation = "Volundr could not verify this revision success criterion."
            blocking = False
            if criterion_type in {"parameter_value", "parameter_unchanged"}:
                detected = constants.get(target_id)
                if detected is None and target_id in metadata.assignments:
                    detected = metadata.assignments[target_id]
                if detected is None:
                    state = "success_unverifiable"
                    explanation = f"Parameter {target_id} could not be evaluated statically."
                elif self._values_equal(expected, detected):
                    state = "success_verified"
                    explanation = f"{target_id} matches the expected value."
                else:
                    state = "success_violated"
                    blocking = True
                    explanation = f"{target_id} does not match the Revision Plan success criterion."
            elif criterion_type == "output_exists":
                output = outputs.get(target_id)
                detected = output.execution_state if output is not None else None
                if output is not None and output.execution_state in OUTPUT_READY_STATES:
                    state = "success_verified"
                    explanation = f"Output {target_id} exists and is available for review."
                else:
                    state = "success_violated"
                    blocking = True
                    explanation = f"Output {target_id} is missing or unavailable."
            else:
                state = "success_unverifiable"
                explanation = f"Success criterion type {criterion_type} is not implemented yet."
            row = RevisionSuccessResult(
                project_id=project.id,
                revision_plan_id=revision_plan.id,
                generation_attempt_id=generation_attempt_id,
                revision_id=revision_id,
                criterion_type=criterion_type,
                target_id=target_id,
                verification_state=state,
                expected_value_json=json.dumps(expected, sort_keys=True),
                detected_value_json=json.dumps(detected, sort_keys=True),
                unit=criterion.get("unit"),
                tolerance=criterion.get("tolerance"),
                confidence=1.0 if state != "success_unverifiable" else 0.5,
                is_blocking=blocking,
                explanation=explanation,
                metadata_json=json.dumps({"criterion": criterion}, sort_keys=True),
            )
            self.db.add(row)
            if blocking:
                self.db.add(
                    ValidationFinding(
                        revision_id=revision_id,
                        rule_id="revision.success_criterion_failed",
                        category="revision_success",
                        severity="critical",
                        is_blocking=True,
                        title="Revision success criterion failed",
                        explanation=explanation,
                        suggested_correction="Create a new revision from the failed success criterion.",
                        detected_value=str(detected) if detected is not None else None,
                        unit=criterion.get("unit"),
                        threshold_value=str(expected) if expected is not None else None,
                        orientation_dependent=False,
                        metadata_json=json.dumps({"revision_plan_id": revision_plan.id, "criterion": criterion}, sort_keys=True),
                    )
                )
        self.db.flush()

    def _persist_component_revision_summary(
        self,
        *,
        project: Project,
        revision_plan: RevisionPlan,
        generation_attempt: GenerationAttempt,
        base_revision: Revision,
        revision_id: str,
        base_source: str,
        revised_source: str,
        revision_plan_payload: dict[str, Any],
        design_plan_payload: dict[str, Any],
        compliance_result: RevisionComplianceResult,
    ) -> ComponentRevisionSummary:
        revision = self.db.get(Revision, revision_id)
        if revision is None:
            raise ValueError("revision candidate is missing")
        base_outputs = {
            output.output_id: output
            for output in self.db.scalars(
                select(RevisionOutput).where(RevisionOutput.revision_id == base_revision.id)
            )
        }
        revised_outputs = {
            output.output_id: output
            for output in self.db.scalars(
                select(RevisionOutput).where(RevisionOutput.revision_id == revision_id)
            )
        }
        targeted_outputs = set(map(str, revision_plan_payload.get("targeted_outputs", [])))
        protected_outputs = set(map(str, revision_plan_payload.get("protected_outputs", [])))
        targeted_summary = [
            self._targeted_output_change_summary(
                output_id,
                base_outputs.get(output_id),
                revised_outputs.get(output_id),
            )
            for output_id in sorted(targeted_outputs)
        ]
        protected_summary = [
            self._protected_output_preservation_summary(
                revision=revision,
                output_id=output_id,
                base_output=base_outputs.get(output_id),
                revised_output=revised_outputs.get(output_id),
            )
            for output_id in sorted(protected_outputs)
        ]
        interface_checks = self._component_interface_checks(
            revision=revision,
            base_source=base_source,
            revised_source=revised_source,
            revision_plan_payload=revision_plan_payload,
        )
        payload = {
            "schema_version": "component-revision-summary-v1",
            "revision_plan_id": revision_plan.id,
            "base_revision_id": base_revision.id,
            "revision_id": revision_id,
            "revision_scope": {
                "targeted_components": list(map(str, revision_plan_payload.get("targeted_components", []))),
                "targeted_features": list(map(str, revision_plan_payload.get("targeted_features", []))),
                "targeted_outputs": sorted(targeted_outputs),
                "protected_components": list(map(str, revision_plan_payload.get("protected_components", []))),
                "protected_outputs": sorted(protected_outputs),
                "allowed_shared_modules": list(map(str, revision_plan_payload.get("allowed_shared_modules", []))),
            },
            "source_scope": {
                "compliance_result_id": compliance_result.id,
                "passed": compliance_result.passed,
            },
            "targeted_outputs": targeted_summary,
            "protected_outputs": protected_summary,
            "interfaces": interface_checks,
            "configuration_context": {
                "configuration_change_id": revision.configuration_change_id,
                "override_manifest": self._revision_override_manifest_payload(revision),
            },
        }
        result_dir = self._revision_plan_dir(project.id, revision_plan.id)
        result_dir.mkdir(parents=True, exist_ok=True)
        summary_path = result_dir / "component-revision-summary.json"
        self._write_json(summary_path, payload)
        row = ComponentRevisionSummary(
            project_id=project.id,
            revision_plan_id=revision_plan.id,
            revision_id=revision_id,
            base_revision_id=base_revision.id,
            generation_attempt_id=generation_attempt.id,
            base_source_hash=hashlib.sha256(base_source.encode("utf-8")).hexdigest(),
            revised_source_hash=hashlib.sha256(revised_source.encode("utf-8")).hexdigest(),
            equivalence_profile_version="output-preservation-v1",
            summary_path=self._relative(summary_path),
        )
        self.db.add(row)
        self.db.flush()
        return row

    def _targeted_output_change_summary(
        self,
        output_id: str,
        base_output: RevisionOutput | None,
        revised_output: RevisionOutput | None,
    ) -> dict[str, Any]:
        if revised_output is None or revised_output.execution_state not in OUTPUT_READY_STATES:
            return {
                "output_id": output_id,
                "change_state": "changed_but_failed_validation",
                "explanation": "The targeted output is missing or did not finish validation.",
            }
        comparison = self._compare_output_metadata(base_output, revised_output)
        changed = bool(comparison.get("changed"))
        return {
            "output_id": output_id,
            "change_state": "changed_as_expected" if changed else "change_not_detected",
            "comparison": comparison,
            "explanation": "The targeted output changed."
            if changed
            else "No measurable targeted output change was detected.",
        }

    def _protected_output_preservation_summary(
        self,
        *,
        revision: Revision,
        output_id: str,
        base_output: RevisionOutput | None,
        revised_output: RevisionOutput | None,
    ) -> dict[str, Any]:
        if base_output is None or revised_output is None:
            self.db.add(
                self._output_preservation_finding(
                    revision.id,
                    "revision.protected_output_missing",
                    "Protected output missing",
                    f"Protected output {output_id} is missing from the base or revised revision.",
                    output_id=output_id,
                    blocking=True,
                )
            )
            return {"output_id": output_id, "preservation_state": "unexpected_change"}
        if revised_output.execution_state not in OUTPUT_READY_STATES:
            self.db.add(
                self._output_preservation_finding(
                    revision.id,
                    "revision.protected_output_failed",
                    "Protected output failed",
                    f"Protected output {output_id} did not compile or validate successfully.",
                    output_id=output_id,
                    revision_output_id=revised_output.id,
                    blocking=True,
                )
            )
            return {"output_id": output_id, "preservation_state": "unexpected_change"}
        comparison = self._compare_output_metadata(base_output, revised_output)
        if comparison.get("unverifiable"):
            self.db.add(
                self._output_preservation_finding(
                    revision.id,
                    "revision.protected_output_preservation_unverifiable",
                    "Protected output preservation unverifiable",
                    f"Volundr could not verify whether protected output {output_id} remained equivalent.",
                    output_id=output_id,
                    revision_output_id=revised_output.id,
                    blocking=False,
                )
            )
            return {"output_id": output_id, "preservation_state": "unverifiable", "comparison": comparison}
        if comparison.get("beyond_tolerance"):
            self.db.add(
                self._output_preservation_finding(
                    revision.id,
                    "revision.protected_output_unexpected_change",
                    "Protected output changed",
                    f"Protected output {output_id} changed beyond output-preservation tolerance.",
                    output_id=output_id,
                    revision_output_id=revised_output.id,
                    blocking=True,
                    metadata=comparison,
                )
            )
            return {"output_id": output_id, "preservation_state": "unexpected_change", "comparison": comparison}
        state = "changed_within_tolerance" if comparison.get("changed") else "verified_unchanged"
        return {"output_id": output_id, "preservation_state": state, "comparison": comparison}

    def _compare_output_metadata(
        self,
        base_output: RevisionOutput | None,
        revised_output: RevisionOutput | None,
    ) -> dict[str, Any]:
        if base_output is None or revised_output is None:
            return {"unverifiable": True, "reason": "missing_output_record"}
        base_meta = self._output_mesh_metadata(base_output)
        revised_meta = self._output_mesh_metadata(revised_output)
        if base_meta is None or revised_meta is None:
            return {"unverifiable": True, "reason": "missing_mesh_metadata"}
        tolerances = {"dimension_mm": 0.25, "volume_relative": 0.01}
        dimensions: dict[str, dict[str, float]] = {}
        beyond = False
        changed = base_output.stl_hash != revised_output.stl_hash
        for key in ("size_x_mm", "size_y_mm", "size_z_mm"):
            base_value = float(base_meta.get(key, 0) or 0)
            revised_value = float(revised_meta.get(key, 0) or 0)
            delta = abs(revised_value - base_value)
            dimensions[key] = {"base": base_value, "revised": revised_value, "delta": delta}
            if delta > tolerances["dimension_mm"]:
                beyond = True
            if delta > 1e-6:
                changed = True
        base_volume = float(base_meta.get("volume_mm3", 0) or 0)
        revised_volume = float(revised_meta.get("volume_mm3", 0) or 0)
        volume_delta = abs(revised_volume - base_volume)
        if base_volume > 0 and volume_delta / base_volume > tolerances["volume_relative"]:
            beyond = True
        if volume_delta > 1e-6:
            changed = True
        component_delta = int(revised_meta.get("connected_components", 0) or 0) - int(
            base_meta.get("connected_components", 0) or 0
        )
        if component_delta != 0:
            beyond = True
            changed = True
        topology = self._compare_output_topology(base_output, revised_output)
        if topology.get("changed"):
            changed = True
        if topology.get("beyond_tolerance"):
            beyond = True
        return {
            "profile_version": "output-preservation-v1",
            "changed": changed,
            "beyond_tolerance": beyond,
            "dimensions": dimensions,
            "volume_mm3": {"base": base_volume, "revised": revised_volume, "delta": volume_delta},
            "connected_components_delta": component_delta,
            "topology": topology,
            "hash_equal": base_output.stl_hash == revised_output.stl_hash,
            "tolerances": tolerances,
        }

    def _output_mesh_metadata(self, output: RevisionOutput) -> dict[str, Any] | None:
        if not output.metadata_json:
            return None
        try:
            return json.loads(output.metadata_json)
        except json.JSONDecodeError:
            return None

    def _compare_output_topology(
        self,
        base_output: RevisionOutput,
        revised_output: RevisionOutput,
    ) -> dict[str, Any]:
        base_topology = self._output_topology_metadata(base_output)
        revised_topology = self._output_topology_metadata(revised_output)
        if base_topology is None or revised_topology is None:
            return {"unverifiable": True, "reason": "missing_topology_metadata"}
        changed = False
        beyond = False
        scalar_fields = (
            "valid",
            "detected_solid_count",
            "expected_solid_count",
            "allow_disconnected_solids",
            "shell_count",
        )
        scalars: dict[str, dict[str, Any]] = {}
        for field in scalar_fields:
            base_value = base_topology.get(field)
            revised_value = revised_topology.get(field)
            scalars[field] = {"base": base_value, "revised": revised_value}
            if base_value != revised_value:
                changed = True
                if field in {"valid", "detected_solid_count", "expected_solid_count", "shell_count"}:
                    beyond = True
        bounding_box = self._compare_bounding_boxes(
            base_topology.get("bounding_box_mm"),
            revised_topology.get("bounding_box_mm"),
        )
        if bounding_box.get("changed"):
            changed = True
        if bounding_box.get("beyond_tolerance"):
            beyond = True
        advisory: dict[str, dict[str, Any]] = {}
        for field in ("face_count", "edge_count", "volume_mm3"):
            if field not in base_topology and field not in revised_topology:
                continue
            base_value = base_topology.get(field)
            revised_value = revised_topology.get(field)
            advisory[field] = {"base": base_value, "revised": revised_value}
            if base_value != revised_value:
                changed = True
        return {
            "unverifiable": False,
            "changed": changed,
            "beyond_tolerance": beyond,
            "scalars": scalars,
            "bounding_box_mm": bounding_box,
            "advisory": advisory,
        }

    def _compare_bounding_boxes(self, base: Any, revised: Any) -> dict[str, Any]:
        if not isinstance(base, dict) or not isinstance(revised, dict):
            return {"unverifiable": True, "reason": "missing_bounding_box"}
        tolerances = {"dimension_mm": 0.25}
        axes: dict[str, dict[str, float]] = {}
        changed = False
        beyond = False
        for key in ("xlen", "ylen", "zlen"):
            base_value = float(base.get(key, 0) or 0)
            revised_value = float(revised.get(key, 0) or 0)
            delta = abs(revised_value - base_value)
            axes[key] = {"base": base_value, "revised": revised_value, "delta": delta}
            if delta > 1e-6:
                changed = True
            if delta > tolerances["dimension_mm"]:
                beyond = True
        return {
            "unverifiable": False,
            "changed": changed,
            "beyond_tolerance": beyond,
            "dimensions": axes,
            "tolerances": tolerances,
        }

    def _output_topology_metadata(self, output: RevisionOutput) -> dict[str, Any] | None:
        if not output.topology_metadata_json:
            return None
        try:
            return json.loads(output.topology_metadata_json)
        except json.JSONDecodeError:
            return None

    def _component_interface_checks(
        self,
        *,
        revision: Revision,
        base_source: str,
        revised_source: str,
        revision_plan_payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        design_plan_payload = self._revision_design_plan_payload(revision) or {}
        base_scan = self._cadquery_revision_source_metadata(base_source, design_plan_payload)
        revised_scan = self._cadquery_revision_source_metadata(revised_source, design_plan_payload)
        base_constants = evaluate_constants(base_scan.assignments)
        revised_constants = evaluate_constants(revised_scan.assignments)
        checks: list[dict[str, Any]] = []
        for interface in revision_plan_payload.get("protected_interfaces", []):
            interface_id = str(interface.get("id") or "interface")
            for parameter_id in map(str, interface.get("parameters", [])):
                base_value = base_constants.get(parameter_id, base_scan.assignments.get(parameter_id))
                revised_value = revised_constants.get(parameter_id, revised_scan.assignments.get(parameter_id))
                state = "verified"
                blocking = False
                if not self._values_equal(base_value, revised_value):
                    state = "violated"
                    blocking = True
                    self.db.add(
                        self._output_preservation_finding(
                            revision.id,
                            "revision.interface_parameter_changed",
                            "Protected interface changed",
                            f"{parameter_id} changed on protected interface {interface_id}.",
                            blocking=True,
                            metadata={
                                "interface_id": interface_id,
                                "parameter_id": parameter_id,
                                "base_value": base_value,
                                "revised_value": revised_value,
                            },
                        )
                    )
                checks.append(
                    {
                        "interface_id": interface_id,
                        "parameter_id": parameter_id,
                        "verification_state": state,
                        "is_blocking": blocking,
                        "expected_value": base_value,
                        "detected_value": revised_value,
                    }
                )
        return checks

    def _output_preservation_finding(
        self,
        revision_id: str,
        rule_id: str,
        title: str,
        explanation: str,
        *,
        output_id: str | None = None,
        revision_output_id: str | None = None,
        blocking: bool,
        metadata: dict[str, Any] | None = None,
    ) -> ValidationFinding:
        return ValidationFinding(
            revision_id=revision_id,
            revision_output_id=revision_output_id,
            rule_id=rule_id,
            category="output_preservation",
            severity="critical" if blocking else "warning",
            is_blocking=blocking,
            title=title,
            explanation=explanation,
            suggested_correction="Create a new component-targeted revision that preserves protected outputs and interfaces.",
            detected_value=output_id,
            orientation_dependent=False,
            metadata_json=json.dumps(metadata or {"output_id": output_id}, sort_keys=True),
        )

    def _values_equal(self, expected: Any, detected: Any, *, tolerance: float = 1e-6) -> bool:
        if expected is None:
            return detected is None
        try:
            return abs(float(expected) - float(detected)) <= tolerance
        except (TypeError, ValueError):
            return str(expected) == str(detected)

    def _selected_finding_payloads(
        self,
        *,
        project_id: str,
        revision_id: str,
        finding_ids: list[str],
    ) -> list[dict[str, Any]]:
        if not finding_ids:
            return []
        findings: list[dict[str, Any]] = []
        for finding_id in finding_ids:
            finding = self.db.get(ValidationFinding, finding_id)
            if finding is None or finding.revision_id != revision_id:
                raise ValueError("targeted finding not found for base revision")
            if finding.revision_id:
                revision = self.db.get(Revision, finding.revision_id)
                if revision is None or revision.project_id != project_id:
                    raise ValueError("targeted finding not found for project")
            findings.append(
                {
                    "id": finding.id,
                    "revision_id": finding.revision_id,
                    "revision_output_id": finding.revision_output_id,
                    "rule_id": finding.rule_id,
                    "category": finding.category,
                    "severity": finding.severity,
                    "is_blocking": finding.is_blocking,
                    "title": finding.title,
                    "explanation": finding.explanation,
                    "suggested_correction": finding.suggested_correction,
                    "detected_value": finding.detected_value,
                    "threshold_value": finding.threshold_value,
                    "unit": finding.unit,
                    "metadata": json.loads(finding.metadata_json or "{}"),
                }
            )
        return findings

    def _persist_revision_specification_snapshot(
        self,
        *,
        project: Project,
        base_specification: DesignSpecification | None,
        revision_plan: RevisionPlan,
        base_payload: dict[str, Any],
        revision_plan_payload: dict[str, Any],
    ) -> DesignSpecification:
        payload = json.loads(json.dumps(base_payload))
        for change in revision_plan_payload.get("requested_changes", []):
            target_id = change.get("target_id")
            if not target_id:
                continue
            for collection in ("critical_dimensions", "parameters"):
                for item in payload.get(collection, []):
                    if item.get("id") == target_id:
                        item["value"] = change.get("requested_value")
                        item["source"] = "user"
        payload["superseded_by_revision_plan_id"] = revision_plan.id
        spec_dir = self._revision_plan_dir(project.id, revision_plan.id)
        spec_dir.mkdir(parents=True, exist_ok=True)
        spec_path = spec_dir / "revised-design-specification.json"
        self._write_json(spec_path, payload)
        specification = DesignSpecification(
            project_id=project.id,
            generation_attempt_id=revision_plan.generation_attempt_id,
            superseded_specification_id=base_specification.id if base_specification else None,
            version_number=self._next_design_specification_version(project.id),
            schema_version=str(payload.get("schema_version", DESIGN_SPEC_SCHEMA_VERSION)),
            prompt_template_version=revision_plan.prompt_template_version,
            ruleset_version=revision_plan.ruleset_version,
            provider=revision_plan.provider,
            provider_model=revision_plan.provider_model,
            user_instruction=revision_plan.user_instruction,
            raw_response_path=None,
            specification_path=self._relative(spec_path),
            content_hash=self._sha256(json.dumps(payload, sort_keys=True)),
            outcome=str(payload.get("outcome") or RequirementOutcome.GENERATION_READY.value),
            supported_scope=bool(payload.get("supported_scope", True)),
            clarification_required=bool(payload.get("clarification_required", False)),
            generation_ready=bool(payload.get("generation_ready", True)),
        )
        self.db.add(specification)
        self.db.flush()
        return specification

    def _persist_revision_design_plan_snapshot(
        self,
        *,
        project: Project,
        base_plan: DesignPlan,
        revision_plan: RevisionPlan,
        base_payload: dict[str, Any],
        revision_plan_payload: dict[str, Any],
    ) -> DesignPlan:
        payload = json.loads(json.dumps(base_payload))
        for change in revision_plan_payload.get("requested_changes", []):
            target_id = change.get("target_id")
            if not target_id:
                continue
            for parameter in payload.get("parameters", []):
                if parameter.get("id") == target_id:
                    parameter["value"] = change.get("requested_value")
        requested_controls = [
            item for item in revision_plan_payload.get("requested_exposed_controls", []) or []
            if isinstance(item, dict) and item.get("parameter_id")
        ]
        if requested_controls:
            existing_controls = [
                item if isinstance(item, dict) else {"parameter_id": item}
                for item in payload.get("exposed_controls", []) or []
                if item
            ]
            by_id = {
                str(item.get("parameter_id")): item
                for item in existing_controls
                if item.get("parameter_id")
            }
            for control in requested_controls:
                by_id[str(control["parameter_id"])] = dict(control)
            payload["exposed_controls"] = list(by_id.values())
        payload["superseded_by_revision_plan_id"] = revision_plan.id
        plan_dir = self._revision_plan_dir(project.id, revision_plan.id)
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_path = plan_dir / "revised-design-plan.json"
        self._write_json(plan_path, payload)
        plan = DesignPlan(
            project_id=project.id,
            design_specification_id=revision_plan.revised_design_specification_id
            or base_plan.design_specification_id,
            generation_attempt_id=revision_plan.generation_attempt_id,
            superseded_design_plan_id=base_plan.id,
            version_number=self._next_design_plan_version(project.id),
            schema_version=str(payload.get("schema_version", DESIGN_PLAN_SCHEMA_VERSION)),
            prompt_template_version=revision_plan.prompt_template_version,
            ruleset_version=revision_plan.ruleset_version,
            provider=revision_plan.provider,
            provider_model=revision_plan.provider_model,
            raw_response_path=None,
            plan_path=self._relative(plan_path),
            content_hash=self._sha256(json.dumps(payload, sort_keys=True)),
            outcome=DesignPlanOutcome.PLAN_READY.value,
            review_state=DesignPlanReviewState.APPROVED.value,
            clarification_required=False,
            plan_ready=True,
            approved_at=project_utcnow(),
        )
        self.db.add(plan)
        self.db.flush()
        return plan

    def _revision_success_result_read(self, row: RevisionSuccessResult) -> RevisionSuccessResultRead:
        return RevisionSuccessResultRead(
            id=row.id,
            project_id=row.project_id,
            revision_plan_id=row.revision_plan_id,
            generation_attempt_id=row.generation_attempt_id,
            revision_id=row.revision_id,
            criterion_type=row.criterion_type,
            target_id=row.target_id,
            verification_state=row.verification_state,
            expected_value=json.loads(row.expected_value_json)
            if row.expected_value_json is not None
            else None,
            detected_value=json.loads(row.detected_value_json)
            if row.detected_value_json is not None
            else None,
            unit=row.unit,
            tolerance=row.tolerance,
            confidence=row.confidence,
            is_blocking=row.is_blocking,
            explanation=row.explanation,
            metadata=json.loads(row.metadata_json or "{}"),
        )

    def _persist_geometric_analysis(
        self,
        *,
        revision: Revision,
        stl_path: Path,
        source: str,
        design_specification_payload: dict[str, Any] | None,
        design_specification_id: str | None,
        revision_output: RevisionOutput | None = None,
    ) -> None:
        if design_specification_payload is None:
            return
        loaded = trimesh.load(stl_path, force="mesh")
        mesh = _as_mesh(loaded)
        source_metadata = self._cadquery_revision_source_metadata(
            source,
            self._revision_design_plan_payload(revision) or {},
        )
        design_plan_payload = self._revision_design_plan_payload(revision) or {}
        context = GeometricAnalysisContext(
            mesh=mesh,
            design_specification=design_specification_payload,
            source_metadata=source_metadata,
            source_hash=source_metadata.source_hash,
            mesh_hash=mesh_hash(mesh),
        )
        result = GeometryAnalyzerRegistry.default().analyze(context)
        functional_contract = design_plan_payload.get("functional_contract")
        if isinstance(functional_contract, dict):
            parameter_manifest = None
            if revision.execution_manifest_path:
                execution_manifest = self._read_json_file(revision.execution_manifest_path)
                if isinstance(execution_manifest, dict):
                    parameter_manifest = execution_manifest.get("parameters")
            result.findings.extend(
                FunctionalGeometryVerifierRegistry.default().verify(
                    FunctionalGeometryContext(
                        product_plan=design_plan_payload,
                        output_shape=mesh,
                        source_metadata=source_metadata,
                        parameter_manifest=parameter_manifest,
                    )
                )
            )
        authority = authority_from_generation_context(design_plan_payload=design_plan_payload)
        if authority is not None:
            try:
                validate_cadquery_source_authority(source, authority)
            except CadQuerySourceAuthorityError as error:
                for source_finding in error.findings:
                    if source_finding.get("rule_id") not in {
                        "cadquery.protected_parameter_no_geometry_effect",
                        "cadquery.functional_parameter_unused",
                        "functional.feature_declared_not_invoked",
                        "functional.feature_result_discarded",
                        "functional.protected_feature_missing",
                        "geometry_body.required_effect_missing",
                        "geometry_body.derived_dependency_broken",
                        "geometry_body.pattern_count_hardcoded",
                        "geometry_body.pattern_spacing_hardcoded",
                        "geometry_body.dimension_bypassed_by_literal",
                        "geometry_body.effect_unverifiable",
                    }:
                        continue
                    result.findings.append(
                        GeometricFinding(
                            rule_id=f"functional.{source_finding['rule_id'].split('.', 1)[-1]}",
                            requirement_id=source_finding.get("parameter_id"),
                            verification_state="violated",
                            expected_value=source_finding.get("expected_value"),
                            detected_value=source_finding.get("detected_value"),
                            unit=None,
                            tolerance=None,
                            confidence=1.0,
                            severity="critical",
                            is_blocking=True,
                            title="Functional parameter or feature implementation",
                            explanation=source_finding.get("explanation") or source_finding.get("message") or "Functional source evidence is missing.",
                            suggested_correction="Regenerate the source so the approved functional parameter or feature changes the intended geometry.",
                            feature_id=source_finding.get("feature_id"),
                            metadata={"source_contract_rule_id": source_finding.get("rule_id")},
                        )
                    )
        if not source_metadata.geometry_mappings and self._has_protected_design_invariants(
            design_specification_payload
        ):
            result.findings.append(
                GeometricFinding(
                    rule_id="geometry.missing_geometry_metadata",
                    requirement_id=None,
                    verification_state="unverifiable",
                    expected_value="protected geometry metadata",
                    detected_value=None,
                    unit=None,
                    tolerance=None,
                    confidence=0.0,
                    severity="warning",
                    is_blocking=False,
                    title="Geometric invariants not verified",
                    explanation="The compiled model has protected Design Specification values, but the source and Design Plan did not provide parseable geometry metadata for supported invariant checks.",
                    suggested_correction="Review the model manually or revise the source or Design Plan metadata to map measurable protected bounds, holes, hole groups, or wall thickness.",
                    metadata={"metadata_source": "cadquery_source_and_design_plan"},
                )
            )
        requirement_ledger = RequirementLedgerStore(self.db).load(revision.project_id)
        active_requirement_items = active_requirements(requirement_ledger)
        if active_requirement_items:
            result.findings.extend(
                evaluate_requirement_compliance(
                    active_requirement_items,
                    evidence=list(result.findings),
                    present_feature_ids=set(source_metadata.feature_mappings),
                )
            )
        revision_dir = self._revision_dir(revision.project_id, revision.id)
        result_path = (
            revision_dir / "geometry-analysis.json"
            if revision_output is None
            else revision_dir / "geometry" / f"{self._safe_stem(revision_output.output_id)}.json"
        )
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_payload = result.to_json()

        persisted = GeometricAnalysisResult(
            revision_id=revision.id,
            revision_output_id=revision_output.id if revision_output is not None else None,
            design_specification_id=design_specification_id,
            analysis_version=result.analysis_version,
            tolerance_profile_version=result.tolerance_profile_version,
            mesh_hash=result.mesh_hash,
            source_hash=result.source_hash,
            result_path=self._relative(result_path),
            analysis_ms=result.analysis_ms,
        )
        self.db.add(persisted)
        self.db.flush()
        for index, finding in enumerate(result.findings):
            if finding.verification_state in {"violated", "unverifiable", "human_review"}:
                validation_finding = self._validation_finding_from_geometric_result(
                    finding,
                    revision_id=revision.id,
                    revision_output_id=revision_output.id if revision_output is not None else None,
                    design_specification_id=design_specification_id,
                    analysis_result_id=persisted.id,
                    analysis_version=result.analysis_version,
                    tolerance_profile_version=result.tolerance_profile_version,
                    mesh_hash_value=result.mesh_hash,
                    source_hash_value=result.source_hash,
                )
                self.db.add(validation_finding)
                self.db.flush()
                result_payload["findings"][index]["validation_finding_id"] = validation_finding.id
            else:
                result_payload["findings"][index]["validation_finding_id"] = None
        self._write_json(result_path, result_payload)

    def _validation_finding_from_geometric_result(
        self,
        finding: GeometricFinding,
        *,
        revision_id: str,
        revision_output_id: str | None = None,
        design_specification_id: str | None,
        analysis_result_id: str,
        analysis_version: str,
        tolerance_profile_version: str,
        mesh_hash_value: str,
        source_hash_value: str | None,
    ) -> ValidationFinding:
        metadata = dict(finding.metadata)
        metadata.update(
            {
                "finding_origin": "geometric_invariant",
                "analysis_result_id": analysis_result_id,
                "analysis_version": analysis_version,
                "tolerance_profile_version": tolerance_profile_version,
                "mesh_hash": mesh_hash_value,
                "source_hash": source_hash_value,
                "requirement_id": finding.requirement_id,
                "feature_id": finding.feature_id,
                "verification_state": finding.verification_state,
                "confidence": finding.confidence,
                "expected_value": finding.expected_value,
                "detected_value": finding.detected_value,
                "tolerance": finding.tolerance,
            }
        )
        return ValidationFinding(
            revision_id=revision_id,
            revision_output_id=revision_output_id,
            design_specification_id=design_specification_id,
            rule_id=finding.rule_id,
            category="requirement" if finding.rule_id.startswith("requirement.") else "geometry",
            severity=finding.severity,
            is_blocking=finding.is_blocking,
            title=finding.title,
            explanation=finding.explanation,
            suggested_correction=finding.suggested_correction,
            detected_value=self._format_finding_value(finding.detected_value),
            unit=finding.unit,
            threshold_value=self._format_finding_value(finding.expected_value),
            orientation_dependent=finding.rule_id.startswith("geometry.build_plate"),
            affected_geometry_summary=f"feature={finding.feature_id}"
            if finding.feature_id
            else None,
            metadata_json=json.dumps(metadata, sort_keys=True),
        )

    def _format_finding_value(self, value: float | int | str | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, float):
            return f"{value:.3f}".rstrip("0").rstrip(".")
        return str(value)

    def _has_protected_design_invariants(self, payload: dict[str, Any]) -> bool:
        return any(
            entry.get("protected")
            for entry in [
                *payload.get("critical_dimensions", []),
                *payload.get("parameters", []),
                *payload.get("functional_requirements", []),
            ]
            if isinstance(entry, dict)
        )

    def _persist_validation_findings(
        self,
        *,
        revision: Revision,
        stl_path: Path,
        revision_output: RevisionOutput | None = None,
    ) -> None:
        report = inspect_printability(stl_path, PrintabilityProfile())
        for result in report.results:
            if result.severity == "Pass":
                continue
            self.db.add(
                self._validation_finding_from_printability_result(
                    revision.id,
                    result,
                    revision_output=revision_output,
                )
            )
        self.db.flush()

    def _validation_finding_from_printability_result(
        self,
        revision_id: str,
        result: PrintabilityResult,
        *,
        revision_output: RevisionOutput | None = None,
    ) -> ValidationFinding:
        severity = result.severity.lower()
        metadata = {
            "printability_profile_version": "printability-fdm-v1",
            "affected_count": result.affected_count,
            "affected_area_mm2": result.affected_area_mm2,
            "highlight": result.highlight.model_dump() if result.highlight is not None else None,
        }
        return ValidationFinding(
            revision_id=revision_id,
            revision_output_id=revision_output.id if revision_output is not None else None,
            rule_id=result.rule_id,
            category=result.rule_id.split(".", 1)[0],
            severity=severity,
            is_blocking=self._is_blocking_printability_result(
                result,
                revision_output=revision_output,
            ),
            title=result.rule_id.replace(".", " ").replace("_", " ").title(),
            explanation=result.explanation,
            suggested_correction=result.suggested_correction,
            detected_value=str(result.detected_value.value),
            unit=result.detected_value.units,
            threshold_value=None,
            orientation_dependent=result.orientation_dependent,
            affected_geometry_summary=self._affected_geometry_summary(result),
            metadata_json=json.dumps(metadata, sort_keys=True),
        )

    def _is_blocking_printability_result(
        self,
        result: PrintabilityResult,
        *,
        revision_output: RevisionOutput | None = None,
    ) -> bool:
        if result.rule_id == "mesh.disconnected_components" and revision_output is not None:
            component_ids = self._json_list(revision_output.component_ids_json)
            if revision_output.required and len(component_ids) <= 1:
                return True
        if result.rule_id in BLOCKING_RULE_IDS:
            return True
        return result.severity == "Critical" and result.rule_id in BLOCKING_CRITICAL_RULE_IDS

    def _json_list(self, value: str | None) -> list[Any]:
        if not value:
            return []
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []

    def _affected_geometry_summary(self, result: PrintabilityResult) -> str | None:
        pieces = []
        if result.affected_count is not None:
            pieces.append(f"affected_count={result.affected_count}")
        if result.affected_area_mm2 is not None:
            pieces.append(f"affected_area_mm2={result.affected_area_mm2}")
        return ", ".join(pieces) if pieces else None

    def _derive_review_state(self, revision_id: str) -> str:
        findings = list(
            self.db.scalars(select(ValidationFinding).where(ValidationFinding.revision_id == revision_id))
        )
        if any(finding.is_blocking for finding in findings):
            return "blocked"
        if findings:
            return "ready_with_warnings"
        return "ready"

    def _derive_functional_status(self, revision_id: str) -> str:
        revision = self.db.get(Revision, revision_id)
        findings = list(
            self.db.scalars(
                select(ValidationFinding).where(
                    ValidationFinding.revision_id == revision_id,
                    ValidationFinding.rule_id.like("functional.%"),
                )
            )
        )
        if not findings:
            plan_payload = (
                self._read_json_file(revision.design_plan.plan_path)
                if revision is not None and revision.design_plan is not None
                else None
            )
            functional_contract = plan_payload.get("functional_contract") if isinstance(plan_payload, dict) else None
            if not isinstance(functional_contract, dict) or not any(
                isinstance(functional_contract.get(collection), list) and functional_contract.get(collection)
                for collection in (
                    "mounting_interfaces",
                    "support_interfaces",
                    "containment_interfaces",
                    "retention_interfaces",
                )
            ):
                return "functionally_verified"
            return "functionally_unverified"
        if any(finding.is_blocking for finding in findings):
            return "functionally_violated"
        if any(finding.verification_state in {"partially_verified", "unverifiable"} for finding in findings):
            return "functionally_partially_verified"
        return "functionally_verified"

    def _should_auto_accept_revision(
        self,
        *,
        project: Project,
        source_type: str,
        review_state: str,
    ) -> bool:
        if review_state == "blocked":
            return False
        if source_type in AI_SOURCE_TYPES:
            return False
        return project.active_revision_id is None

    def _has_blocking_findings(self, revision_id: str) -> bool:
        return (
            self.db.scalar(
                select(func.count(ValidationFinding.id)).where(
                    ValidationFinding.revision_id == revision_id,
                    ValidationFinding.is_blocking.is_(True),
                )
            )
            or 0
        ) > 0

    def _has_design_artifact_consistency_blockers(self, revision_id: str) -> bool:
        return (
            self.db.scalar(
                select(func.count(ValidationFinding.id)).where(
                    ValidationFinding.revision_id == revision_id,
                    ValidationFinding.category == "design_artifact_consistency",
                    ValidationFinding.is_blocking.is_(True),
                )
            )
            or 0
        ) > 0

    def _validation_summary(
        self,
        revision_id: str,
        *,
        revision_output_id: str | None = None,
    ) -> ValidationSummaryRead:
        query = select(ValidationFinding).where(ValidationFinding.revision_id == revision_id)
        if revision_output_id is not None:
            query = query.where(ValidationFinding.revision_output_id == revision_output_id)
        findings = list(self.db.scalars(query))
        return ValidationSummaryRead(
            blocking_count=sum(1 for finding in findings if finding.is_blocking),
            advisory_count=sum(1 for finding in findings if not finding.is_blocking),
            dismissed_count=sum(1 for finding in findings if finding.dismissed_at is not None),
        )

    def _create_failed_ai_revision(
        self,
        *,
        project: Project,
        user_instruction: str,
        source_type: str,
        raw_ai_output: str,
        error_message: str,
    ) -> RevisionRead:
        revision_number = self._next_revision_number(project.id)
        revision = Revision(
            project_id=project.id,
            parent_revision_id=project.active_revision_id,
            revision_number=revision_number,
            source_type=source_type,
            user_instruction=user_instruction,
            cad_backend="cadquery",
            source_language="python",
            source_path="",
            status="failed",
            is_accepted=False,
        )
        self.db.add(revision)
        self.db.flush()

        revision_dir = self._revision_dir(project.id, revision.id)
        revision_dir.mkdir(parents=True, exist_ok=True)
        source_path = revision_dir / "source.py"
        source_path.write_text("", encoding="utf-8")
        ai_output_path = revision_dir / "ai-output.txt"
        ai_output_path.write_text(raw_ai_output, encoding="utf-8")
        compile_log_path = revision_dir / "compile.log"
        compile_log_path.write_text(error_message, encoding="utf-8")

        revision.source_path = self._relative(source_path)
        revision.source_hash = self._sha256("")
        revision.source_contract_version = "cadquery-v1"
        revision.ai_output_path = self._relative(ai_output_path)
        revision.compile_log_path = self._relative(compile_log_path)
        self._record_revision_messages(revision=revision, user_instruction=user_instruction)
        self.db.commit()
        self.db.refresh(revision)
        return self._revision_read(revision, error_message=error_message)

    async def _create_cadquery_revision_from_planned_source(
        self,
        *,
        project_id: str,
        source: str,
        user_instruction: str | None,
        source_type: str,
        raw_ai_output: str | None,
        design_specification_id: str | None,
        design_specification_payload: dict[str, Any] | None,
        design_plan_id: str | None,
        design_plan_payload: dict[str, Any],
        source_validation_result_id: str | None,
        parameter_values: dict[str, Any] | None = None,
        parent_revision_id: str | None = None,
        configuration_change_id: str | None = None,
        parameter_overrides: dict[str, Any] | None = None,
        auto_accept: bool = False,
        workflow_run: WorkflowRun | None = None,
    ) -> RevisionRead | None:
        project = self.db.get(Project, project_id)
        if project is None:
            return None

        outputs = self._planned_printable_outputs(design_plan_payload)
        if not outputs:
            raise ValueError("Design Plan has no printable outputs")

        revision_number = self._next_revision_number(project_id)
        revision = Revision(
            project_id=project_id,
            parent_revision_id=parent_revision_id or project.active_revision_id,
            design_specification_id=design_specification_id,
            design_plan_id=design_plan_id,
            configuration_change_id=configuration_change_id,
            revision_number=revision_number,
            source_type=source_type,
            user_instruction=user_instruction,
            cad_backend="cadquery",
            source_language="python",
            source_path="",
            status="compiling",
            is_accepted=False,
            expected_output_count=len(outputs),
            required_output_count=sum(1 for output in outputs if output["required"]),
            successful_output_count=0,
            blocked_output_count=0,
            failed_output_count=0,
        )
        self.db.add(revision)
        self.db.flush()
        if source_validation_result_id is not None:
            self._attach_source_validation_to_revision(
                source_validation_result_id=source_validation_result_id,
                revision_id=revision.id,
            )

        revision_dir = self._revision_dir(project_id, revision.id)
        revision_dir.mkdir(parents=True, exist_ok=True)
        stl_dir = revision_dir / "stl"
        step_dir = revision_dir / "step"
        brep_dir = revision_dir / "brep"
        log_dir = revision_dir / "logs"
        metadata_dir = revision_dir / "metadata"
        for directory in (stl_dir, step_dir, brep_dir, log_dir, metadata_dir):
            directory.mkdir(parents=True, exist_ok=True)

        source_path = revision_dir / "source.py"
        source_path.write_text(source, encoding="utf-8")
        source_hash = self._sha256(source)
        ai_output_relative_path: str | None = None
        if raw_ai_output is not None:
            ai_output_path = revision_dir / "ai-output.txt"
            ai_output_path.write_text(raw_ai_output, encoding="utf-8")
            ai_output_relative_path = self._relative(ai_output_path)

        compile_parameter_values = self._cadquery_execution_parameter_values(
            source=source,
            design_plan_payload=design_plan_payload,
            overrides=parameter_values,
        )
        explicit_inventory = inventory_from_design_specification(design_specification_payload)
        if explicit_inventory:
            validate_execution_parameters(compile_parameter_values, explicit_inventory)
        parameter_hash = self._configuration_parameter_hash(compile_parameter_values)
        generation_attempt_id = self._source_validation_generation_attempt_id(source_validation_result_id)
        if design_plan_id is not None:
            pre_execution_consistency = self._persist_design_artifact_consistency(
                revision=revision,
                source=source,
                design_specification_payload=design_specification_payload,
                design_plan_payload=design_plan_payload,
                execution_parameters=compile_parameter_values,
                parameter_overrides=parameter_overrides,
                generation_attempt_id=generation_attempt_id,
            )
            if not pre_execution_consistency.pre_execution_passed:
                payload = self._read_design_artifact_consistency_payload(pre_execution_consistency)
                error_message = consistency_failure_message(payload)
                revision.status = "failed"
                revision.review_state = "blocked"
                revision.source_path = self._relative(source_path)
                revision.source_hash = source_hash
                revision.source_contract_version = "cadquery-v1"
                revision.ai_output_path = ai_output_relative_path
                self._record_revision_messages(revision=revision, user_instruction=user_instruction)
                self.db.commit()
                self.db.refresh(revision)
                return self._revision_read(revision, error_message=error_message)
        used_filenames: set[str] = set()
        output_records: list[RevisionOutput] = []
        requested_outputs: list[dict[str, Any]] = []
        for output in outputs:
            filename = self._safe_output_filename(output["output_id"], output["filename"], used_filenames)
            used_filenames.add(filename.lower())
            requested_output = {
                "output_id": output["output_id"],
                "required": output["required"],
            }
            if output["expected_solid_count"] is not None:
                requested_output["expected_solid_count"] = output["expected_solid_count"]
            if output["allow_disconnected_solids"] is not None:
                requested_output["allow_disconnected_solids"] = output[
                    "allow_disconnected_solids"
                ]
            requested_outputs.append(requested_output)
            record = RevisionOutput(
                revision_id=revision.id,
                design_plan_id=design_plan_id,
                design_specification_id=design_specification_id,
                output_id=output["output_id"],
                component_id=output["component_id"],
                component_ids_json=json.dumps(output["component_ids"]),
                execution_state="queued",
                output_type=output["output_type"],
                label=output["label"],
                filename=filename,
                quantity=output["quantity"],
                required=output["required"],
                entrypoint=output["entrypoint"],
                source_hash=source_hash,
                parameter_hash=parameter_hash,
                expected_solid_count=output["expected_solid_count"],
                allow_disconnected_solids=output["allow_disconnected_solids"],
                preferred_orientation_json=json.dumps(output["preferred_orientation"])
                if output["preferred_orientation"] is not None
                else None,
            )
            self.db.add(record)
            output_records.append(record)
        self.db.flush()

        started = time.perf_counter()
        for output_record in output_records:
            output_record.execution_state = "compiling"
        self.db.flush()
        self._record_workflow_event(
            workflow_run,
            stage="worker_submission",
            event_type="worker.submitted",
            severity="summary",
            message="CAD worker job submitted.",
            deduplication_key=f"worker-submitted-{revision.id}",
            revision_id=revision.id,
            worker_job_id=revision.id,
            metadata={
                "requested_output_ids": [item["output_id"] for item in requested_outputs],
                "source_hash": source_hash,
                "parameter_hash": parameter_hash,
            },
        )
        for parameter_id, parameter_value in sorted(compile_parameter_values.items()):
            self._record_workflow_event(
                workflow_run,
                stage="worker_submission",
                event_type="execution.parameter_submitted",
                severity="standard",
                message=f"Parameter {parameter_id} submitted to CAD worker.",
                deduplication_key=f"worker-parameter-{revision.id}-{parameter_id}",
                entity_type="parameter",
                entity_id=str(parameter_id),
                detected=parameter_value,
                revision_id=revision.id,
                design_specification_id=design_specification_id,
                design_plan_id=design_plan_id,
                configuration_change_id=configuration_change_id,
                worker_job_id=revision.id,
                metadata={"value_source": "submitted_parameter"},
            )
        result = await self._cadquery_runner().compile(
            source,
            job_id=revision.id,
            parameter_values=compile_parameter_values,
            requested_outputs=requested_outputs,
        )
        compile_ms = round((time.perf_counter() - started) * 1000, 3)
        worker_event = self._record_workflow_event(
            workflow_run,
            stage="cad_execution",
            event_type="worker.completed" if result.success else "worker.failed",
            severity="summary" if result.success else "error",
            blocking=not result.success,
            rule_id="cad_execution.failed" if not result.success else None,
            message="CAD worker job completed." if result.success else result.error_message or "CAD worker job failed.",
            deduplication_key=f"worker-completed-{revision.id}",
            revision_id=revision.id,
            worker_job_id=result.job_id,
            metadata={"compile_ms": compile_ms},
        )
        compile_log_path = log_dir / "cadquery.log"
        compile_log_path.write_text(self._compile_log(result), encoding="utf-8")
        execution_manifest_source = getattr(result, "execution_manifest_path", None)
        execution_manifest_relative_path: str | None = None
        if isinstance(execution_manifest_source, Path) and execution_manifest_source.exists():
            execution_manifest_path = revision_dir / "execution-manifest.json"
            shutil.copyfile(execution_manifest_source, execution_manifest_path)
            execution_manifest_relative_path = self._relative(execution_manifest_path)
        result_outputs = {output.output_id: output for output in getattr(result, "outputs", [])}
        for output_record in output_records:
            output_result = result_outputs.get(output_record.output_id)
            output_record.compile_ms = compile_ms
            output_record.execution_command_json = json.dumps(result.command_args or [])
            output_record.compile_log_path = self._relative(compile_log_path)
            output_record.source_hash = source_hash
            output_record.parameter_hash = parameter_hash
            if output_result is None or not output_result.success or output_result.stl_path is None:
                output_record.execution_state = "failed"
                output_record.compile_error = (
                    output_result.compile_error
                    if output_result is not None
                    else result.error_message or "CadQuery output was not produced"
                )
                if output_result is not None and output_result.topology_metadata is not None:
                    output_record.topology_metadata_json = json.dumps(
                        output_result.topology_metadata,
                        sort_keys=True,
                    )
                    self._apply_topology_metadata_fields(
                        output_record,
                        output_result.topology_metadata,
                    )
                output_record.validation_summary_json = json.dumps(ValidationSummaryRead().model_dump())
                continue
            self._persist_cadquery_output_artifacts(
                revision=revision,
                output=output_record,
                output_result=output_result,
                source=source,
                stl_dir=stl_dir,
                step_dir=step_dir,
                brep_dir=brep_dir,
                metadata_dir=metadata_dir,
                design_specification_payload=design_specification_payload,
                design_specification_id=design_specification_id,
            )

        self._persist_assembly_output_findings(revision)
        self._refresh_revision_output_counts(revision)
        first_blocking_validation_event = None
        for output_record in output_records:
            topology = self._output_topology_metadata(output_record)
            if not topology or topology.get("valid", True) is not False:
                continue
            first_blocking_validation_event = first_blocking_validation_event or self._record_workflow_event(
                workflow_run,
                stage="topology_validation",
                event_type="topology.failed",
                severity="error",
                blocking=True,
                rule_id="topology.solid_count_mismatch",
                message="A required printable part contains separate solid bodies that were expected to be connected.",
                deduplication_key=f"topology-failed-{output_record.id}",
                revision_id=revision.id,
                revision_output_id=output_record.id,
                expected=output_record.expected_solid_count,
                detected=output_record.detected_solid_count,
                worker_job_id=revision.id,
                metadata={"output_id": output_record.output_id, "topology": topology},
            )
        revision.status = "succeeded" if revision.successful_output_count > 0 else "failed"
        revision.source_path = self._relative(source_path)
        revision.source_hash = source_hash
        revision.source_contract_version = "cadquery-v1"
        revision.execution_manifest_path = execution_manifest_relative_path
        revision.ai_output_path = ai_output_relative_path
        revision.compile_log_path = self._relative(compile_log_path)
        revision.stl_path = self._first_successful_output_stl(revision)
        output_manifest_path = self._write_output_manifest(revision)
        revision.output_manifest_path = self._relative(output_manifest_path)
        self._record_workflow_artifact(
            workflow_run,
            stage="source_generation" if source_type in {"ai_initial", "ai_revision"} else "configuration_execution",
            artifact_type="cadquery_source",
            role=f"{source_type}_source",
            relative_path=revision.source_path,
        )
        self._record_workflow_artifact(
            workflow_run,
            stage="cad_execution",
            artifact_type="worker_diagnostics",
            role="compile_log",
            relative_path=revision.compile_log_path,
        )
        self._record_workflow_artifact(
            workflow_run,
            stage="cad_execution",
            artifact_type="worker_result_manifest",
            role="execution_manifest",
            relative_path=revision.execution_manifest_path,
        )
        self._record_workflow_artifact(
            workflow_run,
            stage="output_preservation",
            artifact_type="output_manifest",
            role="output_manifest",
            relative_path=revision.output_manifest_path,
        )
        for output_record in output_records:
            self._record_workflow_artifact(
                workflow_run,
                stage="topology_validation",
                artifact_type="topology_result",
                role=f"topology_{output_record.output_id}",
                relative_path=revision.output_manifest_path,
                metadata={"output_id": output_record.output_id},
            )
        execution_manifest_payload = (
            self._read_json_file(execution_manifest_relative_path)
            if execution_manifest_relative_path is not None
            else None
        )
        output_manifest_payload = self._read_json_file(revision.output_manifest_path)
        if design_plan_id is not None:
            self._persist_design_artifact_consistency(
                revision=revision,
                source=source,
                design_specification_payload=design_specification_payload,
                design_plan_payload=design_plan_payload,
                execution_parameters=compile_parameter_values,
                execution_manifest=execution_manifest_payload,
                output_manifest=output_manifest_payload,
                parameter_overrides=parameter_overrides,
                generation_attempt_id=generation_attempt_id,
            )
        functional_findings = list(
            self.db.scalars(
                select(ValidationFinding).where(
                    ValidationFinding.revision_id == revision.id,
                    ValidationFinding.rule_id.like("functional.%"),
                )
            )
        )
        functional_validation_event = None
        if functional_findings:
            first_functional = functional_findings[0]
            functional_validation_event = self._record_workflow_event(
                workflow_run,
                stage="topology_validation",
                event_type="functional.verification.completed",
                severity="error" if any(item.is_blocking for item in functional_findings) else "summary",
                blocking=any(item.is_blocking for item in functional_findings),
                rule_id=first_functional.rule_id,
                message="Functional design checks completed.",
                deduplication_key=f"functional-verification-{revision.id}",
                revision_id=revision.id,
                metadata={
                    "finding_count": len(functional_findings),
                    "blocking_count": sum(1 for item in functional_findings if item.is_blocking),
                },
            )
        revision.functional_status = self._derive_functional_status(revision.id)
        revision.review_state = (
            self._derive_review_state(revision.id)
            if revision.status == "succeeded" or source_type != "manual_edit"
            else None
        )
        self._record_workflow_event(
            workflow_run,
            stage="candidate_classification",
            event_type="candidate.classified",
            severity="summary" if revision.review_state in ACCEPTABLE_CANDIDATE_STATES else "error",
            blocking=revision.review_state == "blocked" or revision.status == "failed",
            rule_id="candidate.blocked"
            if revision.review_state == "blocked" or revision.status == "failed"
            else None,
            message=f"Candidate classified as {revision.review_state or revision.status}.",
            deduplication_key=f"candidate-classified-{revision.id}",
            caused_by_event_id=(
                first_blocking_validation_event.id
                if first_blocking_validation_event is not None
                else (
                    functional_validation_event.id
                    if functional_validation_event is not None and functional_validation_event.blocking
                    else worker_event.id
                    if revision.status == "failed" and worker_event is not None
                    else None
                )
            ),
            is_downstream_symptom=(
                first_blocking_validation_event is not None
                or (functional_validation_event is not None and functional_validation_event.blocking)
                or revision.status == "failed"
            ),
            revision_id=revision.id,
            metadata={
                "review_state": revision.review_state,
                "status": revision.status,
                "successful_output_count": revision.successful_output_count,
                "failed_output_count": revision.failed_output_count,
                "blocked_output_count": revision.blocked_output_count,
            },
        )
        revision.is_accepted = False
        if (
            auto_accept
            and revision.status == "succeeded"
            and self._should_auto_accept_revision(
                project=project,
                source_type=source_type,
                review_state=revision.review_state,
            )
        ):
            revision.review_state = "accepted"
            revision.is_accepted = True
            revision.accepted_at = project_utcnow()
            project.active_revision_id = revision.id
        self._record_revision_messages(revision=revision, user_instruction=user_instruction)
        self.db.commit()
        self.db.refresh(revision)
        revision_error = None
        if revision.status == "failed":
            revision_error = result.error_message or next(
                (output.compile_error for output in output_records if output.compile_error),
                None,
            )
        return self._revision_read(revision, error_message=revision_error)

    def read_revision_source(self, revision_id: str) -> str | None:
        path = self.resolve_revision_source(revision_id)
        if path is None:
            return None
        return path.read_text(encoding="utf-8")

    def resolve_revision_source(self, revision_id: str) -> Path | None:
        revision = self.db.get(Revision, revision_id)
        if revision is None or not revision.source_path:
            return None
        path = self.data_dir / revision.source_path
        return path if path.exists() else None

    def read_revision_compile_log(self, revision_id: str) -> str | None:
        revision = self.db.get(Revision, revision_id)
        if revision is None or not revision.compile_log_path:
            return None
        path = self.data_dir / revision.compile_log_path
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def read_revision_ai_output(self, revision_id: str) -> str | None:
        revision = self.db.get(Revision, revision_id)
        if revision is None or not revision.ai_output_path:
            return None
        path = self.data_dir / revision.ai_output_path
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def read_revision_diff(self, revision_id: str) -> str | None:
        revision = self.db.get(Revision, revision_id)
        if revision is None or revision.parent_revision_id is None:
            return None
        parent_revision = self.db.get(Revision, revision.parent_revision_id)
        if parent_revision is None:
            return None
        parent_path = self.resolve_revision_source(parent_revision.id)
        revision_path = self.resolve_revision_source(revision.id)
        if parent_path is None or revision_path is None:
            return None
        diff_lines = difflib.unified_diff(
            parent_path.read_text(encoding="utf-8").splitlines(),
            revision_path.read_text(encoding="utf-8").splitlines(),
            fromfile=f"R{parent_revision.revision_number}",
            tofile=f"R{revision.revision_number}",
            lineterm="",
        )
        return "\n".join(diff_lines)

    def resolve_revision_stl(self, revision_id: str) -> Path | None:
        revision = self.db.get(Revision, revision_id)
        if revision is None or revision.stl_path is None:
            return None
        path = self.data_dir / revision.stl_path
        return path if path.exists() else None

    def resolve_revision_output_stl(self, output_artifact_id: str) -> Path | None:
        output = self.db.get(RevisionOutput, output_artifact_id)
        if output is None or output.stl_path is None:
            return None
        path = self.data_dir / output.stl_path
        return path if path.exists() else None

    def resolve_revision_output_step(self, output_artifact_id: str) -> Path | None:
        output = self.db.get(RevisionOutput, output_artifact_id)
        if output is None or output.step_path is None:
            return None
        path = self.data_dir / output.step_path
        return path if path.exists() else None

    def read_revision_output_compile_log(self, output_artifact_id: str) -> str | None:
        output = self.db.get(RevisionOutput, output_artifact_id)
        if output is None or output.compile_log_path is None:
            return None
        path = self.data_dir / output.compile_log_path
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def read_output_manifest(self, revision_id: str) -> dict[str, Any] | None:
        revision = self.db.get(Revision, revision_id)
        if revision is None:
            return None
        if revision.output_manifest_path:
            path = self.data_dir / revision.output_manifest_path
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        return self._output_manifest_payload(revision)

    def build_revision_export(self, revision_id: str) -> Path | None:
        revision = self.db.get(Revision, revision_id)
        if revision is None:
            return None
        if revision.status != "succeeded" or revision.review_state not in {"accepted", "ready", "ready_with_warnings"}:
            raise ValueError("exports require a successful non-blocked revision")
        workflow_run = self._start_child_workflow_run(
            project_id=revision.project_id,
            workflow_type="export",
        )
        self._record_workflow_event(
            workflow_run,
            stage="export",
            event_type="export.requested",
            severity="summary",
            message="Revision export requested.",
            deduplication_key=f"export-requested-{revision.id}",
            revision_id=revision.id,
        )
        revision_dir = self._revision_dir(revision.project_id, revision.id)
        revision_dir.mkdir(parents=True, exist_ok=True)
        export_path = revision_dir / "project-export.zip"
        payload = self._output_manifest_payload(revision)
        project = self.db.get(Project, revision.project_id)
        root = self._safe_stem(project.slug if project else f"revision-{revision.revision_number}")
        plan_payload = self._revision_design_plan_payload(revision)
        spec_payload = self._revision_design_specification_payload(revision)
        outputs = list(
            self.db.scalars(
                select(RevisionOutput)
                .where(RevisionOutput.revision_id == revision.id)
                .order_by(RevisionOutput.created_at.asc(), RevisionOutput.output_id.asc())
            )
        )
        with zipfile.ZipFile(export_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(f"{root}/README.md", self._export_readme(revision, outputs, plan_payload))
            archive.writestr(
                f"{root}/design-specification.json",
                json.dumps(spec_payload or {}, indent=2, sort_keys=True),
            )
            archive.writestr(
                f"{root}/design-plan.json",
                json.dumps(plan_payload or {}, indent=2, sort_keys=True),
            )
            source_path = self.resolve_revision_source(revision.id)
            if source_path is not None:
                archive.write(source_path, f"{root}/{source_path.name}")
            if revision.execution_manifest_path:
                execution_manifest_path = self.data_dir / revision.execution_manifest_path
                if execution_manifest_path.exists():
                    archive.write(execution_manifest_path, f"{root}/execution-manifest.json")
            archive.writestr(
                f"{root}/output-manifest.json",
                json.dumps(payload, indent=2, sort_keys=True),
            )
            config_payload = self._revision_configuration_payload(revision)
            override_payload = self._revision_override_manifest_payload(revision)
            if config_payload is not None:
                archive.writestr(
                    f"{root}/configuration.json",
                    json.dumps(config_payload, indent=2, sort_keys=True, default=str),
                )
            if override_payload is not None:
                archive.writestr(
                    f"{root}/parameter-overrides.json",
                    json.dumps(override_payload, indent=2, sort_keys=True),
                )
            archive.writestr(f"{root}/assembly-notes.md", self._assembly_notes(plan_payload, outputs))
            for output in outputs:
                if output.stl_path is None:
                    continue
                stl_path = self.data_dir / output.stl_path
                if stl_path.exists():
                    archive.write(stl_path, f"{root}/stl/{output.filename}")
                if output.step_path:
                    step_path = self.data_dir / output.step_path
                    if step_path.exists():
                        archive.write(step_path, f"{root}/step/{Path(output.step_path).name}")
                if output.brep_path:
                    brep_path = self.data_dir / output.brep_path
                    if brep_path.exists():
                        archive.write(brep_path, f"{root}/brep/{Path(output.brep_path).name}")
                metadata_json = output.mesh_metadata_json or output.metadata_json
                if metadata_json:
                    archive.writestr(
                        f"{root}/metadata/{self._safe_stem(output.output_id)}.metadata.json",
                        json.dumps(json.loads(metadata_json), indent=2, sort_keys=True),
                    )
        self._record_workflow_artifact(
            workflow_run,
            stage="export",
            artifact_type="export_zip",
            role="revision_export",
            relative_path=self._relative(export_path),
        )
        self._record_workflow_event(
            workflow_run,
            stage="export",
            event_type="export.completed",
            severity="summary",
            message="Revision export bundle created.",
            deduplication_key=f"export-completed-{revision.id}",
            revision_id=revision.id,
            metadata={"path": self._relative(export_path)},
        )
        self._workflow_recorder().complete_run(workflow_run, status="completed")
        return export_path

    async def retry_revision_output(self, output_artifact_id: str) -> RevisionOutputRead | None:
        output = self.db.get(RevisionOutput, output_artifact_id)
        if output is None:
            return None
        if output.execution_state != "failed":
            raise ValueError("Only failed outputs can be retried")
        revision = self.db.get(Revision, output.revision_id)
        if revision is None:
            return None
        source_path = self.resolve_revision_source(revision.id)
        if source_path is None:
            raise ValueError("Revision source is missing")
        source = source_path.read_text(encoding="utf-8")
        expected_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        if output.source_hash and output.source_hash != expected_hash:
            raise ValueError("Source hash changed; output retry is not safe")
        if revision.cad_backend != "cadquery":
            raise ValueError("output retry requires a CadQuery revision")

        active_retry = self.db.scalar(
            select(WorkflowRun)
            .join(WorkflowEvent, WorkflowEvent.workflow_run_id == WorkflowRun.id)
            .where(
                WorkflowRun.workflow_type == "output_retry",
                WorkflowRun.status == "running",
                WorkflowEvent.revision_output_id == output.id,
            )
        )
        if active_retry is not None:
            raise ValueError("Output retry is already running")

        revision_dir = self._revision_dir(revision.project_id, revision.id)
        workflow_run = self._start_child_workflow_run(
            project_id=revision.project_id,
            workflow_type="output_retry",
            parent=self._workflow_run_for_revision(revision.id),
        )
        pre_retry_snapshot_path = revision_dir / "logs" / f"{self._safe_stem(output.output_id)}-pre-retry.json"
        pre_retry_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json(
            pre_retry_snapshot_path,
            {
                "schema_version": "workflow-output-retry-snapshot-v1",
                "revision_output_id": output.id,
                "revision_id": revision.id,
                "output_id": output.output_id,
                "execution_state": output.execution_state,
                "compile_error": output.compile_error,
                "compile_log_path": output.compile_log_path,
                "source_hash": output.source_hash,
                "parameter_hash": output.parameter_hash,
                "topology_metadata": json.loads(output.topology_metadata_json)
                if output.topology_metadata_json
                else None,
                "validation_summary": json.loads(output.validation_summary_json)
                if output.validation_summary_json
                else None,
            },
        )
        self._record_workflow_artifact(
            workflow_run,
            stage="output_preservation",
            artifact_type="worker_result_snapshot",
            role="pre_retry_worker_result",
            relative_path=self._relative(pre_retry_snapshot_path),
        )
        self._record_workflow_event(
            workflow_run,
            stage="output_preservation",
            event_type="output_retry.started",
            severity="summary",
            message="Output retry started.",
            deduplication_key=f"output-retry-started-{output.id}",
            revision_id=revision.id,
            revision_output_id=output.id,
            metadata={"output_id": output.output_id},
        )
        design_plan_payload = self._revision_design_plan_payload(revision)
        parameter_overrides = None
        if revision.configuration_change_id is not None:
            change = self.db.get(ConfigurationChange, revision.configuration_change_id)
            if change is not None:
                parameter_overrides = dict(
                    self._configuration_override_manifest(change).get("parameter_values") or {}
                )
        parameter_values = (
            self._cadquery_execution_parameter_values(
                source=source,
                design_plan_payload=design_plan_payload,
                overrides=parameter_overrides,
            )
            if design_plan_payload is not None
            else self._cadquery_source_parameter_values(source)
        )
        parameter_hash = self._configuration_parameter_hash(parameter_values)
        if output.parameter_hash is None:
            raise ValueError("Parameter hash is missing; output retry is not safe")
        if output.parameter_hash != parameter_hash:
            raise ValueError("Parameter hash changed; output retry is not safe")
        stl_dir = revision_dir / "stl"
        step_dir = revision_dir / "step"
        brep_dir = revision_dir / "brep"
        log_dir = revision_dir / "logs"
        metadata_dir = revision_dir / "metadata"
        for directory in (stl_dir, step_dir, brep_dir, log_dir, metadata_dir):
            directory.mkdir(parents=True, exist_ok=True)
        requested_output = {"output_id": output.output_id, "required": output.required}
        if output.expected_solid_count is not None:
            requested_output["expected_solid_count"] = output.expected_solid_count
        if output.allow_disconnected_solids is not None:
            requested_output["allow_disconnected_solids"] = output.allow_disconnected_solids
        requested_outputs = [requested_output]
        retry_job_id = f"{revision.id}-{output.id}-retry-{time.time_ns()}"
        self._record_workflow_event(
            workflow_run,
            stage="worker_submission",
            event_type="worker.submitted",
            severity="summary",
            message="CAD worker retry submitted.",
            deduplication_key=f"output-retry-worker-submitted-{output.id}",
            revision_id=revision.id,
            revision_output_id=output.id,
            worker_job_id=retry_job_id,
            metadata={
                "output_id": output.output_id,
                "source_hash": expected_hash,
                "parameter_hash": parameter_hash,
                "requested_output_ids": [output.output_id],
            },
        )
        output.execution_state = "compiling"
        self.db.commit()
        started = time.perf_counter()
        result = await self._cadquery_runner().compile(
            source,
            job_id=retry_job_id,
            parameter_values=parameter_values,
            requested_outputs=requested_outputs,
        )
        compile_ms = round((time.perf_counter() - started) * 1000, 3)
        self._record_workflow_event(
            workflow_run,
            stage="cad_execution",
            event_type="worker.completed" if result.success else "worker.failed",
            severity="summary" if result.success else "error",
            blocking=not result.success,
            rule_id="cad_execution.failed" if not result.success else None,
            message="Output retry worker job completed."
            if result.success
            else result.error_message or "Output retry worker job failed.",
            deduplication_key=f"output-retry-worker-completed-{output.id}",
            revision_id=revision.id,
            revision_output_id=output.id,
            worker_job_id=result.job_id,
            metadata={"compile_ms": compile_ms, "source_hash": expected_hash, "parameter_hash": parameter_hash},
        )
        compile_log_path = log_dir / f"{self._safe_stem(output.output_id)}-retry.log"
        compile_log_path.write_text(self._compile_log(result), encoding="utf-8")
        output_result = next(
            (candidate for candidate in getattr(result, "outputs", []) if candidate.output_id == output.output_id),
            None,
        )
        output.compile_ms = compile_ms
        output.execution_command_json = json.dumps(result.command_args or [])
        output.compile_log_path = self._relative(compile_log_path)
        output.source_hash = expected_hash
        output.parameter_hash = parameter_hash
        if output_result is None or not output_result.success or output_result.stl_path is None:
            output.execution_state = "failed"
            output.compile_error = (
                output_result.compile_error
                if output_result is not None
                else result.error_message or "CadQuery output was not produced"
            )
            if output_result is not None and output_result.topology_metadata is not None:
                output.topology_metadata_json = json.dumps(
                    output_result.topology_metadata,
                    sort_keys=True,
                )
                self._apply_topology_metadata_fields(output, output_result.topology_metadata)
            output.validation_summary_json = json.dumps(ValidationSummaryRead().model_dump())
        else:
            output.compile_error = None
            self._persist_cadquery_output_artifacts(
                revision=revision,
                output=output,
                output_result=output_result,
                source=source,
                stl_dir=stl_dir,
                step_dir=step_dir,
                brep_dir=brep_dir,
                metadata_dir=metadata_dir,
                design_specification_payload=self._revision_design_specification_payload(revision),
                design_specification_id=revision.design_specification_id,
            )
        self._clear_assembly_output_findings(revision.id)
        self._persist_assembly_output_findings(revision)
        self._refresh_revision_output_counts(revision)
        revision.status = (
            "succeeded"
            if revision.successful_output_count >= revision.required_output_count
            else "failed"
        )
        revision.stl_path = self._first_successful_output_stl(revision)
        revision.output_manifest_path = self._relative(self._write_output_manifest(revision))
        revision.execution_manifest_path = self._relative(
            self._write_revision_execution_manifest(
                revision=revision,
                source_hash=expected_hash,
                parameter_hash=parameter_hash,
                parameter_values=parameter_values,
            )
        )
        revision.compile_log_path = self._relative(
            self._write_assembly_compile_log(revision, revision_dir / "logs")
        )
        self._certify_revision_artifacts(revision)
        revision.review_state = self._derive_review_state(revision.id)
        self._record_workflow_artifact(
            workflow_run,
            stage="cad_execution",
            artifact_type="worker_diagnostics",
            role="retry_compile_log",
            relative_path=output.compile_log_path,
        )
        self._record_workflow_artifact(
            workflow_run,
            stage="output_preservation",
            artifact_type="output_manifest",
            role="retry_output_manifest",
            relative_path=revision.output_manifest_path,
        )
        self._record_workflow_artifact(
            workflow_run,
            stage="cad_execution",
            artifact_type="worker_result_manifest",
            role="retry_execution_manifest",
            relative_path=revision.execution_manifest_path,
        )
        self._record_workflow_event(
            workflow_run,
            stage="output_preservation",
            event_type="output_retry.completed",
            severity="summary" if output.execution_state != "failed" else "error",
            blocking=output.execution_state == "failed",
            rule_id="output_retry.failed" if output.execution_state == "failed" else None,
            message="Output retry completed.",
            deduplication_key=f"output-retry-completed-{output.id}",
            revision_id=revision.id,
            revision_output_id=output.id,
            metadata={"execution_state": output.execution_state, "revision_status": revision.status},
        )
        retry_worker_event = self.db.scalar(
            select(WorkflowEvent)
            .where(WorkflowEvent.workflow_run_id == workflow_run.id)
            .where(WorkflowEvent.event_type.in_(("worker.completed", "worker.failed")))
            .order_by(WorkflowEvent.sequence_number.desc())
        )
        self._record_workflow_event(
            workflow_run,
            stage="candidate_classification",
            event_type="candidate.classified",
            severity="summary" if revision.review_state in ACCEPTABLE_CANDIDATE_STATES else "error",
            blocking=revision.review_state == "blocked" or revision.status == "failed",
            rule_id="candidate.blocked"
            if revision.review_state == "blocked" or revision.status == "failed"
            else None,
            message=f"Candidate classified as {revision.review_state or revision.status} after output retry.",
            deduplication_key=f"output-retry-candidate-classified-{output.id}",
            caused_by_event_id=(
                retry_worker_event.id
                if retry_worker_event is not None and revision.status == "failed"
                else None
            ),
            is_downstream_symptom=revision.status == "failed",
            revision_id=revision.id,
            revision_output_id=output.id,
            worker_job_id=retry_job_id,
            metadata={
                "review_state": revision.review_state,
                "status": revision.status,
                "source_hash": expected_hash,
                "parameter_hash": parameter_hash,
            },
        )
        self.db.commit()
        self._workflow_recorder().complete_run(
            workflow_run,
            status="completed" if output.execution_state != "failed" else "failed",
        )
        self.db.refresh(output)
        return self._revision_output_read(output)

    def restore_revision(self, revision_id: str) -> Project | None:
        revision = self.db.get(Revision, revision_id)
        if (
            revision is None
            or revision.status != "succeeded"
            or revision.review_state != "accepted"
            or self._has_blocking_findings(revision.id)
        ):
            return None
        project = self.db.get(Project, revision.project_id)
        if project is None:
            return None
        project.active_revision_id = revision.id
        self._record_message(
            project_id=project.id,
            revision_id=revision.id,
            role="system_event",
            content=f"Restored R{revision.revision_number}",
        )
        self.db.commit()
        self.db.refresh(project)
        return project

    def _configuration_context(
        self,
        project_id: str,
        *,
        base_revision_id: str | None = None,
    ) -> tuple[Project, Revision, DesignPlan, dict[str, Any], str, str] | None:
        project = self.db.get(Project, project_id)
        if project is None:
            return None
        revision_id = base_revision_id or project.active_revision_id
        if revision_id is None:
            return None
        base_revision = self.db.get(Revision, revision_id)
        if (
            base_revision is None
            or base_revision.project_id != project.id
            or base_revision.status != "succeeded"
            or base_revision.design_plan_id is None
        ):
            return None
        design_plan = self.db.get(DesignPlan, base_revision.design_plan_id)
        if design_plan is None or design_plan.review_state != DesignPlanReviewState.APPROVED.value:
            return None
        source = self.read_revision_source(base_revision.id)
        if source is None:
            return None
        source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        return (
            project,
            base_revision,
            design_plan,
            self._read_design_plan_payload(design_plan),
            source,
            source_hash,
        )

    def _configuration_parameter_read(
        self,
        parameter: dict[str, Any],
        design_plan_payload: dict[str, Any],
        metadata: Any,
    ) -> ConfigurationParameterRead:
        parameter_id = str(parameter.get("id"))
        parameter_type = self._configuration_parameter_type(parameter)
        minimum, maximum = self._configuration_parameter_range(parameter)
        affected = self._configuration_impacts([parameter_id], design_plan_payload)
        return ConfigurationParameterRead(
            id=parameter_id,
            label=str(parameter.get("label") or parameter_id),
            value=parameter.get("value"),
            unit=parameter.get("unit"),
            type=parameter_type,
            editable=bool(parameter.get("editable", True)),
            protected=bool(parameter.get("protected", False)),
            component_id=parameter.get("component_id"),
            source_requirement_id=parameter.get("source_requirement_id"),
            description=parameter.get("description") or parameter.get("explanation"),
            minimum=minimum,
            maximum=maximum,
            allowed_values=list(parameter.get("allowed_values") or parameter.get("enum_values") or []),
            source_mapped=self._parameter_has_source_mapping(parameter_id, metadata),
            affected_components=affected["affected_components"],
            affected_outputs=affected["affected_outputs"],
        )

    def _configuration_source_metadata(
        self,
        *,
        source: str,
        design_plan_payload: dict[str, Any],
        cad_backend: str,
        design_specification_payload: dict[str, Any] | None = None,
    ) -> Any:
        if cad_backend != "cadquery":
            raise ValueError("CadQuery source is required for configuration metadata")
        return validate_cadquery_source(source, contract_version="cadquery-v1")

    def _configuration_preset_read(self, preset: ConfigurationPreset) -> ConfigurationPresetRead:
        return ConfigurationPresetRead(
            id=preset.id,
            project_id=preset.project_id,
            design_plan_id=preset.design_plan_id,
            preset_id=preset.preset_id,
            label=preset.label,
            parameter_values=json.loads(preset.parameter_values_json),
            source="project",
            created_at=preset.created_at,
        )

    def _resolve_configuration(
        self,
        *,
        design_plan_payload: dict[str, Any],
        source: str,
        cad_backend: str,
        selected_preset_id: str | None,
        requested_values: dict[str, Any],
        user_overrides: dict[str, Any],
        project_id: str | None = None,
        design_plan_id: str | None = None,
    ) -> dict[str, Any]:
        parameter_map = {
            str(parameter.get("id")): parameter
            for parameter in design_plan_payload.get("parameters", [])
            if parameter.get("id")
        }
        derived_ids = {
            str(parameter.get("id"))
            for parameter in design_plan_payload.get("derived_parameters", [])
            if parameter.get("id")
        }
        preset_values = self._configuration_preset_values(
            design_plan_payload=design_plan_payload,
            selected_preset_id=selected_preset_id,
            project_id=project_id,
            design_plan_id=design_plan_id,
        )
        source_metadata = self._configuration_source_metadata(
            source=source,
            design_plan_payload=design_plan_payload,
            cad_backend=cad_backend,
        )
        combined: dict[str, Any] = {}
        combined.update(preset_values)
        combined.update(requested_values)
        combined.update(user_overrides)
        validation_errors: list[dict[str, Any]] = []
        structural_errors: list[dict[str, Any]] = []
        for parameter_id, value in combined.items():
            if parameter_id in derived_ids:
                structural_errors.append(
                    self._configuration_error(
                        "derived_parameter_not_directly_editable",
                        parameter_id,
                        "Derived parameters are recalculated by the CadQuery source and cannot be overridden directly.",
                    )
                )
                continue
            parameter = parameter_map.get(parameter_id)
            if parameter is None:
                structural_errors.append(
                    self._configuration_error(
                        "unknown_parameter",
                        parameter_id,
                        "The requested parameter is not part of the approved Design Plan.",
                    )
                )
                continue
            if not bool(parameter.get("editable", True)):
                structural_errors.append(
                    self._configuration_error(
                        "parameter_not_editable",
                        parameter_id,
                        "This Design Plan parameter is not user editable.",
                    )
                )
                continue
            if bool(parameter.get("protected", False)) and value != parameter.get("value"):
                structural_errors.append(
                    self._configuration_error(
                        "protected_parameter_change",
                        parameter_id,
                        "Protected Design Plan parameter values require a structured design revision.",
                        {
                            "expected_value": parameter.get("value"),
                            "detected_value": value,
                        },
                    )
                )
                continue
            if not self._parameter_has_source_mapping(parameter_id, source_metadata):
                structural_errors.append(
                    self._configuration_error(
                        "parameter_not_source_mapped",
                        parameter_id,
                        "The accepted CAD source does not expose this parameter for configuration.",
                    )
                )
                continue
            validation_errors.extend(self._configuration_value_errors(parameter, value))
        affected_parameters = self._affected_parameters(list(combined.keys()), design_plan_payload)
        impacts = self._configuration_impacts(affected_parameters, design_plan_payload)
        resolved = {
            parameter_id: parameter.get("value")
            for parameter_id, parameter in parameter_map.items()
        }
        resolved.update(combined)
        if structural_errors:
            state = ConfigurationValidationState.REQUIRES_DESIGN_REVISION.value
            errors = structural_errors + validation_errors
        elif validation_errors:
            state = ConfigurationValidationState.INVALID_CONFIGURATION.value
            errors = validation_errors
        else:
            state = ConfigurationValidationState.CONFIGURATION_READY.value
            errors = []
        return {
            "validation_state": state,
            "requested_changes": dict(requested_values),
            "preset_values": preset_values,
            "user_overrides": dict(user_overrides),
            "resolved_parameters": resolved,
            "affected_parameters": affected_parameters,
            "affected_components": impacts["affected_components"],
            "affected_outputs": impacts["affected_outputs"],
            "validation_errors": errors,
        }

    def _configuration_value_errors(
        self,
        parameter: dict[str, Any],
        value: Any,
    ) -> list[dict[str, Any]]:
        parameter_id = str(parameter.get("id"))
        parameter_type = self._configuration_parameter_type(parameter)
        errors: list[dict[str, Any]] = []
        if parameter_type == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                errors.append(self._configuration_error("invalid_integer", parameter_id, "Expected an integer value."))
                return errors
        elif parameter_type == "number":
            if not isinstance(value, int | float) or isinstance(value, bool):
                errors.append(self._configuration_error("invalid_number", parameter_id, "Expected a numeric value."))
                return errors
        elif parameter_type == "boolean":
            if not isinstance(value, bool):
                errors.append(self._configuration_error("invalid_boolean", parameter_id, "Expected true or false."))
                return errors
        elif parameter_type == "enum":
            allowed = list(parameter.get("allowed_values") or parameter.get("enum_values") or [])
            if value not in allowed:
                errors.append(
                    self._configuration_error(
                        "invalid_enum_value",
                        parameter_id,
                        "Expected one of the approved enum values.",
                        {"allowed_values": allowed, "detected_value": value},
                    )
                )
                return errors
        else:
            errors.append(
                self._configuration_error(
                    "unsupported_parameter_type",
                    parameter_id,
                    "This parameter type requires a structured AI revision.",
                )
            )
            return errors
        minimum, maximum = self._configuration_parameter_range(parameter)
        if isinstance(value, int | float) and not isinstance(value, bool):
            if minimum is not None and value < minimum:
                errors.append(
                    self._configuration_error(
                        "below_minimum",
                        parameter_id,
                        "Value is below the approved configurable range.",
                        {"minimum": minimum, "detected_value": value},
                    )
                )
            if maximum is not None and value > maximum:
                errors.append(
                    self._configuration_error(
                        "above_maximum",
                        parameter_id,
                        "Value is above the approved configurable range.",
                        {"maximum": maximum, "detected_value": value},
                    )
                )
        return errors

    def _configuration_parameter_type(self, parameter: dict[str, Any]) -> str:
        explicit = str(parameter.get("type") or parameter.get("parameter_type") or "").strip().lower()
        if explicit in {"number", "integer", "boolean", "enum"}:
            return explicit
        value = parameter.get("value")
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, str) and (parameter.get("allowed_values") or parameter.get("enum_values")):
            return "enum"
        return "unsupported"

    def _configuration_parameter_range(self, parameter: dict[str, Any]) -> tuple[float | int | None, float | int | None]:
        minimum = parameter.get("minimum", parameter.get("min"))
        maximum = parameter.get("maximum", parameter.get("max"))
        return (
            minimum if isinstance(minimum, int | float) and not isinstance(minimum, bool) else None,
            maximum if isinstance(maximum, int | float) and not isinstance(maximum, bool) else None,
        )

    def _parameter_has_source_mapping(self, parameter_id: str, metadata: Any) -> bool:
        parameter_ids = set(getattr(metadata, "parameter_ids", []) or [])
        if parameter_id in parameter_ids:
            return True
        parameter_mappings = getattr(metadata, "parameter_mappings", {}) or {}
        assignments = getattr(metadata, "assignments", {}) or {}
        return parameter_id in parameter_mappings or parameter_id in assignments

    def _affected_parameters(
        self,
        changed_parameter_ids: list[str],
        design_plan_payload: dict[str, Any],
    ) -> list[str]:
        affected = set(changed_parameter_ids)
        edges = [
            (str(edge.get("from") or edge.get("from_") or ""), str(edge.get("to") or ""))
            for edge in design_plan_payload.get("dependency_edges", [])
        ]
        changed = True
        while changed:
            changed = False
            for from_id, to_id in edges:
                if from_id in affected and to_id and to_id not in affected:
                    affected.add(to_id)
                    changed = True
        return sorted(affected)

    def _configuration_impacts(
        self,
        affected_parameter_ids: list[str],
        design_plan_payload: dict[str, Any],
    ) -> dict[str, list[str]]:
        affected = set(affected_parameter_ids)
        components: set[str] = set()
        for parameter in design_plan_payload.get("parameters", []):
            if parameter.get("id") in affected and parameter.get("component_id"):
                components.add(str(parameter.get("component_id")))
        for component in design_plan_payload.get("components", []):
            component_id = str(component.get("id"))
            if affected.intersection(set(component.get("parameters") or [])):
                components.add(component_id)
        for feature in design_plan_payload.get("features", []):
            if affected.intersection(set(feature.get("parameters") or [])) and feature.get("component_id"):
                components.add(str(feature.get("component_id")))
        outputs: set[str] = set()
        for output in self._planned_printable_outputs(design_plan_payload):
            if components.intersection(set(output["component_ids"])):
                outputs.add(output["output_id"])
        return {
            "affected_components": sorted(components),
            "affected_outputs": sorted(outputs),
        }

    def _configuration_preset_values(
        self,
        *,
        design_plan_payload: dict[str, Any],
        selected_preset_id: str | None,
        project_id: str | None,
        design_plan_id: str | None,
    ) -> dict[str, Any]:
        if not selected_preset_id:
            return {}
        for preset in design_plan_payload.get("presets", []):
            if isinstance(preset, dict) and preset.get("id") == selected_preset_id:
                return dict(preset.get("parameter_values") or {})
        if project_id is not None and design_plan_id is not None:
            preset = self.db.scalar(
                select(ConfigurationPreset)
                .where(ConfigurationPreset.project_id == project_id)
                .where(ConfigurationPreset.design_plan_id == design_plan_id)
                .where(ConfigurationPreset.preset_id == selected_preset_id)
                .order_by(ConfigurationPreset.created_at.desc())
            )
            if preset is not None:
                return json.loads(preset.parameter_values_json)
        return {}

    def _configuration_error(
        self,
        code: str,
        parameter_id: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "code": code,
            "parameter_id": parameter_id,
            "message": message,
            "metadata": metadata or {},
        }

    def _configuration_parameter_hash(self, parameter_values: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(parameter_values, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def _persist_configuration_change(
        self,
        *,
        project_id: str,
        base_revision: Revision,
        design_plan: DesignPlan,
        reason: str,
        selected_preset_id: str | None,
        source_hash: str,
        resolution: dict[str, Any],
    ) -> ConfigurationChange:
        hash_payload = {
            "schema_version": "configuration-change-v1",
            "project_id": project_id,
            "base_revision_id": base_revision.id,
            "design_specification_id": base_revision.design_specification_id,
            "design_plan_id": design_plan.id,
            "reason": reason,
            "selected_preset_id": selected_preset_id,
            "base_source_hash": source_hash,
            **resolution,
        }
        content_hash = hashlib.sha256(
            json.dumps(hash_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        change = ConfigurationChange(
            project_id=project_id,
            base_revision_id=base_revision.id,
            design_specification_id=base_revision.design_specification_id,
            design_plan_id=design_plan.id,
            reason=reason,
            selected_preset_id=selected_preset_id,
            validation_state=resolution["validation_state"],
            base_source_hash=source_hash,
            content_hash=content_hash,
            requested_changes_json=json.dumps(resolution["requested_changes"], sort_keys=True),
            preset_values_json=json.dumps(resolution["preset_values"], sort_keys=True),
            user_overrides_json=json.dumps(resolution["user_overrides"], sort_keys=True),
            resolved_parameters_json=json.dumps(resolution["resolved_parameters"], sort_keys=True),
            affected_parameters_json=json.dumps(resolution["affected_parameters"], sort_keys=True),
            affected_components_json=json.dumps(resolution["affected_components"], sort_keys=True),
            affected_outputs_json=json.dumps(resolution["affected_outputs"], sort_keys=True),
            validation_errors_json=json.dumps(resolution["validation_errors"], sort_keys=True),
        )
        self.db.add(change)
        self.db.flush()
        config_dir = self.data_dir / "projects" / project_id / "configuration-changes" / change.id
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "configuration.json"
        overrides_path = config_dir / "parameter-overrides.json"
        self._write_configuration_json(config_path, self._configuration_change_payload(change))
        self._write_json(overrides_path, self._configuration_override_manifest(change))
        change.configuration_path = self._relative(config_path)
        change.override_manifest_path = self._relative(overrides_path)
        return change

    def _configuration_change_read(self, change: ConfigurationChange) -> ConfigurationChangeRead:
        return ConfigurationChangeRead(**self._configuration_change_payload(change))

    def _configuration_change_payload(self, change: ConfigurationChange) -> dict[str, Any]:
        return {
            "id": change.id,
            "project_id": change.project_id,
            "base_revision_id": change.base_revision_id,
            "generated_revision_id": change.generated_revision_id,
            "design_specification_id": change.design_specification_id,
            "design_plan_id": change.design_plan_id,
            "schema_version": change.schema_version,
            "reason": change.reason,
            "selected_preset_id": change.selected_preset_id,
            "validation_state": change.validation_state,
            "base_source_hash": change.base_source_hash,
            "content_hash": change.content_hash,
            "requested_changes": json.loads(change.requested_changes_json),
            "preset_values": json.loads(change.preset_values_json),
            "user_overrides": json.loads(change.user_overrides_json),
            "resolved_parameters": json.loads(change.resolved_parameters_json),
            "affected_parameters": json.loads(change.affected_parameters_json),
            "affected_components": json.loads(change.affected_components_json),
            "affected_outputs": json.loads(change.affected_outputs_json),
            "validation_errors": json.loads(change.validation_errors_json),
            "override_manifest_path": change.override_manifest_path,
            "configuration_path": change.configuration_path,
            "created_at": change.created_at,
            "approved_at": change.approved_at,
        }

    def _configuration_override_manifest(self, change: ConfigurationChange) -> dict[str, Any]:
        base_revision = self.db.get(Revision, change.base_revision_id)
        cad_backend = base_revision.cad_backend if base_revision is not None else "cadquery"
        source_language = base_revision.source_language if base_revision is not None else "python"
        parameter_values = (
            json.loads(change.resolved_parameters_json)
            if change.validation_state == ConfigurationValidationState.CONFIGURATION_READY.value
            else {}
        )
        return {
            "schema_version": "parameter-overrides-v1",
            "configuration_change_id": change.id,
            "base_revision_id": change.base_revision_id,
            "base_source_hash": change.base_source_hash,
            "cad_backend": cad_backend,
            "source_language": source_language,
            "selected_preset_id": change.selected_preset_id,
            "preset_values": json.loads(change.preset_values_json),
            "user_overrides": json.loads(change.user_overrides_json),
            "parameter_values": parameter_values,
            "parameter_hash": self._configuration_parameter_hash(parameter_values),
            "resolved_parameters": json.loads(change.resolved_parameters_json),
            "affected_parameters": json.loads(change.affected_parameters_json),
            "affected_components": json.loads(change.affected_components_json),
            "affected_outputs": json.loads(change.affected_outputs_json),
        }

    def _configured_design_specification_payload(
        self,
        base_revision: Revision,
        change: ConfigurationChange,
    ) -> dict[str, Any] | None:
        payload = self._revision_design_specification_payload(base_revision)
        if payload is None:
            return None
        configured = json.loads(json.dumps(payload))
        resolved = json.loads(change.resolved_parameters_json)
        for key in ("critical_dimensions", "parameters"):
            for item in configured.get(key, []):
                item_id = item.get("id")
                if item_id in resolved:
                    item["value"] = resolved[item_id]
                    item["source"] = "configuration"
        configured["configuration_change_id"] = change.id
        configured["configuration_base_specification_id"] = base_revision.design_specification_id
        return configured

    def _record_revision_messages(
        self,
        *,
        revision: Revision,
        user_instruction: str | None,
    ) -> None:
        if user_instruction:
            self._record_message(
                project_id=revision.project_id,
                revision_id=revision.id,
                role="user",
                content=user_instruction,
            )
        self._record_message(
            project_id=revision.project_id,
            revision_id=revision.id,
            role="system_event",
            content=f"Revision R{revision.revision_number} {revision.status}",
        )

    def _record_message(
        self,
        *,
        project_id: str,
        revision_id: str | None,
        role: str,
        content: str,
    ) -> None:
        self.db.add(
            ProjectMessage(
                project_id=project_id,
                revision_id=revision_id,
                role=role,
                content=content,
                created_at=project_utcnow(),
            )
        )

    def _revision_read(
        self,
        revision: Revision,
        *,
        metadata: MeshMetadata | None = None,
        error_message: str | None = None,
    ) -> RevisionRead:
        metadata_read = (
            MeshMetadataRead(**asdict(metadata))
            if metadata is not None
            else self._read_revision_metadata(revision)
        )
        return RevisionRead(
            id=revision.id,
            project_id=revision.project_id,
            parent_revision_id=revision.parent_revision_id,
            design_specification_id=revision.design_specification_id,
            design_plan_id=revision.design_plan_id,
            configuration_change_id=revision.configuration_change_id,
            revision_number=revision.revision_number,
            source_type=revision.source_type,
            user_instruction=revision.user_instruction,
            cad_backend=revision.cad_backend,
            source_language=revision.source_language,
            source_path=revision.source_path,
            source_hash=revision.source_hash,
            source_contract_version=revision.source_contract_version,
            execution_manifest_path=revision.execution_manifest_path,
            stl_path=revision.stl_path,
            compile_log_path=revision.compile_log_path,
            ai_output_path=revision.ai_output_path,
            output_manifest_path=revision.output_manifest_path,
            expected_output_count=revision.expected_output_count,
            required_output_count=revision.required_output_count,
            successful_output_count=revision.successful_output_count,
            blocked_output_count=revision.blocked_output_count,
            failed_output_count=revision.failed_output_count,
            status=revision.status,
            is_accepted=revision.is_accepted,
            review_state=revision.review_state,
            functional_status=revision.functional_status,
            accepted_at=revision.accepted_at,
            rejected_at=revision.rejected_at,
            created_at=revision.created_at,
            metadata=metadata_read,
            error_message=error_message,
            validation_summary=self._validation_summary(revision.id),
            design_consistency=self._design_artifact_consistency_read(revision),
        )

    def _design_artifact_consistency_read(
        self,
        revision: Revision,
    ) -> DesignArtifactConsistencyRead | None:
        if revision.cad_backend != "cadquery" or revision.design_plan_id is None:
            return None
        result = self._latest_design_artifact_consistency(revision.id)
        if result is None:
            return DesignArtifactConsistencyRead(status="legacy_unverified")
        payload = self._read_design_artifact_consistency_payload(result)
        findings = [
            finding for finding in payload.get("findings", []) if isinstance(finding, dict)
        ]
        blocking_count = sum(1 for finding in findings if finding.get("is_blocking"))
        advisory_count = len(findings) - blocking_count
        if result.revision_base_ready:
            status = "passed"
        elif blocking_count:
            status = "blocked"
        elif result.pre_execution_passed and not result.post_execution_passed:
            status = "needs_execution_evidence"
        else:
            status = "legacy_unverified"
        return DesignArtifactConsistencyRead(
            schema_version=result.schema_version,
            status=status,
            pre_execution_passed=result.pre_execution_passed,
            post_execution_passed=result.post_execution_passed,
            revision_base_ready=result.revision_base_ready,
            configuration_ready=result.configuration_ready,
            blocking_count=blocking_count,
            advisory_count=advisory_count,
            findings=findings,
            result_id=result.id,
            result_path=result.result_path,
            certified_at=str(payload.get("certified_at") or result.created_at.isoformat()),
        )

    def _revision_output_read(self, output: RevisionOutput) -> RevisionOutputRead:
        metadata = MeshMetadataRead(**json.loads(output.metadata_json)) if output.metadata_json else None
        preferred_orientation = self._preferred_orientation_read(
            output.preferred_orientation_json
        )
        return RevisionOutputRead(
            id=output.id,
            revision_id=output.revision_id,
            design_plan_id=output.design_plan_id,
            design_specification_id=output.design_specification_id,
            output_id=output.output_id,
            component_id=output.component_id,
            component_ids=json.loads(output.component_ids_json),
            execution_state=output.execution_state,
            output_type=output.output_type,
            label=output.label,
            filename=output.filename,
            quantity=output.quantity,
            required=output.required,
            entrypoint=output.entrypoint,
            source_hash=output.source_hash,
            parameter_hash=output.parameter_hash,
            step_path=output.step_path,
            step_hash=output.step_hash,
            brep_path=output.brep_path,
            brep_hash=output.brep_hash,
            stl_path=output.stl_path,
            stl_hash=output.stl_hash,
            compile_log_path=output.compile_log_path,
            compile_ms=output.compile_ms,
            compile_error=output.compile_error,
            expected_solid_count=output.expected_solid_count,
            detected_solid_count=output.detected_solid_count,
            allow_disconnected_solids=output.allow_disconnected_solids,
            execution_command=json.loads(output.execution_command_json),
            topology_metadata=json.loads(output.topology_metadata_json)
            if output.topology_metadata_json
            else None,
            mesh_metadata=MeshMetadataRead(**json.loads(output.mesh_metadata_json))
            if output.mesh_metadata_json
            else None,
            metadata=metadata,
            validation_summary=self._validation_summary(
                output.revision_id,
                revision_output_id=output.id,
            ),
            preferred_orientation=preferred_orientation,
            created_at=output.created_at,
            updated_at=output.updated_at,
        )

    def _preferred_orientation_read(
        self,
        preferred_orientation_json: str | None,
    ) -> dict[str, Any] | None:
        if not preferred_orientation_json:
            return None
        value = json.loads(preferred_orientation_json)
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            return {"description": value}
        return {"value": value}

    def _planned_printable_outputs(self, design_plan_payload: dict[str, Any]) -> list[dict[str, Any]]:
        outputs: list[dict[str, Any]] = []
        for output in design_plan_payload.get("printable_outputs", []):
            if not isinstance(output, dict):
                continue
            output_type = str(output.get("output_type") or "printable_component")
            if output_type not in PRINTABLE_OUTPUT_TYPES:
                continue
            output_id = str(output.get("id") or "").strip()
            if not output_id:
                continue
            component_ids = [
                str(component_id)
                for component_id in (
                    output.get("component_ids")
                    or ([output.get("component_id")] if output.get("component_id") else [])
                )
                if component_id
            ]
            component_id = str(output.get("component_id") or (component_ids[0] if component_ids else ""))
            entrypoint = str(output.get("entrypoint") or output_id).strip()
            required = bool(output.get("required", output_type != "optional_printable_component"))
            preferred_orientation = output.get("preferred_orientation") or output.get("orientation")
            outputs.append(
                {
                    "output_id": output_id,
                    "label": str(output.get("label") or output_id),
                    "component_id": component_id or None,
                    "component_ids": component_ids,
                    "entrypoint": entrypoint,
                    "filename": str(output.get("filename") or f"{output_id}.stl"),
                    "quantity": int(output.get("quantity") or 1),
                    "required": required,
                    "expected_solid_count": self._optional_int(
                        output.get("expected_solid_count")
                    ),
                    "allow_disconnected_solids": self._optional_bool(
                        output.get("allow_disconnected_solids")
                    ),
                    "output_type": output_type,
                    "preferred_orientation": preferred_orientation,
                }
            )
        return outputs

    def _safe_output_filename(self, output_id: str, requested: str | None, used: set[str]) -> str:
        raw = requested or f"{output_id}.stl"
        name = re.sub(r"[\x00-\x1f/\\:]+", "-", raw).strip(". -")
        if not name or name in {".", ".."} or ".." in name:
            name = f"{output_id}.stl"
        if not name.lower().endswith(".stl"):
            name = f"{name}.stl"
        reserved = {"con", "prn", "aux", "nul", "com1", "com2", "lpt1", "lpt2"}
        stem = Path(name).stem
        if stem.lower() in reserved:
            name = f"{output_id}.stl"
            stem = Path(name).stem
        suffix = Path(name).suffix or ".stl"
        candidate = name
        index = 2
        while candidate.lower() in used:
            candidate = f"{stem}-{index}{suffix}"
            index += 1
        return candidate

    def _safe_stem(self, value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-") or "artifact"

    def _file_sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _write_output_manifest(self, revision: Revision) -> Path:
        manifest_path = self._revision_dir(revision.project_id, revision.id) / "output-manifest.json"
        self._write_json(manifest_path, self._output_manifest_payload(revision))
        return manifest_path

    def _output_manifest_payload(self, revision: Revision) -> dict[str, Any]:
        outputs = list(
            self.db.scalars(
                select(RevisionOutput)
                .where(RevisionOutput.revision_id == revision.id)
                .order_by(RevisionOutput.created_at.asc(), RevisionOutput.output_id.asc())
            )
        )
        source_path = self.resolve_revision_source(revision.id)
        source_hash = self._file_sha256(source_path) if source_path is not None else None
        parameter_hash = next(
            (output.parameter_hash for output in outputs if output.parameter_hash),
            None,
        )
        return {
            "schema_version": "output-manifest-v1",
            "project_id": revision.project_id,
            "revision_id": revision.id,
            "design_plan_id": revision.design_plan_id,
            "configuration_change_id": revision.configuration_change_id,
            "parameter_hash": parameter_hash,
            "source": {
                "filename": Path(revision.source_path).name if revision.source_path else None,
                "path": revision.source_path,
                "sha256": source_hash,
                "cad_backend": revision.cad_backend,
                "source_language": revision.source_language,
                "source_contract_version": revision.source_contract_version,
            },
            "outputs": [self._output_manifest_entry(output) for output in outputs],
        }

    def _output_manifest_entry(self, output: RevisionOutput) -> dict[str, Any]:
        metadata = json.loads(output.mesh_metadata_json or output.metadata_json) if (
            output.mesh_metadata_json or output.metadata_json
        ) else None
        dimensions = None
        if metadata is not None:
            dimensions = {
                "x": metadata.get("size_x_mm"),
                "y": metadata.get("size_y_mm"),
                "z": metadata.get("size_z_mm"),
            }
        return {
            "output_id": output.output_id,
            "component_id": output.component_id,
            "component_ids": json.loads(output.component_ids_json),
            "filename": output.filename,
            "entrypoint": output.entrypoint,
            "parameter_hash": output.parameter_hash,
            "quantity": output.quantity,
            "required": output.required,
            "state": output.execution_state,
            "compile_ms": output.compile_ms,
            "expected_solid_count": output.expected_solid_count,
            "detected_solid_count": output.detected_solid_count,
            "allow_disconnected_solids": output.allow_disconnected_solids,
            "step": {"path": output.step_path, "sha256": output.step_hash},
            "brep": {"path": output.brep_path, "sha256": output.brep_hash},
            "stl": {"path": output.stl_path, "sha256": output.stl_hash},
            "sha256": output.stl_hash,
            "topology": json.loads(output.topology_metadata_json)
            if output.topology_metadata_json
            else None,
            "dimensions_mm": dimensions,
        }

    def _revision_design_plan_payload(self, revision: Revision) -> dict[str, Any] | None:
        if revision.design_plan_id is None:
            return None
        plan = self.db.get(DesignPlan, revision.design_plan_id)
        return self._read_design_plan_payload(plan) if plan is not None else None

    def _revision_design_specification_payload(self, revision: Revision) -> dict[str, Any] | None:
        if revision.design_specification_id is None:
            return None
        specification = self.db.get(DesignSpecification, revision.design_specification_id)
        return self._read_design_specification_payload(specification) if specification is not None else None

    def _revision_configuration_payload(self, revision: Revision) -> dict[str, Any] | None:
        if revision.configuration_change_id is None:
            return None
        change = self.db.get(ConfigurationChange, revision.configuration_change_id)
        return self._configuration_change_payload(change) if change is not None else None

    def _revision_override_manifest_payload(self, revision: Revision) -> dict[str, Any] | None:
        if revision.configuration_change_id is None:
            return None
        change = self.db.get(ConfigurationChange, revision.configuration_change_id)
        return self._configuration_override_manifest(change) if change is not None else None

    def _export_readme(
        self,
        revision: Revision,
        outputs: list[RevisionOutput],
        design_plan_payload: dict[str, Any] | None,
    ) -> str:
        project = self.db.get(Project, revision.project_id)
        lines = [
            f"# {project.name if project else 'Volundr Project'}",
            "",
            f"Revision: R{revision.revision_number} ({revision.id})",
            f"Generated: {revision.created_at.isoformat()}",
        ]
        config_payload = self._revision_configuration_payload(revision)
        if config_payload is not None:
            lines.extend(
                [
                    f"Base revision: {config_payload['base_revision_id']}",
                    f"Selected preset: {config_payload.get('selected_preset_id') or 'none'}",
                    "",
                    "## Configuration Overrides",
                ]
            )
            overrides = config_payload.get("user_overrides") or config_payload.get("requested_changes") or {}
            if overrides:
                for key, value in overrides.items():
                    lines.append(f"- {key}: {value}")
            else:
                lines.append("- None.")
        lines.extend(["", "## Parameters"])
        for parameter in (design_plan_payload or {}).get("parameters", []):
            lines.append(f"- {parameter.get('label') or parameter.get('id')}: {parameter.get('value')} {parameter.get('unit') or ''}".rstrip())
        if not (design_plan_payload or {}).get("parameters"):
            lines.append("- No structured parameters were available.")
        lines.extend(["", "## Printable Outputs"])
        for output in outputs:
            lines.append(
                f"- {output.label}: {output.filename}, quantity {output.quantity}, state {output.execution_state}"
            )
        lines.extend(
            [
                "",
                "## Known Warnings",
            ]
        )
        findings = list(
            self.db.scalars(
                select(ValidationFinding)
                .where(ValidationFinding.revision_id == revision.id)
                .where(ValidationFinding.is_blocking.is_(False))
                .order_by(ValidationFinding.rule_id.asc())
            )
        )
        if findings:
            for finding in findings:
                lines.append(f"- {finding.title}: {finding.explanation}")
        else:
            lines.append("- None recorded.")
        lines.extend(
            [
                "",
                "## Assembly Disclaimer",
                "Volundr validates printable artifacts, but this export does not prove assembled fit, fastener compatibility, or load capacity.",
                "",
                "## Regeneration",
                "Regenerate from the included Design Specification, Design Plan, and source.py to reproduce these outputs.",
            ]
        )
        return "\n".join(lines) + "\n"

    def _assembly_notes(
        self,
        design_plan_payload: dict[str, Any] | None,
        outputs: list[RevisionOutput],
    ) -> str:
        plan = design_plan_payload or {}
        assembly = plan.get("assembly_strategy", {})
        lines = ["# Assembly Notes", "", "## Components"]
        for output in outputs:
            lines.append(f"- {output.label}: quantity {output.quantity}")
        lines.extend(["", "## Relationships"])
        relationships = assembly.get("relationships") or assembly.get("instructions") or []
        if relationships:
            for relationship in relationships:
                if isinstance(relationship, dict):
                    lines.append(
                        f"- {relationship.get('from_component_id') or relationship.get('from') or 'component'} "
                        f"{relationship.get('relationship') or relationship.get('type') or 'relates to'} "
                        f"{relationship.get('to_component_id') or relationship.get('to') or 'component'}"
                    )
                else:
                    lines.append(f"- {relationship}")
        else:
            lines.append("- No detailed assembly relationships were provided by the Design Plan.")
        hardware = assembly.get("hardware") or plan.get("purchased_hardware") or []
        lines.extend(["", "## Purchased Hardware"])
        if hardware:
            for item in hardware:
                lines.append(f"- {item}")
        else:
            lines.append("- None listed.")
        lines.extend(["", "## Risks"])
        risks = plan.get("risks", [])
        if risks:
            for risk in risks:
                lines.append(f"- {risk.get('description') or risk}")
        else:
            lines.append("- No structured risks were listed.")
        return "\n".join(lines) + "\n"

    def _clear_assembly_output_findings(self, revision_id: str) -> None:
        self.db.execute(
            delete(ValidationFinding).where(
                ValidationFinding.revision_id == revision_id,
                ValidationFinding.category == "assembly",
            )
        )
        self.db.flush()

    def _next_revision_number(self, project_id: str) -> int:
        current = self.db.scalar(
            select(func.max(Revision.revision_number)).where(Revision.project_id == project_id)
        )
        return int(current or 0) + 1

    def _next_generation_attempt_number(self, project_id: str) -> int:
        current = self.db.scalar(
            select(func.max(GenerationAttempt.attempt_number)).where(
                GenerationAttempt.project_id == project_id
            )
        )
        return int(current or 0) + 1

    def _next_design_specification_version(self, project_id: str) -> int:
        current = self.db.scalar(
            select(func.max(DesignSpecification.version_number)).where(
                DesignSpecification.project_id == project_id
            )
        )
        return int(current or 0) + 1

    def _next_design_plan_version(self, project_id: str) -> int:
        current = self.db.scalar(
            select(func.max(DesignPlan.version_number)).where(
                DesignPlan.project_id == project_id
            )
        )
        return int(current or 0) + 1

    def _next_revision_plan_version(self, project_id: str) -> int:
        current = self.db.scalar(
            select(func.max(RevisionPlan.version_number)).where(
                RevisionPlan.project_id == project_id
            )
        )
        return int(current or 0) + 1

    def _revision_dir(self, project_id: str, revision_id: str) -> Path:
        return self.data_dir / "projects" / project_id / "revisions" / revision_id

    def _generation_attempt_dir(self, project_id: str, attempt_id: str) -> Path:
        return self.data_dir / "projects" / project_id / "generation-runs" / attempt_id

    def _revision_plan_dir(self, project_id: str, revision_plan_id: str) -> Path:
        return self.data_dir / "projects" / project_id / "revision-plans" / revision_plan_id

    def _relative(self, path: Path) -> str:
        return str(path.relative_to(self.data_dir))

    def _write_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _write_configuration_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")

    def _read_json_file(self, relative_path: str) -> dict[str, Any] | None:
        path = self.data_dir / relative_path
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _sha256(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _read_revision_metadata(self, revision: Revision) -> MeshMetadataRead | None:
        if revision.status != "succeeded" or not revision.source_path:
            return None
        metadata_path = (self.data_dir / revision.source_path).parent / "metadata.json"
        if not metadata_path.exists():
            output = self.db.scalar(
                select(RevisionOutput)
                .where(
                    RevisionOutput.revision_id == revision.id,
                    RevisionOutput.metadata_json.is_not(None),
                )
                .order_by(RevisionOutput.required.desc(), RevisionOutput.created_at.asc())
            )
            if output is None or output.metadata_json is None:
                return None
            return MeshMetadataRead(**json.loads(output.metadata_json))
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        return MeshMetadataRead(**payload)

    def _unique_slug(self, name: str, *, exclude_project_id: str | None = None) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"
        slug = base
        suffix = 2
        while True:
            existing_project = self.db.scalar(select(Project).where(Project.slug == slug))
            if existing_project is None or existing_project.id == exclude_project_id:
                return slug
            slug = f"{base}-{suffix}"
            suffix += 1

    def _next_draft_id(self) -> str:
        return project_utcnow().strftime("%Y%m%d%H%M%S%f")

    def _delete_project_files(self, project_id: str) -> None:
        project_dir = self.data_dir / "projects" / project_id
        if project_dir.exists():
            shutil.rmtree(project_dir)

    def _delete_workflow_debug_bundles(self, workflow_run_ids: list[str]) -> None:
        bundle_dir = self.data_dir / "workflow-debug-bundles"
        if bundle_dir.exists():
            for workflow_run_id in workflow_run_ids:
                (bundle_dir / f"workflow-debug-{workflow_run_id}.zip").unlink(missing_ok=True)

    def _delete_project_records(self, project: Project) -> None:
        project.active_revision_id = None
        self.db.flush()
        run_ids = list(
            self.db.scalars(select(WorkflowRun.id).where(WorkflowRun.project_id == project.id))
        )
        if run_ids:
            self.db.execute(delete(FrontendWorkflowEvent).where(FrontendWorkflowEvent.project_id == project.id))
            self.db.execute(delete(WorkflowDiagnosis).where(WorkflowDiagnosis.workflow_run_id.in_(run_ids)))
            self.db.execute(delete(WorkflowArtifact).where(WorkflowArtifact.project_id == project.id))
            self.db.execute(delete(WorkflowEvent).where(WorkflowEvent.project_id == project.id))
            self.db.execute(delete(WorkflowRun).where(WorkflowRun.project_id == project.id))
        self.db.execute(delete(ProjectMessage).where(ProjectMessage.project_id == project.id))
        self.db.execute(delete(Revision).where(Revision.project_id == project.id))
        self.db.delete(project)

    def _compile_log(self, result) -> str:
        parts: list[str] = []
        if result.stdout_path is not None and result.stdout_path.exists():
            stdout = result.stdout_path.read_text(encoding="utf-8", errors="replace").strip()
            if stdout:
                parts.append(stdout)
        if result.stderr_path is not None and result.stderr_path.exists():
            stderr = result.stderr_path.read_text(encoding="utf-8", errors="replace").strip()
            if stderr:
                parts.append(stderr)
        if not parts and result.error_message:
            parts.append(result.error_message)
        return "\n".join(parts)
