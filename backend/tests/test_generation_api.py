from collections.abc import Generator
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
import trimesh

from app.api.dependencies import get_ai_provider, get_cad_runner, get_data_dir
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.services.ai.provider import (
    ModelGenerationRequest,
    ModelGenerationResult,
    RequirementExtractionRequest,
    RequirementExtractionResult,
)
from app.services.ai.gemini_cli import GeminiCliProvider
from app.services.cad.runner import CadCompileResult
from app.services.mesh.inspect import MeshMetadata


class FakeAiProvider:
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
            raw_output=f"""
```scad
/*
Project: {request.project_name}
Units: millimeters
Purpose: {request.user_instruction}
Assumptions: Simple rectangular calibration block.
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
module main_model() {{
  cube([width, 10, 10]);
}}

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
            raw_output="I cannot produce OpenSCAD for that.",
            provider="fake",
            provider_model="fake-model",
        )


class RepairingAiProvider:
    def __init__(self) -> None:
        self.requests: list[ModelGenerationRequest] = []

    async def generate_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        self.requests.append(request)
        if len(self.requests) == 1:
            source = """
```scad
/*
Project: Repairable output
Units: millimeters
Purpose: Create a cube
Assumptions: Simple calibration block.
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
  broken();
}
// ===== FINAL MODEL =====
main_model();
```
"""
        else:
            source = """
```scad
/*
Project: Repairable output
Units: millimeters
Purpose: Create a cube
Assumptions: Simple calibration block.
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
"""
        return ModelGenerationResult(raw_output=source, provider="fake", provider_model="fake-model")


class ContextAwareAiProvider:
    def __init__(self) -> None:
        self.requests: list[ModelGenerationRequest] = []

    async def generate_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        self.requests.append(request)
        return ModelGenerationResult(
            raw_output="""
```scad
/*
Project: Resize generated part
Units: millimeters
Purpose: Resize block
Assumptions: Preserve rectangular block geometry.
Print notes: Print flat on the build plate.
*/
// ===== QUALITY =====
$fn = 32;
// ===== USER PARAMETERS =====
width = 20;
// ===== DERIVED VALUES =====
half_width = width / 2;
// ===== VALIDATION =====
assert(width > 0);
// ===== MODULES =====
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
        if "broken(" in source:
            stdout_path.write_text("", encoding="utf-8")
            stderr_path.write_text("Parser error: syntax error", encoding="utf-8")
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
                error_message="Parser error: syntax error",
            )

        mesh = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
        mesh.apply_translation([0.0, 0.0, 5.0])
        mesh.export(stl_path)
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
    app.dependency_overrides[get_ai_provider] = lambda: FakeAiProvider()
    app.dependency_overrides[get_cad_runner] = lambda: FakeCadRunner()
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def ready_spec_json(instruction: str) -> str:
    return f"""{{
  "schema_version": "1.0",
  "object_type": "calibration_cube",
  "purpose": {instruction!r},
  "units": "mm",
  "supported_scope": true,
  "critical_dimensions": [
    {{
      "id": "width",
      "label": "Width",
      "value": 10,
      "unit": "mm",
      "tolerance": null,
      "source": "user",
      "importance": "critical",
      "protected": true
    }}
  ],
  "parameters": [],
  "functional_requirements": [
    {{
      "id": "simple_block",
      "description": "Create a simple block",
      "source": "user",
      "importance": "critical",
      "protected": true
    }}
  ],
  "print_requirements": {{}},
  "assumptions": [],
  "conflicts": [],
  "missing_requirements": [],
  "clarification_required": false,
  "clarification_questions": [],
  "generation_ready": true,
  "outcome": "generation_ready"
}}""".replace("'", '"')


def create_ready_spec(client: TestClient, project_id: str, instruction: str) -> dict:
    response = client.post(
        f"/api/projects/{project_id}/requirements",
        json={"user_instruction": instruction},
    )
    assert response.status_code == 201
    return response.json()


