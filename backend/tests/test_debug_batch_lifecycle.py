from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.debug_batch import DebugBatch, DebugBatchMembership
from app.models.project import Project
from app.schemas.debug_batch import DebugBatchStart
from app.schemas.project import ProjectCreate
from app.services.debug_batches.service import DebugBatchService
from app.services.projects.service import ProjectService


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_start_trims_label_and_captures_immutable_identity(tmp_path) -> None:
    with _session() as session:
        batch = DebugBatchService(db=session, data_dir=tmp_path).start(
            DebugBatchStart(label="  live-01  ", target_project_count=5, notes="notes")
        )

        assert batch.label == "live-01"
        assert batch.notes == "notes"
        assert batch.state == "active"
        assert batch.git_head
        assert batch.migration_head
        assert batch.provider
        assert batch.configuration_hash


def test_project_creation_and_membership_are_transactional(tmp_path) -> None:
    with _session() as session:
        DebugBatchService(db=session, data_dir=tmp_path).start(
            DebugBatchStart(label="live-01", target_project_count=5)
        )

        project = ProjectService(db=session, data_dir=tmp_path).create_project(
            ProjectCreate(name="New project", original_intent="Make a thing")
        )

        membership = session.scalar(
            select(DebugBatchMembership).where(DebugBatchMembership.project_id == project.id)
        )
        assert membership is not None
        assert membership.position == 0


def test_existing_project_does_not_join_a_later_batch(tmp_path) -> None:
    with _session() as session:
        project = ProjectService(db=session, data_dir=tmp_path).create_project(
            ProjectCreate(name="Old project", original_intent="Old")
        )
        DebugBatchService(db=session, data_dir=tmp_path).start(
            DebugBatchStart(label="live-01", target_project_count=5)
        )

        assert session.scalar(
            select(DebugBatchMembership).where(DebugBatchMembership.project_id == project.id)
        ) is None


def test_finish_is_idempotent_and_freezes_membership(tmp_path) -> None:
    with _session() as session:
        service = DebugBatchService(db=session, data_dir=tmp_path)
        batch = service.start(DebugBatchStart(label="live-01", target_project_count=5))
        finished = service.finish(batch.id)
        repeated = service.finish(batch.id)

        assert finished.state == "frozen"
        assert repeated.state == "frozen"
        assert repeated.finished_at == finished.finished_at
        assert session.scalar(select(DebugBatch).where(DebugBatch.state == "active")) is None


def test_frozen_batch_cannot_accept_membership(tmp_path) -> None:
    with _session() as session:
        service = DebugBatchService(db=session, data_dir=tmp_path)
        batch = service.start(DebugBatchStart(label="live-01", target_project_count=5))
        service.finish(batch.id)
        project = Project(name="Late", slug="late", original_intent="Late")
        session.add(project)
        session.flush()

        assert service.attach_new_project(project) is None
        assert session.scalar(
            select(DebugBatchMembership).where(DebugBatchMembership.project_id == project.id)
        ) is None
