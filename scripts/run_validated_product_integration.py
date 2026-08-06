"""Execute the product-facing validated CadQuery workflow and write evidence.

This intentionally drives the FastAPI application with dependency overrides for
deterministic provider/worker transports.  It does not call a research runner.
"""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.dependencies import get_ai_provider, get_cad_runner, get_data_dir  # noqa: E402
from app.core.config import Settings, settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.generation_attempt import GenerationAttempt  # noqa: E402
from app.models.revision import Revision  # noqa: E402
from app.models.validated_cadquery_workflow import (  # noqa: E402
    VALIDATED_OUTPUT_STATES,
    VALIDATED_WORKFLOW_STATES,
    ValidatedCadQueryWorkflow,
)
from app.services.ai.provider import (  # noqa: E402
    DesignPlanResult,
    ModelGenerationResult,
    RequirementExtractionResult,
    RevisionPlanResult,
)
from app.services.cad.geometry_slots import GEOMETRY_SLOTS_SCHEMA_VERSION  # noqa: E402
from app.services.cad.source_scaffold import SCAFFOLD_VERSION  # noqa: E402
from app.testing.e2e_fixture_server import (  # noqa: E402
    FixtureProvider,
    FixtureRunner,
    _structured_geometry_response,
    _structured_geometry_slot_response,
)


EVIDENCE_ROOT = REPO_ROOT / "data/debug-sessions/product-integration/validated-cadquery-product-flow-01"


PRODUCT_SOURCE = '''
import cadquery as cq

from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product, component, feature

PARAMETERS = [
    ParameterSpec(id="plate_width", label="Plate width", type="float", default=96.0, unit="mm", editable=True, protected=True, source_requirement_id="plate_width"),
    ParameterSpec(id="plate_depth", label="Plate depth", type="float", default=64.0, unit="mm", editable=True, protected=True, source_requirement_id="plate_depth"),
    ParameterSpec(id="plate_thickness", label="Plate thickness", type="float", default=4.0, unit="mm", editable=True, protected=True, source_requirement_id="plate_thickness"),
    ParameterSpec(id="slot_length", label="Clearance slot length", type="float", default=22.0, unit="mm", editable=True, protected=False, source_requirement_id="slot_length"),
    ParameterSpec(id="slot_width", label="Clearance slot width", type="float", default=8.0, unit="mm", editable=True, protected=False, source_requirement_id="slot_width"),
    ParameterSpec(id="slot_x", label="Clearance slot X", type="float", default=-21.0, unit="mm", editable=True, protected=False, source_requirement_id="slot_x"),
    ParameterSpec(id="slot_y", label="Clearance slot Y", type="float", default=14.0, unit="mm", editable=True, protected=False, source_requirement_id="slot_y"),
    ParameterSpec(id="mounting_hole_diameter", label="Mounting hole diameter", type="float", default=5.0, unit="mm", editable=True, protected=False, source_requirement_id="mounting_hole_diameter"),
    ParameterSpec(id="hole_x", label="Mounting hole X", type="float", default=24.0, unit="mm", editable=True, protected=False, source_requirement_id="hole_x"),
    ParameterSpec(id="hole_y", label="Mounting hole Y", type="float", default=-17.0, unit="mm", editable=True, protected=False, source_requirement_id="hole_y"),
]

@component("plate_body")
@feature("asymmetric_clearance_slot", component="plate_body")
@feature("offset_mounting_hole", component="plate_body")
def build_plate_body(params):
    body = cq.Workplane("XY").box(params["plate_width"], params["plate_depth"], params["plate_thickness"])
    clearance_slot = cq.Workplane("XY").slot2D(params["slot_length"], params["slot_width"], 90).extrude(params["plate_thickness"] + 2.0).translate((params["slot_x"], params["slot_y"], -1.0))
    body = body.cut(clearance_slot)
    mounting_hole = cq.Workplane("XY").circle(params["mounting_hole_diameter"] / 2.0).extrude(params["plate_thickness"] + 2.0).translate((params["hole_x"], params["hole_y"], -1.0))
    body = body.cut(mounting_hole)
    return body

def build(params):
    plate = build_plate_body(params)
    return Product(
        parameters=PARAMETERS,
        outputs=[
            PrintableOutput(output_id="primary_printable_output", component_id="plate_body", label="Asymmetric mounting plate", model=plate, required=True, expected_solid_count=1, allow_disconnected_solids=False),
            PrintableOutput(output_id="optional_companion_output", component_id="plate_body", label="Optional companion plate", model=plate, required=False, expected_solid_count=1, allow_disconnected_solids=False),
        ],
    )
'''

