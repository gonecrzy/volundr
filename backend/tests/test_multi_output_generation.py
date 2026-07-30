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


def design_plan(*, optional_lid: bool = False) -> dict[str, Any]:
    return {
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
            }
        ],
        "derived_parameters": [],
        "dependency_edges": [],
        "components": [
            {
                "id": "body",
                "label": "Body",
                "description": "Main enclosure body",
                "features": ["body_shell"],
                "parameters": ["body_width"],
            },
            {
                "id": "lid",
                "label": "Lid",
                "description": "Removable enclosure lid",
                "features": ["lid_panel"],
                "parameters": ["body_width"],
            },
        ],
        "features": [
            {
                "id": "body_shell",
                "component_id": "body",
                "type": "shell",
                "description": "Open electronics body",
                "parameters": ["body_width"],
                "protected": True,
            },
            {
                "id": "lid_panel",
                "component_id": "lid",
                "type": "cover",
                "description": "Flat removable lid",
                "parameters": ["body_width"],
                "protected": True,
            },
        ],
        "presets": [],
        "assembly_strategy": {
            "type": "separate_parts",
            "relationships": [
                {
                    "from_component_id": "lid",
                    "to_component_id": "body",
                    "relationship": "fits over",
                }
            ],
            "hardware": [{"label": "M3 screws", "quantity": 4}],
        },
        "printable_outputs": [
            {
                "id": "body",
                "label": "Body",
                "component_id": "body",
                "component_ids": ["body"],
                "entrypoint": "body",
                "filename": "body.stl",
                "quantity": 1,
                "required": True,
                "expected_solid_count": 1,
                "allow_disconnected_solids": False,
                "output_type": "printable_component",
            },
            {
                "id": "lid",
                "label": "Lid",
                "component_id": "lid",
                "component_ids": ["lid"],
                "entrypoint": "lid",
                "filename": "lid.stl",
                "quantity": 1,
                "required": not optional_lid,
                "expected_solid_count": 1,
                "allow_disconnected_solids": False,
                "output_type": "optional_printable_component"
                if optional_lid
                else "printable_component",
            },
        ],
        "risks": [{"id": "fit", "severity": "warning", "description": "Lid fit requires review."}],
        "clarification_required": False,
        "clarification_questions": [],
        "plan_ready": True,
        "outcome": "plan_ready",
    }


MULTI_OUTPUT_SOURCE = """
import cadquery as cq

from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product

PARAMETERS = [
    ParameterSpec(id="body_width", label="Body width", type="float", default=80.0, unit="mm"),
]


def build(params):
    body_width = params.get("body_width", 80.0)
    body = cq.Workplane("XY").box(body_width, 50.0, 6.0)
    lid = cq.Workplane("XY").box(body_width, 50.0, 3.0)
    return Product(
        parameters=PARAMETERS,
        outputs=[
            PrintableOutput(
                output_id="body",
                label="Body",
                model=body,
                component_id="body",
                expected_solid_count=1,
                allow_disconnected_solids=False,
            ),
            PrintableOutput(
                output_id="lid",
                label="Lid",
                model=lid,
                component_id="lid",
                expected_solid_count=1,
                allow_disconnected_solids=False,
            ),
        ]
    )
"""


class MultiOutputProvider:
    def __init__(self, *, plan: dict[str, Any] | None = None, source: str = MULTI_OUTPUT_SOURCE) -> None:
        self.plan = plan or design_plan()
        self.source = source
        self.generation_requests: list[ModelGenerationRequest] = []

    @property
    def ruleset_version(self) -> str:
        return "gemini-ruleset-v1"

    def provider_settings(self) -> dict[str, Any]:
        return {"model": "fake-multi-output-model"}

    def requirement_prompt_template_version(self) -> str:
        return "requirements-v1"

    def design_plan_prompt_template_version(self) -> str:
        return "design-plan-v1"

    def cadquery_prompt_template_version(self) -> str:
        return "cadquery-generation-v1"

    def build_requirement_prompt(self, request: RequirementExtractionRequest) -> str:
        return "requirements prompt"

    def build_design_plan_prompt(self, request: DesignPlanRequest) -> str:
        return "design plan prompt"

    def build_cadquery_prompt(self, request: ModelGenerationRequest) -> str:
        return "planned CadQuery source prompt"

    async def extract_requirements(
        self,
        request: RequirementExtractionRequest,
    ) -> RequirementExtractionResult:
        return RequirementExtractionResult(
            raw_output=json.dumps(READY_SPEC),
            provider="fake",
            provider_model="fake-multi-output-model",
        )

    async def create_design_plan(self, request: DesignPlanRequest) -> DesignPlanResult:
        return DesignPlanResult(
            raw_output=json.dumps(self.plan),
            provider="fake",
            provider_model="fake-multi-output-model",
        )

    async def generate_cadquery_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        self.generation_requests.append(request)
        return ModelGenerationResult(
            raw_output=f"```python\n{self.source}\n```",
            provider="fake",
            provider_model="fake-multi-output-model",
        )


