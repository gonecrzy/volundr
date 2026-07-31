import json
import hashlib
from collections.abc import Generator
from pathlib import Path
from typing import Any

import trimesh
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import get_ai_provider, get_cad_runner, get_data_dir
from app.api.projects import router as projects_router
from app.db.base import Base
from app.db.session import get_db
from app.models.revision import Revision
from app.models.project import Project
from app.models.workflow import FrontendWorkflowEvent, WorkflowArtifact, WorkflowEvent, WorkflowRun
from app.services.ai.provider import (
    DesignPlanRequest,
    DesignPlanResult,
    ModelGenerationRequest,
    ModelGenerationResult,
    RequirementExtractionRequest,
    RequirementExtractionResult,
    RevisionPlanRequest,
    RevisionPlanResult,
    SourceBriefRequest,
    SourceBriefResult,
)
from app.services.cad.cadquery_runner import CadQueryCompileResult, CadQueryOutputResult
from app.services.mesh.inspect import MeshMetadata


PLATE_SOURCE = '''
import cadquery as cq

from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product, component, feature

PARAMETERS = [
    ParameterSpec(
        id="plate_width",
        label="Plate width",
        type="float",
        default=80.0,
        unit="mm",
        editable=True,
        protected=True,
        source_requirement_id="plate_width",
    ),
]

@component("plate")
@feature("mounting_plate", component="plate")
def build_plate(params):
    return cq.Workplane("XY").box(params["plate_width"], 50.0, 3.0)

def build(params):
    plate = build_plate(params)
    return Product(
        parameters=PARAMETERS,
        outputs=[
            PrintableOutput(
                output_id="plate",
                component_id="plate",
                label="Mounting plate",
                model=plate,
                expected_solid_count=1,
                allow_disconnected_solids=False,
            ),
        ],
    )
'''


PLATE_PLAN: dict[str, Any] = {
    "schema_version": "1.0",
    "design_level": "product",
    "product_type": "mounting_plate",
    "purpose": "A simple printable mounting plate",
    "units": "mm",
    "parameters": [
        {
            "id": "plate_width",
            "label": "Plate width",
            "value": 80,
            "unit": "mm",
            "source_requirement_id": "plate_width",
            "editable": True,
            "protected": True,
            "component_id": "plate",
        },
    ],
    "derived_parameters": [],
    "dependency_edges": [],
    "components": [
        {
            "id": "plate",
            "label": "Mounting plate",
            "description": "Flat printable mounting plate",
            "features": ["mounting_plate"],
            "parameters": ["plate_width"],
        },
    ],
    "features": [
        {
            "id": "mounting_plate",
            "component_id": "plate",
            "type": "plate",
            "description": "Flat mounting surface",
            "parameters": ["plate_width"],
            "protected": True,
        },
    ],
    "presets": [],
    "assembly_strategy": {"type": "single_part", "instructions": ["Print flat."]},
    "printable_outputs": [
        {
            "id": "plate",
            "label": "Mounting plate",
            "component_id": "plate",
            "component_ids": ["plate"],
            "entrypoint": "plate",
            "filename": "mounting-plate.stl",
            "quantity": 1,
            "required": True,
            "expected_solid_count": 1,
            "allow_disconnected_solids": False,
            "output_type": "printable_component",
        },
    ],
    "risks": [],
    "clarification_required": False,
    "clarification_questions": [],
    "plan_ready": True,
    "outcome": "plan_ready",
}


