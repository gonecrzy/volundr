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
from app.models.revision import Revision
from app.services.cad.cadquery_runner import CadQueryCompileResult, CadQueryOutputResult
from app.services.mesh.inspect import MeshMetadata


CADQUERY_MANUAL_SOURCE = """
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product

PARAMETERS = [
    ParameterSpec(id="width", label="Width", type="float", default=10.0, unit="mm"),
    ParameterSpec(id="depth", label="Depth", type="float", default=20.0, unit="mm"),
    ParameterSpec(id="height", label="Height", type="float", default=30.0, unit="mm"),
]


def build(params):
    body = cq.Workplane("XY").box(params["width"], params["depth"], params["height"])
    return Product(
        parameters=PARAMETERS,
        outputs=[
            PrintableOutput(
                output_id="body",
                label="Body",
                component_id="body",
                component_ids=("body",),
                model=body,
                expected_solid_count=1,
                allow_disconnected_solids=False,
            )
        ],
    )
"""

CADQUERY_WIDE_SOURCE = CADQUERY_MANUAL_SOURCE.replace(
    'ParameterSpec(id="width", label="Width", type="float", default=10.0',
    'ParameterSpec(id="width", label="Width", type="float", default=20.0',
)


class FakeCadRunner:
    async def compile(
        self,
        source: str,
        job_id: str,
        *,
        parameter_values: dict | None = None,
        requested_outputs: list[dict] | None = None,
    ) -> CadQueryCompileResult:
        job_dir = Path("/tmp") / "volundr-fake-jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        output_id = requested_outputs[0]["output_id"] if requested_outputs else "body"
        source_path = job_dir / "model.py"
        stl_path = job_dir / f"{output_id}.stl"
        step_path = job_dir / f"{output_id}.step"
        brep_path = job_dir / f"{output_id}.brep"
        stdout_path = job_dir / "stdout.log"
        stderr_path = job_dir / "stderr.log"
        metadata_path = job_dir / "metadata.json"
        topology_path = job_dir / "topology.json"
        execution_manifest_path = job_dir / "result.json"
        source_path.write_text(source, encoding="utf-8")
        stdout_path.write_text("", encoding="utf-8")

        if "broken" in source:
            stderr_path.write_text("Parser error", encoding="utf-8")
            return CadQueryCompileResult(
                job_id=job_id,
                success=False,
                timed_out=False,
                exit_code=1,
                source_path=source_path,
                stl_path=None,
                step_path=None,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                metadata_path=None,
                source_hash="fake-cadquery-source-hash",
                output_size_bytes=0,
                metadata=None,
                error_message="Parser error",
                outputs=[],
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
        step_path.write_text("STEP", encoding="utf-8")
        brep_path.write_text("BREP", encoding="utf-8")
        topology_path.write_text(
            '{"valid": true, "expected_solid_count": 1, "detected_solid_count": 1, '
            '"allow_disconnected_solids": false}',
            encoding="utf-8",
        )
        execution_manifest_path.write_text('{"success": true}', encoding="utf-8")
        output = CadQueryOutputResult(
            output_id=output_id,
            entrypoint=output_id,
            required=bool((requested_outputs or [{"required": True}])[0].get("required", True)),
            success=True,
            stl_path=stl_path,
            step_path=step_path,
            brep_path=brep_path,
            metadata_path=metadata_path,
            topology_metadata_path=topology_path,
            stl_hash="1" * 64,
            step_hash="2" * 64,
            brep_hash="3" * 64,
            output_size_bytes=stl_path.stat().st_size,
            metadata=metadata,
            topology_metadata={
                "valid": True,
                "expected_solid_count": 1,
                "detected_solid_count": 1,
                "allow_disconnected_solids": False,
            },
        )
        result = CadQueryCompileResult(
            job_id=job_id,
            success=True,
            timed_out=False,
            exit_code=0,
            source_path=source_path,
            stl_path=stl_path,
            step_path=step_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            metadata_path=metadata_path,
            source_hash="fake-cadquery-source-hash",
            output_size_bytes=stl_path.stat().st_size,
            metadata=metadata,
            error_message=None,
            command_args=["python", "_volundr_cadquery_runner.py"],
            outputs=[output],
        )
        object.__setattr__(result, "execution_manifest_path", execution_manifest_path)
        return result


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
            "source": CADQUERY_MANUAL_SOURCE,
            "user_instruction": "Initial manual model.",
        },
    )

    assert revision_response.status_code == 201
    revision = revision_response.json()
    assert revision["status"] == "succeeded"
    assert revision["is_accepted"] is True
    assert revision["cad_backend"] == "cadquery"
    assert revision["source_language"] == "python"
    assert revision["source_contract_version"] == "cadquery-v1"
    assert revision["execution_manifest_path"] == f"projects/{project['id']}/revisions/{revision['id']}/execution-result.json"
    assert revision["expected_output_count"] == 1
    assert revision["successful_output_count"] == 1
    assert revision["metadata"]["triangle_count"] == 12
    assert revision["metadata"]["size_z_mm"] == 30.0

    refreshed_project = client.get(f"/api/projects/{project['id']}").json()
    assert refreshed_project["active_revision_id"] == revision["id"]

    revision_dir = tmp_path / "data" / "projects" / project["id"] / "revisions" / revision["id"]
    assert (revision_dir / "source.py").read_text(encoding="utf-8") == CADQUERY_MANUAL_SOURCE
    assert (revision_dir / "stl" / "body.stl").exists()
    assert (revision_dir / "step" / "body.step").exists()
    assert (revision_dir / "brep" / "body.brep").exists()
    assert (revision_dir / "execution-result.json").exists()
    assert (revision_dir / "logs" / "cadquery.log").read_text(encoding="utf-8") == "Compilation finished"
    assert (revision_dir / "metadata" / "body.metadata.json").exists()

    source_response = client.get(f"/api/revisions/{revision['id']}/source")
    assert source_response.status_code == 200
    assert source_response.text == CADQUERY_MANUAL_SOURCE

    revisions_response = client.get(f"/api/projects/{project['id']}/revisions")
    assert revisions_response.status_code == 200
    revisions = revisions_response.json()
    assert revisions[0]["metadata"]["triangle_count"] == 12


