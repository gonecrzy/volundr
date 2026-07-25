from collections.abc import Generator
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_cad_runner, get_data_dir
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.services.cad.runner import CadCompileResult
from app.services.mesh.inspect import MeshMetadata


class FakeCadRunner:
    async def compile(self, source: str, job_id: str) -> CadCompileResult:
        job_dir = Path("/tmp") / "volundr-fake-jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        source_path = job_dir / "model.scad"
        stl_path = job_dir / "model.stl"
        stdout_path = job_dir / "stdout.log"
        stderr_path = job_dir / "stderr.log"
        metadata_path = job_dir / "metadata.json"
        source_path.write_text(source, encoding="utf-8")
        stdout_path.write_text("", encoding="utf-8")

        if "broken" in source:
            stderr_path.write_text("Parser error", encoding="utf-8")
            return CadCompileResult(
                job_id=job_id,
                success=False,
                timed_out=False,
                exit_code=1,
                source_path=source_path,
                stl_path=None,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                metadata_path=None,
                source_hash="fake-source-hash",
                output_size_bytes=0,
                metadata=None,
                error_message="Parser error",
            )

        stl_path.write_bytes(b"solid fake\nendsolid fake\n")
        stderr_path.write_text("Compilation finished", encoding="utf-8")
        metadata = MeshMetadata(
            size_x_mm=10.0,
            size_y_mm=20.0,
            size_z_mm=30.0,
            volume_mm3=6000.0,
            triangle_count=12,
            connected_components=1,
            is_watertight=True,
            is_winding_consistent=True,
            center_of_mass=(5.0, 10.0, 15.0),
        )
        metadata_path.write_text('{"triangle_count": 12}', encoding="utf-8")
        return CadCompileResult(
            job_id=job_id,
            success=True,
            timed_out=False,
            exit_code=0,
            source_path=source_path,
            stl_path=stl_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            metadata_path=metadata_path,
            source_hash="fake-source-hash",
            output_size_bytes=24,
            metadata=metadata,
            error_message=None,
        )


def build_client(tmp_path: Path) -> TestClient:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)

    def override_db() -> Generator[Session, None, None]:
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_data_dir] = lambda: tmp_path / "data"
    app.dependency_overrides[get_cad_runner] = lambda: FakeCadRunner()
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_create_project_and_compile_successful_manual_revision(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    project_response = client.post(
        "/api/projects",
        json={
            "name": "Mounting bracket",
            "original_intent": "Create a simple mounting bracket.",
        },
    )

    assert project_response.status_code == 201
    project = project_response.json()
    assert project["name"] == "Mounting bracket"
    assert project["active_revision_id"] is None

    revision_response = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={
            "scad_source": "cube([10, 20, 30]);",
            "user_instruction": "Initial manual model.",
        },
    )

    assert revision_response.status_code == 201
    revision = revision_response.json()
    assert revision["status"] == "succeeded"
    assert revision["is_accepted"] is True
    assert revision["metadata"]["triangle_count"] == 12
    assert revision["metadata"]["size_z_mm"] == 30.0

    refreshed_project = client.get(f"/api/projects/{project['id']}").json()
    assert refreshed_project["active_revision_id"] == revision["id"]

    revision_dir = tmp_path / "data" / "projects" / project["id"] / "revisions" / revision["id"]
    assert (revision_dir / "model.scad").read_text(encoding="utf-8") == "cube([10, 20, 30]);"
    assert (revision_dir / "model.stl").exists()
    assert (revision_dir / "compile.log").read_text(encoding="utf-8") == "Compilation finished"
    assert (revision_dir / "metadata.json").exists()

    source_response = client.get(f"/api/revisions/{revision['id']}/source")
    assert source_response.status_code == 200
    assert source_response.text == "cube([10, 20, 30]);"

    revisions_response = client.get(f"/api/projects/{project['id']}/revisions")
    assert revisions_response.status_code == 200
    revisions = revisions_response.json()
    assert revisions[0]["metadata"]["triangle_count"] == 12


def test_project_can_be_renamed(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    project = client.post(
        "/api/projects",
        json={
            "name": "Draft fixture",
            "original_intent": "Create a fixture.",
        },
    ).json()

    response = client.patch(
        f"/api/projects/{project['id']}",
        json={"name": "Final fixture"},
    )

    assert response.status_code == 200
    renamed = response.json()
    assert renamed["name"] == "Final fixture"
    assert renamed["slug"] == "final-fixture"
    assert renamed["original_intent"] == "Create a fixture."


def test_archived_project_is_hidden_from_default_project_list(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    kept_project = client.post(
        "/api/projects",
        json={
            "name": "Keep",
            "original_intent": "Keep this project.",
        },
    ).json()
    archived_project = client.post(
        "/api/projects",
        json={
            "name": "Archive",
            "original_intent": "Archive this project.",
        },
    ).json()

    archive_response = client.post(f"/api/projects/{archived_project['id']}/archive")

    assert archive_response.status_code == 200
    archived = archive_response.json()
    assert archived["status"] == "archived"
    assert archived["archived_at"] is not None

    list_response = client.get("/api/projects")
    assert list_response.status_code == 200
    projects = list_response.json()
    assert [project["id"] for project in projects] == [kept_project["id"]]


def test_failed_manual_revision_does_not_replace_active_revision(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    project = client.post(
        "/api/projects",
        json={
            "name": "Spacer",
            "original_intent": "Create a spacer.",
        },
    ).json()
    first_revision = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={
            "scad_source": "cube([10, 10, 10]);",
            "user_instruction": "Initial manual model.",
        },
    ).json()

    failed_response = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={
            "scad_source": "broken(",
            "user_instruction": "Bad manual edit.",
        },
    )

    assert failed_response.status_code == 201
    failed_revision = failed_response.json()
    assert failed_revision["status"] == "failed"
    assert failed_revision["is_accepted"] is False
    assert failed_revision["error_message"] == "Parser error"

    refreshed_project = client.get(f"/api/projects/{project['id']}").json()
    assert refreshed_project["active_revision_id"] == first_revision["id"]

    log_response = client.get(f"/api/revisions/{failed_revision['id']}/compile-log")
    assert log_response.status_code == 200
    assert log_response.text == "Parser error"


def test_successful_revision_can_be_restored_as_active(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    project = client.post(
        "/api/projects",
        json={
            "name": "Handle",
            "original_intent": "Create a simple handle.",
        },
    ).json()
    first_revision = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={
            "scad_source": "cube([10, 10, 10]);",
            "user_instruction": "Initial manual model.",
        },
    ).json()
    second_revision = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={
            "scad_source": "cube([20, 10, 10]);",
            "user_instruction": "Wider handle.",
        },
    ).json()
    assert second_revision["is_accepted"] is True

    restore_response = client.post(f"/api/revisions/{first_revision['id']}/restore")

    assert restore_response.status_code == 200
    restored_project = restore_response.json()
    assert restored_project["active_revision_id"] == first_revision["id"]

    source_response = client.get(f"/api/revisions/{first_revision['id']}/source")
    assert source_response.headers["content-disposition"].endswith('filename="model.scad"')
