import hashlib
import json
import zipfile
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
    "object_type": "configurable_box",
    "purpose": "Hold electronics in a configurable body with a lid",
    "units": "mm",
    "supported_scope": True,
    "critical_dimensions": [
        {
            "id": "body_width",
            "label": "Body width",
            "value": 80,
            "unit": "mm",
            "source": "user",
            "importance": "critical",
            "protected": True,
        }
    ],
    "parameters": [],
    "functional_requirements": [
        {
            "id": "body_and_lid",
            "description": "A printable body and lid",
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
    "design_level": "assembly",
    "product_type": "electronics_enclosure",
    "purpose": "Hold electronics in a configurable body with a lid",
    "units": "mm",
    "parameters": [
        {
            "id": "body_width",
            "label": "Body width",
            "value": 80,
            "unit": "mm",
            "type": "number",
            "minimum": 50,
            "maximum": 120,
            "editable": True,
            "protected": True,
            "component_id": "body",
            "description": "Outer body width.",
            "source_requirement_id": "body_width",
        },
        {
            "id": "slot_count",
            "label": "Slot count",
            "value": 4,
            "type": "integer",
            "minimum": 1,
            "maximum": 12,
            "editable": True,
            "protected": False,
            "component_id": "body",
        },
        {
            "id": "lid_enabled",
            "label": "Include lid",
            "value": True,
            "type": "boolean",
            "editable": True,
            "protected": False,
            "component_id": "lid",
        },
        {
            "id": "fit_class",
            "label": "Fit class",
            "value": "standard",
            "type": "enum",
            "allowed_values": ["loose", "standard", "tight"],
            "editable": True,
            "protected": False,
            "component_id": "lid",
        },
        {
            "id": "wall_thickness",
            "label": "Wall thickness",
            "value": 3,
            "unit": "mm",
            "type": "number",
            "minimum": 1.6,
            "maximum": 5,
            "editable": False,
            "protected": True,
            "component_id": "body",
        },
    ],
    "derived_parameters": [
        {
            "id": "slot_spacing",
            "label": "Slot spacing",
            "expression": "body_width / slot_count",
            "unit": "mm",
            "depends_on": ["body_width", "slot_count"],
        }
    ],
    "dependency_edges": [
        {"from": "body_width", "to": "slot_spacing", "relationship": "Width controls spacing"},
        {"from": "slot_count", "to": "slot_spacing", "relationship": "Count controls spacing"},
    ],
    "components": [
        {
            "id": "body",
            "label": "Body",
            "description": "Configurable body",
            "features": ["body_shell"],
            "parameters": ["body_width", "slot_count", "wall_thickness", "slot_spacing"],
        },
        {
            "id": "lid",
            "label": "Lid",
            "description": "Lid",
            "features": ["lid_panel"],
            "parameters": ["body_width", "lid_enabled", "fit_class"],
        },
    ],
    "features": [
        {
            "id": "body_shell",
            "component_id": "body",
            "type": "shell",
            "description": "Body shell",
            "parameters": ["body_width", "slot_count", "slot_spacing"],
            "protected": True,
        },
        {
            "id": "lid_panel",
            "component_id": "lid",
            "type": "cover",
            "description": "Lid panel",
            "parameters": ["body_width", "lid_enabled", "fit_class"],
            "protected": False,
        },
    ],
    "presets": [
        {
            "id": "wide",
            "label": "Wide",
            "parameter_values": {"body_width": 100, "slot_count": 5},
        }
    ],
    "assembly_strategy": {"type": "separate_parts", "relationships": []},
    "printable_outputs": [
        {
            "id": "body",
            "label": "Body",
            "component_id": "body",
            "component_ids": ["body"],
            "module_name": "body",
            "filename": "body.stl",
            "quantity": 1,
            "required": True,
            "output_type": "printable_component",
        },
        {
            "id": "lid",
            "label": "Lid",
            "component_id": "lid",
            "component_ids": ["lid"],
            "module_name": "lid",
            "filename": "lid.stl",
            "quantity": 1,
            "required": True,
            "output_type": "printable_component",
        },
    ],
    "risks": [],
    "clarification_required": False,
    "clarification_questions": [],
    "plan_ready": True,
    "outcome": "plan_ready",
}


CONFIGURABLE_SOURCE = """
/*
Project: Configurable box
Units: millimeters
Purpose: electronics enclosure
Assumptions: none
Print notes: print flat
*/
// ===== QUALITY =====
$fn = 48;
selected_output = "body";
// ===== USER PARAMETERS =====
// @volundr-requirement body_width
// @volundr-parameter body_width type=number editable=true
body_width = 80;
// @volundr-parameter slot_count type=integer editable=true
slot_count = 4;
// @volundr-parameter lid_enabled type=boolean editable=true
lid_enabled = true;
// @volundr-parameter fit_class type=enum editable=true
fit_class = "standard";
// @volundr-parameter wall_thickness type=number editable=false
wall_thickness = 3;
// ===== DERIVED VALUES =====
// @volundr-dependency body_width -> slot_spacing
// @volundr-dependency slot_count -> slot_spacing
slot_spacing = body_width / slot_count;
lid_thickness = 3;
// ===== VALIDATION =====
assert(body_width >= 50 && body_width <= 120, "body_width outside supported configuration range");
assert(slot_count >= 1 && slot_count <= 12, "slot_count outside supported configuration range");
assert(selected_output == "body" || selected_output == "lid", "Unknown selected_output");
// ===== MODULES =====
// @volundr-feature body_and_lid @volundr-feature body_shell
// @volundr-component body
// @volundr-geometry type=bounds component=body x=body_width y=50 z=wall_thickness
// @volundr-output body module=body required=true filename=body.stl components=body
module body() { cube([body_width, 50, wall_thickness]); }
// @volundr-feature lid_panel
// @volundr-component lid
// @volundr-output lid module=lid required=true filename=lid.stl components=lid
module lid() { cube([body_width, 50, lid_thickness]); }
// ===== FINAL MODEL =====
module render_selected_output() {
  if (selected_output == "body") { body(); }
  else if (selected_output == "lid") { lid(); }
  else { assert(false, str("Unknown selected_output: ", selected_output)); }
}
render_selected_output();
"""


class ConfigurationProvider:
    @property
    def ruleset_version(self) -> str:
        return "gemini-ruleset-v1"

    def provider_settings(self) -> dict[str, Any]:
        return {"model": "fake-config-model"}

    def requirement_prompt_template_version(self) -> str:
        return "requirements-v1"

    def design_plan_prompt_template_version(self) -> str:
        return "design-plan-v1"

    def revision_plan_prompt_template_version(self) -> str:
        return "revision-planning-v1"

    def prompt_template_version_for(self, request: ModelGenerationRequest) -> str:
        return "openscad-generation-v5"

    def build_requirement_prompt(self, request: RequirementExtractionRequest) -> str:
        return "requirements prompt"

    def build_design_plan_prompt(self, request: DesignPlanRequest) -> str:
        return "design plan prompt"

    def build_prompt(self, request: ModelGenerationRequest) -> str:
        return "model prompt"

    async def extract_requirements(self, request: RequirementExtractionRequest) -> RequirementExtractionResult:
        return RequirementExtractionResult(
            raw_output=json.dumps(READY_SPEC),
            provider="fake",
            provider_model="fake-config-model",
        )

    async def create_design_plan(self, request: DesignPlanRequest) -> DesignPlanResult:
        return DesignPlanResult(
            raw_output=json.dumps(READY_PLAN),
            provider="fake",
            provider_model="fake-config-model",
        )

    async def generate_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        return ModelGenerationResult(
            raw_output=f"```openscad\n{CONFIGURABLE_SOURCE}\n```",
            provider="fake",
            provider_model="fake-config-model",
        )


class ConfigurationRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def compile(
        self,
        source: str,
        job_id: str,
        *,
        selected_output: str | None = None,
        defines: dict[str, str | int | float | bool] | None = None,
    ) -> CadCompileResult:
        output_id = selected_output or "body"
        defines = defines or {}
        self.calls.append(
            {
                "job_id": job_id,
                "source_hash": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                "selected_output": output_id,
                "defines": dict(defines),
            }
        )
        job_dir = Path("/tmp") / "volundr-fake-configuration-jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        source_path = job_dir / "model.scad"
        stl_path = job_dir / f"{output_id}.stl"
        stdout_path = job_dir / "stdout.log"
        stderr_path = job_dir / "stderr.log"
        metadata_path = job_dir / "metadata.json"
        source_path.write_text(source, encoding="utf-8")
        stdout_path.write_text("", encoding="utf-8")
        body_width = float(defines.get("body_width", 80))
        thickness = 3.0 if output_id == "body" else 4.0
        extents = (body_width, 50.0, thickness)
        mesh = trimesh.creation.box(extents=extents)
        mesh.apply_translation([extents[0] / 2, extents[1] / 2, extents[2] / 2])
        mesh.export(stl_path)
        stderr_path.write_text("Compilation finished", encoding="utf-8")
        metadata = MeshMetadata(
            size_x_mm=extents[0],
            size_y_mm=extents[1],
            size_z_mm=extents[2],
            volume_mm3=extents[0] * extents[1] * extents[2],
            triangle_count=12,
            connected_components=1,
            is_watertight=True,
            is_winding_consistent=True,
            center_of_mass=(extents[0] / 2, extents[1] / 2, extents[2] / 2),
        )
        metadata_path.write_text(json.dumps(metadata.__dict__), encoding="utf-8")
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
            source_hash=hashlib.sha256(source.encode("utf-8")).hexdigest(),
            output_size_bytes=stl_path.stat().st_size,
            metadata=metadata,
            error_message=None,
            command_args=["openscad", "-D", f'selected_output="{output_id}"'],
        )


