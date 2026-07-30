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
from app.core.config import settings
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
from app.services.cad.cadquery_runner import CadQueryCompileResult, CadQueryOutputResult
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


CADQUERY_CONFIGURABLE_SOURCE = """
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product

PARAMETERS = [
    ParameterSpec(id="body_width", label="Body width", type="float", default=80.0, unit="mm", min_value=50.0, max_value=120.0, editable=True, protected=True),
    ParameterSpec(id="slot_count", label="Slot count", type="int", default=4, min_value=1.0, max_value=12.0, editable=True),
    ParameterSpec(id="lid_enabled", label="Include lid", type="bool", default=True, editable=True),
    ParameterSpec(id="fit_class", label="Fit class", type="enum", default="standard", choices=("loose", "standard", "tight"), editable=True),
    ParameterSpec(id="wall_thickness", label="Wall thickness", type="float", default=3.0, unit="mm", min_value=1.6, max_value=5.0, editable=False, protected=True),
]


def build(params):
    body = cq.Workplane("XY").box(float(params["body_width"]), 50, float(params["wall_thickness"]))
    lid = cq.Workplane("XY").box(float(params["body_width"]), 50, 3)
    return Product(
        parameters=PARAMETERS,
        outputs=[
            PrintableOutput(output_id="body", label="Body", component_id="body", component_ids=("body",), model=body, expected_solid_count=1),
            PrintableOutput(output_id="lid", label="Lid", component_id="lid", component_ids=("lid",), model=lid, expected_solid_count=1),
        ],
    )
"""


