import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_cad_runner, get_data_dir
from app.db.base import Base
from app.db.session import get_db
from app.main import app

from test_project_api import CADQUERY_MANUAL_SOURCE, FakeCadRunner


def _client(tmp_path: Path) -> TestClient:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)

    def override_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_data_dir] = lambda: tmp_path / "data"
    app.dependency_overrides[get_cad_runner] = lambda: FakeCadRunner()
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def _revision(client: TestClient) -> tuple[dict, dict]:
    project = client.post(
        "/api/projects",
        json={"name": "Bracket / final", "original_intent": "Make a printable bracket."},
    ).json()
    revision = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={"source": CADQUERY_MANUAL_SOURCE, "user_instruction": "Initial version."},
    ).json()
    return project, revision


def test_selected_stl_export_has_deterministic_name_and_persisted_record(tmp_path: Path) -> None:
    client = _client(tmp_path)
    project, revision = _revision(client)

    response = client.post(
        f"/api/projects/{project['id']}/exports",
        json={"export_type": "stl", "revision_id": revision["id"], "output_id": "body"},
    )

    assert response.status_code == 201
    export = response.json()
    assert export["status"] == "completed"
    assert export["filename"] == "bracket-final_body_r1.stl"
    assert export["sha256"]
    assert export["revision_id"] == revision["id"]
    downloaded = client.get(f"/api/exports/{export['id']}/download")
    assert downloaded.status_code == 200
    assert downloaded.headers["content-disposition"].endswith('filename="bracket-final_body_r1.stl"')
    assert len(downloaded.content) > 0

    listed = client.get(f"/api/projects/{project['id']}/exports").json()
    assert [entry["id"] for entry in listed] == [export["id"]]


def test_project_package_contains_manifest_history_and_no_provider_secret(tmp_path: Path) -> None:
    client = _client(tmp_path)
    project, revision = _revision(client)

    response = client.post(
        f"/api/projects/{project['id']}/exports",
        json={"export_type": "project_package", "revision_id": revision["id"]},
    )

    assert response.status_code == 201
    export = response.json()
    downloaded = client.get(f"/api/exports/{export['id']}/download")
    package_path = tmp_path / "project.zip"
    package_path.write_bytes(downloaded.content)
    with zipfile.ZipFile(package_path) as package:
        names = set(package.namelist())
        assert "project.json" in names
        assert "requirements.json" in names
        assert "requirement-history.json" in names
        assert "revision-history.json" in names
        assert "verification-summary.json" in names
        manifest = json.loads(package.read("manifest.json"))
        assert manifest["project_id"] == project["id"]
        assert manifest["revision_id"] == revision["id"]
        assert all("GEMINI_API_KEY" not in package.read(name).decode("utf-8", "ignore") for name in names)


def test_blocked_revision_cannot_be_exported_as_a_successful_design(tmp_path: Path) -> None:
    client = _client(tmp_path)
    project, revision = _revision(client)
    blocked_revision = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={"source": CADQUERY_MANUAL_SOURCE.replace("body =", "broken body ="), "user_instruction": "Broken."},
    )
    assert blocked_revision.status_code == 201

    response = client.post(
        f"/api/projects/{project['id']}/exports",
        json={"export_type": "project_package", "revision_id": blocked_revision.json()["id"]},
    )

    assert response.status_code in {409, 422}
    assert "successful" in response.json()["detail"].lower()
    assert client.get(f"/api/projects/{project['id']}").json()["active_revision_id"] == revision["id"]