def test_generates_initial_revision_from_prompt(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    project = client.post(
        "/api/projects",
        json={
            "name": "Generated cube",
            "original_intent": "Create a calibration cube.",
        },
    ).json()
    spec = create_ready_spec(client, project["id"], "Create a 10mm cube with named parameters.")

    response = client.post(f"/api/design-specifications/{spec['id']}/generate")

    assert response.status_code == 201
    revision = response.json()
    assert revision["source_type"] == "ai_initial"
    assert revision["status"] == "succeeded"
    assert revision["review_state"] == "ready_with_warnings"
    assert revision["is_accepted"] is False
    assert revision["metadata"]["volume_mm3"] == 1000.0

    revision_dir = tmp_path / "data" / "projects" / project["id"] / "revisions" / revision["id"]
    assert "main_model();" in (revision_dir / "model.scad").read_text(encoding="utf-8")
    assert "```scad" in (revision_dir / "ai-output.txt").read_text(encoding="utf-8")

    refreshed_project = client.get(f"/api/projects/{project['id']}").json()
    assert refreshed_project["active_revision_id"] is None


def test_generation_provider_failure_returns_visible_error(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    project = client.post(
        "/api/projects",
        json={
            "name": "Blocked generation",
            "original_intent": "Create a generated part.",
        },
    ).json()
    spec = create_ready_spec(client, project["id"], "Create a cube.")
    app.dependency_overrides[get_ai_provider] = lambda: FailingAiProvider()

    response = client.post(f"/api/design-specifications/{spec['id']}/generate")

    assert response.status_code == 502
    assert response.json()["detail"] == "Gemini CLI authentication failed"


def test_generation_extraction_failure_is_preserved_as_failed_revision(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    project = client.post(
        "/api/projects",
        json={
            "name": "Bad output",
            "original_intent": "Create a generated part.",
        },
    ).json()
    spec = create_ready_spec(client, project["id"], "Create a cube.")
    app.dependency_overrides[get_ai_provider] = lambda: InvalidSourceAiProvider()

    response = client.post(f"/api/design-specifications/{spec['id']}/generate")

    assert response.status_code == 201
    revision = response.json()
    assert revision["source_type"] == "ai_initial"
    assert revision["status"] == "failed"
    assert revision["is_accepted"] is False
    assert "OpenSCAD source" in revision["error_message"]

    revision_dir = tmp_path / "data" / "projects" / project["id"] / "revisions" / revision["id"]
    assert (revision_dir / "ai-output.txt").read_text(encoding="utf-8") == "I cannot produce OpenSCAD for that."
    assert (revision_dir / "compile.log").exists()
    ai_output_response = client.get(f"/api/revisions/{revision['id']}/ai-output")
    assert ai_output_response.status_code == 200
    assert ai_output_response.text == "I cannot produce OpenSCAD for that."

    refreshed_project = client.get(f"/api/projects/{project['id']}").json()
    assert refreshed_project["active_revision_id"] is None


def test_generation_repairs_once_after_compile_failure(tmp_path: Path) -> None:
    provider = RepairingAiProvider()
    client = build_client(tmp_path)
    project = client.post(
        "/api/projects",
        json={
            "name": "Repairable output",
            "original_intent": "Create a generated part.",
        },
    ).json()
    spec = create_ready_spec(client, project["id"], "Create a cube.")
    app.dependency_overrides[get_ai_provider] = lambda: provider

    response = client.post(f"/api/design-specifications/{spec['id']}/generate")

    assert response.status_code == 201
    revision = response.json()
    assert revision["source_type"] == "ai_repair"
    assert revision["status"] == "succeeded"
    assert len(provider.requests) == 2
    assert provider.requests[1].current_source is not None
    assert provider.requests[1].compiler_diagnostics == "Parser error: syntax error"

    revisions = client.get(f"/api/projects/{project['id']}/revisions").json()
    assert [entry["status"] for entry in revisions] == ["failed", "succeeded"]
    assert revisions[0]["source_type"] == "ai_initial"
    assert revisions[1]["source_type"] == "ai_repair"


def test_generation_with_active_revision_uses_current_source_context(tmp_path: Path) -> None:
    provider = ContextAwareAiProvider()
    client = build_client(tmp_path)
    app.dependency_overrides[get_ai_provider] = lambda: provider
    project = client.post(
        "/api/projects",
        json={
            "name": "Resize generated part",
            "original_intent": "Create a configurable block.",
        },
    ).json()
    manual_source = """
module main_model() {
  cube([10, 10, 10]);
}
main_model();
"""
    base_revision = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={
            "scad_source": manual_source,
            "user_instruction": "Initial manual cube.",
        },
    ).json()

    response = client.post(
        f"/api/projects/{project['id']}/generate",
        json={"user_instruction": "Make it 20 mm wide while preserving the other dimensions."},
    )

    assert response.status_code == 201
    revision = response.json()
    assert revision["source_type"] == "ai_revision"
    assert revision["parent_revision_id"] == base_revision["id"]
    assert revision["status"] == "succeeded"
    assert revision["review_state"] == "ready"
    assert revision["is_accepted"] is False
    assert len(provider.requests) == 1
    assert provider.requests[0].current_source == manual_source
    assert provider.requests[0].compiler_diagnostics is None

    refreshed_project = client.get(f"/api/projects/{project['id']}").json()
    assert refreshed_project["active_revision_id"] == base_revision["id"]
    revisions = client.get(f"/api/projects/{project['id']}/revisions").json()
    assert [entry["source_type"] for entry in revisions] == ["manual_edit", "ai_revision"]


def test_gemini_cli_provider_uses_headless_trust_flag() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")

    command = provider.build_command("prompt")

    assert "--skip-trust" in command
    assert command[command.index("--model") : command.index("--model") + 2] == [
        "--model",
        "gemini-3.5-flash-lite",
    ]
    assert "--policy" in command
    policy_path = command[command.index("--policy") + 1]
    assert policy_path.endswith("gemini_no_tools_policy.toml")


def test_gemini_initial_prompt_sets_functional_cad_ground_rules() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")

    prompt = provider._build_prompt(
        ModelGenerationRequest(
            project_name="Draft",
            original_intent="",
            user_instruction="Build a tackle tray carrier.",
        )
    )

    assert "Do not add decorative cutouts, lightening holes, pass-through holes" in prompt
    assert "Every subtraction must directly serve the user's requested function" in prompt
    assert "Preserve load-bearing walls, tray support surfaces, retention features, and handles" in prompt
