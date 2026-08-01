import ast
import json
import hashlib
from collections.abc import Generator
from pathlib import Path
from typing import Any
from uuid import uuid4

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
from app.models.revision_plan import RevisionPlan
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
from app.services.cad.geometry_bodies import GEOMETRY_BODIES_SCHEMA_VERSION
from app.services.cad.source_scaffold import SCAFFOLD_VERSION, _component_geometry_name, _feature_geometry_name
from app.services.mesh.inspect import MeshMetadata
from app.schemas.project import ProjectCreate, RequirementExtractionCreate
from app.services.projects.service import ProjectService


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

ORGANIZER_SOURCE = PLATE_SOURCE.replace(
    'PARAMETERS = [',
    '''PARAMETERS = [
    ParameterSpec(id="column_count", label="Column count", type="int", default=4, editable=True, source_requirement_id="column_count", source="user"),
    ParameterSpec(id="wall_thickness", label="Wall thickness", type="float", default=3.0, unit="mm", editable=False, protected=True),''',
).replace(
    'return cq.Workplane("XY").box(params["plate_width"], 50.0, 3.0)',
    'return cq.Workplane("XY").box(params["plate_width"] + params["column_count"] * 0.0, 50.0, params["wall_thickness"])',
)

ORGANIZER_PLAN: dict[str, Any] = {
    **PLATE_PLAN,
    "product_type": "repeated_cell_organizer",
    "purpose": "A configurable repeated-cell organizer",
    "exposed_controls": [
        {"parameter_id": "column_count", "label": "Column count", "source": "explicit_user_request"}
    ],
    "parameters": [
        PLATE_PLAN["parameters"][0],
        {
            "id": "column_count",
            "label": "Column count",
            "value": 4,
            "type": "integer",
            "minimum": 1,
            "maximum": 12,
            "editable": True,
            "protected": False,
            "component_id": "plate",
            "source_requirement_id": "column_count",
            "constraint_mode": "configurable_parameter",
            "provenance": {
                "relationship": "direct",
                "source_requirement_ids": ["column_count"],
            },
        },
        {
            "id": "wall_thickness",
            "label": "Wall thickness",
            "value": 3,
            "unit": "mm",
            "type": "number",
            "editable": False,
            "protected": True,
            "component_id": "plate",
        },
    ],
    "derived_parameters": [
        {
            "id": "overall_width",
            "label": "Overall width",
            "expression": "column_count * 20",
            "unit": "mm",
            "depends_on": ["column_count"],
        }
    ],
    "dependency_edges": [
        {"from": "column_count", "to": "overall_width", "relationship": "Count sets organizer width"}
    ],
}

ENCLOSURE_SOURCE = '''
import cadquery as cq

from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product, component, feature

PARAMETERS = [
    ParameterSpec(id="body_width", label="Body width", type="float", default=80.0, unit="mm", editable=True, protected=True, source_requirement_id="body_width"),
    ParameterSpec(id="body_depth", label="Body depth", type="float", default=50.0, unit="mm", editable=True, protected=True, source_requirement_id="body_depth"),
    ParameterSpec(id="wall_thickness", label="Wall thickness", type="float", default=3.0, unit="mm", editable=False, protected=True),
    ParameterSpec(id="lid_thickness", label="Lid thickness", type="float", default=3.0, unit="mm", editable=False, protected=True),
    ParameterSpec(id="fit_clearance", label="Fit clearance", type="float", default=0.4, unit="mm", editable=False, protected=True),
]

@component("base_shell")
@feature("base_shell", component="base_shell")
def base_shell_model(params):
    return cq.Workplane("XY").box(params["body_width"], params["body_depth"], params["wall_thickness"])

@component("snap_lid")
@feature("lid_panel", component="snap_lid")
def snap_lid_model(params):
    return cq.Workplane("XY").box(params["body_width"], params["body_depth"] + params["fit_clearance"] * 0.0, params["lid_thickness"])

def build(params):
    base = base_shell_model(params)
    lid = snap_lid_model(params)
    return Product(
        parameters=PARAMETERS,
        outputs=[
            PrintableOutput(output_id="base", label="Enclosure base", component_id="base_shell", component_ids=("base_shell",), model=base, expected_solid_count=1, allow_disconnected_solids=False),
            PrintableOutput(output_id="lid", label="Snap lid", component_id="snap_lid", component_ids=("snap_lid",), model=lid, expected_solid_count=1, allow_disconnected_solids=False),
        ],
    )
'''