class MultiOutputCadRunner:
    def __init__(
        self,
        *,
        fail_outputs: set[str] | None = None,
        invalid_topology_outputs: set[str] | None = None,
        disconnected_outputs: set[str] | None = None,
    ) -> None:
        self.fail_outputs = fail_outputs or set()
        self.invalid_topology_outputs = invalid_topology_outputs or set()
        self.disconnected_outputs = disconnected_outputs or set()
        self.calls: list[dict[str, Any]] = []

    async def compile(
        self,
        source: str,
        job_id: str,
        *,
        parameter_values: dict[str, Any] | None = None,
        requested_outputs: list[dict[str, Any]] | None = None,
    ) -> CadQueryCompileResult:
        output_ids = [str(output["output_id"]) for output in requested_outputs or [{"output_id": "body"}]]
        self.calls.append(
            {
                "job_id": job_id,
                "source_hash": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                "parameter_values": parameter_values or {},
                "requested_outputs": output_ids,
            }
        )
        job_dir = Path("/tmp") / "volundr-fake-multi-output-jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        source_path = job_dir / "source.py"
        stdout_path = job_dir / "stdout.log"
        stderr_path = job_dir / "stderr.log"
        execution_manifest_path = job_dir / "result.json"
        source_path.write_text(source, encoding="utf-8")
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text("Compilation finished", encoding="utf-8")
        execution_manifest_path.write_text('{"success": true}', encoding="utf-8")

        outputs: list[CadQueryOutputResult] = []
        first_stl_path: Path | None = None
        first_metadata_path: Path | None = None
        first_metadata: MeshMetadata | None = None
        total_bytes = 0
        for output_id in output_ids:
            if output_id in self.invalid_topology_outputs:
                topology_metadata = {
                    "valid": False,
                    "expected_solid_count": 1,
                    "detected_solid_count": 2,
                    "allow_disconnected_solids": False,
                }
                topology_metadata_path = job_dir / f"{output_id}-topology.json"
                topology_metadata_path.write_text(json.dumps(topology_metadata), encoding="utf-8")
                outputs.append(
                    CadQueryOutputResult(
                        output_id=output_id,
                        entrypoint=output_id,
                        required=True,
                        success=False,
                        stl_path=None,
                        step_path=None,
                        brep_path=None,
                        metadata_path=None,
                        topology_metadata_path=topology_metadata_path,
                        stl_hash=None,
                        step_hash=None,
                        brep_hash=None,
                        output_size_bytes=0,
                        metadata=None,
                        topology_metadata=topology_metadata,
                        compile_error="output shape is invalid",
                    )
                )
                continue
            if output_id in self.fail_outputs:
                outputs.append(
                    CadQueryOutputResult(
                        output_id=output_id,
                        entrypoint=output_id,
                        required=True,
                        success=False,
                        stl_path=None,
                        step_path=None,
                        brep_path=None,
                        metadata_path=None,
                        topology_metadata_path=None,
                        stl_hash=None,
                        step_hash=None,
                        brep_hash=None,
                        output_size_bytes=0,
                        metadata=None,
                        topology_metadata=None,
                        compile_error=f"{output_id} failed",
                    )
                )
                continue

            stl_path = job_dir / f"{output_id}.stl"
            step_path = job_dir / f"{output_id}.step"
            brep_path = job_dir / f"{output_id}.brep"
            metadata_path = job_dir / f"{output_id}.json"
            topology_metadata_path = job_dir / f"{output_id}-topology.json"
            extents = (80.0, 50.0, 6.0 if output_id == "body" else 3.0)
            mesh = trimesh.creation.box(extents=extents)
            mesh.apply_translation([extents[0] / 2, extents[1] / 2, extents[2] / 2])
            connected_components = 1
            triangle_count = 12
            if output_id in self.disconnected_outputs:
                handle = trimesh.creation.box(extents=(20.0, 8.0, 6.0))
                handle.apply_translation([extents[0] / 2, extents[1] / 2, extents[2] + 20.0])
                mesh = trimesh.util.concatenate([mesh, handle])
                connected_components = 2
                triangle_count = int(len(mesh.faces))
            mesh.export(stl_path)
            step_path.write_text("STEP", encoding="utf-8")
            brep_path.write_text("BREP", encoding="utf-8")
            metadata = MeshMetadata(
                size_x_mm=extents[0],
                size_y_mm=extents[1],
                size_z_mm=float(mesh.bounding_box.extents[2]),
                volume_mm3=float(abs(mesh.volume)),
                triangle_count=triangle_count,
                connected_components=connected_components,
                is_watertight=True,
                is_winding_consistent=True,
                center_of_mass=tuple(float(value) for value in mesh.center_mass),
            )
            topology_metadata = {
                "valid": connected_components == 1,
                "expected_solid_count": 1,
                "detected_solid_count": connected_components,
                "allow_disconnected_solids": False,
            }
            metadata_path.write_text(json.dumps(metadata.__dict__), encoding="utf-8")
            topology_metadata_path.write_text(json.dumps(topology_metadata), encoding="utf-8")
            total_bytes += stl_path.stat().st_size
            first_stl_path = first_stl_path or stl_path
            first_metadata_path = first_metadata_path or metadata_path
            first_metadata = first_metadata or metadata
            outputs.append(
                CadQueryOutputResult(
                    output_id=output_id,
                    entrypoint=output_id,
                    required=True,
                    success=True,
                    stl_path=stl_path,
                    step_path=step_path,
                    brep_path=brep_path,
                    metadata_path=metadata_path,
                    topology_metadata_path=topology_metadata_path,
                    stl_hash=hashlib.sha256(stl_path.read_bytes()).hexdigest(),
                    step_hash=hashlib.sha256(step_path.read_bytes()).hexdigest(),
                    brep_hash=hashlib.sha256(brep_path.read_bytes()).hexdigest(),
                    output_size_bytes=stl_path.stat().st_size,
                    metadata=metadata,
                    topology_metadata=topology_metadata,
                )
            )
        success = all(output.success or not output.required for output in outputs)
        result = CadQueryCompileResult(
            job_id=job_id,
            success=success,
            timed_out=False,
            exit_code=0 if success else 1,
            source_path=source_path,
            stl_path=first_stl_path,
            step_path=None,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            metadata_path=first_metadata_path,
            source_hash=hashlib.sha256(source.encode("utf-8")).hexdigest(),
            output_size_bytes=total_bytes,
            metadata=first_metadata,
            error_message=None if success else "one or more outputs failed",
            command_args=["cadquery", *output_ids],
            outputs=outputs,
        )
        object.__setattr__(result, "execution_manifest_path", execution_manifest_path)
        return result