class FixtureProvider:
    """A deterministic provider used only by browser integration tests."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    @property
    def ruleset_version(self) -> str:
        return "fixture-ruleset-v1"

    def provider_settings(self) -> dict[str, Any]:
        return {"provider": "fixture", "model": "fixture-model"}

    def requirement_prompt_template_version(self) -> str:
        return "fixture-requirements-v1"

    def design_plan_prompt_template_version(self) -> str:
        return "fixture-design-plan-v1"

    def revision_plan_prompt_template_version(self) -> str:
        return "fixture-revision-plan-v1"

    def cadquery_prompt_template_version(self) -> str:
        return "fixture-cadquery-v1"

    def prompt_template_version_for(self, _request: ModelGenerationRequest) -> str:
        return "fixture-cadquery-v1"

    def build_requirement_prompt(self, _request: RequirementExtractionRequest) -> str:
        return "fixture requirements prompt"

    def build_design_plan_prompt(self, _request: DesignPlanRequest) -> str:
        return "fixture design plan prompt"

    def build_prompt(self, _request: ModelGenerationRequest) -> str:
        return "fixture CadQuery prompt"

    def build_cadquery_prompt(self, _request: ModelGenerationRequest) -> str:
        return "fixture CadQuery prompt"

    async def extract_requirements(
        self, request: RequirementExtractionRequest
    ) -> RequirementExtractionResult:
        self.calls.append("requirement_extraction")
        payload = {
            "schema_version": "1.0",
            "object_type": "mounting_plate",
            "purpose": request.user_instruction,
            "units": "mm",
            "supported_scope": True,
            "critical_dimensions": [
                {
                    "id": "plate_width",
                    "label": "Plate width",
                    "value": 80,
                    "unit": "mm",
                    "source": "user",
                    "importance": "critical",
                    "protected": True,
                }
            ],
            "parameters": [
                {
                    "id": "wall_thickness",
                    "label": "Wall thickness",
                    "value": 3,
                    "unit": "mm",
                    "source": "product_default",
                    "importance": "important",
                    "protected": False,
                    "editable": True,
                },
                {
                    "id": "overall_width",
                    "label": "Overall width",
                    "value": 90,
                    "unit": "mm",
                    "source": "calculated",
                    "importance": "important",
                    "protected": False,
                    "editable": False,
                },
            ],
            "functional_requirements": [],
            "print_requirements": {},
            "assumptions": [],
            "conflicts": [],
            "missing_requirements": [],
            "clarification_required": False,
            "clarification_questions": [],
            "generation_ready": True,
            "outcome": "generation_ready",
        }
        if "holder" in request.user_instruction.lower() and not request.clarification_answers:
            payload.update(
                {
                    "object_type": "intent_first_holder",
                    "purpose": request.user_instruction,
                    "clarification_required": True,
                    "clarification_questions": [
                        {
                            "id": "holder_height",
                            "question": "What is the maximum available height?",
                            "reason": "The holder must fit its available space.",
                            "related_requirement_id": "available_height",
                        }
                    ],
                    "generation_ready": False,
                    "outcome": "clarification_required",
                }
            )
        return RequirementExtractionResult(
            raw_output=json.dumps(payload), provider="fixture", provider_model="fixture-model"
        )

    async def create_design_plan(self, _request: DesignPlanRequest) -> DesignPlanResult:
        self.calls.append("design_plan_generation")
        return DesignPlanResult(
            raw_output=json.dumps(PLATE_PLAN), provider="fixture", provider_model="fixture-model"
        )

    async def generate_model(self, _request: ModelGenerationRequest) -> ModelGenerationResult:
        raise AssertionError("fixture requires CadQuery generation")

    async def generate_cadquery_model(self, _request: ModelGenerationRequest) -> ModelGenerationResult:
        self.calls.append("source_generation")
        return ModelGenerationResult(
            raw_output=f"```python\n{PLATE_SOURCE}\n```",
            provider="fixture",
            provider_model="fixture-model",
        )

    async def create_revision_plan(self, _request: RevisionPlanRequest) -> RevisionPlanResult:
        raise AssertionError("revision planning is not enabled in the initial fixture slice")

    async def create_source_brief(self, _request: SourceBriefRequest) -> SourceBriefResult:
        raise AssertionError("source briefs are not enabled in the initial fixture slice")


class FixtureRunner:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[dict[str, Any]] = []

    async def compile(
        self,
        source: str,
        job_id: str,
        *,
        parameter_values: dict[str, Any] | None = None,
        requested_outputs: list[dict[str, Any]] | None = None,
        **_kwargs: Any,
    ) -> CadQueryCompileResult:
        values = parameter_values or {}
        output_id = str((requested_outputs or [{"output_id": "plate"}])[0]["output_id"])
        self.calls.append({"job_id": job_id, "parameter_values": values, "output_id": output_id})
        job_dir = self.root / "cad-jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        source_path = job_dir / "source.py"
        stl_path = job_dir / f"{output_id}.stl"
        step_path = job_dir / f"{output_id}.step"
        brep_path = job_dir / f"{output_id}.brep"
        stdout_path = job_dir / "stdout.log"
        stderr_path = job_dir / "stderr.log"
        metadata_path = job_dir / f"{output_id}.json"
        topology_path = job_dir / f"{output_id}-topology.json"
        manifest_path = job_dir / "execution-manifest.json"
        source_path.write_text(source, encoding="utf-8")
        mesh = trimesh.creation.box(extents=(float(values.get("plate_width", 80)), 50.0, 3.0))
        mesh.apply_translation((0.0, 0.0, 1.5))
        mesh.export(stl_path)
        step_path.write_text("ISO-10303-21; END-ISO-10303-21;", encoding="utf-8")
        brep_path.write_text("BREP", encoding="utf-8")
        stdout_path.write_text("Fixture CAD execution completed", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        metadata = MeshMetadata(
            size_x_mm=float(values.get("plate_width", 80)),
            size_y_mm=50.0,
            size_z_mm=3.0,
            volume_mm3=float(values.get("plate_width", 80)) * 150.0,
            triangle_count=12,
            connected_components=1,
            is_watertight=True,
            is_winding_consistent=True,
            center_of_mass=(0.0, 0.0, 0.0),
        )
        topology = {
            "valid": True,
            "expected_solid_count": 1,
            "detected_solid_count": 1,
            "allow_disconnected_solids": False,
        }
        metadata_path.write_text(json.dumps(metadata.__dict__), encoding="utf-8")
        topology_path.write_text(json.dumps(topology), encoding="utf-8")
        source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        parameter_hash = hashlib.sha256(
            json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        stl_hash = hashlib.sha256(stl_path.read_bytes()).hexdigest()
        step_hash = hashlib.sha256(step_path.read_bytes()).hexdigest()
        brep_hash = hashlib.sha256(brep_path.read_bytes()).hexdigest()
        manifest_path.write_text(
            json.dumps(
                {
                    "cad_backend": "cadquery",
                    "source_language": "python",
                    "source_contract_version": "cadquery-v1",
                    "source_hash": source_hash,
                    "parameter_hash": parameter_hash,
                    "parameters": values,
                    "requested_output_ids": [output_id],
                    "output_ids": [output_id],
                    "outputs": [{"output_id": output_id, "required": True, "success": True, "topology_metadata": topology}],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        output = CadQueryOutputResult(
            output_id=output_id,
            entrypoint=output_id,
            required=True,
            success=True,
            stl_path=stl_path,
            step_path=step_path,
            brep_path=brep_path,
            metadata_path=metadata_path,
            topology_metadata_path=topology_path,
            stl_hash=stl_hash,
            step_hash=step_hash,
            brep_hash=brep_hash,
            output_size_bytes=stl_path.stat().st_size,
            metadata=metadata,
            topology_metadata=topology,
        )
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
            source_hash=source_hash,
            output_size_bytes=stl_path.stat().st_size,
            metadata=metadata,
            error_message=None,
            command_args=["fixture-cadquery", output_id],
            outputs=[output],
            execution_manifest_path=manifest_path,
        )


def create_e2e_fixture_app(root: Path) -> FastAPI:
    root.mkdir(parents=True, exist_ok=True)
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{root / 'fixture.sqlite'}", connect_args={"check_same_thread": False}
    )
    session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)
    provider = FixtureProvider()
    runner = FixtureRunner(root)

    app = FastAPI(title="Volundr E2E Fixture API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(projects_router)

    def override_db() -> Generator[Session, None, None]:
        with session_local() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_data_dir] = lambda: data_dir
    app.dependency_overrides[get_ai_provider] = lambda: provider
    app.dependency_overrides[get_cad_runner] = lambda: runner

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    def build_summary(project_id: str, db: Session) -> dict[str, Any]:
        runs = list(
            db.scalars(
                select(WorkflowRun).where(WorkflowRun.project_id == project_id).order_by(WorkflowRun.started_at)
            )
        )
        if not runs:
            raise HTTPException(status_code=404, detail="fixture project has no workflow runs")
        return {
            "provider_call_count": len(provider.calls),
            "provider_calls": list(provider.calls),
            "workflow_run_ids": [run.id for run in runs],
            "workflow_runs": [
                {
                    "id": run.id,
                    "workflow_type": run.workflow_type,
                    "parent_workflow_run_id": run.parent_workflow_run_id,
                    "root_workflow_run_id": run.root_workflow_run_id,
                    "correlation_id": run.correlation_id,
                }
                for run in runs
            ],
            "workflow_event_types": list(
                db.scalars(
                    select(WorkflowEvent.event_type)
                    .where(WorkflowEvent.project_id == project_id)
                    .order_by(WorkflowEvent.workflow_run_id, WorkflowEvent.sequence_number)
                )
            ),
            "artifact_stages": list(
                db.scalars(
                    select(WorkflowArtifact.stage)
                    .where(WorkflowArtifact.project_id == project_id)
                    .order_by(WorkflowArtifact.created_at)
                )
            ),
            "frontend_actions": list(
                db.scalars(
                    select(FrontendWorkflowEvent.action_name)
                    .where(FrontendWorkflowEvent.project_id == project_id)
                    .order_by(FrontendWorkflowEvent.recorded_at)
                )
            ),
            "revisions": [
                {
                    "id": revision.id,
                    "review_state": revision.review_state,
                    "is_accepted": revision.is_accepted,
                    "source_hash": revision.source_hash,
                }
                for revision in db.scalars(
                    select(Revision).where(Revision.project_id == project_id).order_by(Revision.revision_number)
                )
            ],
        }

    @app.get("/api/test-fixture/projects/{project_id}/summary", include_in_schema=False)
    def persisted_fixture_summary(project_id: str, db: Session = Depends(override_db)) -> dict[str, Any]:
        return build_summary(project_id, db)

    @app.get("/api/test-fixture/latest-summary", include_in_schema=False)
    def latest_fixture_summary(db: Session = Depends(override_db)) -> dict[str, Any]:
        project_id = db.scalar(select(Project.id).order_by(Project.created_at.desc()))
        if project_id is None:
            raise HTTPException(status_code=404, detail="fixture has no projects")
        return build_summary(project_id, db)

    return app


if __name__ == "__main__":
    import os

    import uvicorn

    fixture_root = Path(os.environ.get("VOLUNDR_E2E_DATA_DIR", "/tmp/volundr-e2e-fixture"))
    fixture_port = int(os.environ.get("VOLUNDR_E2E_PORT", "8000"))
    uvicorn.run(create_e2e_fixture_app(fixture_root), host="127.0.0.1", port=fixture_port)
