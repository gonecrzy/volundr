import hashlib
import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

import trimesh
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_ai_provider, get_cad_runner, get_data_dir
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.services.ai.provider import ModelGenerationRequest, ModelGenerationResult
from app.services.cad.cadquery_runner import CadQueryCompileResult, CadQueryOutputResult
from app.services.mesh.inspect import MeshMetadata


class UnusedAiProvider:
    async def generate_cadquery_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        raise AssertionError("candidate lifecycle tests should not call the AI provider")


class CandidateCadRunner:
    async def compile(
        self,
        source: str,
        job_id: str,
        *,
        parameter_values: dict[str, Any] | None = None,
        requested_outputs: list[dict[str, Any]] | None = None,
    ) -> CadQueryCompileResult:
        output_id = str((requested_outputs or [{"output_id": "body"}])[0]["output_id"])
        job_dir = Path("/tmp") / "volundr-fake-candidate-jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        source_path = job_dir / "source.py"
        stdout_path = job_dir / "stdout.log"
        stderr_path = job_dir / "stderr.log"
        source_path.write_text(source, encoding="utf-8")
        stdout_path.write_text("", encoding="utf-8")

        source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        if "compile_fail" in source:
            stderr_path.write_text("Parser error: syntax error", encoding="utf-8")
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
                source_hash=source_hash,
                output_size_bytes=0,
                metadata=None,
                error_message="Parser error: syntax error",
                outputs=[],
            )

        stl_path = job_dir / f"{output_id}.stl"
        step_path = job_dir / f"{output_id}.step"
        brep_path = job_dir / f"{output_id}.brep"
        metadata_path = job_dir / f"{output_id}.json"
        topology_path = job_dir / f"{output_id}-topology.json"
        mesh = mesh_for_source(source)
        mesh.export(stl_path)
        step_path.write_text("STEP", encoding="utf-8")
        brep_path.write_text("BREP", encoding="utf-8")
        stderr_path.write_text("Compilation finished", encoding="utf-8")
        metadata = MeshMetadata(
            size_x_mm=float(mesh.bounding_box.extents[0]),
            size_y_mm=float(mesh.bounding_box.extents[1]),
            size_z_mm=float(mesh.bounding_box.extents[2]),
            volume_mm3=float(abs(mesh.volume)),
            triangle_count=int(len(mesh.faces)),
            connected_components=2 if "advisory_components" in source else 1,
            is_watertight=bool(mesh.is_watertight),
            is_winding_consistent=True,
            center_of_mass=(0.0, 0.0, 0.0),
        )
        metadata_path.write_text(json.dumps(metadata.__dict__), encoding="utf-8")
        topology = {"solid_count": metadata.connected_components}
        topology_path.write_text(json.dumps(topology), encoding="utf-8")
        output = CadQueryOutputResult(
            output_id=output_id,
            entrypoint=output_id,
            required=True,
            success=True,
            stl_path=stl_path,
            step_path=step_path,
            brep_path=brep_path,
            metadata_path=metadata_path,
            topology_metadata_path=topology_path,
            stl_hash=hashlib.sha256(stl_path.read_bytes()).hexdigest(),
            step_hash=hashlib.sha256(step_path.read_bytes()).hexdigest(),
            brep_hash=hashlib.sha256(brep_path.read_bytes()).hexdigest(),
            output_size_bytes=stl_path.stat().st_size,
            metadata=metadata,
            topology_metadata=topology,
        )
        return CadQueryCompileResult(
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
            source_hash=source_hash,
            output_size_bytes=stl_path.stat().st_size,
            metadata=metadata,
            error_message=None,
            command_args=["python", "_volundr_cadquery_runner.py", output_id],
            outputs=[output],
        )


def build_client(tmp_path: Path) -> tuple[TestClient, sessionmaker[Session]]:
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
    app.dependency_overrides[get_ai_provider] = lambda: UnusedAiProvider()
    app.dependency_overrides[get_cad_runner] = lambda: CandidateCadRunner()
    return TestClient(app), TestingSessionLocal


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_manual_cadquery_candidate_does_not_replace_active_revision(tmp_path: Path) -> None:
    client, _SessionLocal = build_client(tmp_path)
    project, active_revision = create_project_with_active_revision(client)

    response = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={"source": clean_source(width=12), "user_instruction": "Create a second cube."},
    )

    assert response.status_code == 201
    candidate = response.json()
    assert candidate["cad_backend"] == "cadquery"
    assert candidate["source_language"] == "python"
    assert candidate["status"] == "succeeded"
    assert candidate["review_state"] in {"ready", "ready_with_warnings"}
    assert candidate["is_accepted"] is False
    assert client.get(f"/api/projects/{project['id']}").json()["active_revision_id"] == active_revision["id"]
    assert [entry["id"] for entry in client.get(f"/api/projects/{project['id']}/candidates").json()] == [
        candidate["id"]
    ]


