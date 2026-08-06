from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.models.project import Project
from app.models.project_message import ProjectMessage
from app.models.revision import Revision
from app.models.revision_output import RevisionOutput
from app.models.validation_finding import ValidationFinding
from app.models.validated_cadquery_operation import ValidatedCadQueryOperation
from app.models.validated_cadquery_workflow import ValidatedCadQueryWorkflow
from app.schemas.validated_cadquery import ValidatedCadQueryStart
from app.services.projects.output_outcomes import OutputOutcome
from app.services.projects.service import ProjectService
from app.services.validated_cadquery_security import canonical_idempotency_hash
from app.services.validated_cadquery_workflow import ValidatedCadQueryWorkflowService


def _database() -> tuple[object, Session]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def _candidate(
    db: Session,
    data_dir: Path,
    *,
    review_state: str = "ready",
    output_ready: bool = True,
    blocking_finding: bool = False,
) -> tuple[Project, Revision]:
    source = data_dir / "source.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("result = 1\n", encoding="utf-8")
    project = Project(name="Candidate", slug="candidate", original_intent="Candidate fixture")
    db.add(project)
    db.flush()
    revision = Revision(
        project_id=project.id,
        revision_number=1,
        source_type="ai_generated",
        user_instruction="Candidate fixture",
        cad_backend="other",
        source_path="source.py",
        source_contract_version="validated-cadquery-product-v1",
        status="succeeded",
        review_state=review_state,
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
            execution_state="ready" if output_ready else "failed",
            stl_path="body.stl" if output_ready else None,
            required=True,
        )
    )
    if blocking_finding:
        db.add(
            ValidationFinding(
                revision_id=revision.id,
                rule_id="functional.blocked",
                category="functional",
                severity="critical",
                is_blocking=True,
                title="Functional verification blocked",
                explanation="The current candidate has a blocking functional finding.",
                suggested_correction="Resolve the functional finding before acceptance.",
                detected_value="blocked",
                metadata_json="{}",
            )
        )
    db.commit()
    return project, revision


def test_acceptance_uses_one_current_outcome_snapshot_instead_of_stale_review_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _engine, db = _database()
    _project, revision = _candidate(db, tmp_path, review_state="ready", blocking_finding=True)
    service = ProjectService(db=db, data_dir=tmp_path)
    outcomes = iter(
        [
            OutputOutcome(state="candidate_blocked", worker_reached=True, source_valid=True),
            OutputOutcome(state="candidate_ready", worker_reached=True, source_valid=True),
        ]
    )
    monkeypatch.setattr(service, "_revision_output_outcome", lambda _revision_id: next(outcomes))

    with pytest.raises(ValueError, match="candidate state"):
        service.accept_candidate(revision.id)

    db.rollback()
    stored = db.get(Revision, revision.id)
    assert stored is not None
    assert stored.is_accepted is False
    assert db.get(Project, stored.project_id).active_revision_id is None


def test_acceptance_rejects_current_blocking_evidence_even_when_review_state_is_ready(tmp_path: Path) -> None:
    _engine, db = _database()
    project, revision = _candidate(db, tmp_path, review_state="ready", blocking_finding=True)
    service = ProjectService(db=db, data_dir=tmp_path)

    with pytest.raises(ValueError, match="candidate state|blocking"):
        service.accept_candidate(revision.id)

    db.rollback()
    stored = db.get(Revision, revision.id)
    assert stored is not None and stored.is_accepted is False
    assert db.get(Project, project.id).active_revision_id is None


