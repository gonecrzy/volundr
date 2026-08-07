from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.project import Project
from app.models.revision_output import RevisionOutput
from app.services.executable_cadquery.fixtures import (
    FROZEN_MOUNTING_BRACKET_CONTRACT,
    valid_mounting_bracket_source,
)
from app.services.projects.service import ProjectService
from app.testing.e2e_fixture_server import FixtureRunner


@pytest.mark.asyncio
async def test_complete_source_revision_reuses_existing_worker_and_preserves_source(tmp_path) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    source = valid_mounting_bracket_source()
    contract = {**FROZEN_MOUNTING_BRACKET_CONTRACT, "project_id": "pending"}
    runner = FixtureRunner(tmp_path)

    with Session(engine) as db:
        project = Project(
            name="Executable fixture",
            slug="executable-fixture",
            original_intent="Build the frozen mounting bracket.",
        )
        db.add(project)
        db.flush()
        contract["project_id"] = project.id

        revision = await ProjectService(
            db=db,
            data_dir=tmp_path,
            cad_runner=runner,
        ).create_complete_cadquery_revision(
            project_id=project.id,
            source=source,
            user_instruction="Build the frozen mounting bracket.",
            raw_ai_output='{"complete_source": true}',
            design_plan_payload={
                "printable_outputs": [
                    {
                        "id": "mounting_bracket",
                        "label": "Mounting bracket",
                        "component_id": "mounting_bracket",
                        "component_ids": ["mounting_bracket"],
                        "entrypoint": "mounting_bracket",
                        "filename": "mounting_bracket.stl",
                        "required": True,
                        "expected_solid_count": 1,
                        "allow_disconnected_solids": False,
                    }
                ]
            },
        )

        assert revision is not None
        assert revision.source_hash == hashlib.sha256(source.encode("utf-8")).hexdigest()
        persisted = ProjectService(db=db, data_dir=tmp_path).resolve_revision_source(revision.id)
        assert persisted is not None
        assert persisted.read_text(encoding="utf-8") == source
        assert runner.calls and runner.calls[0]["output_ids"] == ["mounting_bracket"]


@pytest.mark.asyncio
async def test_complete_source_output_retry_does_not_require_design_plan(tmp_path) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    source = valid_mounting_bracket_source()
    runner = FixtureRunner(tmp_path)

    with Session(engine) as db:
        project = Project(
            name="Executable retry fixture",
            slug="executable-retry-fixture",
            original_intent="Build the frozen mounting bracket.",
        )
        db.add(project)
        db.flush()
        revision = await ProjectService(
            db=db,
            data_dir=tmp_path,
            cad_runner=runner,
        ).create_complete_cadquery_revision(
            project_id=project.id,
            source=source,
            user_instruction="Build the frozen mounting bracket.",
            raw_ai_output='{"complete_source": true}',
            design_plan_payload={
                "printable_outputs": [
                    {
                        "id": "mounting_bracket",
                        "label": "Mounting bracket",
                        "component_id": "mounting_bracket",
                        "component_ids": ["mounting_bracket"],
                        "entrypoint": "mounting_bracket",
                        "filename": "mounting_bracket.stl",
                        "required": True,
                        "expected_solid_count": 1,
                        "allow_disconnected_solids": False,
                    }
                ]
            },
        )
        assert revision is not None
        output = db.scalar(
            select(RevisionOutput).where(RevisionOutput.revision_id == revision.id)
        )
        assert output is not None
        output.execution_state = "failed"
        db.commit()

        retried = await ProjectService(
            db=db,
            data_dir=tmp_path,
            cad_runner=runner,
        ).retry_revision_output(output.id)

        assert retried is not None
        assert retried.execution_state in {"ready", "ready_with_warnings"}
        assert retried.output_id == "mounting_bracket"


@pytest.mark.asyncio
async def test_output_retry_persists_structured_execution_diagnostics(tmp_path) -> None:
    class DiagnosticRunner(FixtureRunner):
        async def compile(self, *args, **kwargs):
            result = await super().compile(*args, **kwargs)
            return replace(
                result,
                execution_diagnostics={
                    "active_phase": "build_function",
                    "failure_operation": "chamfer",
                    "failure_exception_type": "StdFail_NotDone",
                    "failure_message": "BRep_API: command not done",
                },
            )

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    source = valid_mounting_bracket_source()
    runner = DiagnosticRunner(tmp_path)

    with Session(engine) as db:
        project = Project(
            name="Executable diagnostic retry fixture",
            slug="executable-diagnostic-retry-fixture",
            original_intent="Build the frozen mounting bracket.",
        )
        db.add(project)
        db.flush()
        revision = await ProjectService(
            db=db,
            data_dir=tmp_path,
            cad_runner=runner,
        ).create_complete_cadquery_revision(
            project_id=project.id,
            source=source,
            user_instruction="Build the frozen mounting bracket.",
            raw_ai_output='{"complete_source": true}',
            design_plan_payload={
                "printable_outputs": [
                    {
                        "id": "mounting_bracket",
                        "label": "Mounting bracket",
                        "component_id": "mounting_bracket",
                        "component_ids": ["mounting_bracket"],
                        "entrypoint": "mounting_bracket",
                        "filename": "mounting_bracket.stl",
                        "required": True,
                        "expected_solid_count": 1,
                        "allow_disconnected_solids": False,
                    }
                ]
            },
        )
        assert revision is not None
        output = db.scalar(select(RevisionOutput).where(RevisionOutput.revision_id == revision.id))
        assert output is not None
        output.execution_state = "failed"
        db.commit()

        await ProjectService(db=db, data_dir=tmp_path, cad_runner=runner).retry_revision_output(output.id)
        manifest = json.loads((tmp_path / revision.execution_manifest_path).read_text(encoding="utf-8"))

        assert manifest["diagnostics"]["active_phase"] == "build_function"
        assert manifest["diagnostics"]["failure_operation"] == "chamfer"
        assert manifest["diagnostics"]["failure_exception_type"] == "StdFail_NotDone"