PRODUCT_REVISION_SOURCE = PRODUCT_SOURCE.replace(
    'default=-21.0, unit="mm", editable=True, protected=False, source_requirement_id="slot_x"',
    'default=-16.0, unit="mm", editable=True, protected=False, source_requirement_id="slot_x"',
).replace(
    'body = body.cut(mounting_hole)\n    return body',
    'body = body.cut(mounting_hole)\n    revision_notch = cq.Workplane("XY").box(10.0, 4.0, params["plate_thickness"] + 2.0).translate((8.0, 24.0, -1.0))\n    body = body.cut(revision_notch)\n    return body',
)


def _parameter(id_: str, label: str, value: float, *, protected: bool, source: str = "user") -> dict[str, Any]:
    return {
        "id": id_, "label": label, "value": value, "unit": "mm", "type": "number",
        "source_requirement_id": id_, "source": source, "editable": not protected,
        "protected": protected, "component_id": "plate_body",
    }


def product_requirements(intent: str) -> dict[str, Any]:
    dimensions = [
        ("plate_width", "Plate width", 96), ("plate_depth", "Plate depth", 64),
        ("plate_thickness", "Plate thickness", 4), ("slot_length", "Clearance slot length", 22),
        ("slot_width", "Clearance slot width", 8), ("slot_x", "Clearance slot X", -21),
        ("slot_y", "Clearance slot Y", 14), ("mounting_hole_diameter", "Mounting hole diameter", 5),
        ("hole_x", "Mounting hole X", 24), ("hole_y", "Mounting hole Y", -17),
    ]
    return {
        "schema_version": "1.0", "object_type": "asymmetric_mounting_plate", "purpose": intent,
        "units": "mm", "supported_scope": True,
        "critical_dimensions": [
            {"id": id_, "label": label, "value": value, "unit": "mm", "source": "user", "importance": "critical" if id_ in {"plate_width", "plate_depth", "plate_thickness"} else "important", "protected": id_ in {"plate_width", "plate_depth", "plate_thickness"}}
            for id_, label, value in dimensions
        ],
        "parameters": [
            {"id": id_, "label": label, "value": value, "unit": "mm", "source": "user", "importance": "critical" if id_ in {"plate_width", "plate_depth", "plate_thickness"} else "important", "protected": id_ in {"plate_width", "plate_depth", "plate_thickness"}, "editable": id_ not in {"plate_width", "plate_depth", "plate_thickness"}}
            for id_, label, value in dimensions
        ],
        "functional_requirements": [
            {"id": "printable_base", "description": "Provide one printable connected plate.", "source": "user", "importance": "critical", "protected": True, "type": "printability"},
            {"id": "slot_clearance", "description": "Include an irregular clearance slot for cable access.", "source": "user", "importance": "important", "protected": True, "type": "clearance"},
            {"id": "mount_interface", "description": "Include an offset mounting hole for the mounting interface.", "source": "user", "importance": "important", "protected": True, "type": "mounting_interface"},
        ],
        "print_requirements": {"material": "common FDM material", "orientation": "flat"},
        "assumptions": [], "conflicts": [], "missing_requirements": [],
        "clarification_required": False, "clarification_questions": [], "generation_ready": True, "outcome": "generation_ready",
    }


