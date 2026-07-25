import difflib
import hashlib
import json
import re
import shutil
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.generation_attempt import GenerationAttempt
from app.models.project import Project, utcnow as project_utcnow
from app.models.project_message import ProjectMessage
from app.models.revision import Revision
from app.schemas.project import (
    GenerationCreate,
    ManualRevisionCreate,
    MeshMetadataRead,
    ProjectCreate,
    ProjectMessageRead,
    ProjectSave,
    ProjectUpdate,
    RevisionRead,
)
from app.services.ai.provider import AiProvider, ModelGenerationRequest
from app.services.ai.source_extraction import SourceExtractionError, extract_scad_source
from app.services.cad.runner import OpenScadCliRunner
from app.services.generation.failure_taxonomy import FailureClass
from app.services.mesh.inspect import MeshMetadata

DRAFT_RETENTION_DAYS = 14
ARCHIVED_RETENTION_DAYS = 60


class ProjectService:
    def __init__(
        self,
        *,
        db: Session,
        data_dir: Path | None = None,
        cad_runner: OpenScadCliRunner | None = None,
        ai_provider: AiProvider | None = None,
    ) -> None:
        self.db = db
        self.data_dir = data_dir or settings.data_dir
        self.cad_runner = cad_runner or OpenScadCliRunner()
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
        self._delete_project_records(project)
        self.db.commit()
        self._delete_project_files(deleted_project_id)
        return True

    def list_revisions(self, project_id: str) -> list[RevisionRead]:
        revisions = self.db.scalars(
            select(Revision)
            .where(Revision.project_id == project_id)
            .order_by(Revision.revision_number.asc())
        )
        return [self._revision_read(revision) for revision in revisions]

    async def create_manual_revision(
        self,
        project_id: str,
        payload: ManualRevisionCreate,
    ) -> RevisionRead | None:
        return await self._create_revision_from_source(
            project_id=project_id,
            scad_source=payload.scad_source,
            user_instruction=payload.user_instruction,
            source_type="manual_edit",
        )

    async def generate_initial_revision(
        self,
        project_id: str,
        payload: GenerationCreate,
    ) -> RevisionRead | None:
        project = self.db.get(Project, project_id)
        if project is None:
            return None
        if self.ai_provider is None:
            raise RuntimeError("AI provider is not configured")

        current_source = None
        source_type = "ai_initial"
        if project.active_revision_id is not None:
            current_source = self.read_revision_source(project.active_revision_id)
            if current_source is None:
                raise RuntimeError("active revision source is missing")
            source_type = "ai_revision"

        generation_request = self._generation_request(
            project=project,
            payload=payload,
            current_source=current_source,
        )
        generation_attempt = self._start_generation_attempt(
            project=project,
            request=generation_request,
            base_revision_id=project.active_revision_id,
        )
        try:
            generation_result = await self.ai_provider.generate_model(generation_request)
        except RuntimeError as exc:
            self._finish_generation_attempt(
                generation_attempt,
                status="failed",
                failure_class=FailureClass.PROVIDER_FAILURE,
                error_message=str(exc),
            )
            raise

        self._record_generation_result(generation_attempt, generation_result)
        try:
            scad_source = extract_scad_source(generation_result.raw_output)
        except SourceExtractionError as exc:
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
                failure_class=FailureClass.SOURCE_EXTRACTION_FAILURE,
                error_message=str(exc),
                resulting_revision_id=failed_revision.id,
            )
            return failed_revision

        self._record_generation_extracted_source(generation_attempt, scad_source)
        initial_revision = await self._create_revision_from_source(
            project_id=project_id,
            scad_source=scad_source,
            user_instruction=payload.user_instruction,
            source_type=source_type,
            raw_ai_output=generation_result.raw_output,
        )
        if initial_revision is None or initial_revision.status == "succeeded":
            self._finish_generation_attempt(
                generation_attempt,
                status="succeeded" if initial_revision is not None else "failed",
                failure_class=FailureClass.NONE
                if initial_revision is not None
                else FailureClass.UNKNOWN_FAILURE,
                resulting_revision_id=initial_revision.id if initial_revision is not None else None,
            )
            return initial_revision

        self._finish_generation_attempt(
            generation_attempt,
            status="failed",
            failure_class=FailureClass.OPENSCAD_COMPILE_FAILURE,
            error_message=initial_revision.error_message,
            resulting_revision_id=initial_revision.id,
        )

        repair_request = self._generation_request(
            project=project,
            payload=payload,
            current_source=scad_source,
            compiler_diagnostics=initial_revision.error_message,
        )
        repair_attempt = self._start_generation_attempt(
            project=project,
            request=repair_request,
            base_revision_id=project.active_revision_id,
        )
        try:
            repair_result = await self.ai_provider.generate_model(repair_request)
        except RuntimeError as exc:
            self._finish_generation_attempt(
                repair_attempt,
                status="failed",
                failure_class=FailureClass.PROVIDER_FAILURE,
                error_message=str(exc),
            )
            raise

        self._record_generation_result(repair_attempt, repair_result)
        try:
            repaired_source = extract_scad_source(repair_result.raw_output)
        except SourceExtractionError as exc:
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
                failure_class=FailureClass.SOURCE_EXTRACTION_FAILURE,
                error_message=str(exc),
                resulting_revision_id=failed_repair.id,
            )
            return failed_repair

        self._record_generation_extracted_source(repair_attempt, repaired_source)
        repair_revision = await self._create_revision_from_source(
            project_id=project_id,
            scad_source=repaired_source,
            user_instruction=payload.user_instruction,
            source_type="ai_repair",
            raw_ai_output=repair_result.raw_output,
        )
        self._finish_generation_attempt(
            repair_attempt,
            status="succeeded" if repair_revision and repair_revision.status == "succeeded" else "failed",
            failure_class=FailureClass.NONE
            if repair_revision and repair_revision.status == "succeeded"
            else FailureClass.OPENSCAD_COMPILE_FAILURE,
            error_message=None
            if repair_revision and repair_revision.status == "succeeded"
            else repair_revision.error_message if repair_revision else "repair revision was not created",
            resulting_revision_id=repair_revision.id if repair_revision else None,
        )
        return repair_revision

    def _generation_request(
        self,
        *,
        project: Project,
        payload: GenerationCreate,
        current_source: str | None = None,
        compiler_diagnostics: str | None = None,
    ) -> ModelGenerationRequest:
        return ModelGenerationRequest(
            project_name=project.name,
            original_intent=project.original_intent,
            user_instruction=payload.user_instruction,
            current_source=current_source,
            compiler_diagnostics=compiler_diagnostics,
        )

    def _start_generation_attempt(
        self,
        *,
        project: Project,
        request: ModelGenerationRequest,
        base_revision_id: str | None,
    ) -> GenerationAttempt:
        attempt = GenerationAttempt(
            project_id=project.id,
            base_revision_id=base_revision_id,
            attempt_number=self._next_generation_attempt_number(project.id),
            provider=self._provider_name(),
            provider_model=self._provider_model(),
            provider_settings_json=json.dumps(self._provider_settings(), sort_keys=True),
            prompt_template_version=self._prompt_template_version(request),
            gemini_ruleset_version=self._gemini_ruleset_version(),
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
        prompt_path.write_text(self._render_prompt(request), encoding="utf-8")
        self._write_json(design_spec_path, self._legacy_design_spec(request))
        self._write_json(chain_path, self._attempt_chain(attempt, status="started"))

        attempt.request_payload_path = self._relative(request_path)
        attempt.prompt_path = self._relative(prompt_path)
        attempt.design_spec_path = self._relative(design_spec_path)
        attempt.intermediate_artifacts_path = self._relative(chain_path)
        self._update_attempt_chain(attempt, status="started")
        self.db.commit()
        self.db.refresh(attempt)
        return attempt

    def _record_generation_result(self, attempt: GenerationAttempt, generation_result) -> None:
        run_dir = self._generation_attempt_dir(attempt.project_id, attempt.id)
        raw_output_path = run_dir / "raw-output.txt"
        raw_output_path.write_text(generation_result.raw_output, encoding="utf-8")
        attempt.provider = generation_result.provider
        attempt.provider_model = generation_result.provider_model
        attempt.raw_output_path = self._relative(raw_output_path)
        attempt.output_hash = self._sha256(generation_result.raw_output)
        self._update_attempt_chain(attempt, status=attempt.status)
        self.db.commit()

    def _record_generation_extracted_source(self, attempt: GenerationAttempt, source: str) -> None:
        run_dir = self._generation_attempt_dir(attempt.project_id, attempt.id)
        source_path = run_dir / "extracted-source.scad"
        source_path.write_text(source, encoding="utf-8")
        attempt.extracted_source_path = self._relative(source_path)
        attempt.source_hash = self._sha256(source)
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
        return {
            "chain_version": "generation-chain-v1",
            "attempt_id": attempt.id,
            "status": status,
            "failure_class": attempt.failure_class,
            "error_message": error_message,
            "stages": [
                {
                    "stage": "legacy_openscad_generation",
                    "prompt_template_version": attempt.prompt_template_version,
                    "gemini_ruleset_version": attempt.gemini_ruleset_version,
                    "request_payload_path": attempt.request_payload_path,
                    "prompt_path": attempt.prompt_path,
                    "raw_output_path": attempt.raw_output_path,
                    "extracted_source_path": attempt.extracted_source_path,
                    "design_spec_path": attempt.design_spec_path,
                    "source_hash": attempt.source_hash,
                    "output_hash": attempt.output_hash,
                }
            ],
        }

    def _legacy_design_spec(self, request: ModelGenerationRequest) -> dict:
        return {
            "design_specification_version": "legacy-design-spec-placeholder-v1",
            "artifact_status": "placeholder_until_staged_requirements",
            "sources": ["user", "calculated", "profile_default", "ai_assumption"],
            "project_name": {"value": request.project_name, "source": "user"},
            "original_intent": {"value": request.original_intent, "source": "user"},
            "user_instruction": {"value": request.user_instruction, "source": "user"},
        }

    def _render_prompt(self, request: ModelGenerationRequest) -> str:
        build_prompt = getattr(self.ai_provider, "build_prompt", None)
        if callable(build_prompt):
            return build_prompt(request)
        return ""

    def _prompt_template_version(self, request: ModelGenerationRequest) -> str:
        version_for = getattr(self.ai_provider, "prompt_template_version_for", None)
        if callable(version_for):
            return str(version_for(request))
        if request.compiler_diagnostics:
            return "legacy-compile-repair-v1"
        if request.current_source:
            return "legacy-revision-v1"
        return "legacy-initial-v1"

    def _gemini_ruleset_version(self) -> str:
        return str(getattr(self.ai_provider, "gemini_ruleset_version", "gemini-ruleset-v1"))

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
            scad_source_path="",
            status="failed",
            is_accepted=False,
        )
        self.db.add(revision)
        self.db.flush()

        revision_dir = self._revision_dir(project.id, revision.id)
        revision_dir.mkdir(parents=True, exist_ok=True)
        source_path = revision_dir / "model.scad"
        source_path.write_text("", encoding="utf-8")
        ai_output_path = revision_dir / "ai-output.txt"
        ai_output_path.write_text(raw_ai_output, encoding="utf-8")
        compile_log_path = revision_dir / "compile.log"
        compile_log_path.write_text(error_message, encoding="utf-8")

        revision.scad_source_path = self._relative(source_path)
        revision.ai_output_path = self._relative(ai_output_path)
        revision.compile_log_path = self._relative(compile_log_path)
        self._record_revision_messages(revision=revision, user_instruction=user_instruction)
        self.db.commit()
        self.db.refresh(revision)
        return self._revision_read(revision, error_message=error_message)

    async def _create_revision_from_source(
        self,
        *,
        project_id: str,
        scad_source: str,
        user_instruction: str | None,
        source_type: str,
        raw_ai_output: str | None = None,
    ) -> RevisionRead | None:
        project = self.db.get(Project, project_id)
        if project is None:
            return None

        revision_number = self._next_revision_number(project_id)
        revision = Revision(
            project_id=project_id,
            parent_revision_id=project.active_revision_id,
            revision_number=revision_number,
            source_type=source_type,
            user_instruction=user_instruction,
            scad_source_path="",
            status="compiling",
            is_accepted=False,
        )
        self.db.add(revision)
        self.db.flush()

        revision_dir = self._revision_dir(project_id, revision.id)
        revision_dir.mkdir(parents=True, exist_ok=True)
        source_path = revision_dir / "model.scad"
        source_path.write_text(scad_source, encoding="utf-8")

        ai_output_relative_path: str | None = None
        if raw_ai_output is not None:
            ai_output_path = revision_dir / "ai-output.txt"
            ai_output_path.write_text(raw_ai_output, encoding="utf-8")
            ai_output_relative_path = self._relative(ai_output_path)

        result = await self.cad_runner.compile(scad_source, job_id=revision.id)

        compile_log_path = revision_dir / "compile.log"
        compile_log_path.write_text(self._compile_log(result), encoding="utf-8")

        metadata: MeshMetadata | None = None
        stl_relative_path: str | None = None
        if result.success and result.stl_path is not None and result.metadata is not None:
            stl_path = revision_dir / "model.stl"
            shutil.copyfile(result.stl_path, stl_path)
            metadata_path = revision_dir / "metadata.json"
            metadata_path.write_text(json.dumps(asdict(result.metadata), indent=2), encoding="utf-8")
            metadata = result.metadata
            stl_relative_path = self._relative(stl_path)
            revision.status = "succeeded"
            revision.is_accepted = True
            project.active_revision_id = revision.id
        else:
            revision.status = "failed"
            revision.is_accepted = False

        revision.scad_source_path = self._relative(source_path)
        revision.stl_path = stl_relative_path
        revision.compile_log_path = self._relative(compile_log_path)
        revision.ai_output_path = ai_output_relative_path
        self._record_revision_messages(revision=revision, user_instruction=user_instruction)
        self.db.commit()
        self.db.refresh(revision)
        return self._revision_read(revision, metadata=metadata, error_message=result.error_message)

    def read_revision_source(self, revision_id: str) -> str | None:
        path = self.resolve_revision_source(revision_id)
        if path is None:
            return None
        return path.read_text(encoding="utf-8")

    def resolve_revision_source(self, revision_id: str) -> Path | None:
        revision = self.db.get(Revision, revision_id)
        if revision is None or not revision.scad_source_path:
            return None
        path = self.data_dir / revision.scad_source_path
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

    def restore_revision(self, revision_id: str) -> Project | None:
        revision = self.db.get(Revision, revision_id)
        if revision is None or revision.status != "succeeded":
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
            revision_number=revision.revision_number,
            source_type=revision.source_type,
            user_instruction=revision.user_instruction,
            scad_source_path=revision.scad_source_path,
            stl_path=revision.stl_path,
            compile_log_path=revision.compile_log_path,
            ai_output_path=revision.ai_output_path,
            status=revision.status,
            is_accepted=revision.is_accepted,
            created_at=revision.created_at,
            metadata=metadata_read,
            error_message=error_message,
        )

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

    def _revision_dir(self, project_id: str, revision_id: str) -> Path:
        return self.data_dir / "projects" / project_id / "revisions" / revision_id

    def _generation_attempt_dir(self, project_id: str, attempt_id: str) -> Path:
        return self.data_dir / "projects" / project_id / "generation-runs" / attempt_id

    def _relative(self, path: Path) -> str:
        return str(path.relative_to(self.data_dir))

    def _write_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _sha256(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _read_revision_metadata(self, revision: Revision) -> MeshMetadataRead | None:
        if revision.status != "succeeded" or not revision.scad_source_path:
            return None
        metadata_path = (self.data_dir / revision.scad_source_path).parent / "metadata.json"
        if not metadata_path.exists():
            return None
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

    def _delete_project_records(self, project: Project) -> None:
        project.active_revision_id = None
        self.db.flush()
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
