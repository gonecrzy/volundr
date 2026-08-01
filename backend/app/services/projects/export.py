"""Backend-owned exports for explicitly selected successful revisions."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.export_record import ExportRecord
from app.models.project import Project, utcnow
from app.models.requirement_ledger import (
    PhysicalTestObservation,
    RequirementDelta,
    RequirementLedgerEntry,
)
from app.models.revision import Revision
from app.models.revision_output import RevisionOutput
from app.models.validation_finding import ValidationFinding
from app.services.projects.requirement_ledger import RequirementLedgerStore, active_requirements
from app.services.workflow.observability import WorkflowRecorder


EXPORT_TYPES = frozenset({"stl", "step", "assembly_step", "print_parts_zip", "project_package"})


class ExportService:
    def __init__(self, *, db: Session, data_dir: Path):
        self.db = db
        self.data_dir = data_dir

    def create(
        self,
        *,
        project_id: str,
        export_type: str,
        revision_id: str | None = None,
        output_id: str | None = None,
    ) -> ExportRecord:
        if export_type not in EXPORT_TYPES:
            raise ValueError(f"unsupported export type: {export_type}")
        project = self.db.get(Project, project_id)
        if project is None:
            raise LookupError("project not found")
        revision = self.db.get(Revision, revision_id or project.active_revision_id)
        if revision is None or revision.project_id != project_id:
            raise ValueError("selected revision does not belong to this project")
        self._require_exportable_revision(revision)
        outputs = self._successful_outputs(revision)
        selected_outputs = self._select_outputs(outputs, export_type=export_type, output_id=output_id)
        selection_hash = self._selection_hash(project, revision, export_type, selected_outputs)
        previous = self.db.scalar(
            select(ExportRecord)
            .where(ExportRecord.project_id == project_id)
            .where(ExportRecord.revision_id == revision.id)
            .where(ExportRecord.selection_hash == selection_hash)
            .where(ExportRecord.status == "completed")
            .order_by(ExportRecord.created_at.desc())
        )
        if previous is not None and previous.output_path and self._resolve(previous.output_path).is_file():
            return previous

        filename = self._filename(project, revision, export_type, selected_outputs)
        record = ExportRecord(
            project_id=project_id,
            revision_id=revision.id,
            export_type=export_type,
            selection_hash=selection_hash,
            status="started",
            filename=filename,
            component_ids_json=json.dumps([output.output_id for output in selected_outputs]),
        )
        self.db.add(record)
        self.db.flush()
        workflow = WorkflowRecorder(db=self.db, data_dir=self.data_dir).start_run(
            project_id=project_id,
            workflow_type="export",
            metadata={"export_id": record.id, "export_type": export_type},
        )
        recorder = WorkflowRecorder(db=self.db, data_dir=self.data_dir)
        recorder.record_event(
            workflow,
            stage="export",
            event_type="export.requested",
            severity="summary",
            message="Export requested for an explicitly selected successful revision.",
            revision_id=revision.id,
            deduplication_key=f"export-requested-{record.id}",
        )
        try:
            output_path, manifest, warnings = self._build(
                project=project,
                revision=revision,
                export_type=export_type,
                selected_outputs=selected_outputs,
                filename=filename,
            )
            record.status = "completed"
            record.output_path = self._relative(output_path)
            record.manifest_json = json.dumps(manifest, sort_keys=True, default=str)
            record.warnings_json = json.dumps(warnings, sort_keys=True)
            record.sha256 = self._sha256_file(output_path)
            record.size_bytes = output_path.stat().st_size
            record.completed_at = utcnow()
            recorder.record_event(
                workflow,
                stage="export",
                event_type="export.completed",
                severity="summary",
                message="Export package completed and registered.",
                revision_id=revision.id,
                deduplication_key=f"export-completed-{record.id}",
                metadata={"export_id": record.id, "filename": filename},
            )
            recorder.complete_run(workflow, status="completed")
            self.db.commit()
            self.db.refresh(record)
            return record
        except Exception as exc:
            record.status = "failed"
            record.error_message = str(exc)
            recorder.record_event(
                workflow,
                stage="export",
                event_type="export.failed",
                severity="error",
                blocking=True,
                message="Export could not be completed.",
                revision_id=revision.id,
                deduplication_key=f"export-failed-{record.id}",
                metadata={"error": str(exc)},
            )
            recorder.complete_run(workflow, status="failed")
            self.db.commit()
            raise

    def list(self, project_id: str) -> list[ExportRecord]:
        return list(
            self.db.scalars(
                select(ExportRecord)
                .where(ExportRecord.project_id == project_id)
                .order_by(ExportRecord.created_at.desc(), ExportRecord.id.desc())
            )
        )

    def get(self, export_id: str, *, project_id: str | None = None) -> ExportRecord | None:
        record = self.db.get(ExportRecord, export_id)
        if record is None or (project_id is not None and record.project_id != project_id):
            return None
        return record

    def resolve_download(self, export_id: str, *, project_id: str | None = None) -> tuple[ExportRecord, Path] | None:
        record = self.get(export_id, project_id=project_id)
        if record is None or record.status != "completed" or not record.output_path:
            return None
        path = self._resolve(record.output_path)
        if not path.is_file() or path.stat().st_size == 0:
            return None
        return record, path

    def _require_exportable_revision(self, revision: Revision) -> None:
        if revision.status != "succeeded" or revision.review_state not in {"accepted", "ready", "ready_with_warnings"}:
            raise ValueError("exports require a successful non-blocked revision")

    def _successful_outputs(self, revision: Revision) -> list[RevisionOutput]:
        outputs = list(
            self.db.scalars(
                select(RevisionOutput)
                .where(RevisionOutput.revision_id == revision.id)
                .where(RevisionOutput.required.is_(True))
                .order_by(RevisionOutput.created_at.asc(), RevisionOutput.output_id.asc())
            )
        )
        if not outputs:
            raise ValueError("selected revision has no printable outputs")
        for output in outputs:
            if output.execution_state not in {"ready", "ready_with_warnings"}:
                raise ValueError("selected revision has an output that is not ready")
            for relative_path in (output.stl_path, output.step_path):
                if relative_path and (not self._resolve(relative_path).is_file() or self._resolve(relative_path).stat().st_size == 0):
                    raise ValueError("selected revision has a missing or empty registered artifact")
        return outputs

    def _select_outputs(self, outputs: list[RevisionOutput], *, export_type: str, output_id: str | None) -> list[RevisionOutput]:
        if export_type in {"stl", "step"}:
            if output_id is None and len(outputs) != 1:
                raise ValueError("select one printable output for a per-part export")
            selected = [output for output in outputs if output.output_id == output_id] if output_id else outputs
            if len(selected) != 1:
                raise ValueError("selected printable output was not found")
            if export_type == "stl" and selected[0].stl_path is None:
                raise ValueError("selected output has no STL artifact")
            if export_type == "step" and selected[0].step_path is None:
                raise ValueError("selected output has no STEP artifact")
            return selected
        if export_type == "assembly_step" and len(outputs) != 1:
            raise ValueError("combined assembly STEP is only available when one exact output is present")
        return outputs

    def _build(self, *, project: Project, revision: Revision, export_type: str, selected_outputs: list[RevisionOutput], filename: str) -> tuple[Path, dict[str, Any], list[str]]:
        export_dir = self.data_dir / "projects" / project.id / "exports" / f"r{revision.revision_number}"
        export_dir.mkdir(parents=True, exist_ok=True)
        output_path = export_dir / filename
        artifacts = self._artifact_manifest(selected_outputs, export_type)
        warnings: list[str] = []
        if export_type in {"stl", "step", "assembly_step"}:
            source_path = self._artifact_path(selected_outputs[0], "stl" if export_type == "stl" else "step")
            shutil.copyfile(source_path, output_path)
        else:
            manifest = {
                "project_id": project.id,
                "project_name": project.name,
                "revision_id": revision.id,
                "revision_number": revision.revision_number,
                "export_type": export_type,
                "units": "mm",
                "artifacts": artifacts,
                "warnings": warnings,
            }
            with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                if export_type == "project_package":
                    self._write_project_package(archive, project, revision, selected_outputs, manifest)
                else:
                    self._write_print_parts_package(archive, selected_outputs, manifest)
        return output_path, {
            "project_id": project.id,
            "revision_id": revision.id,
            "revision_number": revision.revision_number,
            "export_type": export_type,
            "units": "mm",
            "artifacts": artifacts,
            "warnings": warnings,
        }, warnings

    def _write_print_parts_package(self, archive: zipfile.ZipFile, outputs: list[RevisionOutput], manifest: dict[str, Any]) -> None:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
        archive.writestr("README.txt", "Volundr printable parts export. Units: millimeters.\n")
        archive.writestr("verification-summary.json", json.dumps({"readiness": "verified_registered_artifacts", "warnings": manifest["warnings"]}, indent=2, sort_keys=True))
        for output in outputs:
            part_slug = self._safe_stem(output.output_id)
            if output.stl_path:
                archive.write(self._resolve(output.stl_path), f"stl/{part_slug}.stl")
            if output.step_path:
                archive.write(self._resolve(output.step_path), f"step/{part_slug}.step")

    def _write_project_package(self, archive: zipfile.ZipFile, project: Project, revision: Revision, outputs: list[RevisionOutput], manifest: dict[str, Any]) -> None:
        active = active_requirements(RequirementLedgerStore(self.db).load(project.id))
        history_entries = list(self.db.scalars(select(RequirementLedgerEntry).where(RequirementLedgerEntry.project_id == project.id).order_by(RequirementLedgerEntry.created_at.asc())))
        deltas = list(self.db.scalars(select(RequirementDelta).where(RequirementDelta.project_id == project.id).order_by(RequirementDelta.created_at.asc())))
        observations = list(self.db.scalars(select(PhysicalTestObservation).where(PhysicalTestObservation.project_id == project.id).order_by(PhysicalTestObservation.created_at.asc())))
        revisions = list(self.db.scalars(select(Revision).where(Revision.project_id == project.id).order_by(Revision.revision_number.asc())))
        findings = list(self.db.scalars(select(ValidationFinding).where(ValidationFinding.revision_id == revision.id).order_by(ValidationFinding.created_at.asc())))
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True, default=str))
        archive.writestr("project.json", json.dumps({"id": project.id, "name": project.name, "slug": project.slug, "original_intent": project.original_intent, "current_working_revision_id": project.active_revision_id}, indent=2, sort_keys=True))
        archive.writestr("requirements.json", json.dumps(active, indent=2, sort_keys=True, default=str))
        archive.writestr("requirement-history.json", json.dumps({"entries": [self._model_payload(entry) for entry in history_entries], "deltas": [self._model_payload(delta) for delta in deltas], "physical_test_observations": [self._model_payload(item) for item in observations]}, indent=2, sort_keys=True, default=str))
        archive.writestr("revision-history.json", json.dumps([{"id": item.id, "revision_number": item.revision_number, "parent_revision_id": item.parent_revision_id, "status": item.status, "is_accepted": item.is_accepted, "review_state": item.review_state, "user_instruction": item.user_instruction} for item in revisions], indent=2, sort_keys=True, default=str))
        archive.writestr("verification-summary.json", json.dumps({"revision_id": revision.id, "findings": [self._model_payload(finding) for finding in findings], "warnings": manifest["warnings"]}, indent=2, sort_keys=True, default=str))
        source = self._optional_path(revision.source_path)
        if source:
            archive.write(source, "source/model.py")
        if revision.output_manifest_path and self._optional_path(revision.output_manifest_path):
            archive.write(self._resolve(revision.output_manifest_path), "output-manifest.json")
        for output in outputs:
            part_slug = self._safe_stem(output.output_id)
            if output.stl_path:
                archive.write(self._resolve(output.stl_path), f"stl/{part_slug}.stl")
            if output.step_path:
                archive.write(self._resolve(output.step_path), f"step/{part_slug}.step")
            if output.brep_path and self._optional_path(output.brep_path):
                archive.write(self._resolve(output.brep_path), f"brep/{part_slug}.brep")
        archive.writestr("README.txt", "Volundr project package. Geometry units: millimeters.\n")

    def _artifact_manifest(self, outputs: list[RevisionOutput], export_type: str) -> list[dict[str, Any]]:
        artifacts: list[dict[str, Any]] = []
        for output in outputs:
            paths = ["stl"] if export_type == "stl" else ["step"] if export_type in {"step", "assembly_step"} else ["stl", "step"]
            for kind in paths:
                relative = getattr(output, f"{kind}_path")
                if relative:
                    path = self._resolve(relative)
                    artifacts.append({"output_id": output.output_id, "component_id": output.component_id, "kind": kind, "sha256": self._sha256_file(path), "size_bytes": path.stat().st_size, "units": "mm"})
        return artifacts

    def _artifact_path(self, output: RevisionOutput, kind: str) -> Path:
        relative = getattr(output, f"{kind}_path")
        if not relative:
            raise ValueError(f"selected output has no {kind.upper()} artifact")
        return self._resolve(relative)

    def _filename(self, project: Project, revision: Revision, export_type: str, outputs: list[RevisionOutput]) -> str:
        root = self._safe_stem(project.slug)
        if export_type == "stl":
            return f"{root}_{self._safe_stem(outputs[0].output_id)}_r{revision.revision_number}.stl"
        if export_type == "step":
            return f"{root}_{self._safe_stem(outputs[0].output_id)}_r{revision.revision_number}.step"
        if export_type == "assembly_step":
            return f"{root}_assembly_r{revision.revision_number}.step"
        if export_type == "print_parts_zip":
            return f"{root}_print-parts_r{revision.revision_number}.zip"
        return f"{root}_project_r{revision.revision_number}.zip"

    def _selection_hash(self, project: Project, revision: Revision, export_type: str, outputs: list[RevisionOutput]) -> str:
        payload = {"project_id": project.id, "revision_id": revision.id, "export_type": export_type, "outputs": [output.output_id for output in outputs]}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def _resolve(self, relative_path: str) -> Path:
        candidate = (self.data_dir / relative_path).resolve()
        root = self.data_dir.resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError("registered artifact path escapes durable storage")
        return candidate

    def _optional_path(self, relative_path: str | None) -> Path | None:
        if not relative_path:
            return None
        path = self._resolve(relative_path)
        return path if path.is_file() else None

    def _relative(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.data_dir.resolve()))

    @staticmethod
    def _safe_stem(value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-.") or "part"

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _model_payload(model: Any) -> dict[str, Any]:
        return {
            key: value
            for key, value in vars(model).items()
            if not key.startswith("_") and key not in {"project", "revision", "requirement_delta", "project_message"}
        }


def export_read(record: ExportRecord):
    return {
        "id": record.id,
        "project_id": record.project_id,
        "revision_id": record.revision_id,
        "export_type": record.export_type,
        "status": record.status,
        "filename": record.filename,
        "output_path": record.output_path,
        "component_ids": json.loads(record.component_ids_json or "[]"),
        "manifest": json.loads(record.manifest_json or "{}"),
        "warnings": json.loads(record.warnings_json or "[]"),
        "sha256": record.sha256,
        "size_bytes": record.size_bytes,
        "error_message": record.error_message,
        "created_at": record.created_at,
        "completed_at": record.completed_at,
    }
