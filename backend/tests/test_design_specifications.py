import asyncio
import concurrent.futures
import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
import trimesh

from app.api.dependencies import get_ai_provider, get_cad_runner, get_data_dir
from app.core.config import settings
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
from app.services.cad.cadquery_runner import CadQueryCompileResult, CadQueryOutputResult
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
    def ruleset_version(self) -> str:
        return "gemini-ruleset-v1"

    def provider_settings(self) -> dict[str, Any]:
        return {"model": "fake-requirements-model"}

    def prompt_template_version_for(self, request: ModelGenerationRequest) -> str:
        return "cadquery-generation-v1"

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
        raise AssertionError("CadQuery generation must use generate_cadquery_model")


class CancelledRequirementProvider(StagedAiProvider):
    def __init__(self) -> None:
        super().__init__()

    async def extract_requirements(
        self,
        request: RequirementExtractionRequest,
    ) -> RequirementExtractionResult:
        self.requirement_requests.append(request)
        raise asyncio.CancelledError


class FakeCadRunner:
    async def compile(
        self,
        source: str,
        job_id: str,
        *,
        parameter_values: dict[str, Any] | None = None,
        requested_outputs: list[dict[str, Any]] | None = None,
    ) -> CadQueryCompileResult:
        job_dir = Path("/tmp") / "volundr-fake-design-spec-jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        source_path = job_dir / "source.py"
        stdout_path = job_dir / "stdout.log"
        stderr_path = job_dir / "stderr.log"
        source_path.write_text(source, encoding="utf-8")
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text("Compilation finished", encoding="utf-8")
        output_id = (requested_outputs or [{"output_id": "model"}])[0]["output_id"]
        stl_path = job_dir / f"{output_id}.stl"
        step_path = job_dir / f"{output_id}.step"
        brep_path = job_dir / f"{output_id}.brep"
        metadata_path = job_dir / f"{output_id}-metadata.json"
        topology_path = job_dir / f"{output_id}-topology.json"
        mesh = trimesh.creation.box(extents=(20.0, 10.0, 10.0))
        mesh.apply_translation([0.0, 0.0, 5.0])
        mesh.export(stl_path)
        step_path.write_text("step", encoding="utf-8")
        brep_path.write_text("brep", encoding="utf-8")
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
        metadata_path.write_text(json.dumps(metadata.__dict__), encoding="utf-8")
        topology = {"valid": True, "detected_solid_count": 1, "expected_solid_count": 1}
        topology_path.write_text(json.dumps(topology), encoding="utf-8")
        return CadQueryCompileResult(
            job_id=job_id,
            success=True,
            timed_out=False,
            exit_code=0,
            source_path=source_path,
            stl_path=stl_path,
            step_path=step_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            metadata_path=metadata_path,
            source_hash="fake-source-hash",
            output_size_bytes=stl_path.stat().st_size,
            metadata=metadata,
            error_message=None,
            command_args=["python", "_runner.py"],
            outputs=[
                CadQueryOutputResult(
                    output_id=output_id,
                    entrypoint=output_id,
                    required=True,
                    success=True,
                    stl_path=stl_path,
                    step_path=step_path,
                    brep_path=brep_path,
                    metadata_path=metadata_path,
                    topology_metadata_path=topology_path,
                    stl_hash="1" * 64,
                    step_hash="2" * 64,
                    brep_hash="3" * 64,
                    output_size_bytes=stl_path.stat().st_size,
                    metadata=metadata,
                    topology_metadata=topology,
                )
            ],
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
        assert attempt.prompt_version == "requirements-v1"
        assert attempt.design_spec_path is not None

    run_dir = tmp_path / "data" / "projects" / project["id"] / "generation-runs" / attempt.id
    assert json.loads((run_dir / "parsed-design-spec.json").read_text(encoding="utf-8"))["outcome"] == "generation_ready"
    assert (run_dir / "raw-output.txt").exists()


def test_cancelled_requirement_extraction_marks_attempt_failed(tmp_path: Path) -> None:
    provider = CancelledRequirementProvider()
    client, SessionLocal = build_client(tmp_path, provider)
    project = create_project(client)

    with pytest.raises((asyncio.CancelledError, concurrent.futures.CancelledError)):
        client.post(
            f"/api/projects/{project['id']}/requirements",
            json={"user_instruction": "Create a tackle tray carrier."},
        )

    with SessionLocal() as session:
        attempts = list(session.scalars(select(GenerationAttempt)))
        assert len(attempts) == 1
        assert attempts[0].status == "failed"
        assert attempts[0].failure_class == "provider_timeout"
        assert "cancelled" in (attempts[0].error_message or "")


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


def test_unsupported_request_does_not_generate_placeholder_source(tmp_path: Path) -> None:
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
        assert attempts[1].prompt_version == "requirements-v1"


def test_requirement_extraction_normalizes_common_provider_schema_variants(tmp_path: Path) -> None:
    loose_spec = {
        "schema_version": "1.0",
        "object_type": "carrying_case_tackle_box",
        "purpose": "Transport and store 3600 fishing tackle trays.",
        "units": "mm",
        "supported_scope": True,
        "critical_dimensions": [
            {
                "id": "tray_length_3600",
                "label": "Standard 3600 Tray Length",
                "value": 275.0,
                "unit": "mm",
                "source": "product_default",
                "importance": "critical",
                "protected": True,
            }
        ],
        "parameters": [
            {
                "id": "case_inner_length",
                "name": "Case Inner Length",
                "default_value": 275.0,
                "unit": "mm",
                "type": "float",
            }
        ],
        "functional_requirements": [
            {
                "description": "Integrated sturdy carrying handle for transport.",
                "priority": "high",
                "verification_method": "geometric_inspection",
            },
            "Secure tray retention mechanism to prevent trays from sliding out during carrying.",
        ],
        "assumptions": [
            {
                "assumption": "Using standard 3600 fishing tackle tray dimensions.",
                "category": "design_scope",
                "confidence": 0.9,
            },
            "Use PETG or PLA with ordinary FDM wall thickness.",
        ],
        "missing_requirements": [
            "Preferred tray retention mechanism.",
        ],
        "clarification_questions": [
            {
                "id": "q_retention_style",
                "question": "What style of tray retention do you prefer?",
            }
        ],
        "clarification_required": True,
        "generation_ready": False,
        "outcome": "clarification_required",
    }
    provider = StagedAiProvider(loose_spec)
    client, _SessionLocal = build_client(tmp_path, provider)
    project = create_project(client)

    response = client.post(
        f"/api/projects/{project['id']}/requirements",
        json={"user_instruction": "Create a configurable tackle tray carrier."},
    )

    assert response.status_code == 201
    spec = response.json()["specification"]
    assert spec["outcome"] == "clarification_required"
    assert spec["parameters"][0]["label"] == "Case Inner Length"
    assert spec["parameters"][0]["value"] == 275.0
    assert spec["parameters"][0]["source"] == "ai_assumption"
    assert spec["parameters"][0]["importance"] == "important"
    assert spec["functional_requirements"][0]["id"] == "integrated_sturdy_carrying_handle_for_transport"
    assert spec["functional_requirements"][0]["source"] == "user"
    assert spec["functional_requirements"][0]["importance"] == "critical"
    assert spec["functional_requirements"][1]["id"] == "secure_tray_retention_mechanism_to_prevent_trays_from_sliding_out_during_carrying"
    assert spec["assumptions"][0]["description"] == "Using standard 3600 fishing tackle tray dimensions."
    assert spec["assumptions"][0]["source"] == "ai_assumption"
    assert spec["missing_requirements"][0]["id"] == "preferred_tray_retention_mechanism"


def test_generation_cannot_begin_before_requirements_are_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "generation_mode", "advanced")
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