def test_acceptance_is_idempotent_after_first_commit(tmp_path: Path) -> None:
    _engine, db = _database()
    project, revision = _candidate(db, tmp_path, review_state="blocked")
    service = ProjectService(db=db, data_dir=tmp_path)

    first = service.accept_candidate(revision.id)
    assert first is not None
    counts_after_first = tuple(
        db.scalar(select(func.count(model.id)))
        for model in (ProjectMessage,)
    )
    from app.models.workflow import WorkflowEvent, WorkflowRun

    workflow_counts_after_first = (
        db.scalar(select(func.count(WorkflowRun.id))),
        db.scalar(select(func.count(WorkflowEvent.id))),
    )
    second = service.accept_candidate(revision.id)
    assert second is not None
    assert second.id == first.id
    assert counts_after_first == (db.scalar(select(func.count(ProjectMessage.id))),)
    assert workflow_counts_after_first == (
        db.scalar(select(func.count(WorkflowRun.id))),
        db.scalar(select(func.count(WorkflowEvent.id))),
    )
    assert db.get(Project, project.id).active_revision_id == revision.id


def test_acceptance_rolls_back_revision_messages_events_and_workflow_on_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _engine, db = _database()
    project, revision = _candidate(db, tmp_path, review_state="blocked")
    service = ProjectService(db=db, data_dir=tmp_path)

    def inject(_name: str) -> None:
        raise RuntimeError("injected acceptance crash")

    monkeypatch.setattr(service, "_accept_candidate_checkpoint", inject, raising=False)
    with pytest.raises(RuntimeError, match="acceptance crash"):
        service.accept_candidate(revision.id)

    db.rollback()
    stored = db.get(Revision, revision.id)
    assert stored is not None
    assert stored.is_accepted is False
    assert stored.review_state == "blocked"
    assert db.get(Project, project.id).active_revision_id is None
    assert db.scalar(select(func.count(ProjectMessage.id))) == 0

    from app.models.workflow import WorkflowEvent, WorkflowRun

    assert db.scalar(select(func.count(WorkflowRun.id))) == 0
    assert db.scalar(select(func.count(WorkflowEvent.id))) == 0


@pytest.mark.parametrize(
    "checkpoint",
    [
        "after_operation_creation",
        "after_project_flush",
        "after_workflow_flush",
        "after_operation_links",
        "before_commit",
    ],
)
def test_start_design_rolls_back_all_initial_records_at_each_precommit_crash_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    checkpoint: str,
) -> None:
    _engine, db = _database()
    previous = settings.validated_cadquery_flow_enabled
    settings.validated_cadquery_flow_enabled = True

    service = ValidatedCadQueryWorkflowService(db=db, data_dir=tmp_path, owner_id="volundr-single-user")

    def inject(name: str) -> None:
        if name == checkpoint:
            raise RuntimeError(f"injected crash at {name}")

    monkeypatch.setattr(service, "_start_design_checkpoint", inject, raising=False)
    try:
        with pytest.raises(RuntimeError, match=checkpoint):
            asyncio.run(
                service.start_design(
                    ValidatedCadQueryStart(name="Atomic", intent="Create an atomic fixture."),
                    idempotency_key=f"crash-{checkpoint}",
                )
            )
    finally:
        settings.validated_cadquery_flow_enabled = previous

    with Session(_engine) as check:
        assert check.scalar(select(func.count(Project.id))) == 0
        assert check.scalar(select(func.count(ValidatedCadQueryWorkflow.id))) == 0
        assert check.scalar(select(func.count(ValidatedCadQueryOperation.id))) == 0