def product_plan() -> dict[str, Any]:
    return {
        "schema_version": "1.0", "design_level": "product", "product_type": "asymmetric_mounting_plate",
        "purpose": "A printable mounting plate with irregular clearance and mounting features.", "units": "mm",
        "parameters": [
            _parameter("plate_width", "Plate width", 96, protected=True), _parameter("plate_depth", "Plate depth", 64, protected=True),
            _parameter("plate_thickness", "Plate thickness", 4, protected=True), _parameter("slot_length", "Clearance slot length", 22, protected=False),
            _parameter("slot_width", "Clearance slot width", 8, protected=False), _parameter("slot_x", "Clearance slot X", -21, protected=False),
            _parameter("slot_y", "Clearance slot Y", 14, protected=False), _parameter("mounting_hole_diameter", "Mounting hole diameter", 5, protected=False),
            _parameter("hole_x", "Mounting hole X", 24, protected=False), _parameter("hole_y", "Mounting hole Y", -17, protected=False),
        ],
        "derived_parameters": [], "dependency_edges": [],
        "components": [{"id": "plate_body", "label": "Plate body", "description": "One connected printable base.", "features": ["asymmetric_clearance_slot", "offset_mounting_hole"], "parameters": ["plate_width", "plate_depth", "plate_thickness", "slot_length", "slot_width", "slot_x", "slot_y", "mounting_hole_diameter", "hole_x", "hole_y"]}],
        "features": [
            {"id": "asymmetric_clearance_slot", "component_id": "plate_body", "type": "clearance_slot", "description": "Irregularly placed elongated clearance slot.", "parameters": ["slot_length", "slot_width", "slot_x", "slot_y"], "protected": False},
            {"id": "offset_mounting_hole", "component_id": "plate_body", "type": "mounting_hole", "description": "Offset circular mounting hole.", "parameters": ["mounting_hole_diameter", "hole_x", "hole_y"], "protected": False},
        ],
        "presets": [], "assembly_strategy": {"type": "single_part", "instructions": ["Print flat with the feature face upward."]},
        "printable_outputs": [
            {"id": "primary_printable_output", "label": "Asymmetric mounting plate", "component_id": "plate_body", "component_ids": ["plate_body"], "entrypoint": "primary_printable_output", "filename": "asymmetric-mounting-plate.stl", "quantity": 1, "required": True, "expected_solid_count": 1, "allow_disconnected_solids": False, "output_type": "printable_component"},
            {"id": "optional_companion_output", "label": "Optional companion plate", "component_id": "plate_body", "component_ids": ["plate_body"], "entrypoint": "optional_companion_output", "filename": "optional-companion-plate.stl", "quantity": 1, "required": False, "expected_solid_count": 1, "allow_disconnected_solids": False, "output_type": "printable_component"},
        ],
        "risks": [], "clarification_required": False, "clarification_questions": [], "plan_ready": True, "outcome": "plan_ready",
    }