ENCLOSURE_REVISED_SOURCE = ENCLOSURE_SOURCE.replace(
    'return cq.Workplane("XY").box(params["body_width"], params["body_depth"] + params["fit_clearance"] * 0.0, params["lid_thickness"])',
    '# recessed finger pull\n    return cq.Workplane("XY").box(params["body_width"], params["body_depth"] + params["fit_clearance"] * 0.0, params["lid_thickness"]).cut(cq.Workplane("XY").box(18.0, 8.0, 1.0).translate((0.0, -18.0, 1.0)))',
)

ENCLOSURE_SPEC: dict[str, Any] = {
    "schema_version": "1.0",
    "object_type": "electronics_enclosure",
    "purpose": "Protect an electronic assembly in a printable enclosure with a removable lid.",
    "units": "mm",
    "supported_scope": True,
    "critical_dimensions": [
        {"id": "body_width", "label": "Body width", "value": 80, "unit": "mm", "source": "user", "importance": "critical", "protected": True},
        {"id": "body_depth", "label": "Body depth", "value": 50, "unit": "mm", "source": "user", "importance": "critical", "protected": True},
    ],
    "parameters": [],
    "functional_requirements": [{"id": "separate_parts", "description": "Provide a base and removable snap lid.", "source": "user", "importance": "critical", "protected": True}],
    "print_requirements": {},
    "assumptions": [],
    "conflicts": [],
    "missing_requirements": [],
    "clarification_required": False,
    "clarification_questions": [],
    "generation_ready": True,
    "outcome": "generation_ready",
}

ENCLOSURE_PLAN: dict[str, Any] = {
    "schema_version": "1.0",
    "design_level": "assembly",
    "product_type": "electronics_enclosure",
    "purpose": ENCLOSURE_SPEC["purpose"],
    "units": "mm",
    "parameters": [
        {"id": "body_width", "label": "Body width", "value": 80, "unit": "mm", "type": "number", "source_requirement_id": "body_width", "editable": True, "protected": True, "component_id": "base_shell"},
        {"id": "body_depth", "label": "Body depth", "value": 50, "unit": "mm", "type": "number", "source_requirement_id": "body_depth", "editable": True, "protected": True, "component_id": "base_shell"},
        {"id": "wall_thickness", "label": "Wall thickness", "value": 3, "unit": "mm", "type": "number", "editable": False, "protected": True, "component_id": "base_shell"},
        {"id": "lid_thickness", "label": "Lid thickness", "value": 3, "unit": "mm", "type": "number", "editable": False, "protected": True, "component_id": "snap_lid"},
        {"id": "fit_clearance", "label": "Fit clearance", "value": 0.4, "unit": "mm", "type": "number", "editable": False, "protected": True, "component_id": "snap_lid"},
    ],
    "derived_parameters": [],
    "dependency_edges": [],
    "components": [
        {"id": "base_shell", "label": "Enclosure body", "description": "Protected enclosure body", "features": ["base_shell"], "parameters": ["body_width", "body_depth", "wall_thickness"]},
        {"id": "snap_lid", "label": "Snap lid", "description": "Removable lid", "features": ["lid_panel"], "parameters": ["body_width", "body_depth", "lid_thickness", "fit_clearance"]},
    ],
    "features": [
        {"id": "base_shell", "component_id": "base_shell", "type": "shell", "description": "Protected enclosure body", "parameters": ["body_width", "body_depth", "wall_thickness"], "protected": True},
        {"id": "lid_panel", "component_id": "snap_lid", "type": "cover", "description": "Removable snap lid", "parameters": ["body_width", "body_depth", "lid_thickness", "fit_clearance"], "protected": True},
    ],
    "presets": [],
    "assembly_strategy": {"type": "separate_parts", "relationships": [{"from_component_id": "snap_lid", "to_component_id": "base_shell", "relationship": "fits over"}]},
    "printable_outputs": [
        {"id": "base", "label": "Enclosure base", "component_id": "base_shell", "component_ids": ["base_shell"], "entrypoint": "base", "filename": "base.stl", "quantity": 1, "required": True, "expected_solid_count": 1, "allow_disconnected_solids": False, "output_type": "printable_component"},
        {"id": "lid", "label": "Snap lid", "component_id": "snap_lid", "component_ids": ["snap_lid"], "entrypoint": "lid", "filename": "lid.stl", "quantity": 1, "required": True, "expected_solid_count": 1, "allow_disconnected_solids": False, "output_type": "printable_component"},
    ],
    "risks": [],
    "clarification_required": False,
    "clarification_questions": [],
    "plan_ready": True,
    "outcome": "plan_ready",
}

