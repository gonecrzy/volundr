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
from app.services.ai.provider import (
    DesignPlanRequest,
    DesignPlanResult,
    ModelGenerationRequest,
    ModelGenerationResult,
    RequirementExtractionRequest,
    RequirementExtractionResult,
)
from app.services.cad.runner import CadCompileResult
from app.services.mesh.inspect import MeshMetadata


READY_SPEC: dict[str, Any] = {
    "schema_version": "1.0",
    "object_type": "configurable_bracket",
    "purpose": "Mount a small electronics module to a wall",
    "units": "mm",
    "supported_scope": True,
    "critical_dimensions": [
        {
            "id": "mount_hole_spacing",
            "label": "Mounting hole spacing",
            "value": 60,
            "unit": "mm",
            "source": "user",
            "importance": "critical",
            "protected": True,
        }
    ],
    "parameters": [],
    "functional_requirements": [
        {
            "id": "mounting_plate",
            "description": "Flat wall-mounted bracket body",
            "source": "user",
            "importance": "critical",
            "protected": True,
        }
    ],
    "print_requirements": {"printer_profile_id": "default-fdm-256"},
    "assumptions": [],
    "conflicts": [],
    "missing_requirements": [],
    "clarification_required": False,
    "clarification_questions": [],
    "generation_ready": True,
    "outcome": "generation_ready",
}


READY_PLAN: dict[str, Any] = {
    "schema_version": "1.0",
    "design_level": "product",
    "product_type": "configurable_bracket",
    "purpose": "Mount a small electronics module to a wall",
    "units": "mm",
    "parameters": [
        {
            "id": "mount_hole_spacing",
            "label": "Mount hole spacing",
            "value": 60,
            "unit": "mm",
            "source_requirement_id": "mount_hole_spacing",
            "editable": True,
            "protected": True,
            "component_id": "bracket_body",
        },
        {
            "id": "plate_thickness",
            "label": "Plate thickness",
            "value": 6,
            "unit": "mm",
            "editable": True,
            "protected": False,
            "component_id": "bracket_body",
        },
    ],
    "derived_parameters": [
        {
            "id": "plate_height",
            "label": "Plate height",
            "expression": "mount_hole_spacing + 20",
            "unit": "mm",
            "depends_on": ["mount_hole_spacing"],
        }
    ],
    "dependency_edges": [
        {
            "from": "mount_hole_spacing",
            "to": "plate_height",
            "relationship": "spacing controls minimum case height",
        }
    ],
    "components": [
        {
            "id": "bracket_body",
            "label": "Bracket body",
            "description": "Main printable bracket",
            "features": ["mounting_holes", "reinforcement_ribs"],
            "parameters": ["mount_hole_spacing", "plate_thickness"],
        }
    ],
    "features": [
        {
            "id": "mounting_holes",
            "component_id": "bracket_body",
            "type": "hole_group",
            "description": "Two wall mounting holes",
            "parameters": ["mount_hole_spacing"],
            "protected": True,
        },
        {
            "id": "reinforcement_ribs",
            "component_id": "bracket_body",
            "type": "rib",
            "description": "Ribs supporting the load path",
            "parameters": ["plate_thickness"],
            "protected": False,
        },
    ],
    "presets": [
        {
            "id": "default",
            "label": "Default bracket",
            "parameter_values": {"mount_hole_spacing": 60, "plate_thickness": 6},
        }
    ],
    "assembly_strategy": {
        "type": "single_part",
        "instructions": ["Print flat with wall face on the build plate."],
    },
    "printable_outputs": [
        {
            "id": "bracket_body_output",
            "label": "Bracket body",
            "component_ids": ["bracket_body"],
            "quantity": 1,
            "orientation": "wall face on Z=0",
        }
    ],
    "risks": [
        {
            "id": "layer_strength",
            "severity": "warning",
            "description": "Wall loads should be carried by ribs, not a thin flat plate.",
            "mitigation": "Use triangular ribs behind the mounting face.",
        }
    ],
    "clarification_required": False,
    "clarification_questions": [],
    "plan_ready": True,
    "outcome": "plan_ready",
}


