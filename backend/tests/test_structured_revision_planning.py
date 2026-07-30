import copy
import hashlib
import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
import trimesh
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_ai_provider, get_cad_runner, get_data_dir
from app.core.config import settings
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
from app.services.cad.cadquery_runner import CadQueryCompileResult, CadQueryOutputResult
from app.services.mesh.inspect import MeshMetadata


READY_SPEC: dict[str, Any] = {
    "schema_version": "1.0",
    "object_type": "two_part_box",
    "purpose": "Hold electronics in a body with a lid",
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
            "description": "A printable body and separate lid",
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
    "purpose": "Hold electronics in a body with a lid",
    "units": "mm",
    "parameters": [
        {
            "id": "body_width",
            "label": "Body width",
            "value": 80,
            "unit": "mm",
            "source_requirement_id": "body_width",
            "editable": True,
            "protected": True,
            "component_id": "body",
        },
        {
            "id": "lid_thickness",
            "label": "Lid thickness",
            "value": 3,
            "unit": "mm",
            "editable": True,
            "protected": False,
            "component_id": "lid",
        },
        {
            "id": "wall_thickness",
            "label": "Wall thickness",
            "value": 3,
            "unit": "mm",
            "editable": True,
            "protected": True,
            "component_id": "body",
        },
    ],
    "derived_parameters": [
        {
            "id": "lid_lip_depth",
            "label": "Lid lip depth",
            "expression": "lid_thickness + 2",
            "unit": "mm",
            "depends_on": ["lid_thickness"],
        }
    ],
    "dependency_edges": [
        {
            "from": "lid_thickness",
            "to": "lid_lip_depth",
            "relationship": "lid thickness controls lid lip depth",
        }
    ],
    "components": [
        {
            "id": "body",
            "label": "Body",
            "description": "Main enclosure body",
            "features": ["body_shell"],
            "parameters": ["body_width", "wall_thickness"],
        },
        {
            "id": "lid",
            "label": "Lid",
            "description": "Removable enclosure lid",
            "features": ["lid_panel"],
            "parameters": ["body_width", "lid_thickness"],
        },
    ],
    "features": [
        {
            "id": "body_shell",
            "component_id": "body",
            "type": "shell",
            "description": "Open electronics body",
            "parameters": ["body_width", "wall_thickness"],
            "protected": True,
        },
        {
            "id": "lid_panel",
            "component_id": "lid",
            "type": "cover",
            "description": "Flat removable lid",
            "parameters": ["body_width", "lid_thickness"],
            "protected": True,
        },
    ],
    "presets": [],
    "assembly_strategy": {
        "type": "separate_parts",
        "relationships": [{"from_component_id": "lid", "to_component_id": "body", "relationship": "fits over"}],
    },
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


CADQUERY_BASE_SOURCE = """
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product

PARAMETERS = [
    ParameterSpec(id="body_width", label="Body width", type="float", default=80.0, unit="mm", editable=True, protected=True),
    ParameterSpec(id="lid_thickness", label="Lid thickness", type="float", default=3.0, unit="mm", editable=True),
    ParameterSpec(id="wall_thickness", label="Wall thickness", type="float", default=3.0, unit="mm", editable=True, protected=True),
]


def body_model(params):
    return cq.Workplane("XY").box(float(params["body_width"]), 50, float(params["wall_thickness"]))


def lid_model(params):
    return cq.Workplane("XY").box(float(params["body_width"]), 50, float(params["lid_thickness"]))


def build(params):
    body = body_model(params)
    lid = lid_model(params)
    return Product(
        parameters=PARAMETERS,
        outputs=[
            PrintableOutput(output_id="body", label="Body", component_id="body", component_ids=("body",), model=body, expected_solid_count=1),
            PrintableOutput(output_id="lid", label="Lid", component_id="lid", component_ids=("lid",), model=lid, expected_solid_count=1),
        ],
    )
"""


CADQUERY_REVISED_SOURCE = CADQUERY_BASE_SOURCE.replace(
    'ParameterSpec(id="lid_thickness", label="Lid thickness", type="float", default=3.0',
    'ParameterSpec(id="lid_thickness", label="Lid thickness", type="float", default=4.0',
)


CADQUERY_UNAUTHORIZED_SOURCE = CADQUERY_REVISED_SOURCE.replace(
    'ParameterSpec(id="wall_thickness", label="Wall thickness", type="float", default=3.0',
    'ParameterSpec(id="wall_thickness", label="Wall thickness", type="float", default=5.0',
)


def ready_revision_plan() -> dict[str, Any]:
    return {
        "schema_version": "revision-plan-v1",
        "reason": "parameter_change",
        "summary": "Increase lid thickness from 3 mm to 4 mm",
        "requested_changes": [
            {
                "target_type": "product_parameter",
                "target_id": "lid_thickness",
                "current_value": 3,
                "requested_value": 4,
                "change_type": "replace",
                "source": "user",
            }
        ],
        "targeted_components": ["lid"],
        "targeted_features": ["lid_panel"],
        "targeted_outputs": ["lid"],
        "targeted_findings": [],
        "allowed_parameter_changes": ["lid_thickness"],
        "required_dependency_changes": [],
        "allowed_component_changes": ["lid"],
        "allowed_feature_changes": ["lid_panel"],
        "protected_parameters": [
            {"parameter_id": "body_width", "expected_value": 80, "unit": "mm"},
            {"parameter_id": "wall_thickness", "expected_value": 3, "unit": "mm"},
        ],
        "protected_components": ["body"],
        "protected_features": ["body_shell"],
        "protected_outputs": ["body"],
        "prohibited_changes": ["Do not change body width", "Do not change wall thickness"],
        "success_criteria": [
            {"type": "parameter_value", "target_id": "lid_thickness", "expected_value": 4, "unit": "mm"},
            {
                "type": "parameter_unchanged",
                "target_id": "wall_thickness",
                "expected_value": 3,
                "unit": "mm",
            },
            {"type": "output_exists", "target_id": "lid"},
        ],
        "requires_design_specification_version": False,
        "requires_design_plan_version": False,
        "clarification_questions": [],
        "outcome": "revision_ready",
    }


CLARIFICATION_PLAN = {
    **ready_revision_plan(),
    "summary": "Clarify lid change",
    "requested_changes": [],
    "clarification_questions": [
        {
            "id": "lid_thickness_value",
            "question": "What lid thickness should Volundr use?",
            "reason": "The requested value is missing.",
            "related_requirement_id": "lid_thickness",
        }
    ],
    "outcome": "clarification_required",
}


class RevisionPlanningProvider:
    def __init__(
        self,
        *,
        plan: dict[str, Any] | None = None,
        revised_source: str = CADQUERY_REVISED_SOURCE,
        correction_source: str | None = None,
    ) -> None:
        self.plan = plan or ready_revision_plan()
        self.revised_source = revised_source
        self.correction_source = correction_source
        self.revision_plan_requests: list[Any] = []
        self.generation_requests: list[ModelGenerationRequest] = []
        self.cadquery_requests: list[ModelGenerationRequest] = []

    @property
    def ruleset_version(self) -> str:
        return "gemini-ruleset-v1"

    def provider_settings(self) -> dict[str, Any]:
        return {"model": "fake-revision-model"}

    def requirement_prompt_template_version(self) -> str:
        return "requirements-v1"

    def design_plan_prompt_template_version(self) -> str:
        return "design-plan-v1"

    def revision_plan_prompt_template_version(self) -> str:
        return "revision-planning-v1"

    def prompt_template_version_for(self, request: ModelGenerationRequest) -> str:
        if getattr(request, "scope_diagnostics", None):
            return "cadquery-scope-correction-v1"
        if getattr(request, "revision_plan", None) and getattr(request, "scoped_revision_context", None):
            return "cadquery-component-revision-v1"
        if getattr(request, "revision_plan", None):
            return "cadquery-revision-v1"
        return "cadquery-generation-v1"

    def cadquery_prompt_template_version(self) -> str:
        return "cadquery-generation-v1"

    def build_requirement_prompt(self, request: RequirementExtractionRequest) -> str:
        return "requirements prompt"

    def build_design_plan_prompt(self, request: DesignPlanRequest) -> str:
        return "design plan prompt"

    def build_revision_plan_prompt(self, request: Any) -> str:
        return "revision plan prompt"

    def build_prompt(self, request: ModelGenerationRequest) -> str:
        return "revision source prompt"

    def build_cadquery_prompt(self, request: ModelGenerationRequest) -> str:
        return "cadquery revision source prompt"

    async def extract_requirements(
        self,
        request: RequirementExtractionRequest,
    ) -> RequirementExtractionResult:
        return RequirementExtractionResult(
            raw_output=json.dumps(READY_SPEC),
            provider="fake",
            provider_model="fake-revision-model",
        )

    async def create_design_plan(self, request: DesignPlanRequest) -> DesignPlanResult:
        return DesignPlanResult(
            raw_output=json.dumps(READY_PLAN),
            provider="fake",
            provider_model="fake-revision-model",
        )

    async def create_revision_plan(self, request: Any) -> Any:
        self.revision_plan_requests.append(request)
        return type(
            "RevisionPlanResult",
            (),
            {
                "raw_output": json.dumps(self.plan),
                "provider": "fake",
                "provider_model": "fake-revision-model",
            },
        )()

    async def generate_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        self.generation_requests.append(request)
        raise AssertionError("CadQuery revision generation must use generate_cadquery_model")

    async def generate_cadquery_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        self.cadquery_requests.append(request)
        if getattr(request, "revision_plan", None):
            source = (
                self.correction_source
                if getattr(request, "scope_diagnostics", None) and self.correction_source
                else self.revised_source
            )
        else:
            source = CADQUERY_BASE_SOURCE
        return ModelGenerationResult(
            raw_output=f"```python\n{source}\n```",
            provider="fake",
            provider_model="fake-revision-model",
        )


class MultiOutputCadRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.body_extents: tuple[float, float, float] = (80.0, 50.0, 3.0)
        self.lid_extents: tuple[float, float, float] | None = None

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
        job_dir = Path("/tmp") / "volundr-fake-cadquery-structured-revision-jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        source_path = job_dir / "model.py"
        stdout_path = job_dir / "stdout.log"
        stderr_path = job_dir / "stderr.log"
        source_path.write_text(source, encoding="utf-8")
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text("Compilation finished", encoding="utf-8")
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
            extents = self.body_extents
            if output_id == "lid":
                extents = self.lid_extents or (80.0, 50.0, 4.0)
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
            topology = {"valid": True, "detected_solid_count": 1, "expected_solid_count": 1}
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
    provider: RevisionPlanningProvider,
    runner: MultiOutputCadRunner,
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
    app.dependency_overrides[get_cad_runner] = lambda: runner
    return TestClient(app), TestingSessionLocal


def teardown_function() -> None:
    app.dependency_overrides.clear()


def create_accepted_multi_output_revision(client: TestClient) -> dict[str, Any]:
    project = client.post(
        "/api/projects",
        json={"name": "Two part box", "original_intent": "Create a two-part box."},
    ).json()
    specification = client.post(
        f"/api/projects/{project['id']}/requirements",
        json={"user_instruction": "Create an 80 mm wide two-part electronics box."},
    ).json()
    plan = client.post(f"/api/design-specifications/{specification['id']}/design-plan").json()
    approved_plan = client.post(f"/api/design-plans/{plan['id']}/approve").json()
    initial_candidate = client.post(f"/api/design-plans/{approved_plan['id']}/generate").json()
    accepted = client.post(f"/api/candidates/{initial_candidate['id']}/accept").json()
    refreshed_project = client.get(f"/api/projects/{project['id']}").json()
    assert refreshed_project["active_revision_id"] == accepted["id"]
    return {
        "project": refreshed_project,
        "specification": specification,
        "design_plan": approved_plan,
        "revision": accepted,
    }


def test_precise_parameter_request_creates_ready_revision_plan_without_generation(
    tmp_path: Path,
) -> None:
    provider = RevisionPlanningProvider()
    runner = MultiOutputCadRunner()
    client, _SessionLocal = build_client(tmp_path, provider, runner)
    context = create_accepted_multi_output_revision(client)
    provider.generation_requests.clear()

    response = client.post(
        f"/api/projects/{context['project']['id']}/revision-plans",
        json={
            "base_revision_id": context["revision"]["id"],
            "user_instruction": "Change lid thickness to 4 mm.",
            "reason": "parameter_change",
        },
    )

    assert response.status_code == 201
    plan = response.json()
    assert plan["outcome"] == "revision_ready"
    assert plan["review_state"] == "pending_review"
    assert plan["base_revision_id"] == context["revision"]["id"]
    assert plan["revision_plan"]["allowed_parameter_changes"] == ["lid_thickness"]
    assert plan["revision_plan"]["protected_outputs"] == ["body"]
    assert provider.revision_plan_requests[0].output_manifest["outputs"][0]["output_id"] == "body"
    assert provider.generation_requests == []


def test_ambiguous_revision_request_creates_clarification_state(tmp_path: Path) -> None:
    provider = RevisionPlanningProvider(plan=CLARIFICATION_PLAN)
    runner = MultiOutputCadRunner()
    client, _SessionLocal = build_client(tmp_path, provider, runner)
    context = create_accepted_multi_output_revision(client)

    response = client.post(
        f"/api/projects/{context['project']['id']}/revision-plans",
        json={
            "base_revision_id": context["revision"]["id"],
            "user_instruction": "Make the lid thicker.",
            "reason": "parameter_change",
        },
    )

    assert response.status_code == 201
    plan = response.json()
    assert plan["outcome"] == "clarification_required"
    assert plan["review_state"] == "clarification_required"
    assert plan["clarification_required"] is True
    questions = client.get(f"/api/revision-plans/{plan['id']}/clarification-questions").json()
    assert questions[0]["question"] == "What lid thickness should Volundr use?"


def test_revision_plan_must_be_approved_before_generation(tmp_path: Path) -> None:
    provider = RevisionPlanningProvider()
    runner = MultiOutputCadRunner()
    client, _SessionLocal = build_client(tmp_path, provider, runner)
    context = create_accepted_multi_output_revision(client)
    plan = client.post(
        f"/api/projects/{context['project']['id']}/revision-plans",
        json={
            "base_revision_id": context["revision"]["id"],
            "user_instruction": "Change lid thickness to 4 mm.",
            "reason": "parameter_change",
        },
    ).json()
    provider.generation_requests.clear()

    blocked = client.post(f"/api/revision-plans/{plan['id']}/generate")

    assert blocked.status_code == 409
    assert provider.generation_requests == []


def test_cadquery_approved_revision_plan_generates_candidate_from_revised_source(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(settings, "generation_mode", "advanced")
    provider = RevisionPlanningProvider(
        plan={
            **ready_revision_plan(),
            "allowed_parameter_changes": ["lid_thickness"],
            "required_dependency_changes": [],
        },
        revised_source=CADQUERY_BASE_SOURCE,
    )
    runner = MultiOutputCadRunner()
    client, _SessionLocal = build_client(tmp_path, provider, runner)
    context = create_accepted_multi_output_revision(client)
    assert context["revision"]["cad_backend"] == "cadquery"
    provider.revised_source = CADQUERY_REVISED_SOURCE
    provider.generate_model = _fail_generate_model  # type: ignore[method-assign]
    provider.cadquery_requests.clear()
    runner.calls.clear()
    plan = client.post(
        f"/api/projects/{context['project']['id']}/revision-plans",
        json={
            "base_revision_id": context["revision"]["id"],
            "user_instruction": "Change lid thickness to 4 mm.",
            "reason": "parameter_change",
        },
    ).json()
    approved = client.post(f"/api/revision-plans/{plan['id']}/approve").json()

    response = client.post(f"/api/revision-plans/{approved['id']}/generate")

    assert response.status_code == 201
    candidate = response.json()
    assert candidate["source_type"] == "ai_revision"
    assert candidate["cad_backend"] == "cadquery"
    assert candidate["source_language"] == "python"
    assert candidate["parent_revision_id"] == context["revision"]["id"]
    assert candidate["review_state"] in {"ready", "ready_with_warnings"}
    assert len(provider.cadquery_requests) == 1
    assert provider.cadquery_requests[0].revision_plan["summary"] == "Increase lid thickness from 3 mm to 4 mm"
    assert provider.cadquery_requests[0].scoped_revision_context["targeted_components"] == ["lid"]
    assert provider.cadquery_requests[0].scoped_revision_context["protected_outputs"] == ["body"]
    assert len(runner.calls) == 1
    assert {output["output_id"] for output in runner.calls[0]["requested_outputs"]} == {"body", "lid"}
    assert runner.calls[0]["parameter_values"]["lid_thickness"] == 4.0
    assert client.get(f"/api/projects/{context['project']['id']}").json()["active_revision_id"] == context["revision"]["id"]
    compliance = client.get(f"/api/revision-plans/{approved['id']}/compliance-result").json()
    assert compliance["passed"] is True


def test_cadquery_protected_parameter_change_blocks_before_compile(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(settings, "generation_mode", "advanced")
    provider = RevisionPlanningProvider(
        plan={
            **ready_revision_plan(),
            "allowed_parameter_changes": ["lid_thickness"],
            "required_dependency_changes": [],
        },
        revised_source=CADQUERY_BASE_SOURCE,
    )
    runner = MultiOutputCadRunner()
    client, _SessionLocal = build_client(tmp_path, provider, runner)
    context = create_accepted_multi_output_revision(client)
    provider.revised_source = CADQUERY_UNAUTHORIZED_SOURCE
    provider.correction_source = CADQUERY_UNAUTHORIZED_SOURCE
    runner.calls.clear()
    plan = client.post(
        f"/api/projects/{context['project']['id']}/revision-plans",
        json={
            "base_revision_id": context["revision"]["id"],
            "user_instruction": "Change lid thickness to 4 mm.",
            "reason": "parameter_change",
        },
    ).json()
    approved = client.post(f"/api/revision-plans/{plan['id']}/approve").json()

    response = client.post(f"/api/revision-plans/{approved['id']}/generate")

    assert response.status_code == 409
    assert runner.calls == []
    compliance = client.get(f"/api/revision-plans/{approved['id']}/compliance-result").json()
    assert compliance["passed"] is False
    assert any(finding["rule_id"] == "revision.unauthorized_parameter_change" for finding in compliance["findings"])


def test_protected_output_drift_blocks_candidate_after_compile(tmp_path: Path) -> None:
    provider = RevisionPlanningProvider()
    runner = MultiOutputCadRunner()
    client, _SessionLocal = build_client(tmp_path, provider, runner)
    context = create_accepted_multi_output_revision(client)
    runner.calls.clear()
    runner.body_extents = (80.0, 60.0, 3.0)
    plan = client.post(
        f"/api/projects/{context['project']['id']}/revision-plans",
        json={
            "base_revision_id": context["revision"]["id"],
            "user_instruction": "Change lid thickness to 4 mm.",
            "reason": "parameter_change",
        },
    ).json()
    approved = client.post(f"/api/revision-plans/{plan['id']}/approve").json()

    response = client.post(f"/api/revision-plans/{approved['id']}/generate")

    assert response.status_code == 201
    candidate = response.json()
    assert candidate["review_state"] == "blocked"
    summary = client.get(f"/api/revision-plans/{approved['id']}/component-revision-summary").json()
    assert summary["summary"]["protected_outputs"][0]["preservation_state"] == "unexpected_change"
    findings = client.get(f"/api/candidates/{candidate['id']}/findings").json()
    assert any(finding["rule_id"] == "revision.protected_output_unexpected_change" for finding in findings)


async def _fail_generate_model(request: ModelGenerationRequest) -> ModelGenerationResult:
    raise AssertionError("CadQuery revision generation must use the CadQuery provider path")


def test_finding_driven_revision_links_targeted_finding(tmp_path: Path) -> None:
    provider = RevisionPlanningProvider()
    runner = MultiOutputCadRunner()
    client, SessionLocal = build_client(tmp_path, provider, runner)
    context = create_accepted_multi_output_revision(client)
    with SessionLocal() as session:
        from app.models.validation_finding import ValidationFinding

        finding = ValidationFinding(
            revision_id=context["revision"]["id"],
            rule_id="geometry.protected_hole_spacing",
            category="geometry",
            severity="critical",
            is_blocking=True,
            title="Hole spacing mismatch",
            explanation="Detected 60 mm, expected 50 mm.",
            suggested_correction="Move the mounting holes to 50 mm spacing.",
            detected_value="60",
            unit="mm",
            threshold_value="50",
            orientation_dependent=False,
            metadata_json=json.dumps({"confidence": 0.95}),
        )
        session.add(finding)
        session.commit()
        finding_id = finding.id
    planned = ready_revision_plan()
    planned["reason"] = "geometric_finding"
    planned["targeted_findings"] = [finding_id]
    provider.plan = planned

    response = client.post(
        f"/api/projects/{context['project']['id']}/revision-plans",
        json={
            "base_revision_id": context["revision"]["id"],
            "user_instruction": "Fix this spacing issue.",
            "reason": "geometric_finding",
            "targeted_finding_ids": [finding_id],
        },
    )

    assert response.status_code == 201
    plan = response.json()
    assert plan["revision_plan"]["targeted_findings"] == [finding_id]
    assert provider.revision_plan_requests[-1].selected_findings[0]["rule_id"] == "geometry.protected_hole_spacing"


def test_clarification_answer_creates_new_revision_plan_version(tmp_path: Path) -> None:
    provider = RevisionPlanningProvider(plan=CLARIFICATION_PLAN)
    runner = MultiOutputCadRunner()
    client, _SessionLocal = build_client(tmp_path, provider, runner)
    context = create_accepted_multi_output_revision(client)
    first = client.post(
        f"/api/projects/{context['project']['id']}/revision-plans",
        json={
            "base_revision_id": context["revision"]["id"],
            "user_instruction": "Make the lid thicker.",
            "reason": "parameter_change",
        },
    ).json()
    question = client.get(f"/api/revision-plans/{first['id']}/clarification-questions").json()[0]
    provider.plan = ready_revision_plan()

    response = client.post(
        f"/api/revision-plans/{first['id']}/clarification-answers",
        json={"answers": [{"question_id": question["id"], "answer": "Use 4 mm."}]},
    )

    assert response.status_code == 201
    second = response.json()
    assert second["id"] != first["id"]
    assert second["superseded_revision_plan_id"] == first["id"]
    assert second["version_number"] == first["version_number"] + 1
    assert second["outcome"] == "revision_ready"


def test_revision_plan_attempts_are_persisted_with_prompt_versions(tmp_path: Path) -> None:
    provider = RevisionPlanningProvider()
    runner = MultiOutputCadRunner()
    client, SessionLocal = build_client(tmp_path, provider, runner)
    context = create_accepted_multi_output_revision(client)

    client.post(
        f"/api/projects/{context['project']['id']}/revision-plans",
        json={
            "base_revision_id": context["revision"]["id"],
            "user_instruction": "Change lid thickness to 4 mm.",
            "reason": "parameter_change",
        },
    )

    with SessionLocal() as session:
        attempt = session.scalar(
            select(GenerationAttempt)
            .where(GenerationAttempt.prompt_template_version == "revision-planning-v1")
            .order_by(GenerationAttempt.attempt_number.desc())
        )
        assert attempt is not None
        assert attempt.raw_output_path is not None
        assert attempt.request_payload_path
        assert attempt.prompt_path
