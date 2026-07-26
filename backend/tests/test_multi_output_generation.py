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
                "required": not optional_lid,
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
/*
Project: Two part enclosure
Units: millimeters
Purpose: electronics enclosure
Assumptions: none
Print notes: print body and lid flat on Z=0
*/
// ===== QUALITY =====
$fn = 48;
selected_output = "body";
// ===== USER PARAMETERS =====
// @volundr-requirement body_width
// @volundr-component body
body_width = 80;
body_depth = 50;
wall_thickness = 3;
// ===== DERIVED VALUES =====
lid_thickness = 3;
// ===== VALIDATION =====
assert(body_width > 0, "body_width must be positive");
assert(selected_output == "body" || selected_output == "lid", "Unknown selected_output");
// ===== MODULES =====
// @volundr-feature body_and_lid
// @volundr-feature body_shell
// @volundr-geometry type=bounds component=body x=body_width y=body_depth z=wall_thickness
// @volundr-output body module=body required=true filename=body.stl components=body
module body() {
  cube([body_width, body_depth, wall_thickness]);
}
// @volundr-feature lid_panel
// @volundr-component lid
// @volundr-geometry type=bounds component=lid x=body_width y=body_depth z=lid_thickness
// @volundr-output lid module=lid required=true filename=lid.stl components=lid
module lid() {
  cube([body_width, body_depth, lid_thickness]);
}
// ===== FINAL MODEL =====
module render_selected_output() {
  if (selected_output == "body") {
    body();
  } else if (selected_output == "lid") {
    lid();
  } else {
    assert(false, str("Unknown selected_output: ", selected_output));
  }
}
render_selected_output();
"""


class MultiOutputProvider:
    def __init__(self, *, plan: dict[str, Any] | None = None, source: str = MULTI_OUTPUT_SOURCE) -> None:
        self.plan = plan or design_plan()
        self.source = source
        self.generation_requests: list[ModelGenerationRequest] = []

    @property
    def gemini_ruleset_version(self) -> str:
        return "gemini-ruleset-v1"

    def provider_settings(self) -> dict[str, Any]:
        return {"model": "fake-multi-output-model"}

    def requirement_prompt_template_version(self) -> str:
        return "requirements-v1"

    def design_plan_prompt_template_version(self) -> str:
        return "design-plan-v1"

    def prompt_template_version_for(self, request: ModelGenerationRequest) -> str:
        return "openscad-generation-v5"

    def build_requirement_prompt(self, request: RequirementExtractionRequest) -> str:
        return "requirements prompt"

    def build_design_plan_prompt(self, request: DesignPlanRequest) -> str:
        return "design plan prompt"

    def build_prompt(self, request: ModelGenerationRequest) -> str:
        return "planned source prompt"

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

    async def generate_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        self.generation_requests.append(request)
        return ModelGenerationResult(
            raw_output=f"```openscad\n{self.source}\n```",
            provider="fake",
            provider_model="fake-multi-output-model",
        )


class MultiOutputCadRunner:
    def __init__(
        self,
        *,
        fail_outputs: set[str] | None = None,
        disconnected_outputs: set[str] | None = None,
    ) -> None:
        self.fail_outputs = fail_outputs or set()
        self.disconnected_outputs = disconnected_outputs or set()
        self.calls: list[dict[str, Any]] = []

    async def compile(
        self,
        source: str,
        job_id: str,
        *,
        selected_output: str | None = None,
        defines: dict[str, str | int | float | bool] | None = None,
    ) -> CadCompileResult:
        output_id = selected_output or str((defines or {}).get("selected_output") or "model")
        self.calls.append(
            {
                "job_id": job_id,
                "source_hash": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                "selected_output": output_id,
            }
        )
        job_dir = Path("/tmp") / "volundr-fake-multi-output-jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        source_path = job_dir / "model.scad"
        stl_path = job_dir / f"{output_id}.stl"
        stdout_path = job_dir / "stdout.log"
        stderr_path = job_dir / "stderr.log"
        metadata_path = job_dir / "metadata.json"
        source_path.write_text(source, encoding="utf-8")
        stdout_path.write_text("", encoding="utf-8")

        if output_id in self.fail_outputs:
            stderr_path.write_text(f"{output_id} failed", encoding="utf-8")
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
                source_hash=hashlib.sha256(source.encode("utf-8")).hexdigest(),
                output_size_bytes=0,
                metadata=None,
                error_message=f"{output_id} failed",
            )

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
        stderr_path.write_text("Compilation finished", encoding="utf-8")
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
        )


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
    assert {call["selected_output"] for call in runner.calls} == {"body", "lid"}
    assert client.get(f"/api/projects/{context['project']['id']}").json()["active_revision_id"] is None

    outputs = client.get(f"/api/revisions/{candidate['id']}/outputs").json()
    assert [(output["output_id"], output["output_state"]) for output in outputs] == [
        ("body", "ready"),
        ("lid", "ready"),
    ]
    assert outputs[0]["stl_hash"]
    assert outputs[0]["metadata"]["size_x_mm"] == 80.0

    manifest = client.get(f"/api/revisions/{candidate['id']}/output-manifest").json()
    assert manifest["schema_version"] == "output-manifest-v1"
    assert [output["output_id"] for output in manifest["outputs"]] == ["body", "lid"]


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
    assert [(output["output_id"], output["output_state"]) for output in outputs] == [
        ("body", "ready"),
        ("lid", "failed"),
    ]
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
    assert outputs[0]["output_state"] == "blocked"
    findings = client.get(f"/api/candidates/{candidate['id']}/findings").json()
    disconnected = next(
        finding for finding in findings if finding["rule_id"] == "mesh.disconnected_components"
    )
    assert disconnected["is_blocking"] is True


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
    assert retried["output_state"] == "ready"
    assert retried["source_hash"] == original_source_hash
    assert len(provider.generation_requests) == 1
    refreshed_candidate = client.get(f"/api/candidates/{candidate['id']}").json()
    assert refreshed_candidate["review_state"] in {"ready", "ready_with_warnings"}


def test_export_zip_contains_project_manifest_source_and_stls(tmp_path: Path) -> None:
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
        assert any(name.endswith("/project.scad") for name in names)
        assert any(name.endswith("/output-manifest.json") for name in names)
        assert any(name.endswith("/assembly-notes.md") for name in names)
        assert any(name.endswith("/stl/body.stl") for name in names)
        assert any(name.endswith("/stl/lid.stl") for name in names)
