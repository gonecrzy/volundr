import json
from collections.abc import Generator
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_data_dir
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.debug_batch import DebugBatch, DebugBatchMembership
from app.schemas.debug_batch import DebugBatchStart
from app.services.debug_batches.reports import DebugBatchReportService
from app.services.debug_batches.service import DebugBatchService


def _client(tmp_path: Path) -> TestClient:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)

    def override_db() -> Generator[Session, None, None]:
        with session_local() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_data_dir] = lambda: tmp_path / "data"
    app.state.debug_batch_session_local = session_local
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()
    if hasattr(app.state, "debug_batch_session_local"):
        del app.state.debug_batch_session_local


def test_frontend_evidence_is_bounded_and_redacted(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "developer_tools_enabled", True)
    client = _client(tmp_path)
    batch = client.post("/api/debug-batches", json={"label": "live-01"}).json()

    response = client.post(
        f"/api/debug-batches/{batch['id']}/frontend-events",
        json={
            "events": [
                {
                    "event_type": "network_failure",
                    "safe_endpoint_path": "/api/projects/project-1",
                    "project_id": "project-1",
                    "workflow_id": "workflow-1",
                    "http_status": 502,
                    "occurred_at": "2026-08-03T00:00:00Z",
                }
            ]
        },
    )

    assert response.status_code == 201
    event_path = tmp_path / "data" / "debug-sessions" / batch["id"] / "frontend" / "events.ndjson"
    assert event_path.exists()
    payload = json.loads(event_path.read_text(encoding="utf-8").strip())
    assert payload["safe_endpoint_path"] == "/api/projects/project-1"
    assert "authorization" not in payload
    assert "cookie" not in payload


def test_failed_report_can_be_regenerated_without_membership_changes(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        service = DebugBatchService(db=session, data_dir=data_dir)
        batch = service.start(DebugBatchStart(label="live-01", target_project_count=1))
        batch.state = "failed"
        session.commit()
        before = [member.project_id for member in batch.memberships]

        DebugBatchReportService(db=session, data_dir=data_dir).generate(batch.id)
        DebugBatchReportService(db=session, data_dir=data_dir).generate(batch.id)

        session.refresh(batch)
        after = [member.project_id for member in batch.memberships]
        assert after == before
        assert batch.report_generation_state == "generated"


def test_finish_generates_report_before_freezing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "developer_tools_enabled", True)
    client = _client(tmp_path)
    batch = client.post("/api/debug-batches", json={"label": "live-01"}).json()

    finished = client.post(f"/api/debug-batches/{batch['id']}/finish")

    assert finished.status_code == 200
    payload = finished.json()
    assert payload["state"] == "frozen"
    assert payload["report_generation_state"] == "generated"
    assert (tmp_path / "data" / "debug-sessions" / batch["id"] / "report.json").exists()
