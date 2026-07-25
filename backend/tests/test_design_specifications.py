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
from app.services.ai.provider import (
    ModelGenerationRequest,
    ModelGenerationResult,
    RequirementExtractionRequest,
    RequirementExtractionResult,
)
from app.services.cad.runner import CadCompileResult
from app.services.mesh.inspect import MeshMetadata


READY_SPEC: dict[str, Any] = {
    "schema_version": "1.0",
    "object_type": "mounting_plate",
    "purpose": "Mount a small controller to a wall",
    "units": "mm",
    "supported_scope": True,
    "critical_dimensions": [
        {
            "id": "hole_spacing",
            "label": "Mounting hole spacing",
            "value": 60.0,
            "unit": "mm",
            "tolerance": None,
            "source": "user",
            "importance": "critical",
            "protected": True,
        }
    ],
    "parameters": [
        {
            "id": "wall_thickness",
            "label": "Wall thickness",
            "value": 3.0,
            "unit": "mm",
            "source": "product_default",
            "importance": "important",
            "protected": False,
            "editable": True,
            "explanation": "General functional FDM wall thickness",
        }
    ],
    "functional_requirements": [
        {
            "id": "mounting_method",
            "description": "Use two wall screws",
            "source": "user",
            "importance": "critical",
            "protected": True,
        }
    ],
    "print_requirements": {
        "printer_profile_id": "default-fdm-256",
        "nozzle_diameter_mm": 0.4,
        "layer_height_mm": 0.2,
        "material": None,
        "supports_allowed": None,
        "preferred_orientation": "flat back on build plate",
    },
    "assumptions": [
        {
            "id": "default_chamfer",
            "description": "Use a 0.8 mm edge chamfer",
            "source": "product_default",
            "requires_approval": False,
        },
        {
            "id": "button_clearance",
            "description": "Leave open access around the controller button",
            "source": "ai_assumption",
            "requires_approval": False,
        },
    ],
    "conflicts": [],
    "missing_requirements": [],
    "clarification_required": False,
    "clarification_questions": [],
    "generation_ready": True,
    "outcome": "generation_ready",
}


CLARIFICATION_SPEC = {
    **READY_SPEC,
    "critical_dimensions": [],
    "parameters": [],
    "assumptions": [],
    "missing_requirements": [
        {
            "id": "container_diameter",
            "label": "Container diameter",
            "source": "user",
            "importance": "critical",
            "reason": "The holder must fit a real container.",
        }
    ],
    "clarification_required": True,
    "clarification_questions": [
        {
            "id": "container_diameter",
            "question": "What is the outside diameter of the container the holder must fit?",
            "reason": "The fit diameter controls the holder opening.",
            "related_requirement_id": "container_diameter",
        }
    ],
    "generation_ready": False,
    "outcome": "clarification_required",
}


CONFLICT_SPEC = {
    **READY_SPEC,
    "conflicts": [
        {
            "id": "hole_spacing_conflict",
            "description": "Hole spacing was provided as both 50 mm and 60 mm.",
            "related_requirement_ids": ["hole_spacing"],
        }
    ],
    "generation_ready": False,
    "outcome": "requirements_conflict",
}


UNSUPPORTED_SPEC = {
    **READY_SPEC,
    "supported_scope": False,
    "generation_ready": False,
    "outcome": "unsupported_request",
}