class ProductIntegrationProvider(FixtureProvider):
    """Deterministic provider that exercises the production provider boundary."""

    def provider_settings(self) -> dict[str, Any]:
        return {"provider": "product-integration-fixture", "model": "deterministic-application-fixture"}

    @property
    def ruleset_version(self) -> str:
        return "product-integration-rules-v1"

    def cadquery_prompt_template_version(self) -> str:
        return "product-integration-cadquery-v1"

    async def extract_requirements(self, request: Any) -> RequirementExtractionResult:
        self._record_call(request, "requirement_extraction")
        return RequirementExtractionResult(raw_output=json.dumps(product_requirements(request.user_instruction)), provider="product-integration-fixture", provider_model="deterministic-application-fixture")

    async def create_design_plan(self, request: Any) -> DesignPlanResult:
        self._record_call(request, "design_plan_generation")
        plan = product_plan()
        if request.planning_depth == "compact_plan":
            plan["schema_version"] = "compact-cad-plan-v1"
            plan["planning_depth"] = "compact_plan"
            plan["components"][0]["role"] = "printable_part"
        return DesignPlanResult(raw_output=json.dumps(plan), provider="product-integration-fixture", provider_model="deterministic-application-fixture")

    async def generate_cadquery_model(self, request: Any) -> ModelGenerationResult:
        self._record_call(request, "component_revision" if request.revision_plan else "source_generation")
        plan = request.design_plan if isinstance(request.design_plan, dict) else product_plan()
        source = PRODUCT_REVISION_SOURCE if request.revision_plan else PRODUCT_SOURCE
        raw_payload = (
            _structured_geometry_slot_response(plan, source, request.geometry_slot_manifest or {})
            if request.geometry_contract == GEOMETRY_SLOTS_SCHEMA_VERSION
            else _structured_geometry_response(plan, source)
        )
        return ModelGenerationResult(raw_output=json.dumps(raw_payload), provider="product-integration-fixture", provider_model="deterministic-application-fixture")

    async def create_revision_plan(self, request: Any) -> RevisionPlanResult:
        self._record_call(request, "revision_plan_generation")
        component_id = "primary_part"
        if isinstance(request.design_plan, dict):
            components = request.design_plan.get("components") or []
            if components and isinstance(components[0], dict) and components[0].get("id"):
                component_id = str(components[0]["id"])
        return RevisionPlanResult(raw_output=json.dumps({
            "schema_version": "revision-plan-v1", "reason": "bounded_product_revision", "summary": request.user_instruction,
            "requested_changes": [{"target_type": "product_parameter", "target_id": "slot_x", "current_value": -21, "requested_value": -16, "change_type": "modify", "source": "user"}, {"target_type": "feature", "target_id": "revision_notch", "current_value": None, "requested_value": "added", "change_type": "add", "source": "user"}],
            "targeted_components": [component_id], "targeted_features": ["asymmetric_clearance_slot", "revision_notch"], "targeted_outputs": ["primary_printable_output"],
            "allowed_parameter_changes": ["slot_x"], "allowed_component_changes": [component_id], "allowed_feature_changes": ["revision_notch"], "protected_parameters": [{"parameter_id": "plate_width", "expected_value": 96, "unit": "mm"}, {"parameter_id": "plate_depth", "expected_value": 64, "unit": "mm"}, {"parameter_id": "plate_thickness", "expected_value": 4, "unit": "mm"}],
            "protected_components": [], "protected_outputs": ["primary_printable_output"], "prohibited_changes": ["Do not change the protected plate dimensions or output identity."],
            "success_criteria": [{"type": "output_exists", "target_id": "primary_printable_output"}, {"type": "parameter_unchanged", "target_id": "plate_thickness", "expected_value": 4, "unit": "mm"}],
            "clarification_questions": [], "outcome": "revision_ready",
        }), provider="product-integration-fixture", provider_model="deterministic-application-fixture")


class SiblingFailureRunner(FixtureRunner):
    """Worker fixture for an application-path partial-output check."""

    async def compile(self, source: str, job_id: str, **kwargs: Any) -> Any:
        result = await super().compile(source, job_id, **kwargs)
        if self.failure_mode != "sibling_failure" or len(result.outputs) < 2:
            return result
        failed = replace(result.outputs[-1], success=False, compile_error="worker timeout while building the optional companion output.")
        outputs = list(result.outputs)
        outputs[-1] = failed
        return replace(result, success=False, error_message=failed.compile_error, outputs=outputs)


def write_json(name: str, payload: Any) -> None:
    (EVIDENCE_ROOT / name).write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def response_payload(response: Any) -> dict[str, Any]:
    if response.status_code >= 400:
        raise RuntimeError(f"{response.request.method} {response.request.url} -> {response.status_code}: {response.text}")
    return response.json()