def test_accepting_ready_candidate_updates_active_revision(tmp_path: Path) -> None:
    client, _SessionLocal = build_client(tmp_path)
    project, active_revision = create_project_with_active_revision(client)
    candidate = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={"source": clean_source(width=12), "user_instruction": "Create a candidate."},
    ).json()

    response = client.post(f"/api/candidates/{candidate['id']}/accept")

    assert response.status_code == 200
    accepted = response.json()
    assert accepted["review_state"] == "accepted"
    assert accepted["is_accepted"] is True
    assert accepted["accepted_at"] is not None
    assert client.get(f"/api/projects/{project['id']}").json()["active_revision_id"] == candidate["id"]
    previous = next(
        revision
        for revision in client.get(f"/api/projects/{project['id']}/revisions").json()
        if revision["id"] == active_revision["id"]
    )
    assert previous["review_state"] == "accepted"


def test_blocking_finding_prevents_acceptance(tmp_path: Path) -> None:
    client, _SessionLocal = build_client(tmp_path)
    project, active_revision = create_project_with_active_revision(client)
    candidate = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={"source": below_plate_source(), "user_instruction": "Create a below-plate model."},
    ).json()

    assert candidate["review_state"] == "blocked"
    assert client.post(f"/api/candidates/{candidate['id']}/accept").status_code == 409
    assert client.get(f"/api/projects/{project['id']}").json()["active_revision_id"] == active_revision["id"]
    findings = client.get(f"/api/candidates/{candidate['id']}/findings").json()
    below_plate = next(finding for finding in findings if finding["rule_id"] == "orientation.below_build_plate")
    assert below_plate["severity"] == "critical"
    assert below_plate["is_blocking"] is True


def test_rejecting_candidate_preserves_files(tmp_path: Path) -> None:
    client, _SessionLocal = build_client(tmp_path)
    project, active_revision = create_project_with_active_revision(client)
    candidate = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={"source": below_plate_source(), "user_instruction": "Create a blocked candidate."},
    ).json()

    response = client.post(f"/api/candidates/{candidate['id']}/reject")

    assert response.status_code == 200
    rejected = response.json()
    assert rejected["review_state"] == "rejected"
    assert rejected["rejected_at"] is not None
    assert client.get(f"/api/projects/{project['id']}").json()["active_revision_id"] == active_revision["id"]
    assert client.get(f"/api/revisions/{candidate['id']}/source").status_code == 200
    assert client.get(f"/api/revisions/{candidate['id']}/stl").status_code == 200
    assert client.get(f"/api/candidates/{candidate['id']}/findings").json()


def test_failed_cadquery_compile_creates_no_candidate(tmp_path: Path) -> None:
    client, _SessionLocal = build_client(tmp_path)
    project, active_revision = create_project_with_active_revision(client)

    response = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={"source": clean_source(marker="compile_fail"), "user_instruction": "Create invalid CadQuery."},
    )

    assert response.status_code == 201
    revision = response.json()
    assert revision["status"] == "failed"
    assert revision["review_state"] is None
    assert revision["error_message"] == "Parser error: syntax error"
    assert client.get(f"/api/projects/{project['id']}/candidates").json() == []
    assert client.get(f"/api/projects/{project['id']}").json()["active_revision_id"] == active_revision["id"]


def test_simple_generation_without_design_plan_is_rejected(tmp_path: Path) -> None:
    client, _SessionLocal = build_client(tmp_path)
    project, _active_revision = create_project_with_active_revision(client)

    response = client.post(
        f"/api/projects/{project['id']}/generate",
        json={"user_instruction": "Revise without a staged plan."},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Approved Design Plan is required before CAD generation"


def mesh_for_source(source: str) -> trimesh.Trimesh:
    if "advisory_components" in source:
        left = cube_mesh((10.0, 10.0, 10.0), z_min=0.0)
        left.apply_translation([-15.0, 0.0, 0.0])
        right = cube_mesh((10.0, 10.0, 10.0), z_min=0.0)
        right.apply_translation([15.0, 0.0, 0.0])
        return trimesh.util.concatenate([left, right])
    if "below_plate" in source:
        return cube_mesh((10.0, 10.0, 10.0), z_min=-1.0)
    return cube_mesh((10.0, 10.0, 10.0), z_min=0.0)


def cube_mesh(extents: tuple[float, float, float], *, z_min: float) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation([0.0, 0.0, z_min + extents[2] / 2.0])
    return mesh


def create_project_with_active_revision(client: TestClient) -> tuple[dict, dict]:
    project = client.post(
        "/api/projects",
        json={"name": "Candidate fixture", "original_intent": "Create a base cube."},
    ).json()
    revision = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={"source": clean_source(), "user_instruction": "Accepted base cube."},
    ).json()
    return project, revision


def clean_source(*, width: int = 10, marker: str = "") -> str:
    marker_line = f"    marker = {marker!r}" if marker else ""
    return f"""
import cadquery as cq

from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product


def build(params):
    width = params.get("width", {float(width)})
{marker_line}
    body = cq.Workplane("XY").box(width, width, width)
    return Product(
        parameters=[
            ParameterSpec(id="width", label="Width", type="float", default={float(width)}, unit="mm"),
        ],
        outputs=[
            PrintableOutput(output_id="body", label="Body", model=body, component_id="body"),
        ],
    )
"""


def below_plate_source() -> str:
    return clean_source(marker="below_plate")
