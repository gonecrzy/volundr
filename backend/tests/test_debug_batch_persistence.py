from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.debug_batch import DebugBatch, DebugBatchMembership
from app.models.project import Project


def _batch(label: str, *, state: str = "active") -> DebugBatch:
    now = datetime.now(timezone.utc)
    return DebugBatch(
        label=label,
        notes=None,
        target_project_count=5,
        state=state,
        git_head="abc123",
        branch="main",
        migration_head="0027_export_records",
        application_version="app-1",
        frontend_build_identity="frontend-1",
        backend_build_identity="backend-1",
        worker_build_identity="worker-1",
        provider="gemini_api",
        configured_default_model="gemini-3.5-flash-lite",
        stage_model_policy_json="{}",
        actual_provider_models_json="{}",
        prompt_versions_json="{}",
        configuration_hash="config-hash",
        started_at=now,
        evidence_contract_version="debug-batch-v1",
        comparison_status="not_applicable",
        redaction_status="pending",
        integrity_status="pending",
    )


def test_debug_batch_tables_store_identity_and_ordered_membership() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    assert {"debug_batches", "debug_batch_memberships"}.issubset(inspector.get_table_names())

    with Session(engine) as session:
        batch = _batch("live-01")
        first = Project(name="First", slug="first", original_intent="first")
        second = Project(name="Second", slug="second", original_intent="second")
        session.add_all([batch, first, second])
        session.flush()
        session.add_all(
            [
                DebugBatchMembership(batch_id=batch.id, project_id=second.id, position=1),
                DebugBatchMembership(batch_id=batch.id, project_id=first.id, position=0),
            ]
        )
        session.commit()

        stored = session.get(DebugBatch, batch.id)
        assert stored is not None
        assert stored.state == "active"
        assert stored.configuration_hash == "config-hash"
        members = session.query(DebugBatchMembership).filter_by(batch_id=batch.id).order_by(
            DebugBatchMembership.position
        ).all()
        assert [member.project_id for member in members] == [first.id, second.id]


def test_only_one_active_or_finishing_batch_can_exist() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(_batch("live-01"))
        session.commit()
        session.add(_batch("live-02"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_project_cannot_be_assigned_to_two_batches() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        first_batch = _batch("live-01", state="frozen")
        second_batch = _batch("live-02")
        project = Project(name="Project", slug="project", original_intent="project")
        session.add_all([first_batch, second_batch, project])
        session.flush()
        session.add(DebugBatchMembership(batch_id=first_batch.id, project_id=project.id, position=0))
        session.commit()
        session.add(DebugBatchMembership(batch_id=second_batch.id, project_id=project.id, position=0))
        with pytest.raises(IntegrityError):
            session.commit()
