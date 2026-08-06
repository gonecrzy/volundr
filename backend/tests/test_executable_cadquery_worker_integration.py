from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.project import Project
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
