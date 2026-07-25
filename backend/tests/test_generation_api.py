from collections.abc import Generator
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_ai_provider, get_cad_runner, get_data_dir
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.services.ai.provider import ModelGenerationRequest, ModelGenerationResult
from app.services.cad.runner import CadCompileResult
from app.services.mesh.inspect import MeshMetadata


class FakeAiProvider:
    async def generate_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        return ModelGenerationResult(
            raw_output=f"""
```scad
/*
Project: {request.project_name}
Units: millimeters
Purpose: {request.user_instruction}
*/

// ===== QUALITY =====
$fn = 32;

// ===== USER PARAMETERS =====
width = 10;

// ===== MODULES =====
module main_model() {{
  cube([width, 10, 10]);
}}

main_model();
```
""",
            provider="fake",
            provider_model="fake-model",
        )


class FailingAiProvider:
    async def generate_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        raise RuntimeError("Gemini CLI authentication failed")


class FakeCadRunner:
    async def compile(self, source: str, job_id: str) -> CadCompileResult:
        job_dir = Path("/tmp") / "volundr-fake-generation-jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        source_path = job_dir / "model.scad"
        stl_path = job_dir / "model.stl"
        stdout_path = job_dir / "stdout.log"
        stderr_path = job_dir / "stderr.log"
        metadata_path = job_dir / "metadata.json"
        source_path.write_text(source, encoding="utf-8")
        stl_path.write_bytes(b"solid fake\nendsolid fake\n")
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text("Compilation finished", encoding="utf-8")
        metadata_path.write_text('{"triangle_count": 12}', encoding="utf-8")
        metadata = MeshMetadata(
            size_x_mm=10.0,
            size_y_mm=10.0,
            size_z_mm=10.0,
            volume_mm3=1000.0,
            triangle_count=12,
            connected_components=1,
            is_watertight=True,
            is_winding_consistent=True,
            center_of_mass=(5.0, 5.0, 5.0),
        )
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
    app.dependency_overrides[get_ai_provider] = lambda: FakeAiProvider()
    app.dependency_overrides[get_cad_runner] = lambda: FakeCadRunner()
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_generates_initial_revision_from_prompt(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    project = client.post(
        "/api/projects",
        json={
            "name": "Generated cube",
            "original_intent": "Create a calibration cube.",
        },
    ).json()

    response = client.post(
        f"/api/projects/{project['id']}/generate",
        json={"user_instruction": "Create a 10mm cube with named parameters."},
    )

    assert response.status_code == 201
    revision = response.json()
    assert revision["source_type"] == "ai_initial"
    assert revision["status"] == "succeeded"
    assert revision["metadata"]["volume_mm3"] == 1000.0

    revision_dir = tmp_path / "data" / "projects" / project["id"] / "revisions" / revision["id"]
    assert "main_model();" in (revision_dir / "model.scad").read_text(encoding="utf-8")
    assert "```scad" in (revision_dir / "ai-output.txt").read_text(encoding="utf-8")

    refreshed_project = client.get(f"/api/projects/{project['id']}").json()
    assert refreshed_project["active_revision_id"] == revision["id"]


def test_generation_provider_failure_returns_visible_error(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    app.dependency_overrides[get_ai_provider] = lambda: FailingAiProvider()
    project = client.post(
        "/api/projects",
        json={
            "name": "Blocked generation",
            "original_intent": "Create a generated part.",
        },
    ).json()

    response = client.post(
        f"/api/projects/{project['id']}/generate",
        json={"user_instruction": "Create a cube."},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Gemini CLI authentication failed"