ENCLOSURE_REVISION_PLAN: dict[str, Any] = {
    "schema_version": "revision-plan-v1",
    "reason": "user_request",
    "summary": "Add a recessed finger pull to the snap lid while preserving the enclosure body and fit.",
    "requested_changes": [{"target_type": "feature", "target_id": "lid_panel", "current_value": "flat lid", "requested_value": "recessed finger pull", "change_type": "modify", "source": "user"}],
    "targeted_components": ["snap_lid"],
    "targeted_features": ["lid_panel"],
    "targeted_outputs": ["lid"],
    "targeted_findings": [],
    "allowed_parameter_changes": [],
    "required_dependency_changes": [],
    "allowed_component_changes": ["snap_lid"],
    "allowed_feature_changes": ["lid_panel"],
    "protected_parameters": [
        {"parameter_id": "body_width", "expected_value": 80, "unit": "mm"},
        {"parameter_id": "body_depth", "expected_value": 50, "unit": "mm"},
        {"parameter_id": "wall_thickness", "expected_value": 3, "unit": "mm"},
        {"parameter_id": "lid_thickness", "expected_value": 3, "unit": "mm"},
        {"parameter_id": "fit_clearance", "expected_value": 0.4, "unit": "mm"},
    ],
    "protected_components": ["base_shell"],
    "protected_features": ["base_shell"],
    "protected_outputs": ["base"],
    "prohibited_changes": ["Do not change base_shell", "Do not change base output", "Do not change enclosure fit parameters"],
    "success_criteria": [
        {"type": "output_exists", "target_id": "base"},
        {"type": "output_exists", "target_id": "lid"},
        {"type": "parameter_unchanged", "target_id": "wall_thickness", "expected_value": 3, "unit": "mm"},
    ],
    "requires_design_specification_version": False,
    "requires_design_plan_version": False,
    "clarification_questions": [],
    "outcome": "revision_ready",
}


def _structured_geometry_response(plan: dict[str, Any], source: str) -> dict[str, Any]:
    """Adapt deterministic fixture geometry to the production body contract."""

    tree = ast.parse(source)
    builders = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name != "build"
    ]
    functions: list[dict[str, Any]] = []
    for component, builder in zip(
        [item for item in plan.get("components", []) if isinstance(item, dict)],
        builders,
    ):
        component_id = str(component["id"])
        function_id = _component_geometry_name(component_id)
        if component_id == "snap_lid" and "lid_component" in source:
            function_id = _component_geometry_name("lid_component")
        return_statement = next(
            (statement for statement in reversed(builder.body) if isinstance(statement, ast.Return)),
            None,
        )
        result_symbol = (
            return_statement.value.id
            if return_statement is not None and isinstance(return_statement.value, ast.Name)
            else "body"
        )
        statements = [
            ast.unparse(statement)
            for statement in builder.body
            if not isinstance(statement, ast.Return)
        ]
        if return_statement is not None and not isinstance(return_statement.value, ast.Name):
            statements.append(f"{result_symbol} = {ast.unparse(return_statement.value)}")
        functions.append(
            {
                "function_id": function_id,
                "statements": statements,
                "result_symbol": result_symbol,
            }
        )
    for feature in plan.get("features", []) or []:
        if not isinstance(feature, dict) or not feature.get("id"):
            continue
        feature_parameter_ids = [
            str(parameter_id)
            for parameter_id in feature.get("parameters", []) or []
            if parameter_id
        ]
        statements = [
            (
                f'body = body.union(cq.Workplane("XY").box('
                f'params[{parameter_id!r}] * 0.001, 0.001, 0.001))'
            )
            for parameter_id in feature_parameter_ids
        ]
        functions.append(
            {
                "function_id": _feature_geometry_name(str(feature["id"])),
                "statements": statements,
                "result_symbol": "body",
            }
        )
    return {
        "schema_version": GEOMETRY_BODIES_SCHEMA_VERSION,
        "functions": functions,
    }


