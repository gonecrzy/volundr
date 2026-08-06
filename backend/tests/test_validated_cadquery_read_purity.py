from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.models.project import Project
from app.models.revision import Revision
from app.models.revision_output import RevisionOutput
from app.models.validated_cadquery_workflow import (
    ValidatedCadQueryOutput,
    ValidatedCadQueryWorkflow,
)
from app.services.validated_cadquery_workflow import ValidatedCadQueryWorkflowService


def _database() -> tuple[object, Session]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def _workflow_fixture(
    db: Session,
    *,
    state: str = "worker_running",
    routing_state: str = "selected",
    with_missing_artifact: bool = False,
) -> ValidatedCadQueryWorkflow:
    project = Project(name="Workflow", slug="workflow", original_intent="Workflow fixture")
    db.add(project)
    db.flush()
    revision = None
    if with_missing_artifact:
        revision = Revision(
            project_id=project.id,
            revision_number=1,
            source_type="ai_generated",
            cad_backend="other",
            source_path="source.py",
            status="succeeded",
            review_state="accepted",
        )
        db.add(revision)
        db.flush()
        db.add(
            RevisionOutput(
                revision_id=revision.id,
                output_id="body",
                label="Body",
                filename="body.stl",
                entrypoint="body",
                execution_state="ready",
                stl_path="missing.stl",
                stl_hash="missing-hash",
                step_path="missing.step",
                step_hash="missing-step-hash",
                required=True,
            )
        )
    workflow = ValidatedCadQueryWorkflow(
        project_id=project.id,
        owner_id="volundr-single-user",
        revision_id=revision.id if revision is not None else None,
        state=state,
        routing_state=routing_state,
        route="validated-cadquery-v1",
        user_instruction="Workflow fixture",
    )
    db.add(workflow)
    db.flush()
    if revision is not None:
        db.add(
            ValidatedCadQueryOutput(
                workflow_id=workflow.id,
                output_id="body",
                revision_output_id=revision.outputs[0].id,
                required=True,
                generation_status="completed",
                worker_status="succeeded",
                state="completed",
                artifact_available=True,
            )
        )
    db.commit()
    return workflow


def test_validated_workflow_read_verification_and_metadata_gets_are_side_effect_free(tmp_path: Path) -> None:
    engine, db = _database()
    workflow = _workflow_fixture(db)
    previous = settings.validated_cadquery_flow_enabled
    settings.validated_cadquery_flow_enabled = False
    try:
        service = ValidatedCadQueryWorkflowService(db=db, data_dir=tmp_path, owner_id="volundr-single-user")
        with Session(engine) as check:
            stored = check.get(ValidatedCadQueryWorkflow, workflow.id)
            before = (stored.state, stored.routing_state, stored.state_version, stored.diagnostics_json)

        service.read(workflow.id)
        service.verification(workflow.id)
        service.requirements(workflow.id)
        service.plan(workflow.id)

        with Session(engine) as check:
            stored = check.get(ValidatedCadQueryWorkflow, workflow.id)
            after = (stored.state, stored.routing_state, stored.state_version, stored.diagnostics_json)
        assert after == before
    finally:
        settings.validated_cadquery_flow_enabled = previous


def test_validated_artifact_listing_does_not_reconcile_missing_files_into_database(tmp_path: Path) -> None:
    engine, db = _database()
    workflow = _workflow_fixture(db, state="candidate_ready", with_missing_artifact=True)
    previous = settings.validated_cadquery_flow_enabled
    settings.validated_cadquery_flow_enabled = True
    try:
        service = ValidatedCadQueryWorkflowService(db=db, data_dir=tmp_path, owner_id="volundr-single-user")
        with Session(engine) as check:
            before_workflow = check.get(ValidatedCadQueryWorkflow, workflow.id)
            before_output = check.scalar(
                select(ValidatedCadQueryOutput).where(ValidatedCadQueryOutput.workflow_id == workflow.id)
            )
            before = (
                before_workflow.state,
                before_workflow.state_version,
                before_workflow.diagnostics_json,
                before_output.artifact_available,
                before_output.state,
            )

        artifacts = service.artifacts(workflow.id)
        assert artifacts
        assert all(item.available is False for item in artifacts if item.kind in {"stl", "step"})

        with Session(engine) as check:
            after_workflow = check.get(ValidatedCadQueryWorkflow, workflow.id)
            after_output = check.scalar(
                select(ValidatedCadQueryOutput).where(ValidatedCadQueryOutput.workflow_id == workflow.id)
            )
            after = (
                after_workflow.state,
                after_workflow.state_version,
                after_workflow.diagnostics_json,
                after_output.artifact_available,
                after_output.state,
            )
        assert after == before
    finally:
        settings.validated_cadquery_flow_enabled = previous
