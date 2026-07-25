import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

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
from app.models.revision import Revision
from app.models.validation_finding import ValidationFinding
from app.services.ai.provider import (
    ModelGenerationRequest,
    ModelGenerationResult,
    RequirementExtractionRequest,
    RequirementExtractionResult,
)
from app.services.cad.runner import CadCompileResult
from app.services.mesh.inspect import MeshMetadata


DESIGN_SPEC = {
    "schema_version": "1.0",
    "object_type": "mounting_plate",
    "purpose": "Mount a controller",
    "units": "mm",
    "supported_scope": True,
    "critical_dimensions": [
        {
            "id": "hole_spacing",
            "label": "Hole spacing",
            "value": 60,
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
            "id": "mounting_method",
            "description": "Use mounting holes",
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


def valid_source() -> str:
    return """
```openscad
/*
Project: Mounting plate
Units: millimeters
Purpose: Mount a controller
Assumptions:
- none
Print notes:
- flat on Z=0
*/

// ===== QUALITY =====
$fn = 48;
eps = 0.01;

// ===== USER PARAMETERS =====
// @volundr-requirement hole_spacing
hole_spacing = 60;

// ===== DERIVED VALUES =====
plate_width = 90;

// ===== VALIDATION =====
assert(hole_spacing > 0, "hole_spacing must be positive");

// ===== MODULES =====
// @volundr-feature mounting_method
module mounting_holes() {
  translate([hole_spacing / 2, 0, 0]) cylinder(h=6, d=4.5);
}

// ===== FINAL MODEL =====
module main_model() {
  difference() {
    cube([plate_width, 30, 6]);
    mounting_holes();
  }
}

main_model();
```
"""


def mismatched_source() -> str:
    return valid_source().replace("hole_spacing = 60;", "hole_spacing = 55;")


def quality_source() -> str:
    return (
        valid_source()
        .replace('assert(hole_spacing > 0, "hole_spacing must be positive");', "")
        .replace("$fn = 48;", "$fn = 180;")
    )


class ContractAiProvider:
    def __init__(self, *sources: str) -> None:
        self.sources = list(sources)
        self.requests: list[ModelGenerationRequest] = []

    @property
    def gemini_ruleset_version(self) -> str:
        return "gemini-ruleset-v1"

    def provider_settings(self) -> dict[str, Any]:
        return {"model": "fake-contract-model"}

    def requirement_prompt_template_version(self) -> str:
        return "requirements-v1"

    def prompt_template_version_for(self, request: ModelGenerationRequest) -> str:
        if request.contract_diagnostics:
            return "contract-repair-v2"
        if request.compiler_diagnostics:
            return "legacy-compile-repair-v1"
        if request.design_specification:
            return "openscad-generation-v3"
        return "legacy-revision-v1"

    def build_prompt(self, request: ModelGenerationRequest) -> str:
        return request.contract_diagnostics or "prompt"

    def build_requirement_prompt(self, request: RequirementExtractionRequest) -> str:
        return "requirements prompt"

    async def extract_requirements(
        self,
        request: RequirementExtractionRequest,
    ) -> RequirementExtractionResult:
        return RequirementExtractionResult(
            raw_output=json.dumps(DESIGN_SPEC),
            provider="fake",
            provider_model="fake-contract-model",
        )

    async def generate_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        self.requests.append(request)
        source = self.sources.pop(0) if self.sources else valid_source()
        return ModelGenerationResult(
            raw_output=source,
            provider="fake",
            provider_model="fake-contract-model",
        )


class CountingCadRunner:
    def __init__(self) -> None:
        self.compile_count = 0

    async def compile(self, source: str, job_id: str) -> CadCompileResult:
        self.compile_count += 1
        job_dir = Path("/tmp") / "volundr-source-contract-pipeline" / job_id
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


def build_client(
    tmp_path: Path,
    ai_provider: ContractAiProvider,
    cad_runner: CountingCadRunner,
) -> tuple[TestClient, sessionmaker[Session]]:
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
    app.dependency_overrides[get_cad_runner] = lambda: cad_runner
    return TestClient(app), TestingSessionLocal


def teardown_function() -> None:
    app.dependency_overrides.clear()


def create_project_and_ready_spec(client: TestClient) -> tuple[dict[str, Any], dict[str, Any]]:
    project = client.post(
        "/api/projects",
        json={"name": "Source contract", "original_intent": "Create a mounting plate."},
    ).json()
    spec = client.post(
        f"/api/projects/{project['id']}/requirements",
        json={"user_instruction": "Create a mounting plate with 60 mm hole spacing."},
    ).json()
    return project, spec


def test_hard_contract_failure_prevents_compile_and_creates_no_candidate(tmp_path: Path) -> None:
    provider = ContractAiProvider(mismatched_source(), mismatched_source())
    cad_runner = CountingCadRunner()
    client, SessionLocal = build_client(tmp_path, provider, cad_runner)
    project, spec = create_project_and_ready_spec(client)

    response = client.post(f"/api/design-specifications/{spec['id']}/generate")

    assert response.status_code == 409
    assert "Model source rejected before compile" in response.json()["detail"]
    assert cad_runner.compile_count == 0
    assert client.get(f"/api/projects/{project['id']}/revisions").json() == []
    with SessionLocal() as session:
        attempts = list(
            session.scalars(select(GenerationAttempt).order_by(GenerationAttempt.attempt_number))
        )
        assert [attempt.prompt_template_version for attempt in attempts] == [
            "requirements-v1",
            "openscad-generation-v3",
            "contract-repair-v2",
        ]
        assert attempts[-1].failure_class == "source_contract_hard_rejection"
        findings = list(session.scalars(select(ValidationFinding)))
        assert any(
            finding.rule_id == "specification_compliance.protected_value_mismatch"
            for finding in findings
        )


def test_quality_findings_compile_and_create_ready_with_warnings_candidate(tmp_path: Path) -> None:
    provider = ContractAiProvider(quality_source())
    cad_runner = CountingCadRunner()
    client, SessionLocal = build_client(tmp_path, provider, cad_runner)
    project, spec = create_project_and_ready_spec(client)

    response = client.post(f"/api/design-specifications/{spec['id']}/generate")

    assert response.status_code == 201
    candidate = response.json()
    assert candidate["review_state"] == "ready_with_warnings"
    assert candidate["validation_summary"]["advisory_count"] >= 2
    assert cad_runner.compile_count == 1
    findings = client.get(f"/api/candidates/{candidate['id']}/findings").json()
    assert {finding["rule_id"] for finding in findings} >= {
        "source_parameterization.missing_assertions",
        "source_complexity.excessive_fn",
    }
    with SessionLocal() as session:
        revision = session.get(Revision, candidate["id"])
        assert revision is not None
        assert revision.design_specification_id == spec["id"]


def test_contract_repair_success_compiles_once_after_hard_failure(tmp_path: Path) -> None:
    provider = ContractAiProvider(
        valid_source().replace("// @volundr-feature mounting_method\n", ""),
        valid_source(),
    )
    cad_runner = CountingCadRunner()
    client, SessionLocal = build_client(tmp_path, provider, cad_runner)
    _project, spec = create_project_and_ready_spec(client)

    response = client.post(f"/api/design-specifications/{spec['id']}/generate")

    assert response.status_code == 201
    assert cad_runner.compile_count == 1
    assert len(provider.requests) == 2
    assert provider.requests[1].contract_diagnostics is not None
    assert provider.requests[1].compiler_diagnostics is None
    with SessionLocal() as session:
        attempts = list(
            session.scalars(select(GenerationAttempt).order_by(GenerationAttempt.attempt_number))
        )
        assert [attempt.prompt_template_version for attempt in attempts] == [
            "requirements-v1",
            "openscad-generation-v3",
            "contract-repair-v2",
        ]
        assert attempts[-1].status == "succeeded"


def test_compile_repair_begins_only_after_contract_checks_pass(tmp_path: Path) -> None:
    class FailingAfterContractCadRunner(CountingCadRunner):
        async def compile(self, source: str, job_id: str) -> CadCompileResult:
            self.compile_count += 1
            return CadCompileResult(
                job_id=job_id,
                success=False,
                timed_out=False,
                exit_code=1,
                source_path=None,
                stl_path=None,
                stdout_path=None,
                stderr_path=None,
                metadata_path=None,
                source_hash="fake",
                output_size_bytes=0,
                metadata=None,
                error_message="Parser error",
            )

    provider = ContractAiProvider(valid_source(), valid_source())
    cad_runner = FailingAfterContractCadRunner()
    client, _SessionLocal = build_client(tmp_path, provider, cad_runner)
    _project, spec = create_project_and_ready_spec(client)

    response = client.post(f"/api/design-specifications/{spec['id']}/generate")

    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert len(provider.requests) == 2
    assert provider.requests[0].contract_diagnostics is None
    assert provider.requests[1].compiler_diagnostics == "Parser error"
    assert provider.requests[1].contract_diagnostics is None