class ConfigurationProvider:
    def __init__(self) -> None:
        self.cadquery_requests: list[ModelGenerationRequest] = []

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
        return "cadquery-generation-v1"

    def cadquery_prompt_template_version(self) -> str:
        return "cadquery-generation-v1"

    def build_requirement_prompt(self, request: RequirementExtractionRequest) -> str:
        return "requirements prompt"

    def build_design_plan_prompt(self, request: DesignPlanRequest) -> str:
        return "design plan prompt"

    def build_prompt(self, request: ModelGenerationRequest) -> str:
        return "model prompt"

    def build_cadquery_prompt(self, request: ModelGenerationRequest) -> str:
        return "cadquery model prompt"

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
        raise AssertionError("CadQuery generation must use generate_cadquery_model")

    async def generate_cadquery_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        self.cadquery_requests.append(request)
        return ModelGenerationResult(
            raw_output=f"```python\n{CADQUERY_CONFIGURABLE_SOURCE}\n```",
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
        parameter_values: dict[str, Any] | None = None,
        requested_outputs: list[dict[str, Any]] | None = None,
    ) -> CadQueryCompileResult:
        return self._compile_cadquery(
            source=source,
            job_id=job_id,
            parameter_values=parameter_values or {},
            requested_outputs=requested_outputs or [],
        )

    def _compile_cadquery(
        self,
        *,
        source: str,
        job_id: str,
        parameter_values: dict[str, Any],
        requested_outputs: list[dict[str, Any]],
    ) -> CadQueryCompileResult:
        self.calls.append(
            {
                "job_id": job_id,
                "source_hash": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                "parameter_values": dict(parameter_values),
                "requested_outputs": list(requested_outputs),
            }
        )
        job_dir = Path("/tmp") / "volundr-fake-cadquery-configuration-jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        source_path = job_dir / "model.py"
        stdout_path = job_dir / "stdout.log"
        stderr_path = job_dir / "stderr.log"
        source_path.write_text(source, encoding="utf-8")
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text("Compilation finished", encoding="utf-8")
        body_width = float(parameter_values.get("body_width", 80))
        outputs: list[CadQueryOutputResult] = []
        first_stl: Path | None = None
        first_step: Path | None = None
        first_metadata: Path | None = None
        for requested in requested_outputs:
            output_id = requested["output_id"]
            stl_path = job_dir / f"{output_id}.stl"
            step_path = job_dir / f"{output_id}.step"
            brep_path = job_dir / f"{output_id}.brep"
            metadata_path = job_dir / f"{output_id}-metadata.json"
            topology_path = job_dir / f"{output_id}-topology.json"
            thickness = 3.0 if output_id == "body" else 4.0
            extents = (body_width, 50.0, thickness)
            mesh = trimesh.creation.box(extents=extents)
            mesh.apply_translation([extents[0] / 2, extents[1] / 2, extents[2] / 2])
            mesh.export(stl_path)
            step_path.write_text("step", encoding="utf-8")
            brep_path.write_text("brep", encoding="utf-8")
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
            topology = {
                "valid": True,
                "detected_solid_count": 1,
                "expected_solid_count": 1,
            }
            metadata_path.write_text(json.dumps(metadata.__dict__), encoding="utf-8")
            topology_path.write_text(json.dumps(topology), encoding="utf-8")
            outputs.append(
                CadQueryOutputResult(
                    output_id=output_id,
                    entrypoint=output_id,
                    required=bool(requested.get("required", True)),
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
            )
            first_stl = first_stl or stl_path
            first_step = first_step or step_path
            first_metadata = first_metadata or metadata_path
        return CadQueryCompileResult(
            job_id=job_id,
            success=True,
            timed_out=False,
            exit_code=0,
            source_path=source_path,
            stl_path=first_stl,
            step_path=first_step,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            metadata_path=first_metadata,
            source_hash=hashlib.sha256(source.encode("utf-8")).hexdigest(),
            output_size_bytes=sum(output.output_size_bytes for output in outputs),
            metadata=outputs[0].metadata if outputs else None,
            error_message=None,
            command_args=["python", "_volundr_cadquery_runner.py"],
            outputs=outputs,
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


def test_configuration_generation_uses_parameter_values_without_legacy_provider_and_keeps_active_revision(
    tmp_path: Path,
) -> None:
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
    assert change["validation_state"] == "configuration_ready"

    generated = client.post(f"/api/configuration-changes/{change['id']}/generate")

    assert generated.status_code == 201
    revision = generated.json()
    assert revision["configuration_change_id"] == change["id"]
    assert revision["review_state"] in {"ready", "ready_with_warnings"}
    assert len(runner.calls) == 1
    assert runner.calls[0]["parameter_values"]["body_width"] == 100
    assert runner.calls[0]["parameter_values"]["slot_count"] == 5
    assert "defines" not in runner.calls[0]
    refreshed_project = client.get(f"/api/projects/{context['project']['id']}").json()
    assert refreshed_project["active_revision_id"] == context["revision"]["id"]


def test_cadquery_configuration_generation_uses_parameter_values_without_provider(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(settings, "generation_mode", "advanced")
    provider = ConfigurationProvider()
    runner = ConfigurationRunner()
    client = build_client(tmp_path, provider, runner)
    context = create_accepted_revision(client)
    assert context["revision"]["cad_backend"] == "cadquery"
    base_source_hash = context["revision"]["source_hash"]
    runner.calls.clear()
    provider.generate_cadquery_model = _fail_generate_cadquery_model  # type: ignore[method-assign]
    change = client.post(
        f"/api/projects/{context['project']['id']}/configuration/preview",
        json={"parameter_values": {"body_width": 100, "slot_count": 5}},
    ).json()

    generated = client.post(f"/api/configuration-changes/{change['id']}/generate")

    assert generated.status_code == 201
    revision = generated.json()
    assert revision["configuration_change_id"] == change["id"]
    assert revision["cad_backend"] == "cadquery"
    assert revision["source_language"] == "python"
    assert revision["source_hash"] == base_source_hash
    assert len(runner.calls) == 1
    assert runner.calls[0]["parameter_values"]["body_width"] == 100
    assert runner.calls[0]["parameter_values"]["slot_count"] == 5
    assert runner.calls[0]["parameter_values"]["wall_thickness"] == 3
    assert {output["output_id"] for output in runner.calls[0]["requested_outputs"]} == {"body", "lid"}
    assert "defines" not in runner.calls[0]
    manifest = client.get(f"/api/configuration-changes/{change['id']}/override-manifest").json()
    assert manifest["cad_backend"] == "cadquery"
    assert manifest["source_language"] == "python"
    assert manifest["parameter_values"]["body_width"] == 100
    assert manifest["parameter_values"]["slot_count"] == 5
    assert manifest["parameter_hash"]


def test_cadquery_configuration_parameters_and_hash_are_stable(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(settings, "generation_mode", "advanced")
    provider = ConfigurationProvider()
    runner = ConfigurationRunner()
    client = build_client(tmp_path, provider, runner)
    context = create_accepted_revision(client)

    parameters_response = client.get(f"/api/projects/{context['project']['id']}/configuration/parameters")
    first_change = client.post(
        f"/api/projects/{context['project']['id']}/configuration/preview",
        json={"parameter_values": {"body_width": 100, "slot_count": 5}},
    ).json()
    second_change = client.post(
        f"/api/projects/{context['project']['id']}/configuration/preview",
        json={"parameter_values": {"slot_count": 5, "body_width": 100}},
    ).json()

    assert parameters_response.status_code == 200
    parameters = {parameter["id"]: parameter for parameter in parameters_response.json()}
    assert parameters["body_width"]["source_mapped"] is True
    assert parameters["wall_thickness"]["editable"] is False
    assert first_change["validation_state"] == "configuration_ready"
    assert second_change["validation_state"] == "configuration_ready"
    first_manifest = client.get(f"/api/configuration-changes/{first_change['id']}/override-manifest").json()
    second_manifest = client.get(f"/api/configuration-changes/{second_change['id']}/override-manifest").json()
    assert first_manifest["parameter_values"] == second_manifest["parameter_values"]
    assert first_manifest["parameter_hash"] == second_manifest["parameter_hash"]


async def _fail_generate_model(request: ModelGenerationRequest) -> ModelGenerationResult:
    raise AssertionError("configuration generation must not call Gemini")


async def _fail_generate_cadquery_model(request: ModelGenerationRequest) -> ModelGenerationResult:
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