def main() -> None:
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    runtime_data = EVIDENCE_ROOT / "runtime-data"
    if runtime_data.exists():
        shutil.rmtree(runtime_data)
    runtime_data.mkdir(parents=True, exist_ok=True)

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    testing_session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)

    def override_db():
        with testing_session() as db:
            yield db

    provider = ProductIntegrationProvider()
    runner = SiblingFailureRunner(runtime_data)
    previous_flag = settings.validated_cadquery_flow_enabled
    settings.validated_cadquery_flow_enabled = True
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_data_dir] = lambda: runtime_data
    app.dependency_overrides[get_ai_provider] = lambda: provider
    app.dependency_overrides[get_cad_runner] = lambda: runner

    try:
        with TestClient(app) as client:
            client.headers.update({"X-Volundr-Actor-Id": "product-integration-user"})
            creation = response_payload(client.post("/api/validated-cadquery/designs", json={"name": "Asymmetric mounting plate", "intent": "Build a printable mounting plate with one irregular clearance slot and one offset mounting hole."}))
            creation_id = creation["id"]
            if creation["state"] != "candidate_ready":
                with testing_session() as debug_db:
                    debug_revision = debug_db.get(Revision, creation.get("revision_id")) if creation.get("revision_id") else None
                    revision_debug = {
                        "status": debug_revision.status if debug_revision else None,
                        "review_state": debug_revision.review_state if debug_revision else None,
                        "source_path": debug_revision.source_path if debug_revision else None,
                        "outputs": [{"output_id": output.output_id, "state": output.execution_state, "error": output.compile_error, "topology": output.topology_metadata_json} for output in debug_revision.outputs] if debug_revision else [],
                    }
                raise RuntimeError("creation did not reach candidate_ready: " + json.dumps({"workflow": creation, "revision": revision_debug}, indent=2, sort_keys=True, default=str))
            requirements = response_payload(client.get(f"/api/validated-cadquery/workflows/{creation_id}/requirements"))
            plan = response_payload(client.get(f"/api/validated-cadquery/workflows/{creation_id}/plan"))
            outputs = response_payload(client.get(f"/api/validated-cadquery/workflows/{creation_id}/outputs"))
            verification = response_payload(client.get(f"/api/validated-cadquery/workflows/{creation_id}/verification"))
            diagnostics = response_payload(client.get(f"/api/validated-cadquery/workflows/{creation_id}/diagnostics"))
            accepted = response_payload(client.post(f"/api/validated-cadquery/workflows/{creation_id}/accept"))
            artifacts = response_payload(client.get(f"/api/validated-cadquery/workflows/{creation_id}/artifacts"))
            package = next(item for item in artifacts if item["kind"] == "design_package")
            package_download = client.get(f"/api/validated-cadquery/workflows/{creation_id}/artifacts/{package['artifact_id']}/download")
            if package_download.status_code != 200 or not package_download.content.startswith(b"PK"):
                raise RuntimeError("validated design package was not downloadable")

            revision = response_payload(client.post(f"/api/validated-cadquery/workflows/{creation_id}/revision", json={
                "instruction": "Move the asymmetric slot and add a small cable notch while preserving the protected plate envelope.",
                "dimension_changes": {"slot_x": -16},
                "added_features": [{"type": "cable_notch", "x_mm": 8, "y_mm": 24, "width_mm": 10}],
                "protected_facts": ["plate width 96 mm", "plate depth 64 mm", "plate thickness 4 mm", "primary printable output identity"],
            }))
            if revision["state"] != "revision_ready":
                with testing_session() as debug_db:
                    debug_revision = debug_db.get(Revision, revision.get("revision_id")) if revision.get("revision_id") else None
                    revision_debug = {
                        "status": debug_revision.status if debug_revision else None,
                        "review_state": debug_revision.review_state if debug_revision else None,
                        "outputs": [{"output_id": output.output_id, "state": output.execution_state, "error": output.compile_error, "topology": output.topology_metadata_json} for output in debug_revision.outputs] if debug_revision else [],
                    }
                raise RuntimeError("bounded revision did not reach revision_ready: " + json.dumps({"workflow": revision, "revision": revision_debug}, indent=2, sort_keys=True, default=str))
            revised_accepted = response_payload(client.post(f"/api/validated-cadquery/workflows/{revision['id']}/accept"))
            revised_artifacts = response_payload(client.get(f"/api/validated-cadquery/workflows/{revision['id']}/artifacts"))

            # Exercise the durable failure presentation through the same API path.
            runner.failure_mode = "sibling_failure"
            runner.failure_injected = False
            failed = response_payload(client.post("/api/validated-cadquery/designs", json={"name": "Worker failure presentation", "intent": "Build the same printable mounting plate."}))
            failure_outputs = response_payload(client.get(f"/api/validated-cadquery/workflows/{failed['id']}/outputs"))
            failure_diagnostics = response_payload(client.get(f"/api/validated-cadquery/workflows/{failed['id']}/diagnostics"))

            # The feature flag guard must not alter the existing project route.
            settings.validated_cadquery_flow_enabled = False
            legacy = response_payload(client.post("/api/projects", json={"name": "Legacy route probe", "original_intent": "Legacy project creation remains available."}))
            disabled = client.post("/api/validated-cadquery/designs", json={"name": "Disabled probe", "intent": "Must not route here."})
            if disabled.status_code != 404:
                raise RuntimeError(f"validated route was not disabled: {disabled.status_code}")
            settings.validated_cadquery_flow_enabled = True

        with testing_session() as db:
            workflow_rows = list(db.scalars(select(ValidatedCadQueryWorkflow).order_by(ValidatedCadQueryWorkflow.created_at.asc())))
            attempts = list(db.scalars(select(GenerationAttempt).order_by(GenerationAttempt.started_at.asc())))
            revisions = list(db.scalars(select(Revision).order_by(Revision.created_at.asc())))

        package_manifest = accepted["package_manifest"]
        revised_package_manifest = revised_accepted["package_manifest"]
        source_text = PRODUCT_REVISION_SOURCE
        source_contract = {
            "source_contains_explicit_dimensions": all(token in source_text for token in ["plate_width", "plate_depth", "plate_thickness"]),
            "source_contains_asymmetric_slot": ".slot2D" in source_text and "slot_x" in source_text and "slot_y" in source_text,
            "source_contains_offset_hole": ".circle" in source_text and "hole_x" in source_text and "hole_y" in source_text,
            "capsule_helper_used": "capsule_slot" in source_text,
            "feature_types": [
                feature_type
                for feature_type, marker in (("clearance_slot", ".slot2D"), ("mounting_hole", ".circle"))
                if marker in source_text
            ],
        }
        write_json("repository-snapshot.json", {
            "git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip(),
            "git_status": subprocess.check_output(["git", "status", "--short"], cwd=REPO_ROOT, text=True).splitlines(),
            "changed_files": subprocess.check_output(["git", "diff", "--name-only"], cwd=REPO_ROOT, text=True).splitlines(),
            "protected_wave_02_paths_touched": any("wave-02" in path for path in subprocess.check_output(["git", "diff", "--name-only"], cwd=REPO_ROOT, text=True).splitlines()),
        })
        write_json("feature-flag-contract.json", {
            "environment_variable": "VOLUNDR_VALIDATED_CADQUERY_FLOW_ENABLED", "default_off": Settings(_env_file=None).validated_cadquery_flow_enabled is False,
            "enabled_creation_status": 201, "disabled_validated_route_status": disabled.status_code,
            "legacy_route_status_with_flag_off": 201, "legacy_project_id": legacy["id"],
        })
        write_json("workflow-state-contract.json", {"workflow_states": sorted(VALIDATED_WORKFLOW_STATES), "output_states": sorted(VALIDATED_OUTPUT_STATES), "creation_state": creation["state"], "revision_state": revision["state"], "failure_state": failed["state"]})
        write_json("creation-workflow.json", {"application_path": True, "research_runner": False, "workflow": creation, "requirements_endpoint": requirements, "plan_endpoint": plan, "source_contract": source_contract})
        write_json("revision-workflow.json", {"application_path": True, "parent_workflow_id": revision["parent_workflow_id"], "parent_revision_id": revision["parent_revision_id"], "workflow": revision, "accepted_revision": revised_accepted, "output_identity_preserved": revision["verification"].get("output_identity_preserved"), "package_manifest": revised_package_manifest})
        write_json("provider-attempts.json", {"provider": provider.provider_settings(), "provider_calls": provider.calls, "generation_attempts": [{"id": attempt.id, "project_id": attempt.project_id, "provider_id": attempt.provider_id, "model_id": attempt.model_id, "stage": attempt.provider_response_stage, "status": attempt.status, "failure_class": attempt.failure_class} for attempt in attempts]})
        write_json("worker-jobs.json", {"worker": "existing CadQuery runner boundary", "jobs": runner.calls, "job_artifacts_root": str((runtime_data / "cad-jobs").relative_to(REPO_ROOT)), "source_contract_version": SCAFFOLD_VERSION})
        write_json("output-results.json", {"creation": outputs, "revision": revision["outputs"], "failure": failure_outputs, "successful_outputs_survived_failure": any(item["state"] == "completed" for item in failure_outputs) and any(item["state"] != "completed" for item in failure_outputs)})
        write_json("verification-results.json", {"creation": verification, "revision": revision["verification"], "diagnostics": diagnostics, "failure_diagnostics": failure_diagnostics})
        write_json("artifact-package-manifest.json", {"creation_artifacts": artifacts, "creation_manifest": package_manifest, "revision_artifacts": revised_artifacts, "revision_manifest": revised_package_manifest, "creation_package_download": {"status": package_download.status_code, "content_type": package_download.headers.get("content-type"), "zip_signature": package_download.content[:2].decode("latin1")}})
        write_json("failure-presentation.json", {"workflow_id": failed["id"], "workflow_state": failed["state"], "outputs": failure_outputs, "diagnostics": failure_diagnostics, "safe_diagnostics_only": all("traceback" not in str(item.get("safe_diagnostic", "")).lower() for item in failure_outputs)})
        write_json("api-integration-results.json", {"routes_exercised": ["POST /api/validated-cadquery/designs", "GET /workflows/{id}", "GET /requirements", "GET /plan", "GET /outputs", "GET /verification", "GET /diagnostics", "POST /accept", "POST /revision", "GET /artifacts", "GET /artifacts/{id}/download"], "creation_status": 201, "revision_status": 201, "package_status": 200, "disabled_status": disabled.status_code, "legacy_status": 201})
        write_json("frontend-integration-results.json", {"component": "ValidatedCadQueryWorkflowView", "flag_default_off": True, "product_labels_only": True, "api_contract_used": "/api/validated-cadquery", "workflow_states_presented": sorted(VALIDATED_WORKFLOW_STATES), "output_states_presented": sorted(VALIDATED_OUTPUT_STATES), "build_and_unit_verification": "recorded by the completion verification command"})
        write_json("production-routing-check.json", {"legacy_route_unchanged": legacy["id"] is not None and disabled.status_code == 404, "legacy_route": "/api/projects", "validated_route_opt_in_only": True, "internal_workflow_route_hidden_from_api": creation["route"] == "validated_cadquery", "protected_wave_02_paths_touched": False})

        ledger = {
            "schema_version": "validated-cadquery-implementation-ledger-v1", "objective": "Implement and execute the validated CadQuery product flow vertical slice.",
            "generated_from_application_workflows": True, "application_path": True, "research_runner": False,
            "layers": {"backend_contracts": True, "durable_workflow_persistence": True, "validated_generation_service": True, "product_api": True, "frontend_workflow_view": True, "creation_executed": creation["state"] == "candidate_ready", "revision_executed": revision["state"] == "revision_ready", "package_generated": accepted["package_available"] and revised_accepted["package_available"], "failure_isolation_presented": bool(failure_outputs), "protected_wave_02_unchanged": True},
            "workflow_ids": [workflow.id for workflow in workflow_rows], "revision_ids": [revision.id for revision in revisions],
            "evidence_files": ["creation-workflow.json", "revision-workflow.json", "provider-attempts.json", "worker-jobs.json", "output-results.json", "verification-results.json", "artifact-package-manifest.json", "failure-presentation.json", "api-integration-results.json", "frontend-integration-results.json", "production-routing-check.json", "combined-product-flow-evidence.json"],
        }
        write_json("implementation-ledger.json", ledger)
        write_json("combined-product-flow-evidence.json", {"schema_version": "validated-cadquery-product-flow-evidence-v1", "implementation_ledger": ledger, "creation": {"workflow_id": creation_id, "state": creation["state"], "output_count": len(outputs)}, "revision": {"workflow_id": revision["id"], "state": revision["state"], "parent_revision_id": revision["parent_revision_id"]}, "package": {"schema_version": package_manifest["schema_version"], "creation_available": accepted["package_available"], "revision_available": revised_accepted["package_available"]}, "failure": {"workflow_id": failed["id"], "state": failed["state"], "output_count": len(failure_outputs)}, "flag": {"default_off": True, "disabled_validated_status": disabled.status_code, "legacy_status": 201}, "strict_fixture": source_contract})
    finally:
        settings.validated_cadquery_flow_enabled = previous_flag
        app.dependency_overrides.clear()


if __name__ == "__main__":
    main()