def build_client(
    tmp_path: Path,
    provider: ConfigurationProvider,
    runner: ConfigurationRunner,
) -> TestClient:
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
    app.dependency_overrides[get_cad_runner] = lambda: runner
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def create_accepted_revision(client: TestClient) -> dict[str, Any]:
    project = client.post(
        "/api/projects",
        json={"name": "Configurable box", "original_intent": "Create a configurable box."},
    ).json()
    specification = client.post(
        f"/api/projects/{project['id']}/requirements",
        json={"user_instruction": "Create an 80 mm configurable box."},
    ).json()
    plan = client.post(f"/api/design-specifications/{specification['id']}/design-plan").json()
    approved_plan = client.post(f"/api/design-plans/{plan['id']}/approve").json()
    candidate = client.post(f"/api/design-plans/{approved_plan['id']}/generate").json()
    accepted = client.post(f"/api/candidates/{candidate['id']}/accept").json()
    return {
        "project": client.get(f"/api/projects/{project['id']}").json(),
        "specification": specification,
        "design_plan": approved_plan,
        "revision": accepted,
    }


def test_lists_editable_configuration_parameters_with_source_mapping(tmp_path: Path) -> None:
    client = build_client(tmp_path, ConfigurationProvider(), ConfigurationRunner())
    context = create_accepted_revision(client)

    response = client.get(f"/api/projects/{context['project']['id']}/configuration/parameters")

    assert response.status_code == 200
    parameters = response.json()
    by_id = {parameter["id"]: parameter for parameter in parameters}
    assert by_id["body_width"]["type"] == "number"
    assert by_id["body_width"]["editable"] is True
    assert by_id["body_width"]["source_mapped"] is True
    assert by_id["slot_count"]["type"] == "integer"
    assert by_id["lid_enabled"]["type"] == "boolean"
    assert by_id["fit_class"]["allowed_values"] == ["loose", "standard", "tight"]