PLAN_CLARIFICATION = {
    **READY_PLAN,
    "parameters": [],
    "components": [],
    "features": [],
    "printable_outputs": [],
    "clarification_required": True,
    "clarification_questions": [
        {
            "id": "separate_outputs",
            "question": "Should the lid and base print as separate parts?",
            "reason": "The output plan changes assembly and export packaging.",
            "related_plan_field": "printable_outputs",
        }
    ],
    "plan_ready": False,
    "outcome": "plan_clarification_required",
}


class PlanningAiProvider:
    def __init__(self, *plan_outputs: str | dict[str, Any]) -> None:
        self.plan_outputs = list(plan_outputs)
        self.plan_requests: list[DesignPlanRequest] = []
        self.generation_requests: list[ModelGenerationRequest] = []

    @property
    def gemini_ruleset_version(self) -> str:
        return "gemini-ruleset-v1"

    def provider_settings(self) -> dict[str, Any]:
        return {"model": "fake-planning-model"}

    def requirement_prompt_template_version(self) -> str:
        return "requirements-v1"

    def design_plan_prompt_template_version(self) -> str:
        return "design-plan-v1"

    def prompt_template_version_for(self, request: ModelGenerationRequest) -> str:
        return "openscad-generation-v4" if request.design_plan else "openscad-generation-v3"

    def build_requirement_prompt(self, request: RequirementExtractionRequest) -> str:
        return "requirements prompt"

    def build_design_plan_prompt(self, request: DesignPlanRequest) -> str:
        return f"design plan prompt\n{json.dumps(request.design_specification, sort_keys=True)}"

    def build_prompt(self, request: ModelGenerationRequest) -> str:
        return f"OpenSCAD from approved plan\n{json.dumps(request.design_plan, sort_keys=True)}"

    async def extract_requirements(
        self,
        request: RequirementExtractionRequest,
    ) -> RequirementExtractionResult:
        return RequirementExtractionResult(
            raw_output=json.dumps(READY_SPEC),
            provider="fake",
            provider_model="fake-planning-model",
        )

    async def create_design_plan(self, request: DesignPlanRequest) -> DesignPlanResult:
        self.plan_requests.append(request)
        output = self.plan_outputs.pop(0)
        raw_output = output if isinstance(output, str) else json.dumps(output)
        return DesignPlanResult(
            raw_output=raw_output,
            provider="fake",
            provider_model="fake-planning-model",
        )

    async def generate_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        self.generation_requests.append(request)
        return ModelGenerationResult(
            raw_output="""
```openscad
/*
Project: Planned bracket
Units: millimeters
Purpose: bracket
Assumptions: none
Print notes: flat
*/
// ===== QUALITY =====
$fn = 32;
// ===== USER PARAMETERS =====
// @volundr-requirement mount_hole_spacing
// @volundr-component bracket_body
mount_hole_spacing = 60;
plate_thickness = 6;
// ===== DERIVED VALUES =====
// @volundr-dependency mount_hole_spacing -> plate_height
plate_height = mount_hole_spacing + 20;
// ===== VALIDATION =====
assert(mount_hole_spacing > 0);
// ===== MODULES =====
// @volundr-feature mounting_plate
// @volundr-feature mounting_holes
// @volundr-geometry type=hole_group count=2 diameter=4.5 spacing=mount_hole_spacing axis=z
module mounting_holes() {}
// @volundr-feature reinforcement_ribs
module reinforcement_ribs() {}
// @volundr-output bracket_body_output components=bracket_body
module main_model() {
  cube([80, plate_height, plate_thickness]);
  reinforcement_ribs();
}
// ===== FINAL MODEL =====
main_model();
```
""",
            provider="fake",
            provider_model="fake-planning-model",
        )