def spec_payload(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = json.loads(json.dumps(READY_SPEC))
    if overrides:
        payload.update(overrides)
    return payload


class StagedAiProvider:
    def __init__(self, *requirement_outputs: str | dict[str, Any]) -> None:
        self.requirement_outputs = list(requirement_outputs)
        self.requirement_requests: list[RequirementExtractionRequest] = []
        self.generation_requests: list[ModelGenerationRequest] = []

    @property
    def gemini_ruleset_version(self) -> str:
        return "gemini-ruleset-v1"

    def provider_settings(self) -> dict[str, Any]:
        return {"model": "fake-requirements-model"}

    def prompt_template_version_for(self, request: ModelGenerationRequest) -> str:
        return "openscad-generation-v2" if request.design_specification else "legacy-initial-v1"

    def requirement_prompt_template_version(self) -> str:
        return "requirements-v1"

    def build_prompt(self, request: ModelGenerationRequest) -> str:
        return f"Design Specification authoritative:\n{json.dumps(request.design_specification, sort_keys=True)}"

    def build_requirement_prompt(self, request: RequirementExtractionRequest) -> str:
        return f"Extract requirements:\n{request.user_instruction}"

    async def extract_requirements(
        self,
        request: RequirementExtractionRequest,
    ) -> RequirementExtractionResult:
        self.requirement_requests.append(request)
        output = self.requirement_outputs.pop(0)
        raw_output = output if isinstance(output, str) else json.dumps(output)
        return RequirementExtractionResult(
            raw_output=raw_output,
            provider="fake",
            provider_model="fake-requirements-model",
        )

    async def generate_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        self.generation_requests.append(request)
        return ModelGenerationResult(
            raw_output="""
```scad
/*
Project: Mounting plate
Units: millimeters
Purpose: Mount a controller
Assumptions: Use rectangular plate geometry.
Print notes: Print flat on the build plate.
*/
// ===== QUALITY =====
$fn = 32;
// ===== USER PARAMETERS =====
// @volundr-requirement hole_spacing
hole_spacing = 60;
plate_width = 90;
// ===== DERIVED VALUES =====
half_spacing = hole_spacing / 2;
// ===== VALIDATION =====
assert(hole_spacing == 60);
// ===== MODULES =====
// @volundr-feature mounting_method
module mounting_holes() {
  translate([-half_spacing, 0, -0.5]) cylinder(h = 4, d = 4.5);
  translate([half_spacing, 0, -0.5]) cylinder(h = 4, d = 4.5);
}
module main_model() {
  difference() {
    cube([plate_width, 40, 3], center = true);
    mounting_holes();
  }
}
// ===== FINAL MODEL =====
main_model();
```
""",
            provider="fake",
            provider_model="fake-generation-model",
        )


class FakeCadRunner:
    async def compile(self, source: str, job_id: str) -> CadCompileResult:
        job_dir = Path("/tmp") / "volundr-fake-design-spec-jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        source_path = job_dir / "model.scad"
        stl_path = job_dir / "model.stl"
        stdout_path = job_dir / "stdout.log"
        stderr_path = job_dir / "stderr.log"
        metadata_path = job_dir / "metadata.json"
        source_path.write_text(source, encoding="utf-8")
        mesh = trimesh.creation.box(extents=(20.0, 10.0, 10.0))
        mesh.apply_translation([0.0, 0.0, 5.0])
        mesh.export(stl_path)
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text("Compilation finished", encoding="utf-8")
        metadata_path.write_text("{}", encoding="utf-8")
        metadata = MeshMetadata(
            size_x_mm=20.0,
            size_y_mm=10.0,
            size_z_mm=10.0,
            volume_mm3=2000.0,
            triangle_count=12,
            connected_components=1,
            is_watertight=True,
            is_winding_consistent=True,
            center_of_mass=(10.0, 5.0, 5.0),
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
    ai_provider: StagedAiProvider,
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
    app.dependency_overrides[get_cad_runner] = lambda: FakeCadRunner()
    return TestClient(app), TestingSessionLocal


def teardown_function() -> None:
    app.dependency_overrides.clear()


def create_project(client: TestClient) -> dict[str, Any]:
    return client.post(
        "/api/projects",
        json={
            "name": "Structured holder",
            "original_intent": "Create practical FDM parts.",
        },
    ).json()


def test_complete_request_creates_requirements_ready_specification(tmp_path: Path) -> None:
    provider = StagedAiProvider(READY_SPEC)
    client, SessionLocal = build_client(tmp_path, provider)
    project = create_project(client)

    response = client.post(
        f"/api/projects/{project['id']}/requirements",
        json={"user_instruction": "Create a 90 x 40 mm mounting plate with holes 60 mm apart."},
    )

    assert response.status_code == 201
    spec = response.json()
    assert spec["outcome"] == "generation_ready"
    assert spec["generation_ready"] is True
    assert spec["schema_version"] == "1.0"
    assert spec["version_number"] == 1
    assert spec["content_hash"]
    assert spec["specification"]["critical_dimensions"][0]["source"] == "user"
    assert spec["specification"]["critical_dimensions"][0]["protected"] is True
    assert spec["specification"]["parameters"][0]["source"] == "product_default"
    assert spec["specification"]["assumptions"][1]["source"] == "ai_assumption"

    with SessionLocal() as session:
        attempt = session.scalar(select(GenerationAttempt))
        assert attempt is not None
        assert attempt.status == "succeeded"
        assert attempt.prompt_template_version == "requirements-v1"
        assert attempt.design_spec_path is not None

    run_dir = tmp_path / "data" / "projects" / project["id"] / "generation-runs" / attempt.id
    assert json.loads((run_dir / "parsed-design-spec.json").read_text(encoding="utf-8"))["outcome"] == "generation_ready"
    assert (run_dir / "raw-output.txt").exists()


def test_clarification_required_persists_questions_and_creates_no_candidate(tmp_path: Path) -> None:
    provider = StagedAiProvider(CLARIFICATION_SPEC)
    client, _SessionLocal = build_client(tmp_path, provider)
    project = create_project(client)

    response = client.post(
        f"/api/projects/{project['id']}/requirements",
        json={"user_instruction": "Make this bottle fit on the wall."},
    )

    assert response.status_code == 201
    spec = response.json()
    assert spec["outcome"] == "clarification_required"
    assert spec["generation_ready"] is False
    assert spec["clarification_required"] is True
    assert spec["clarification_questions"][0]["question"].startswith("What is the outside diameter")
    assert client.get(f"/api/projects/{project['id']}/candidates").json() == []
    assert client.get(f"/api/projects/{project['id']}/revisions").json() == []


def test_conflicting_dimensions_do_not_generate_scad(tmp_path: Path) -> None:
    provider = StagedAiProvider(CONFLICT_SPEC)
    client, _SessionLocal = build_client(tmp_path, provider)
    project = create_project(client)

    spec = client.post(
        f"/api/projects/{project['id']}/requirements",
        json={"user_instruction": "Make holes 50 mm apart and 60 mm apart."},
    ).json()
    response = client.post(f"/api/design-specifications/{spec['id']}/generate")

    assert response.status_code == 409
    assert "generation_ready" in response.json()["detail"]
    assert provider.generation_requests == []


def test_unsupported_request_does_not_generate_placeholder_scad(tmp_path: Path) -> None:
    provider = StagedAiProvider(UNSUPPORTED_SPEC)
    client, _SessionLocal = build_client(tmp_path, provider)
    project = create_project(client)

    spec = client.post(
        f"/api/projects/{project['id']}/requirements",
        json={"user_instruction": "Generate an organic sculpture from a photo."},
    ).json()
    response = client.post(f"/api/design-specifications/{spec['id']}/generate")

    assert spec["outcome"] == "unsupported_request"
    assert response.status_code == 409
    assert provider.generation_requests == []


def test_clarification_answer_creates_new_ready_specification_version(tmp_path: Path) -> None:
    ready_after_answer = spec_payload(
        {
            "object_type": "cylindrical_holder",
            "purpose": "Hold an 81 mm container on a vertical wall",
            "critical_dimensions": [
                {
                    "id": "container_diameter",
                    "label": "Container diameter",
                    "value": 81.0,
                    "unit": "mm",
                    "tolerance": None,
                    "source": "clarification",
                    "importance": "critical",
                    "protected": True,
                }
            ],
        }
    )
    provider = StagedAiProvider(CLARIFICATION_SPEC, ready_after_answer)
    client, _SessionLocal = build_client(tmp_path, provider)
    project = create_project(client)
    first_spec = client.post(
        f"/api/projects/{project['id']}/requirements",
        json={"user_instruction": "Make this bottle fit on the wall."},
    ).json()

    response = client.post(
        f"/api/design-specifications/{first_spec['id']}/clarification-answers",
        json={
            "answers": [
                {
                    "question_id": first_spec["clarification_questions"][0]["id"],
                    "answer": "The container diameter is 81 mm.",
                }
            ]
        },
    )

    assert response.status_code == 201
    next_spec = response.json()
    assert next_spec["outcome"] == "generation_ready"
    assert next_spec["version_number"] == 2
    assert next_spec["superseded_specification_id"] == first_spec["id"]
    assert next_spec["specification"]["critical_dimensions"][0]["source"] == "clarification"
    assert provider.requirement_requests[1].previous_specification is not None
    assert provider.requirement_requests[1].clarification_answers[0]["answer"] == "The container diameter is 81 mm."


def test_invalid_extraction_json_is_classified_and_bounded_repair_is_attempted(tmp_path: Path) -> None:
    provider = StagedAiProvider("{not-json", READY_SPEC)
    client, SessionLocal = build_client(tmp_path, provider)
    project = create_project(client)

    response = client.post(
        f"/api/projects/{project['id']}/requirements",
        json={"user_instruction": "Create a complete 60 mm spacer."},
    )

    assert response.status_code == 201
    spec = response.json()
    assert spec["outcome"] == "generation_ready"
    assert len(provider.requirement_requests) == 2
    assert provider.requirement_requests[1].schema_repair_of_raw_output == "{not-json"
    with SessionLocal() as session:
        attempts = list(
            session.scalars(select(GenerationAttempt).order_by(GenerationAttempt.attempt_number))
        )
        assert [attempt.status for attempt in attempts] == ["failed", "succeeded"]
        assert attempts[0].failure_class == "design_spec_invalid"
        assert attempts[1].prompt_template_version == "requirements-v1"


def test_generation_cannot_begin_before_requirements_are_ready(tmp_path: Path) -> None:
    provider = StagedAiProvider(READY_SPEC)
    client, _SessionLocal = build_client(tmp_path, provider)
    project = create_project(client)

    response = client.post(
        f"/api/projects/{project['id']}/generate",
        json={"user_instruction": "Create a cube without using staged requirements."},
    )

    assert response.status_code == 409
    assert "Design Specification" in response.json()["detail"]
    assert provider.generation_requests == []


def test_generation_from_ready_spec_uses_specification_as_prompt_authority(tmp_path: Path) -> None:
    provider = StagedAiProvider(READY_SPEC)
    client, SessionLocal = build_client(tmp_path, provider)
    project = create_project(client)
    spec = client.post(
        f"/api/projects/{project['id']}/requirements",
        json={"user_instruction": "Create a 90 x 40 mm mounting plate with holes 60 mm apart."},
    ).json()

    response = client.post(f"/api/design-specifications/{spec['id']}/generate")

    assert response.status_code == 201
    candidate = response.json()
    assert candidate["source_type"] == "ai_initial"
    assert candidate["status"] == "succeeded"
    assert candidate["review_state"] == "ready"
    assert candidate["is_accepted"] is False
    assert len(provider.generation_requests) == 1
    assert provider.generation_requests[0].design_specification["purpose"] == READY_SPEC["purpose"]

    with SessionLocal() as session:
        revision = session.get(Revision, candidate["id"])
        attempts = list(
            session.scalars(select(GenerationAttempt).order_by(GenerationAttempt.attempt_number))
        )
        assert revision is not None
        assert attempts[-1].resulting_revision_id == revision.id
        assert attempts[-1].prompt_template_version == "openscad-generation-v2"
        assert attempts[-1].design_spec_path is not None
    assert client.get(f"/api/projects/{project['id']}").json()["active_revision_id"] is None


def test_legacy_project_without_specification_still_allows_active_revision_edit(tmp_path: Path) -> None:
    provider = StagedAiProvider(READY_SPEC)
    client, _SessionLocal = build_client(tmp_path, provider)
    project = create_project(client)
    base = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={
            "scad_source": "module main_model() { cube([10, 10, 10]); }\nmain_model();",
            "user_instruction": "Manual base.",
        },
    ).json()

    response = client.post(
        f"/api/projects/{project['id']}/generate",
        json={"user_instruction": "Make it 20 mm wide."},
    )

    assert response.status_code == 201
    candidate = response.json()
    assert candidate["source_type"] == "ai_revision"
    assert candidate["parent_revision_id"] == base["id"]
    assert len(provider.generation_requests) == 1
    assert provider.generation_requests[0].current_source is not None
