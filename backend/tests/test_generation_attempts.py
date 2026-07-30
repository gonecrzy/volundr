import json
from collections.abc import Generator
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
import trimesh

from app.api.dependencies import get_ai_provider, get_cad_runner, get_data_dir
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.generation_attempt import GenerationAttempt
from app.services.ai.provider import (
    ModelGenerationRequest,
    ModelGenerationResult,
    RequirementExtractionRequest,
    RequirementExtractionResult,
)
from app.services.cad.runner import CadCompileResult
from app.services.mesh.inspect import MeshMetadata


class SuccessfulAiProvider:
    async def extract_requirements(
        self,
        request: RequirementExtractionRequest,
    ) -> RequirementExtractionResult:
        return RequirementExtractionResult(
            raw_output=ready_spec_json(request.user_instruction),
            provider="fake",
            provider_model="fake-model",
        )

    async def generate_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        return ModelGenerationResult(
            raw_output="""
```scad
/*
Project: Generated cube
Units: millimeters
Purpose: Calibration cube
Assumptions: None
Print notes: Print flat on the build plate.
*/
// ===== QUALITY =====
$fn = 32;
// ===== USER PARAMETERS =====
// @volundr-requirement width
width = 10;
// ===== DERIVED VALUES =====
half_width = width / 2;
// ===== VALIDATION =====
assert(width > 0);
// ===== MODULES =====
// @volundr-feature simple_block
module main_model() {
  cube([width, 10, 10]);
}
// ===== FINAL MODEL =====
main_model();
```
""",
            provider="fake",
            provider_model="fake-model",
        )


class FailingAiProvider:
    async def generate_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        raise RuntimeError("Gemini CLI authentication failed")


class InvalidSourceAiProvider:
    async def generate_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        return ModelGenerationResult(
            raw_output="I need more information.",
            provider="fake",
            provider_model="fake-model",
        )


class FakeCadRunner:
    async def compile(self, source: str, job_id: str) -> CadCompileResult:
        job_dir = Path("/tmp") / "volundr-fake-attempt-jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        source_path = job_dir / "model.scad"
        stl_path = job_dir / "model.stl"
        stdout_path = job_dir / "stdout.log"
        stderr_path = job_dir / "stderr.log"
        metadata_path = job_dir / "metadata.json"
        source_path.write_text(source, encoding="utf-8")
        mesh = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
        mesh.apply_translation([0.0, 0.0, 5.0])
        mesh.export(stl_path)
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text("Compilation finished", encoding="utf-8")
        metadata_path.write_text("{}", encoding="utf-8")
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
            output_size_bytes=stl_path.stat().st_size,
            metadata=metadata,
            error_message=None,
        )


def build_client(tmp_path: Path, ai_provider) -> tuple[TestClient, sessionmaker[Session]]:
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
    app.dependency_overrides[get_ai_provider] = lambda: ai_provider
    app.dependency_overrides[get_cad_runner] = lambda: FakeCadRunner()
    return TestClient(app), TestingSessionLocal


def teardown_function() -> None:
    app.dependency_overrides.clear()


def ready_spec_json(instruction: str) -> str:
    return json.dumps(
        {
            "schema_version": "1.0",
            "object_type": "calibration_cube",
            "purpose": instruction,
            "units": "mm",
            "supported_scope": True,
            "critical_dimensions": [
                {
                    "id": "width",
                    "label": "Width",
                    "value": 10,
                    "unit": "mm",
                    "tolerance": None,
                    "source": "user",
                    "importance": "critical",
                    "protected": True,
                }
            ],
            "parameters": [],
            "functional_requirements": [
                {
                    "id": "simple_block",
                    "description": "Create a simple block",
                    "source": "user",
                    "importance": "critical",
                    "protected": True,
                }
            ],
            "print_requirements": {},
            "assumptions": [],
            "conflicts": [],
            "missing_requirements": [],
            "clarification_required": False,
            "clarification_questions": [],
            "generation_ready": True,
            "outcome": "generation_ready",
        }
    )


def create_ready_spec(client: TestClient, project_id: str, instruction: str) -> dict:
    response = client.post(
        f"/api/projects/{project_id}/requirements",
        json={"user_instruction": instruction},
    )
    assert response.status_code == 201
    return response.json()


