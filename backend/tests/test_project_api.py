from collections.abc import Generator
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
import trimesh

from app.api.dependencies import get_cad_runner, get_data_dir
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.project import Project, utcnow
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

        mesh = trimesh.creation.box(extents=(10.0, 20.0, 30.0))
        mesh.apply_translation([0.0, 0.0, 15.0])
        mesh.export(stl_path)
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
            output_size_bytes=stl_path.stat().st_size,
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


def test_revision_printability_endpoint_returns_profiled_findings(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    project = client.post(
        "/api/projects",
        json={
            "name": "Printable box",
            "original_intent": "Create a box for printability inspection.",
        },
    ).json()
    revision = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={
            "scad_source": "cube([10, 20, 30]);",
            "user_instruction": "Initial manual model.",
        },
    ).json()

    response = client.post(
        f"/api/revisions/{revision['id']}/printability",
        json={
            "printer_name": "Bambu Lab H2C",
            "build_volume": {"x_mm": 325, "y_mm": 320, "z_mm": 320},
            "nozzle_diameter_mm": 0.4,
            "default_layer_height_mm": 0.2,
        },
    )

    assert response.status_code == 200
    report = response.json()
    assert "score" not in report
    assert report["profile"]["printer_name"] == "Bambu Lab H2C"
    assert report["profile_version"] == "printability-fdm-v1"
    rule_ids = {result["rule_id"] for result in report["results"]}
    assert {
        "mesh.empty_or_zero_volume",
        "mesh.non_watertight",
        "orientation.overhangs",
        "orientation.bridge_spans",
        "profile.build_volume",
    }.issubset(rule_ids)
    build_volume = next(result for result in report["results"] if result["rule_id"] == "profile.build_volume")
    assert build_volume["severity"] == "Pass"
    for result in report["results"]:
        assert set(
            [
                "severity",
                "rule_id",
                "detected_value",
                "affected_count",
                "affected_area_mm2",
                "explanation",
                "suggested_correction",
                "orientation_dependent",
                "dismissed",
                "highlight",
            ]
        ).issubset(result)


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


def test_draft_project_is_hidden_from_project_list_and_can_compile(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    draft_response = client.post("/api/projects/draft")

    assert draft_response.status_code == 201
    draft = draft_response.json()
    assert draft["status"] == "draft"
    assert draft["name"].startswith("Draft ")
    assert draft["original_intent"] == ""

    list_response = client.get("/api/projects")
    assert list_response.status_code == 200
    assert list_response.json() == []

    revision_response = client.post(
        f"/api/projects/{draft['id']}/revisions",
        json={
            "scad_source": "cube([10, 20, 30]);",
            "user_instruction": None,
        },
    )

    assert revision_response.status_code == 201
    revision = revision_response.json()
    assert revision["project_id"] == draft["id"]
    assert revision["status"] == "succeeded"


def test_draft_project_can_be_saved_as_active_project(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    draft = client.post("/api/projects/draft").json()

    response = client.post(
        f"/api/projects/{draft['id']}/save",
        json={
            "name": "Saved bracket",
            "original_intent": "Keep this bracket.",
        },
    )

    assert response.status_code == 200
    saved = response.json()
    assert saved["status"] == "active"
    assert saved["name"] == "Saved bracket"
    assert saved["original_intent"] == "Keep this bracket."

    projects = client.get("/api/projects").json()
    assert [project["id"] for project in projects] == [draft["id"]]


def test_old_draft_projects_are_cleaned_after_fourteen_days(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    current_draft = client.post("/api/projects/draft").json()

    with next(app.dependency_overrides[get_db]()) as session:
        old_draft = Project(
            name="Draft old",
            slug="draft-old",
            original_intent="",
            status="draft",
            created_at=utcnow() - timedelta(days=15),
            updated_at=utcnow() - timedelta(days=15),
        )
        session.add(old_draft)
        session.commit()
        old_draft_id = old_draft.id

    list_response = client.get("/api/projects")

    assert list_response.status_code == 200
    with next(app.dependency_overrides[get_db]()) as session:
        assert session.get(Project, old_draft_id) is None
        assert session.get(Project, current_draft["id"]) is not None


def test_project_messages_record_project_and_revision_events(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    project = client.post(
        "/api/projects",
        json={
            "name": "Message ledger",
            "original_intent": "Create a traceable project.",
        },
    ).json()

    revision = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={
            "scad_source": "cube([10, 20, 30]);",
            "user_instruction": "Initial traceable model.",
        },
    ).json()

    response = client.get(f"/api/projects/{project['id']}/messages")

    assert response.status_code == 200
    messages = response.json()
    assert [(entry["role"], entry["content"]) for entry in messages] == [
        ("user", "Create a traceable project."),
        ("system_event", "Project created"),
        ("user", "Initial traceable model."),
        ("system_event", "Revision R1 succeeded"),
    ]
    assert messages[2]["revision_id"] == revision["id"]
    assert messages[3]["revision_id"] == revision["id"]


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


def test_revision_diff_compares_revision_to_parent(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    project = client.post(
        "/api/projects",
        json={
            "name": "Diffable",
            "original_intent": "Create a diffable model.",
        },
    ).json()
    first_revision = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={
            "scad_source": "module main_model() {\n  cube([10, 10, 10]);\n}\nmain_model();\n",
            "user_instruction": "Initial cube.",
        },
    ).json()
    second_revision = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={
            "scad_source": "module main_model() {\n  cube([20, 10, 10]);\n}\nmain_model();\n",
            "user_instruction": "Make it wider.",
        },
    ).json()

    response = client.get(f"/api/revisions/{second_revision['id']}/diff")

    assert response.status_code == 200
    assert response.text.splitlines() == [
        f"--- R{first_revision['revision_number']}",
        f"+++ R{second_revision['revision_number']}",
        "@@ -1,4 +1,4 @@",
        " module main_model() {",
        "-  cube([10, 10, 10]);",
        "+  cube([20, 10, 10]);",
        " }",
        " main_model();",
    ]