class FixtureProvider:
    """A deterministic provider used only by browser integration tests."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.calls_by_project: dict[tuple[str, str], list[str]] = {}
        self.revision_mode = "success"

    def _record_call(self, request: Any, call: str) -> None:
        self.calls.append(call)
        key = (request.project_name, request.original_intent)
        self.calls_by_project.setdefault(key, []).append(call)

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
        return "fixture-cadquery-v2"

    def cadquery_generation_contract_version(self) -> str:
        return SCAFFOLD_VERSION

    def prompt_template_version_for(self, _request: ModelGenerationRequest) -> str:
        return "fixture-cadquery-v2"

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
        self._record_call(request, "requirement_extraction")
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
        if "organizer" in request.user_instruction.lower():
            payload["object_type"] = "repeated_cell_organizer"
            payload["parameters"] = [
                {
                    "id": "column_count",
                    "label": "Column count",
                    "value": 4,
                    "source": "user",
                    "importance": "important",
                    "protected": False,
                    "editable": True,
                },
                {
                    "id": "wall_thickness",
                    "label": "Wall thickness",
                    "value": 3,
                    "unit": "mm",
                    "source": "product_default",
                    "importance": "important",
                    "protected": True,
                    "editable": False,
                },
            ]
        if "enclosure" in request.user_instruction.lower() or "enclosure" in request.original_intent.lower():
            payload = ENCLOSURE_SPEC | {"purpose": request.user_instruction}
        return RequirementExtractionResult(
            raw_output=json.dumps(payload), provider="fixture", provider_model="fixture-model"
        )

    async def create_design_plan(self, _request: DesignPlanRequest) -> DesignPlanResult:
        self._record_call(_request, "design_plan_generation")
        if "enclosure" in _request.user_instruction.lower() or "enclosure" in _request.original_intent.lower():
            plan = ENCLOSURE_PLAN
        else:
            plan = ORGANIZER_PLAN if "organizer" in _request.user_instruction.lower() else PLATE_PLAN
        return DesignPlanResult(
            raw_output=json.dumps(plan), provider="fixture", provider_model="fixture-model"
        )

    async def generate_model(self, _request: ModelGenerationRequest) -> ModelGenerationResult:
        raise AssertionError("fixture requires CadQuery generation")

    async def generate_cadquery_model(self, _request: ModelGenerationRequest) -> ModelGenerationResult:
        is_enclosure = "enclosure" in _request.user_instruction.lower() or "enclosure" in _request.original_intent.lower()
        self._record_call(_request, "component_revision" if _request.revision_plan else "source_generation")
        if is_enclosure:
            plan = ENCLOSURE_PLAN
            source = ENCLOSURE_REVISED_SOURCE if _request.revision_plan else ENCLOSURE_SOURCE
            if _request.revision_plan and self.revision_mode == "protected_base_drift":
                source = source.replace(
                    'cq.Workplane("XY").box(params["body_width"], params["body_depth"], params["wall_thickness"])',
                    'cq.Workplane("XY").box(params["body_width"] + 8.0, params["body_depth"], params["wall_thickness"])',
                    1,
                )
            elif _request.revision_plan and self.revision_mode == "identity_replacement":
                source = source.replace('"snap_lid"', '"lid_component"')
        else:
            plan = ORGANIZER_PLAN if "organizer" in _request.user_instruction.lower() else PLATE_PLAN
            source = ORGANIZER_SOURCE if "organizer" in _request.user_instruction.lower() else PLATE_SOURCE
        return ModelGenerationResult(
            raw_output=json.dumps(_structured_geometry_response(plan, source)),
            provider="fixture",
            provider_model="fixture-model",
        )

    async def create_revision_plan(self, _request: RevisionPlanRequest) -> RevisionPlanResult:
        self._record_call(_request, "revision_plan_generation")
        if "enclosure" not in _request.original_intent.lower():
            return RevisionPlanResult(
                raw_output=json.dumps(
                    {
                        "schema_version": "revision-plan-v1",
                        "reason": _request.reason,
                        "summary": _request.user_instruction,
                        "requested_changes": [],
                        "targeted_components": ["plate"],
                        "targeted_outputs": ["plate"],
                        "protected_components": ["plate"],
                        "protected_outputs": ["plate"],
                        "outcome": "revision_ready",
                    }
                ),
                provider="fixture",
                provider_model="fixture-model",
            )
        return RevisionPlanResult(
            raw_output=json.dumps(ENCLOSURE_REVISION_PLAN),
            provider="fixture",
            provider_model="fixture-model",
        )

    async def create_source_brief(self, _request: SourceBriefRequest) -> SourceBriefResult:
        raise AssertionError("source briefs are not enabled in the initial fixture slice")


class FixtureRunner:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[dict[str, Any]] = []
        self.failure_mode = "success"
        self.failure_injected = False

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
        output_specs = requested_outputs or [{"output_id": "plate", "required": True}]
        output_ids = [str(spec["output_id"]) for spec in output_specs]
        self.calls.append({"job_id": job_id, "parameter_values": values, "output_ids": output_ids})
        job_dir = self.root / "cad-jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        source_path = job_dir / "source.py"
        stdout_path = job_dir / "stdout.log"
        stderr_path = job_dir / "stderr.log"
        manifest_path = job_dir / "execution-manifest.json"
        source_path.write_text(source, encoding="utf-8")
        stdout_path.write_text("Fixture CAD execution completed", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        parameter_hash = hashlib.sha256(
            json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if self.failure_mode == "worker_failure" and not self.failure_injected:
            self.failure_injected = True
            manifest_path.write_text(
                json.dumps(
                    {
                        "cad_backend": "cadquery",
                        "source_hash": source_hash,
                        "parameter_hash": parameter_hash,
                        "requested_output_ids": output_ids,
                        "outputs": [
                            {
                                "output_id": output_ids[0],
                                "required": bool(output_specs[0].get("required", True)),
                                "success": False,
                                "error": "worker_timeout",
                            }
                        ],
                        "worker_status": "failed",
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            error_message = "Volundr could not finish building this required printable part."
            failed_output = CadQueryOutputResult(
                output_id=output_ids[0],
                entrypoint=output_ids[0],
                required=bool(output_specs[0].get("required", True)),
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
                compile_error=error_message,
            )
            return CadQueryCompileResult(
                job_id=job_id,
                success=False,
                timed_out=False,
                exit_code=1,
                source_path=source_path,
                stl_path=None,
                step_path=None,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                metadata_path=None,
                source_hash=source_hash,
                output_size_bytes=0,
                metadata=None,
                error_message=error_message,
                command_args=["fixture-cadquery", ",".join(output_ids)],
                outputs=[failed_output],
                execution_manifest_path=manifest_path,
            )
        outputs: list[CadQueryOutputResult] = []
        output_manifest_entries: list[dict[str, Any]] = []
        first_stl: Path | None = None
        first_step: Path | None = None
        first_metadata: Path | None = None
        for spec in output_specs:
            output_id = str(spec["output_id"])
            stl_path = job_dir / f"{output_id}.stl"
            step_path = job_dir / f"{output_id}.step"
            brep_path = job_dir / f"{output_id}.brep"
            metadata_path = job_dir / f"{output_id}.json"
            topology_path = job_dir / f"{output_id}-topology.json"
            if output_id == "base":
                extents = (
                    float(values.get("body_width", 80.0)),
                    float(values.get("body_depth", 50.0)),
                    float(values.get("wall_thickness", 3.0)),
                )
            elif output_id == "lid":
                extents = (
                    float(values.get("body_width", 80.0)),
                    float(values.get("body_depth", 50.0)),
                    float(values.get("lid_thickness", 3.0)),
                )
            else:
                extents = (float(values.get("plate_width", values.get("column_count", 4) * 20)), 50.0, 3.0)
            mesh = trimesh.creation.box(extents=extents)
            mesh.apply_translation((extents[0] / 2, extents[1] / 2, extents[2] / 2))
            if self.failure_mode == "multiple_solids":
                second = trimesh.creation.box(extents=(8.0, 8.0, extents[2]))
                second.apply_translation((extents[0] + 12.0, extents[1] / 2, extents[2] / 2))
                mesh = trimesh.util.concatenate([mesh, second])
            # The structured geometry contract removes provider comments. Detect
            # the executable fixture feature instead of relying on comment text.
            if output_id == "lid" and ".cut(" in source:
                mesh.vertices[0] += (0.1, 0.1, 0.1)
            mesh.export(stl_path)
            step_path.write_text("ISO-10303-21; END-ISO-10303-21;", encoding="utf-8")
            brep_path.write_text("BREP", encoding="utf-8")
            metadata = MeshMetadata(
                size_x_mm=extents[0],
                size_y_mm=extents[1],
                size_z_mm=extents[2],
                volume_mm3=extents[0] * extents[1] * extents[2],
                triangle_count=12,
                connected_components=2 if self.failure_mode == "multiple_solids" else 1,
                is_watertight=True,
                is_winding_consistent=True,
                center_of_mass=(extents[0] / 2, extents[1] / 2, extents[2] / 2),
            )
            topology = {
                "valid": self.failure_mode != "multiple_solids",
                "expected_solid_count": 1,
                "detected_solid_count": 2 if self.failure_mode == "multiple_solids" else 1,
                "shell_count": 2 if self.failure_mode == "multiple_solids" else 1,
                "allow_disconnected_solids": False,
                "failure_reason": "solid_count_mismatch" if self.failure_mode == "multiple_solids" else None,
                "bounding_box_mm": {"xlen": extents[0], "ylen": extents[1], "zlen": extents[2]},
            }
            metadata_path.write_text(json.dumps(metadata.__dict__), encoding="utf-8")
            topology_path.write_text(json.dumps(topology), encoding="utf-8")
            stl_hash = hashlib.sha256(stl_path.read_bytes()).hexdigest()
            step_hash = hashlib.sha256(step_path.read_bytes()).hexdigest()
            brep_hash = hashlib.sha256(brep_path.read_bytes()).hexdigest()
            outputs.append(
                CadQueryOutputResult(
                    output_id=output_id,
                    entrypoint=output_id,
                    required=bool(spec.get("required", True)),
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
            )
            output_manifest_entries.append(
                {
                    "output_id": output_id,
                    "required": bool(spec.get("required", True)),
                    "success": True,
                    "topology_metadata": topology,
                    "stl_hash": stl_hash,
                    "step_hash": step_hash,
                    "brep_hash": brep_hash,
                    "placement_transform": {"translation": [0.0, 0.0, 0.0], "rotation_degrees": [0.0, 0.0, 0.0]},
                }
            )
            first_stl = first_stl or stl_path
            first_step = first_step or step_path
            first_metadata = first_metadata or metadata_path
        manifest_path.write_text(
            json.dumps(
                {
                    "cad_backend": "cadquery",
                    "source_language": "python",
                    "source_contract_version": "cadquery-v1",
                    "source_hash": source_hash,
                    "parameter_hash": parameter_hash,
                    "parameters": values,
                    "requested_output_ids": output_ids,
                    "output_ids": output_ids,
                    "outputs": output_manifest_entries,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
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
            source_hash=source_hash,
            output_size_bytes=sum(output.output_size_bytes for output in outputs),
            metadata=outputs[0].metadata if outputs else None,
            error_message=None,
            command_args=["fixture-cadquery", ",".join(output_ids)],
            outputs=outputs,
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
        service = ProjectService(db=db, data_dir=data_dir)
        project = db.get(Project, project_id)
        project_calls = (
            provider.calls_by_project.get((project.name, project.original_intent), [])
            if project is not None
            else []
        )
        return {
            "provider_call_count": len(project_calls),
            "provider_calls": list(project_calls),
            "worker_calls": [
                call
                for call in runner.calls
                if any(
                    call["job_id"] == revision.id or call["job_id"].startswith(f"{revision.id}-")
                    for revision in db.scalars(select(Revision).where(Revision.project_id == project_id))
                )
            ],
            "workflow_run_ids": [run.id for run in runs],
            "revision_plans": [
                {
                    "id": plan.id,
                    "base_revision_id": plan.base_revision_id,
                    "generated_revision_id": plan.generated_revision_id,
                    "review_state": plan.review_state,
                    "payload": service._read_revision_plan_payload(plan),
                }
                for plan in db.scalars(
                    select(RevisionPlan).where(RevisionPlan.project_id == project_id).order_by(RevisionPlan.created_at)
                )
            ],
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
            "workflow_event_details": [
                {
                    "id": event.id,
                    "workflow_run_id": event.workflow_run_id,
                    "root_workflow_run_id": event.root_workflow_run_id,
                    "correlation_id": event.correlation_id,
                    "sequence_number": event.sequence_number,
                    "event_type": event.event_type,
                    "revision_id": event.revision_id,
                }
                for event in db.scalars(
                    select(WorkflowEvent)
                    .where(WorkflowEvent.project_id == project_id)
                    .order_by(WorkflowEvent.workflow_run_id, WorkflowEvent.sequence_number)
                )
            ],
            "frontend_event_details": [
                {
                    "workflow_run_id": event.workflow_run_id,
                    "correlation_id": event.correlation_id,
                    "action_name": event.action_name,
                    "metadata": json.loads(event.metadata_json),
                }
                for event in db.scalars(
                    select(FrontendWorkflowEvent)
                    .where(FrontendWorkflowEvent.project_id == project_id)
                    .order_by(FrontendWorkflowEvent.recorded_at)
                )
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
            "artifact_types": list(
                db.scalars(
                    select(WorkflowArtifact.artifact_type)
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
                    "configuration_change_id": revision.configuration_change_id,
                    "parameter_hash": (service.read_output_manifest(revision.id) or {}).get("parameter_hash"),
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

    @app.post("/api/test-fixture/scenarios/configure-organizer", status_code=201, include_in_schema=False)
    async def seed_configure_organizer(db: Session = Depends(override_db)) -> dict[str, Any]:
        runner.failure_mode = "success"
        runner.failure_injected = False
        service = ProjectService(db=db, data_dir=data_dir, ai_provider=provider, cad_runner=runner)
        project = service.create_project(
            ProjectCreate(name="Configurable organizer", original_intent="Create a repeated-cell organizer.")
        )
        specification = await service.extract_requirements(
            project.id,
            RequirementExtractionCreate(user_instruction="Create an organizer."),
        )
        assert specification is not None
        plan = await service.create_design_plan_from_specification(specification.id)
        assert plan is not None
        approved_plan = service.approve_design_plan(plan.id)
        assert approved_plan is not None
        candidate = await service.generate_from_design_plan(approved_plan.id)
        assert candidate is not None
        current_revision = service.accept_candidate(candidate.id)
        assert current_revision is not None
        refreshed = service.get_project(project.id)
        assert refreshed is not None
        return {
            "project": {"id": refreshed.id, "active_revision_id": refreshed.active_revision_id},
            "current_revision": current_revision.model_dump(mode="json"),
        }

    @app.post("/api/test-fixture/scenarios/revise-enclosure-lid", status_code=201, include_in_schema=False)
    async def seed_revise_enclosure_lid(
        mode: str = "success",
        db: Session = Depends(override_db),
    ) -> dict[str, Any]:
        if mode not in {"success", "protected_base_drift", "identity_replacement"}:
            raise HTTPException(status_code=400, detail="unsupported enclosure fixture mode")
        provider.revision_mode = mode
        runner.failure_mode = "success"
        runner.failure_injected = False
        service = ProjectService(db=db, data_dir=data_dir, ai_provider=provider, cad_runner=runner)
        project_name = f"Deterministic enclosure {uuid4().hex[:8]}"
        project = service.create_project(
            ProjectCreate(
                name=project_name,
                original_intent="Create a two-part electronics enclosure.",
            )
        )
        specification = await service.extract_requirements(
            project.id,
            RequirementExtractionCreate(user_instruction="Create an electronics enclosure."),
        )
        assert specification is not None
        plan = await service.create_design_plan_from_specification(specification.id)
        assert plan is not None
        approved_plan = service.approve_design_plan(plan.id)
        assert approved_plan is not None
        candidate = await service.generate_from_design_plan(approved_plan.id)
        assert candidate is not None
        current_revision = service.accept_candidate(candidate.id)
        assert current_revision is not None
        refreshed = service.get_project(project.id)
        assert refreshed is not None
        return {
            "project": {
                "id": refreshed.id,
                "name": refreshed.name,
                "active_revision_id": refreshed.active_revision_id,
            },
            "current_revision": current_revision.model_dump(mode="json"),
        }

    @app.post("/api/test-fixture/scenarios/recoverable-blocked-part", status_code=201, include_in_schema=False)
    async def seed_recoverable_blocked_part(
        failure_mode: str = "multiple_solids",
        db: Session = Depends(override_db),
    ) -> dict[str, Any]:
        if failure_mode not in {"multiple_solids", "worker_failure"}:
            raise HTTPException(status_code=400, detail="unsupported blocked fixture mode")
        service = ProjectService(db=db, data_dir=data_dir, ai_provider=provider, cad_runner=runner)
        project = service.create_project(
            ProjectCreate(
                name=f"Recoverable blocked part {uuid4().hex[:8]}",
                original_intent="Create a mounting plate with one required printable part.",
            )
        )
        specification = await service.extract_requirements(
            project.id,
            RequirementExtractionCreate(user_instruction="Create a mounting plate."),
        )
        assert specification is not None
        plan = await service.create_design_plan_from_specification(specification.id)
        assert plan is not None
        approved_plan = service.approve_design_plan(plan.id)
        assert approved_plan is not None
        runner.failure_mode = "success"
        runner.failure_injected = False
        current_revision = await service.generate_from_design_plan(approved_plan.id)
        assert current_revision is not None
        accepted_revision = service.accept_candidate(current_revision.id)
        assert accepted_revision is not None
        runner.failure_mode = failure_mode
        runner.failure_injected = False
        blocked_revision = await service.generate_from_design_plan(approved_plan.id)
        assert blocked_revision is not None
        refreshed = service.get_project(project.id)
        assert refreshed is not None
        current_workflow = db.scalar(
            select(WorkflowRun)
            .join(WorkflowEvent, WorkflowEvent.workflow_run_id == WorkflowRun.id)
            .where(WorkflowEvent.revision_id == accepted_revision.id)
            .where(WorkflowEvent.event_type == "candidate.accepted")
            .order_by(WorkflowRun.started_at.desc())
        )
        blocked_workflow = db.scalar(
            select(WorkflowRun)
            .join(WorkflowEvent, WorkflowEvent.workflow_run_id == WorkflowRun.id)
            .where(WorkflowEvent.revision_id == blocked_revision.id)
            .where(WorkflowEvent.event_type == "candidate.classified")
            .order_by(WorkflowRun.started_at.desc())
        )
        return {
            "project": {
                "id": refreshed.id,
                "name": refreshed.name,
                "active_revision_id": refreshed.active_revision_id,
            },
            "current_revision": accepted_revision.model_dump(mode="json"),
            "blocked_revision": blocked_revision.model_dump(mode="json"),
            "current_workflow_run_id": current_workflow.id if current_workflow is not None else None,
            "blocked_workflow_run_id": blocked_workflow.id if blocked_workflow is not None else None,
        }

    return app


if __name__ == "__main__":
    import os
    import shutil

    import uvicorn

    fixture_root = Path(os.environ.get("VOLUNDR_E2E_DATA_DIR", "/tmp/volundr-e2e-fixture"))
    fixture_port = int(os.environ.get("VOLUNDR_E2E_PORT", "8000"))
    try:
        uvicorn.run(create_e2e_fixture_app(fixture_root), host="127.0.0.1", port=fixture_port)
    finally:
        if os.environ.get("VOLUNDR_E2E_CLEANUP") == "true":
            shutil.rmtree(fixture_root, ignore_errors=True)