def test_preview_configuration_change_persists_dependency_effects(tmp_path: Path) -> None:
    client = build_client(tmp_path, ConfigurationProvider(), ConfigurationRunner())
    context = create_accepted_revision(client)

    response = client.post(
        f"/api/projects/{context['project']['id']}/configuration/preview",
        json={"parameter_values": {"body_width": 100, "slot_count": 5}},
    )

    assert response.status_code == 201
    change = response.json()
    assert change["validation_state"] == "configuration_ready"
    assert change["resolved_parameters"]["body_width"] == 100
    assert "slot_spacing" in change["affected_parameters"]
    assert set(change["affected_outputs"]) == {"body", "lid"}
    assert change["generated_revision_id"] is None


def test_invalid_and_structural_configuration_changes_do_not_compile(tmp_path: Path) -> None:
    runner = ConfigurationRunner()
    client = build_client(tmp_path, ConfigurationProvider(), runner)
    context = create_accepted_revision(client)
    runner.calls.clear()

    invalid = client.post(
        f"/api/projects/{context['project']['id']}/configuration/preview",
        json={"parameter_values": {"slot_count": 2.5}},
    ).json()
    structural = client.post(
        f"/api/projects/{context['project']['id']}/configuration/preview",
        json={"parameter_values": {"new_handle": True}},
    ).json()

    assert invalid["validation_state"] == "invalid_configuration"
    assert structural["validation_state"] == "requires_design_revision"
    assert runner.calls == []