def test_manual_revision_rejects_unknown_source_field(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    project = client.post(
        "/api/projects",
        json={
            "name": "Fish bracket",
            "original_intent": "Create a styled shelf bracket.",
        },
    ).json()
    response = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={
            "source_code": "import cadquery as cq",
            "user_instruction": "Initial manual model.",
        },
    )

    assert response.status_code == 422


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
            "source": CADQUERY_MANUAL_SOURCE,
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
            "source": CADQUERY_MANUAL_SOURCE,
            "user_instruction": None,
        },
    )

    assert revision_response.status_code == 201
    revision = revision_response.json()
    assert revision["project_id"] == draft["id"]
    assert revision["status"] == "succeeded"


def test_manual_revision_rejects_blank_source(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    draft = client.post("/api/projects/draft").json()

    response = client.post(
        f"/api/projects/{draft['id']}/revisions",
        json={
            "source": "   \n\t",
            "user_instruction": None,
        },
    )

    assert response.status_code == 422


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
    old_draft = client.post("/api/projects/draft").json()
    old_draft_revision = client.post(
        f"/api/projects/{old_draft['id']}/revisions",
        json={
            "source": CADQUERY_MANUAL_SOURCE,
            "user_instruction": None,
        },
    ).json()

    with next(app.dependency_overrides[get_db]()) as session:
        stored_old_draft = session.get(Project, old_draft["id"])
        assert stored_old_draft is not None
        stored_old_draft.created_at = utcnow() - timedelta(days=15)
        stored_old_draft.updated_at = utcnow() - timedelta(days=15)
        session.commit()
        old_draft_id = stored_old_draft.id
    old_project_dir = tmp_path / "data" / "projects" / old_draft_id

    assert old_project_dir.exists()

    list_response = client.get("/api/projects")

    assert list_response.status_code == 200
    with next(app.dependency_overrides[get_db]()) as session:
        assert session.get(Project, old_draft_id) is None
        assert session.get(Revision, old_draft_revision["id"]) is None
        assert session.get(Project, current_draft["id"]) is not None
    assert not old_project_dir.exists()


def test_project_can_be_deleted_permanently_with_files(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    project = client.post(
        "/api/projects",
        json={
            "name": "Temporary bracket",
            "original_intent": "Delete this test project.",
        },
    ).json()
    revision = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={
            "source": CADQUERY_MANUAL_SOURCE,
            "user_instruction": None,
        },
    ).json()
    project_dir = tmp_path / "data" / "projects" / project["id"]

    assert project_dir.exists()

    delete_response = client.delete(f"/api/projects/{project['id']}")

    assert delete_response.status_code == 204
    assert not project_dir.exists()
    assert client.get(f"/api/projects/{project['id']}").status_code == 404
    with next(app.dependency_overrides[get_db]()) as session:
        assert session.get(Project, project["id"]) is None
        assert session.get(Revision, revision["id"]) is None


def test_old_archived_projects_are_cleaned_after_sixty_days(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    with next(app.dependency_overrides[get_db]()) as session:
        old_archived = Project(
            name="Archived old",
            slug="archived-old",
            original_intent="Old archived project.",
            status="archived",
            archived_at=utcnow() - timedelta(days=61),
            created_at=utcnow() - timedelta(days=61),
            updated_at=utcnow() - timedelta(days=61),
        )
        recent_archived = Project(
            name="Archived recent",
            slug="archived-recent",
            original_intent="Recent archived project.",
            status="archived",
            archived_at=utcnow() - timedelta(days=30),
            created_at=utcnow() - timedelta(days=30),
            updated_at=utcnow() - timedelta(days=30),
        )
        session.add_all([old_archived, recent_archived])
        session.commit()
        old_archived_id = old_archived.id
        recent_archived_id = recent_archived.id

    old_project_dir = tmp_path / "data" / "projects" / old_archived_id
    recent_project_dir = tmp_path / "data" / "projects" / recent_archived_id
    old_project_dir.mkdir(parents=True)
    recent_project_dir.mkdir(parents=True)

    list_response = client.get("/api/projects")

    assert list_response.status_code == 200
    with next(app.dependency_overrides[get_db]()) as session:
        assert session.get(Project, old_archived_id) is None
        assert session.get(Project, recent_archived_id) is not None
    assert not old_project_dir.exists()
    assert recent_project_dir.exists()


def test_printability_profiles_can_be_saved_updated_listed_and_deleted(
    tmp_path: Path,
) -> None:
    client = build_client(tmp_path)

    create_response = client.post(
        "/api/printability-profiles",
        json={
            "profile_version": "printability-fdm-v1",
            "printer_name": "Bambu Lab H2C",
            "process": "FDM",
            "material_behavior": "general PLA/PETG",
            "build_volume": {
                "x_mm": 325,
                "y_mm": 320,
                "z_mm": 320,
            },
            "nozzle_diameter_mm": 0.4,
            "default_layer_height_mm": 0.2,
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["id"]
    assert created["printer_name"] == "Bambu Lab H2C"
    assert created["build_volume"]["x_mm"] == 325

    list_response = client.get("/api/printability-profiles")
    assert list_response.status_code == 200
    assert [profile["id"] for profile in list_response.json()] == [created["id"]]

    update_response = client.patch(
        f"/api/printability-profiles/{created['id']}",
        json={
            "profile_version": "printability-fdm-v1",
            "printer_name": "Bambu Lab H2C 0.6",
            "process": "FDM",
            "material_behavior": "general PLA/PETG",
            "build_volume": {
                "x_mm": 325,
                "y_mm": 320,
                "z_mm": 320,
            },
            "nozzle_diameter_mm": 0.6,
            "default_layer_height_mm": 0.24,
        },
    )

    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["printer_name"] == "Bambu Lab H2C 0.6"
    assert updated["nozzle_diameter_mm"] == 0.6

    delete_response = client.delete(f"/api/printability-profiles/{created['id']}")

    assert delete_response.status_code == 204
    assert client.get("/api/printability-profiles").json() == []


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
            "source": CADQUERY_MANUAL_SOURCE,
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
            "source": CADQUERY_MANUAL_SOURCE,
            "user_instruction": "Initial manual model.",
        },
    ).json()

    failed_response = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={
            "source": "broken(",
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
            "source": CADQUERY_MANUAL_SOURCE,
            "user_instruction": "Initial manual model.",
        },
    ).json()
    second_revision = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={
            "source": CADQUERY_WIDE_SOURCE,
            "user_instruction": "Wider handle.",
        },
    ).json()
    assert second_revision["is_accepted"] is False
    assert second_revision["review_state"] == "ready"

    restore_response = client.post(f"/api/revisions/{first_revision['id']}/restore")

    assert restore_response.status_code == 200
    restored_project = restore_response.json()
    assert restored_project["active_revision_id"] == first_revision["id"]

    source_response = client.get(f"/api/revisions/{first_revision['id']}/source")
    assert source_response.headers["content-disposition"].endswith('filename="source.py"')


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
            "source": CADQUERY_MANUAL_SOURCE,
            "user_instruction": "Initial cube.",
        },
    ).json()
    second_revision = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={
            "source": CADQUERY_WIDE_SOURCE,
            "user_instruction": "Make it wider.",
        },
    ).json()

    response = client.get(f"/api/revisions/{second_revision['id']}/diff")

    assert response.status_code == 200
    assert response.text.splitlines() == [
        f"--- R{first_revision['revision_number']}",
        f"+++ R{second_revision['revision_number']}",
        "@@ -3,7 +3,7 @@",
        " from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product",
        " ",
        " PARAMETERS = [",
        '-    ParameterSpec(id="width", label="Width", type="float", default=10.0, unit="mm"),',
        '+    ParameterSpec(id="width", label="Width", type="float", default=20.0, unit="mm"),',
        '     ParameterSpec(id="depth", label="Depth", type="float", default=20.0, unit="mm"),',
        '     ParameterSpec(id="height", label="Height", type="float", default=30.0, unit="mm"),',
        " ]",
    ]