def test_successful_generation_persists_complete_attempt_chain(tmp_path: Path) -> None:
    client, SessionLocal = build_client(tmp_path, SuccessfulAiProvider())
    project = client.post(
        "/api/projects",
        json={"name": "Generated cube", "original_intent": "Create a calibration cube."},
    ).json()
    spec = create_ready_spec(client, project["id"], "Create a 10mm cube with named parameters.")

    response = client.post(f"/api/design-specifications/{spec['id']}/generate")

    assert response.status_code == 201
    with SessionLocal() as session:
        attempts = list(
            session.scalars(select(GenerationAttempt).order_by(GenerationAttempt.attempt_number))
        )
        assert len(attempts) == 2
        requirement_attempt, attempt = attempts
        assert requirement_attempt.status == "succeeded"
        assert requirement_attempt.prompt_template_version == "requirements-v1"
        assert requirement_attempt.design_spec_path is not None
        assert attempt.status == "succeeded"
        assert attempt.failure_class == "none"
        assert attempt.prompt_template_version == "openscad-generation-v3"
        assert attempt.ruleset_version == "gemini-ruleset-v1"
        assert attempt.provider == "fake"
        assert attempt.provider_model == "fake-model"
        assert attempt.resulting_revision_id == response.json()["id"]

    run_dir = tmp_path / "data" / "projects" / project["id"] / "generation-runs" / attempt.id
    request_payload = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
    chain = json.loads((run_dir / "chain.json").read_text(encoding="utf-8"))

    assert request_payload["user_instruction"] == "Create a 10mm cube with named parameters."
    assert (run_dir / "prompt.txt").exists()
    assert (run_dir / "raw-output.txt").exists()
    assert (run_dir / "extracted-source.scad").exists()
    design_spec = json.loads((run_dir / "design-spec.json").read_text(encoding="utf-8"))
    assert design_spec["outcome"] == "generation_ready"
    assert design_spec["critical_dimensions"][0]["source"] == "user"
    assert chain["stages"][0]["prompt_template_version"] == "openscad-generation-v3"
    assert chain["stages"][0]["source_contract_result_path"] is not None
    assert chain["stages"][0]["source_contract_passed_hard_checks"] is True


def test_provider_failure_persists_failed_attempt_without_revision(tmp_path: Path) -> None:
    client, SessionLocal = build_client(tmp_path, SuccessfulAiProvider())
    project = client.post(
        "/api/projects",
        json={"name": "Blocked generation", "original_intent": "Create a generated part."},
    ).json()
    spec = create_ready_spec(client, project["id"], "Create a cube.")
    app.dependency_overrides[get_ai_provider] = lambda: FailingAiProvider()

    response = client.post(f"/api/design-specifications/{spec['id']}/generate")

    assert response.status_code == 502
    with SessionLocal() as session:
        attempt = list(
            session.scalars(select(GenerationAttempt).order_by(GenerationAttempt.attempt_number))
        )[-1]
        assert attempt is not None
        assert attempt.status == "failed"
        assert attempt.failure_class == "provider_failure"
        assert attempt.resulting_revision_id is None
        assert "authentication failed" in (attempt.error_message or "")


def test_extraction_failure_persists_raw_output_and_failure_class(tmp_path: Path) -> None:
    client, SessionLocal = build_client(tmp_path, SuccessfulAiProvider())
    project = client.post(
        "/api/projects",
        json={"name": "Bad output", "original_intent": "Create a generated part."},
    ).json()
    spec = create_ready_spec(client, project["id"], "Create a cube.")
    app.dependency_overrides[get_ai_provider] = lambda: InvalidSourceAiProvider()

    response = client.post(f"/api/design-specifications/{spec['id']}/generate")

    assert response.status_code == 201
    with SessionLocal() as session:
        attempt = list(
            session.scalars(select(GenerationAttempt).order_by(GenerationAttempt.attempt_number))
        )[-1]
        assert attempt is not None
        assert attempt.status == "failed"
        assert attempt.failure_class == "source_extraction_failure"
        assert attempt.raw_output_path is not None
        assert attempt.extracted_source_path is None
        assert attempt.resulting_revision_id == response.json()["id"]