def test_start_design_retry_after_postcommit_crash_reuses_durable_workflow_without_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, db = _database()
    previous = settings.validated_cadquery_flow_enabled
    settings.validated_cadquery_flow_enabled = True
    first = ValidatedCadQueryWorkflowService(db=db, data_dir=tmp_path, owner_id="volundr-single-user")

    def inject(name: str) -> None:
        if name == "after_commit_before_response":
            raise RuntimeError("injected crash after commit")

    monkeypatch.setattr(first, "_start_design_checkpoint", inject, raising=False)
    try:
        with pytest.raises(RuntimeError, match="after commit"):
            asyncio.run(
                first.start_design(
                    ValidatedCadQueryStart(name="Retryable", intent="Create a retryable fixture."),
                    idempotency_key="postcommit-crash",
                )
            )
    finally:
        settings.validated_cadquery_flow_enabled = previous


    with Session(engine) as check:
        operation = check.scalar(
            select(ValidatedCadQueryOperation).where(
                ValidatedCadQueryOperation.idempotency_key == "postcommit-crash"
            )
        )
        assert operation is not None
        assert operation.project_id is not None
        assert operation.workflow_id is not None
        assert operation.status == "running"
        workflow_id = operation.workflow_id
        assert check.scalar(select(func.count(Project.id))) == 1
        assert check.scalar(select(func.count(ValidatedCadQueryWorkflow.id))) == 1

    class NoProviderCall:
        def set_validated_attempt_recorder(self, _recorder) -> None:
            return None

        def __getattr__(self, name: str):
            raise AssertionError(f"provider call was made during retry: {name}")

    previous = settings.validated_cadquery_flow_enabled
    settings.validated_cadquery_flow_enabled = True
    try:
        with Session(engine) as retry_db:
            retry = ValidatedCadQueryWorkflowService(
                db=retry_db,
                data_dir=tmp_path,
                ai_provider=NoProviderCall(),
                owner_id="volundr-single-user",
            )
            result = asyncio.run(
                retry.start_design(
                    ValidatedCadQueryStart(name="Retryable", intent="Create a retryable fixture."),
                    idempotency_key="postcommit-crash",
                )
            )
            assert result.id == workflow_id
    finally:
        settings.validated_cadquery_flow_enabled = previous


def test_concurrent_same_key_start_design_creates_one_durable_operation_project_and_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "concurrent.db"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    previous = settings.validated_cadquery_flow_enabled
    settings.validated_cadquery_flow_enabled = True
    ready = threading.Barrier(2)

    async def no_requirements(_self, _project_id, _payload):
        return None

    monkeypatch.setattr(ProjectService, "extract_requirements", no_requirements)

    def invoke() -> object:
        ready.wait(timeout=10)
        with Session(engine) as session:
            service = ValidatedCadQueryWorkflowService(
                db=session,
                data_dir=tmp_path,
                owner_id="volundr-single-user",
            )
            return asyncio.run(
                service.start_design(
                    ValidatedCadQueryStart(name="Concurrent", intent="Create one durable workflow."),
                    idempotency_key="concurrent-start",
                )
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(invoke) for _ in range(2)]
            results = []
            for future in futures:
                try:
                    results.append(future.result(timeout=20))
                except Exception:
                    results.append(None)
    finally:
        settings.validated_cadquery_flow_enabled = previous

    with Session(engine) as check:
        assert check.scalar(select(func.count(ValidatedCadQueryOperation.id))) == 1
        assert check.scalar(select(func.count(Project.id))) == 1
        assert check.scalar(select(func.count(ValidatedCadQueryWorkflow.id))) == 1
        operation = check.scalar(
            select(ValidatedCadQueryOperation).where(
                ValidatedCadQueryOperation.idempotency_key == "concurrent-start"
            )
        )
        assert operation is not None
        assert operation.workflow_id is not None
        assert len([result for result in results if result is not None]) <= 2


def test_completed_start_operation_without_workflow_is_rejected(tmp_path: Path) -> None:
    _engine, db = _database()
    operation = ValidatedCadQueryOperation(
        owner_id="volundr-single-user",
        operation_type="start_design",
        idempotency_key="orphaned-completed-start",
        payload_hash=canonical_idempotency_hash(
            "start_design",
            "orphaned-completed-start",
            {"name": "Orphan", "intent": "Reject an orphaned operation."},
        ),
        status="completed",
    )
    db.add(operation)
    db.commit()
    previous = settings.validated_cadquery_flow_enabled
    settings.validated_cadquery_flow_enabled = True
    try:
        service = ValidatedCadQueryWorkflowService(db=db, data_dir=tmp_path, owner_id="volundr-single-user")
        with pytest.raises(ValueError, match="completed operation has no linked workflow"):
            asyncio.run(
                service.start_design(
                    ValidatedCadQueryStart(name="Orphan", intent="Reject an orphaned operation."),
                    idempotency_key="orphaned-completed-start",
                )
            )
    finally:
        settings.validated_cadquery_flow_enabled = previous
