import json
import re
import shutil
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.project import Project
from app.models.revision import Revision
from app.schemas.project import ManualRevisionCreate, MeshMetadataRead, ProjectCreate, RevisionRead
from app.services.cad.runner import OpenScadCliRunner
from app.services.mesh.inspect import MeshMetadata


class ProjectService:
    def __init__(
        self,
        *,
        db: Session,
        data_dir: Path | None = None,
        cad_runner: OpenScadCliRunner | None = None,
    ) -> None:
        self.db = db
        self.data_dir = data_dir or settings.data_dir
        self.cad_runner = cad_runner or OpenScadCliRunner()

    def create_project(self, payload: ProjectCreate) -> Project:
        project = Project(
            name=payload.name.strip(),
            slug=self._unique_slug(payload.name),
            original_intent=payload.original_intent.strip(),
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        return project

    def list_projects(self) -> list[Project]:
        return list(self.db.scalars(select(Project).order_by(Project.created_at.desc())))

    def get_project(self, project_id: str) -> Project | None:
        return self.db.get(Project, project_id)

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
        project = self.db.get(Project, project_id)
        if project is None:
            return None

        revision_number = self._next_revision_number(project_id)
        revision = Revision(
            project_id=project_id,
            parent_revision_id=project.active_revision_id,
            revision_number=revision_number,
            source_type="manual_edit",
            user_instruction=payload.user_instruction,
            scad_source_path="",
            status="compiling",
            is_accepted=False,
        )
        self.db.add(revision)
        self.db.flush()

        revision_dir = self._revision_dir(project_id, revision.id)
        revision_dir.mkdir(parents=True, exist_ok=True)
        source_path = revision_dir / "model.scad"
        source_path.write_text(payload.scad_source, encoding="utf-8")

        result = await self.cad_runner.compile(payload.scad_source, job_id=revision.id)

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
        self.db.commit()
        self.db.refresh(project)
        return project

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

    def _revision_dir(self, project_id: str, revision_id: str) -> Path:
        return self.data_dir / "projects" / project_id / "revisions" / revision_id

    def _relative(self, path: Path) -> str:
        return str(path.relative_to(self.data_dir))

    def _read_revision_metadata(self, revision: Revision) -> MeshMetadataRead | None:
        if revision.status != "succeeded" or not revision.scad_source_path:
            return None
        metadata_path = (self.data_dir / revision.scad_source_path).parent / "metadata.json"
        if not metadata_path.exists():
            return None
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        return MeshMetadataRead(**payload)

    def _unique_slug(self, name: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"
        slug = base
        suffix = 2
        while self.db.scalar(select(Project).where(Project.slug == slug)) is not None:
            slug = f"{base}-{suffix}"
            suffix += 1
        return slug

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