class FakeCadRunner:
    async def compile(self, source: str, job_id: str) -> CadCompileResult:
        job_dir = Path("/tmp") / "volundr-fake-plan-jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        source_path = job_dir / "model.scad"
        stl_path = job_dir / "model.stl"
        stdout_path = job_dir / "stdout.log"
        stderr_path = job_dir / "stderr.log"
        metadata_path = job_dir / "metadata.json"
        source_path.write_text(source, encoding="utf-8")
        mesh = trimesh.creation.box(extents=(80.0, 80.0, 6.0))
        mesh.apply_translation([40.0, 40.0, 3.0])
        mesh.export(stl_path)
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text("Compilation finished", encoding="utf-8")
        metadata_path.write_text("{}", encoding="utf-8")
        metadata = MeshMetadata(
            size_x_mm=80.0,
            size_y_mm=80.0,
            size_z_mm=6.0,
            volume_mm3=38400.0,
            triangle_count=12,
            connected_components=1,
            is_watertight=True,
            is_winding_consistent=True,
            center_of_mass=(40.0, 40.0, 3.0),
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
    provider: PlanningAiProvider,
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
    app.dependency_overrides[get_ai_provider] = lambda: provider
    app.dependency_overrides[get_cad_runner] = lambda: FakeCadRunner()
    return TestClient(app), TestingSessionLocal


def teardown_function() -> None:
    app.dependency_overrides.clear()


def create_project_and_spec(client: TestClient) -> tuple[dict[str, Any], dict[str, Any]]:
    project = client.post(
        "/api/projects",
        json={"name": "Planned bracket", "original_intent": "Create a configurable bracket."},
    ).json()
    specification = client.post(
        f"/api/projects/{project['id']}/requirements",
        json={"user_instruction": "Create a configurable bracket with 60 mm hole spacing."},
    ).json()
    return project, specification


def test_ready_specification_creates_immutable_design_plan(tmp_path: Path) -> None:
    provider = PlanningAiProvider(READY_PLAN)
    client, SessionLocal = build_client(tmp_path, provider)
    project, specification = create_project_and_spec(client)

    response = client.post(f"/api/design-specifications/{specification['id']}/design-plan")

    assert response.status_code == 201
    plan = response.json()
    assert plan["schema_version"] == "1.0"
    assert plan["design_specification_id"] == specification["id"]
    assert plan["version_number"] == 1
    assert plan["review_state"] == "pending_review"
    assert plan["outcome"] == "plan_ready"
    assert plan["plan"]["design_level"] == "product"
    assert plan["plan"]["parameters"][0]["id"] == "mount_hole_spacing"
    assert plan["plan"]["dependency_edges"][0]["from"] == "mount_hole_spacing"
    assert plan["plan"]["components"][0]["id"] == "bracket_body"
    assert plan["plan"]["printable_outputs"][0]["id"] == "bracket_body_output"
    assert plan["content_hash"]

    with SessionLocal() as session:
        attempt = session.scalar(select(GenerationAttempt).order_by(GenerationAttempt.attempt_number.desc()))
        assert attempt is not None
        assert attempt.prompt_template_version == "design-plan-v1"
        assert attempt.design_plan_path is not None

    run_dir = tmp_path / "data" / "projects" / project["id"] / "generation-runs" / attempt.id
    assert (run_dir / "raw-output.txt").exists()
    assert json.loads((run_dir / "parsed-design-plan.json").read_text(encoding="utf-8"))["outcome"] == "plan_ready"


def test_design_plan_clarification_is_not_a_generation_failure(tmp_path: Path) -> None:
    provider = PlanningAiProvider(PLAN_CLARIFICATION)
    client, _SessionLocal = build_client(tmp_path, provider)
    _project, specification = create_project_and_spec(client)

    response = client.post(f"/api/design-specifications/{specification['id']}/design-plan")

    assert response.status_code == 201
    plan = response.json()
    assert plan["outcome"] == "plan_clarification_required"
    assert plan["review_state"] == "clarification_required"
    assert plan["clarification_required"] is True
    assert plan["plan"]["clarification_questions"][0]["question"].startswith("Should the lid")
    assert provider.generation_requests == []


def test_approval_required_before_generating_from_design_plan(tmp_path: Path) -> None:
    provider = PlanningAiProvider(READY_PLAN)
    client, _SessionLocal = build_client(tmp_path, provider)
    _project, specification = create_project_and_spec(client)
    plan = client.post(f"/api/design-specifications/{specification['id']}/design-plan").json()

    rejected = client.post(f"/api/design-plans/{plan['id']}/generate")

    assert rejected.status_code == 409
    assert "approved" in rejected.json()["detail"]
    assert provider.generation_requests == []


def test_approved_design_plan_generates_candidate_from_plan_authority(tmp_path: Path) -> None:
    provider = PlanningAiProvider(READY_PLAN)
    client, SessionLocal = build_client(tmp_path, provider)
    project, specification = create_project_and_spec(client)
    plan = client.post(f"/api/design-specifications/{specification['id']}/design-plan").json()

    approved = client.post(f"/api/design-plans/{plan['id']}/approve").json()
    response = client.post(f"/api/design-plans/{plan['id']}/generate")

    assert approved["review_state"] == "approved"
    assert response.status_code == 201
    candidate = response.json()
    assert candidate["source_type"] == "ai_initial"
    assert candidate["design_specification_id"] == specification["id"]
    assert len(provider.generation_requests) == 1
    assert provider.generation_requests[0].design_plan["components"][0]["id"] == "bracket_body"
    assert provider.generation_requests[0].design_specification["purpose"] == READY_SPEC["purpose"]
    assert client.get(f"/api/projects/{project['id']}").json()["active_revision_id"] is None

    with SessionLocal() as session:
        attempts = list(session.scalars(select(GenerationAttempt).order_by(GenerationAttempt.attempt_number)))
        assert attempts[-1].prompt_template_version == "openscad-generation-v4"
        assert attempts[-1].design_plan_path is not None


def test_invalid_design_plan_json_is_classified_and_bounded_repair_attempted(tmp_path: Path) -> None:
    provider = PlanningAiProvider("{not-json", READY_PLAN)
    client, SessionLocal = build_client(tmp_path, provider)
    _project, specification = create_project_and_spec(client)

    response = client.post(f"/api/design-specifications/{specification['id']}/design-plan")

    assert response.status_code == 201
    assert response.json()["outcome"] == "plan_ready"
    assert len(provider.plan_requests) == 2
    assert provider.plan_requests[1].schema_repair_of_raw_output == "{not-json"
    with SessionLocal() as session:
        attempts = list(session.scalars(select(GenerationAttempt).order_by(GenerationAttempt.attempt_number)))
        assert [attempt.status for attempt in attempts[-2:]] == ["failed", "succeeded"]
        assert attempts[-2].failure_class == "design_plan_invalid"


def test_replanning_supersedes_prior_unapproved_plan(tmp_path: Path) -> None:
    first = {**READY_PLAN, "purpose": "First plan"}
    second = {**READY_PLAN, "purpose": "Second plan"}
    provider = PlanningAiProvider(first, second)
    client, _SessionLocal = build_client(tmp_path, provider)
    _project, specification = create_project_and_spec(client)

    first_plan = client.post(f"/api/design-specifications/{specification['id']}/design-plan").json()
    second_plan = client.post(f"/api/design-specifications/{specification['id']}/design-plan").json()

    assert second_plan["version_number"] == 2
    assert second_plan["superseded_design_plan_id"] == first_plan["id"]
    assert client.post(f"/api/design-plans/{first_plan['id']}/approve").status_code == 409