def build_client(
    tmp_path: Path,
    provider: MultiOutputProvider,
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


def create_approved_plan(client: TestClient) -> dict[str, Any]:
    project = client.post(
        "/api/projects",
        json={"name": "Two part box", "original_intent": "Create a two-part box."},
    ).json()
    specification = client.post(
        f"/api/projects/{project['id']}/requirements",
        json={"user_instruction": "Create an 80 mm wide two-part electronics box."},
    ).json()
    plan = client.post(f"/api/design-specifications/{specification['id']}/design-plan").json()
    approved = client.post(f"/api/design-plans/{plan['id']}/approve").json()
    assert approved["review_state"] == "approved"
    return {"project": project, "specification": specification, "plan": approved}


def test_multi_output_plan_creates_assembly_candidate_and_output_artifacts(tmp_path: Path) -> None:
    provider = MultiOutputProvider()
    runner = MultiOutputCadRunner()
    client, _SessionLocal = build_client(tmp_path, provider, runner)
    context = create_approved_plan(client)

    response = client.post(f"/api/design-plans/{context['plan']['id']}/generate")

    assert response.status_code == 201
    candidate = response.json()
    assert candidate["status"] == "succeeded"
    assert candidate["design_plan_id"] == context["plan"]["id"]
    assert candidate["expected_output_count"] == 2
    assert candidate["successful_output_count"] == 2
    assert runner.calls[0]["requested_outputs"] == ["body", "lid"]
    assert client.get(f"/api/projects/{context['project']['id']}").json()["active_revision_id"] is None

    outputs = client.get(f"/api/revisions/{candidate['id']}/outputs").json()
    assert [output["output_id"] for output in outputs] == ["body", "lid"]
    assert all(output["execution_state"] in {"ready", "ready_with_warnings"} for output in outputs)
    assert outputs[0]["stl_hash"]
    assert outputs[0]["metadata"]["size_x_mm"] == 80.0
    assert outputs[0]["expected_solid_count"] == 1
    assert outputs[0]["detected_solid_count"] == 1
    assert outputs[0]["allow_disconnected_solids"] is False

    manifest = client.get(f"/api/revisions/{candidate['id']}/output-manifest").json()
    assert manifest["schema_version"] == "output-manifest-v1"
    assert [output["output_id"] for output in manifest["outputs"]] == ["body", "lid"]
    assert manifest["outputs"][0]["expected_solid_count"] == 1
    assert manifest["outputs"][0]["detected_solid_count"] == 1
    assert manifest["outputs"][0]["allow_disconnected_solids"] is False


def test_revision_outputs_normalize_string_preferred_orientation(tmp_path: Path) -> None:
    plan = design_plan()
    plan["printable_outputs"][0]["orientation"] = "base-down vertical orientation"
    provider = MultiOutputProvider(plan=plan)
    runner = MultiOutputCadRunner()
    client, _SessionLocal = build_client(tmp_path, provider, runner)
    context = create_approved_plan(client)
    candidate = client.post(f"/api/design-plans/{context['plan']['id']}/generate").json()

    response = client.get(f"/api/revisions/{candidate['id']}/outputs")

    assert response.status_code == 200
    body_output = next(output for output in response.json() if output["output_id"] == "body")
    assert body_output["preferred_orientation"] == {
        "description": "base-down vertical orientation"
    }


def test_required_output_failure_blocks_assembly_but_preserves_successful_artifacts(
    tmp_path: Path,
) -> None:
    provider = MultiOutputProvider()
    runner = MultiOutputCadRunner(fail_outputs={"lid"})
    client, _SessionLocal = build_client(tmp_path, provider, runner)
    context = create_approved_plan(client)

    candidate = client.post(f"/api/design-plans/{context['plan']['id']}/generate").json()

    assert candidate["status"] == "succeeded"
    assert candidate["review_state"] == "blocked"
    assert candidate["failed_output_count"] == 1
    outputs = client.get(f"/api/revisions/{candidate['id']}/outputs").json()
    assert outputs[0]["output_id"] == "body"
    assert outputs[0]["execution_state"] in {"ready", "ready_with_warnings"}
    assert outputs[1]["output_id"] == "lid"
    assert outputs[1]["execution_state"] == "failed"
    assert outputs[0]["stl_path"] is not None
    findings = client.get(f"/api/candidates/{candidate['id']}/findings").json()
    assert any(finding["rule_id"] == "assembly.required_output_failed" for finding in findings)
    assert client.post(f"/api/candidates/{candidate['id']}/accept").status_code == 409


def test_single_component_output_with_disconnected_bodies_blocks_candidate(tmp_path: Path) -> None:
    single_output_plan = design_plan()
    single_output_plan["printable_outputs"] = [single_output_plan["printable_outputs"][0]]
    single_output_plan["components"] = [single_output_plan["components"][0]]
    single_output_plan["features"] = [single_output_plan["features"][0]]
    provider = MultiOutputProvider(plan=single_output_plan)
    runner = MultiOutputCadRunner(disconnected_outputs={"body"})
    client, _SessionLocal = build_client(tmp_path, provider, runner)
    context = create_approved_plan(client)

    candidate = client.post(f"/api/design-plans/{context['plan']['id']}/generate").json()

    assert candidate["review_state"] == "blocked"
    outputs = client.get(f"/api/revisions/{candidate['id']}/outputs").json()
    assert outputs[0]["execution_state"] == "blocked"
    findings = client.get(f"/api/candidates/{candidate['id']}/findings").json()
    disconnected = next(
        finding for finding in findings if finding["rule_id"] == "mesh.disconnected_components"
    )
    assert disconnected["is_blocking"] is True


def test_invalid_topology_failure_preserves_output_topology_fields(tmp_path: Path) -> None:
    provider = MultiOutputProvider()
    runner = MultiOutputCadRunner(invalid_topology_outputs={"body"})
    client, _SessionLocal = build_client(tmp_path, provider, runner)
    context = create_approved_plan(client)

    candidate = client.post(f"/api/design-plans/{context['plan']['id']}/generate").json()

    body_output = next(
        output
        for output in client.get(f"/api/revisions/{candidate['id']}/outputs").json()
        if output["output_id"] == "body"
    )
    assert body_output["execution_state"] == "failed"
    assert body_output["expected_solid_count"] == 1
    assert body_output["detected_solid_count"] == 2
    assert body_output["allow_disconnected_solids"] is False
    assert body_output["topology_metadata"]["valid"] is False


def test_optional_output_failure_keeps_assembly_reviewable_with_warnings(tmp_path: Path) -> None:
    provider = MultiOutputProvider(plan=design_plan(optional_lid=True))
    runner = MultiOutputCadRunner(fail_outputs={"lid"})
    client, _SessionLocal = build_client(tmp_path, provider, runner)
    context = create_approved_plan(client)

    candidate = client.post(f"/api/design-plans/{context['plan']['id']}/generate").json()

    assert candidate["review_state"] == "ready_with_warnings"
    assert candidate["failed_output_count"] == 1
    findings = client.get(f"/api/candidates/{candidate['id']}/findings").json()
    assert any(finding["rule_id"] == "assembly.optional_output_failed" for finding in findings)


def test_retry_failed_output_uses_same_source_hash_and_does_not_call_provider(tmp_path: Path) -> None:
    provider = MultiOutputProvider()
    runner = MultiOutputCadRunner(fail_outputs={"lid"})
    client, _SessionLocal = build_client(tmp_path, provider, runner)
    context = create_approved_plan(client)
    candidate = client.post(f"/api/design-plans/{context['plan']['id']}/generate").json()
    failed_output = next(
        output
        for output in client.get(f"/api/revisions/{candidate['id']}/outputs").json()
        if output["output_id"] == "lid"
    )
    original_source_hash = failed_output["source_hash"]
    assert len(provider.generation_requests) == 1

    runner.fail_outputs.clear()
    retry_response = client.post(f"/api/revision-outputs/{failed_output['id']}/retry")

    assert retry_response.status_code == 200
    retried = retry_response.json()
    assert retried["execution_state"] in {"ready", "ready_with_warnings"}
    assert retried["source_hash"] == original_source_hash
    assert len(provider.generation_requests) == 1
    refreshed_candidate = client.get(f"/api/candidates/{candidate['id']}").json()
    assert refreshed_candidate["review_state"] in {"ready", "ready_with_warnings"}


def test_export_zip_contains_project_manifest_source_and_cadquery_artifacts(tmp_path: Path) -> None:
    provider = MultiOutputProvider()
    runner = MultiOutputCadRunner()
    client, _SessionLocal = build_client(tmp_path, provider, runner)
    context = create_approved_plan(client)
    candidate = client.post(f"/api/design-plans/{context['plan']['id']}/generate").json()

    response = client.get(f"/api/revisions/{candidate['id']}/export.zip")

    assert response.status_code == 200
    zip_path = tmp_path / "export.zip"
    zip_path.write_bytes(response.content)
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        assert any(name.endswith("/README.md") for name in names)
        assert any(name.endswith("/design-specification.json") for name in names)
        assert any(name.endswith("/design-plan.json") for name in names)
        assert any(name.endswith("/source.py") for name in names)
        assert any(name.endswith("/execution-result.json") for name in names)
        assert any(name.endswith("/output-manifest.json") for name in names)
        assert any(name.endswith("/assembly-notes.md") for name in names)
        assert any(name.endswith("/stl/body.stl") for name in names)
        assert any(name.endswith("/stl/lid.stl") for name in names)
        assert any(name.endswith("/step/body.step") for name in names)
        assert any(name.endswith("/step/lid.step") for name in names)
        assert any(name.endswith("/brep/body.brep") for name in names)
        assert any(name.endswith("/brep/lid.brep") for name in names)
        readme_name = next(name for name in names if name.endswith("/README.md"))
        readme = archive.read(readme_name).decode("utf-8")
        assert "source.py" in readme
        assert "project.scad" not in readme