def test_configuration_generation_uses_defines_without_provider_and_keeps_active_revision(tmp_path: Path) -> None:
    provider = ConfigurationProvider()
    runner = ConfigurationRunner()
    client = build_client(tmp_path, provider, runner)
    context = create_accepted_revision(client)
    runner.calls.clear()
    provider.generate_model = _fail_generate_model  # type: ignore[method-assign]
    change = client.post(
        f"/api/projects/{context['project']['id']}/configuration/preview",
        json={"parameter_values": {"body_width": 100, "slot_count": 5}},
    ).json()

    generated = client.post(f"/api/configuration-changes/{change['id']}/generate")

    assert generated.status_code == 201
    revision = generated.json()
    assert revision["configuration_change_id"] == change["id"]
    assert revision["review_state"] in {"ready", "ready_with_warnings"}
    assert all(call["defines"]["body_width"] == 100 for call in runner.calls)
    assert all(call["defines"]["slot_count"] == 5 for call in runner.calls)
    refreshed_project = client.get(f"/api/projects/{context['project']['id']}").json()
    assert refreshed_project["active_revision_id"] == context["revision"]["id"]


async def _fail_generate_model(request: ModelGenerationRequest) -> ModelGenerationResult:
    raise AssertionError("configuration generation must not call Gemini")


def test_project_local_preset_and_export_include_configuration_files(tmp_path: Path) -> None:
    client = build_client(tmp_path, ConfigurationProvider(), ConfigurationRunner())
    context = create_accepted_revision(client)
    preset = client.post(
        f"/api/projects/{context['project']['id']}/configuration/presets",
        json={
            "design_plan_id": context["design_plan"]["id"],
            "preset_id": "five_slot",
            "label": "Five slot",
            "parameter_values": {"slot_count": 5, "body_width": 100},
        },
    ).json()
    change = client.post(
        f"/api/projects/{context['project']['id']}/configuration/preview",
        json={"selected_preset_id": preset["preset_id"], "user_overrides": {"fit_class": "loose"}},
    ).json()
    revision = client.post(f"/api/configuration-changes/{change['id']}/generate").json()

    manifest = client.get(f"/api/configuration-changes/{change['id']}/override-manifest").json()
    assert manifest["selected_preset_id"] == "five_slot"
    assert manifest["user_overrides"] == {"fit_class": "loose"}
    export_response = client.get(f"/api/revisions/{revision['id']}/export.zip")
    assert export_response.status_code == 200
    export_path = tmp_path / "export.zip"
    export_path.write_bytes(export_response.content)
    with zipfile.ZipFile(export_path) as archive:
        names = archive.namelist()
        assert any(name.endswith("/configuration.json") for name in names)
        assert any(name.endswith("/parameter-overrides.json") for name in names)
