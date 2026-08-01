from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_data_dir
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.project import Project, utcnow
from app.models.workflow import WorkflowRun
from app.services.workflow.observability import WorkflowRecorder

from test_project_api import CADQUERY_MANUAL_SOURCE, FakeCadRunner


def _client(tmp_path: Path) -> TestClient:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)

    def override_db():
        with session_factory() as session:
            yield session

    from app.api.dependencies import get_cad_runner

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_data_dir] = lambda: tmp_path / "data"
    app.dependency_overrides[get_cad_runner] = lambda: FakeCadRunner()
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_workspace_reload_returns_authoritative_project_state(tmp_path: Path) -> None:
    client = _client(tmp_path)
    project = client.post(
        "/api/projects",
        json={"name": "Persistent bracket", "original_intent": "Make a bracket."},
    ).json()
    revision = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={"source": CADQUERY_MANUAL_SOURCE, "user_instruction": "Initial version."},
    ).json()

    response = client.get(f"/api/projects/{project['id']}/workspace")

    assert response.status_code == 200
    workspace = response.json()
    assert workspace["project"]["id"] == project["id"]
    assert workspace["project"]["active_revision_id"] == revision["id"]
    assert workspace["current_working_revision_id"] == revision["id"]
    assert workspace["messages"]
    assert workspace["revisions"][-1]["id"] == revision["id"]
    assert "active_requirements" in workspace
    assert "active_workflow" in workspace
    assert "artifact_integrity" in workspace


def test_startup_recovery_classifies_stale_workflows_without_duplicate_runs(tmp_path: Path) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        project = Project(name="Recovery", slug="recovery", original_intent="Recover me")
        session.add(project)
        session.flush()
        run = WorkflowRecorder(db=session, data_dir=tmp_path / "data").start_run(
            project_id=project.id,
            workflow_type="initial_generation",
        )
        stale_at = utcnow() - timedelta(hours=2)
        run.updated_at = stale_at
        run.started_at = stale_at
        session.commit()
        run_id = run.id

        recovered = WorkflowRecorder(db=session, data_dir=tmp_path / "data").classify_stale_runs(
            max_running_seconds=60,
        )

        assert recovered == 1
        stored = session.get(WorkflowRun, run_id)
        assert stored is not None
        assert stored.status == "abandoned"
        assert stored.completed_at is not None
        assert session.scalar(select(WorkflowRun.id).where(WorkflowRun.id == run_id)) == run_id


def test_workspace_reports_missing_registered_artifacts_instead_of_downloadable_state(tmp_path: Path) -> None:
    client = _client(tmp_path)
    project = client.post(
        "/api/projects",
        json={"name": "Integrity", "original_intent": "Make a printable plate."},
    ).json()
    revision = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={"source": CADQUERY_MANUAL_SOURCE, "user_instruction": "Initial version."},
    ).json()
    stl_path = tmp_path / "data" / "projects" / project["id"] / "revisions" / revision["id"] / "stl" / "body.stl"
    stl_path.unlink()

    workspace = client.get(f"/api/projects/{project['id']}/workspace").json()

    assert workspace["artifact_integrity"]["status"] == "missing"
    assert workspace["artifact_integrity"]["missing_count"] == 1
    assert "body.stl" in workspace["artifact_integrity"]["missing_paths"][0]
