"""Product-facing, durable orchestration for the validated CadQuery flow."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import hashlib
import re
from pathlib import Path
from typing import Any
import zipfile

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.revision import Revision
from app.models.revision_output import RevisionOutput
from app.models.project import Project
from app.models.validated_cadquery_workflow import (
    VALIDATED_OUTPUT_STATES,
    VALIDATED_WORKFLOW_STATES,
    ValidatedCadQueryOutput,
    ValidatedCadQueryWorkflow,
)
from app.models.validated_cadquery_operation import ValidatedCadQueryOperation
from app.models.validated_cadquery_provider_attempt import ValidatedCadQueryProviderAttempt
from app.schemas.project import (
    ClarificationAnswersCreate,
    ClarificationAnswerCreate,
    DesignPlanRead,
    GenerationCreate,
    ProjectCreate,
    RequirementExtractionCreate,
    RevisionPlanCreate,
)
from app.schemas.validated_cadquery import (
    ValidatedArtifactRead,
    ValidatedBoundedRevision,
    ValidatedCadQueryStart,
    ValidatedDiagnosticsRead,
    ValidatedOutputRead,
    ValidatedPlanRead,
    ValidatedRequirementsRead,
    ValidatedVerificationRead,
    ValidatedWorkflowRead,
)
from app.services.projects.export import ExportService
from app.services.projects.service import ProjectService
from app.services.validated_cadquery_security import canonical_idempotency_hash, safe_relative_artifact_path
from app.services.validated_cadquery_security import redact_sensitive_text


__all__ = [
    "ValidatedCadQueryWorkflowService",
    "ValidatedOutputClassification",
    "canonical_idempotency_hash",
    "classify_validated_output",
    "derive_validated_workflow_state",
    "safe_diagnostic",
    "safe_relative_artifact_path",
]


@dataclass(frozen=True)
class ValidatedOutputClassification:
    state: str
    generation_status: str
    worker_status: str
    solid_count: int | None = None
    topology_status: str | None = None
    semantic_verification: str | None = None
    artifact_available: bool = False
    failure_owner: str | None = None
    safe_diagnostic: str | None = None
    artifact_metadata: dict[str, Any] = field(default_factory=dict)


def classify_validated_output(payload: dict[str, Any], *, required: bool) -> ValidatedOutputClassification:
    """Translate worker/verification evidence into a stable product state."""

    topology = payload.get("topology_metadata")
    topology = topology if isinstance(topology, dict) else {}
    semantic = payload.get("semantic_verification")
    semantic = semantic if isinstance(semantic, dict) else {}
    solid_count = topology.get("detected_solid_count")
    solid_count = int(solid_count) if isinstance(solid_count, (int, float)) else None
    topology_status = "failed" if topology.get("valid") is False else "passed" if topology else None
    semantic_status = semantic.get("status") if isinstance(semantic.get("status"), str) else None
    artifact_available = bool(payload.get("stl_path") and payload.get("step_path"))
    success = payload.get("success") is True
    failure_class = str(payload.get("failure_class") or "").lower()
    error = payload.get("compile_error") or payload.get("error") or payload.get("message")

    if not success:
        if failure_class in {"timeout", "worker_timeout", "cadquery_timeout"} or payload.get("timed_out") is True:
            state, owner = "worker_timeout", "worker"
        elif failure_class in {"invalid_shape", "topology_failed"} or topology.get("valid") is False:
            state, owner = "invalid_shape", "verification"
        else:
            state, owner = ("not_generated", "worker") if not required else ("not_generated", "worker")
        return ValidatedOutputClassification(
            state=state,
            generation_status="failed",
            worker_status="failed",
            solid_count=solid_count,
            topology_status=topology_status,
            semantic_verification=semantic_status,
            artifact_available=artifact_available,
            failure_owner=owner,
            safe_diagnostic=safe_diagnostic(str(error or "Output was not generated.")),
            artifact_metadata=_artifact_metadata(payload),
        )

    if topology.get("valid") is False:
        return ValidatedOutputClassification(
            state="invalid_shape",
            generation_status="completed",
            worker_status="completed",
            solid_count=solid_count,
            topology_status="failed",
            semantic_verification=semantic_status,
            artifact_available=artifact_available,
            failure_owner="verification",
            safe_diagnostic=safe_diagnostic(str(error or "The output shape failed topology verification.")),
            artifact_metadata=_artifact_metadata(payload),
        )
    if semantic_status in {"failed", "rejected", "not_verified"}:
        return ValidatedOutputClassification(
            state="semantic_verification_failed",
            generation_status="completed",
            worker_status="completed",
            solid_count=solid_count,
            topology_status=topology_status,
            semantic_verification=semantic_status,
            artifact_available=artifact_available,
            failure_owner="verification",
            safe_diagnostic=safe_diagnostic(str(error or "Semantic verification did not pass.")),
            artifact_metadata=_artifact_metadata(payload),
        )
    if not artifact_available:
        return ValidatedOutputClassification(
            state="export_failed",
            generation_status="completed",
            worker_status="completed",
            solid_count=solid_count,
            topology_status=topology_status,
            semantic_verification=semantic_status,
            artifact_available=False,
            failure_owner="artifact",
            safe_diagnostic="The output was generated but its downloadable artifacts are unavailable.",
            artifact_metadata=_artifact_metadata(payload),
        )
    return ValidatedOutputClassification(
        state="completed",
        generation_status="completed",
        worker_status="completed",
        solid_count=solid_count,
        topology_status=topology_status or "passed",
        semantic_verification=semantic_status or "passed",
        artifact_available=True,
        artifact_metadata=_artifact_metadata(payload),
    )


def derive_validated_workflow_state(outputs: list[dict[str, Any]]) -> str:
    """Derive a product state from durable output facts, not thrown exceptions."""

    if not outputs:
        return "failed"
    required = [item for item in outputs if bool(item.get("required", True))]
    completed = [item for item in outputs if item.get("state") == "completed"]
    failed = [item for item in outputs if item.get("state") not in {"completed", "pending"}]
    if completed and failed:
        return "partially_completed"
    if required and all(item.get("state") == "completed" for item in required):
        return "candidate_ready"
    if any(item.get("state") in {"invalid_shape", "semantic_verification_failed"} for item in outputs):
        return "verification_failed"
    if any(item.get("state") in VALIDATED_OUTPUT_STATES - {"pending"} for item in outputs):
        return "failed"
    return "worker_running"


def safe_diagnostic(value: str) -> str:
    for secret in (settings.gemini_api_key, settings.gemini_api_key_2):
        if secret:
            value = value.replace(secret, "[redacted]")
    value = redact_sensitive_text(value)
    value = re.sub(r"(?i)(?:key|api[_-]?key|authorization|token)\s*[=:]\s*[^\s,;]+", "[redacted]", value)
    value = re.sub(r"(?i)(?:/[^\s:]+)+(?:\.py|\.json|\.log)?", "[path]", value)
    value = re.sub(r"(?i)(?:api[_-]?key|authorization|token)\s*[:=]\s*[^\s,;]+", "[redacted]", value)
    value = re.sub(r"Traceback \(most recent call last\):.*", "Execution failed; detailed traceback is not available.", value, flags=re.DOTALL)
    return value[:800]


def _artifact_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: payload[key]
        for key in ("stl_path", "step_path", "brep_path", "stl_hash", "step_hash", "brep_hash")
        if payload.get(key)
    }


class ValidatedCadQueryWorkflowService:
    """Owns product workflow state while delegating CAD work to existing services."""

    route = "validated-cadquery-v1"

    def __init__(
        self,
        *,
        db: Session,
        data_dir: Path,
        ai_provider: Any | None = None,
        cad_runner: Any | None = None,
        owner_id: str = "anonymous",
    ):
        self.db = db
        self.data_dir = data_dir
        self.ai_provider = ai_provider
        self.cad_runner = cad_runner
        self.owner_id = owner_id
        self._active_workflow_id: str | None = None
        if self.ai_provider is not None and hasattr(self.ai_provider, "set_validated_attempt_recorder"):
            self.ai_provider.set_validated_attempt_recorder(self._persist_provider_attempt)

    async def start_design(
        self,
        payload: ValidatedCadQueryStart,
        *,
        idempotency_key: str | None = None,
    ) -> ValidatedWorkflowRead:
        self.require_enabled()
        operation = self._begin_operation(
            "start_design",
            idempotency_key,
            payload.model_dump(mode="json"),
        )
        if operation.workflow_id:
            return self.read(operation.workflow_id)
        if operation.status == "completed":
            raise ValueError("completed start operation has no linked workflow")
        project_service = self._project_service()
        try:
            self._start_design_checkpoint("after_operation_creation")
            project = self.db.get(Project, operation.project_id) if operation.project_id else None
            if project is None:
                project = project_service.create_project(
                    ProjectCreate(name=payload.name, original_intent=payload.intent),
                    commit=False,
                )
                self._start_design_checkpoint("after_project_flush")
            workflow = ValidatedCadQueryWorkflow(
                project_id=project.id,
                owner_id=self.owner_id,
                state="requirements_ready",
                route=self.route,
                user_instruction=payload.intent,
                provenance_json=json.dumps(
                    {
                        "selected_route": "validated_t2_t0_t5_cadquery",
                        "feature_flag": "VOLUNDR_VALIDATED_CADQUERY_FLOW_ENABLED",
                        "feature_flag_enabled": True,
                        "provider_transport": "existing_application_provider",
                        "contract_version": "validated-cadquery-product-v1",
                    },
                    sort_keys=True,
                ),
            )
            self.db.add(workflow)
            self.db.flush()
            self._start_design_checkpoint("after_workflow_flush")
            operation.project_id = project.id
            operation.workflow_id = workflow.id
            operation.status = "running"
            self.db.flush()
            self._start_design_checkpoint("after_operation_links")
            self._start_design_checkpoint("before_commit")
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self._start_design_checkpoint("after_commit_before_response")
        try:
            specification = await project_service.extract_requirements(
                project.id,
                RequirementExtractionCreate(user_instruction=payload.intent),
            )
            if specification is None:
                raise ValueError("requirements could not be created")
            workflow.design_specification_id = specification.id
            workflow.requirements_json = json.dumps(specification.specification, sort_keys=True, default=str)
            workflow.state = "awaiting_clarification" if specification.clarification_required else "requirements_ready"
            self.db.commit()
            if specification.clarification_required:
                self._complete_operation(operation)
                self.db.commit()
                return self.read(workflow.id)
            result = await self._continue_from_specification(workflow, specification.id)
            self._complete_operation(operation)
            self.db.commit()
            return result
        except Exception as exc:
            result = self._fail(workflow, exc)
            operation.status = "failed"
            self.db.commit()
            return result

    async def submit_clarification(
        self,
        workflow_id: str,
        answers: ClarificationAnswersCreate,
        *,
        idempotency_key: str | None = None,
    ) -> ValidatedWorkflowRead:
        workflow = self._get(workflow_id)
        if workflow is None:
            raise LookupError("validated workflow not found")
        if workflow.design_specification_id is None:
            raise ValueError("workflow has no clarification context")
        operation = self._begin_operation(
            "submit_clarification",
            idempotency_key,
            {"workflow_id": workflow_id, "answers": answers.model_dump(mode="json")},
            project_id=workflow.project_id,
            workflow_id=workflow.id,
        )
        if operation.status == "completed" or operation.status == "failed":
            return self.read(workflow.id)
        if operation.status == "running":
            self.reconcile_workflow(workflow)
            self.db.commit()
            return self.read(workflow.id)
        operation.status = "running"
        self.db.commit()
        try:
            specification = await self._project_service().submit_clarification_answers(
                workflow.design_specification_id,
                answers,
            )
            if specification is None:
                raise ValueError("clarification specification not found")
            workflow.design_specification_id = specification.id
            workflow.requirements_json = json.dumps(specification.specification, sort_keys=True, default=str)
            self.db.commit()
            if specification.clarification_required:
                workflow.state = "awaiting_clarification"
                self.db.commit()
                result = self.read(workflow.id)
            else:
                result = await self._continue_from_specification(workflow, specification.id)
            self._complete_operation(operation)
            self.db.commit()
            return result
        except Exception as exc:
            result = self._fail(workflow, exc)
            operation.status = "failed"
            self.db.commit()
            return result

    async def _continue_from_specification(
        self,
        workflow: ValidatedCadQueryWorkflow,
        specification_id: str,
    ) -> ValidatedWorkflowRead:
        self._active_workflow_id = workflow.id
        project_service = self._project_service()
        workflow.state = "plan_ready"
        self.db.commit()
        plan, _route = await project_service.create_proportional_plan_from_specification(specification_id)
        if plan is None:
            workflow.state = "awaiting_clarification"
            self.db.commit()
            return self.read(workflow.id)
        workflow.design_plan_id = plan.id
        workflow.plan_json = json.dumps(plan.plan, sort_keys=True, default=str)
        self.db.commit()
        if getattr(plan.review_state, "value", plan.review_state) == "pending_review":
            project_service.approve_design_plan(plan.id)
        workflow.state = "geometry_generating"
        self.db.commit()
        revision = await project_service.generate_from_design_plan(plan.id)
        if revision is None:
            raise ValueError("validated CAD candidate was not created")
        revision_model = self.db.get(Revision, revision.id)
        if revision_model is None:
            raise ValueError("validated CAD candidate disappeared before state materialization")
        workflow.state = "worker_running"
        self.db.commit()
        self.sync_outputs(workflow, revision_model)
        self._record_generation_provenance(workflow, revision_model)
        self.db.commit()
        return self.read(workflow.id)

    async def start_bounded_revision(
        self,
        workflow_id: str,
        payload: ValidatedBoundedRevision,
        *,
        idempotency_key: str | None = None,
    ) -> ValidatedWorkflowRead:
        self.require_enabled()
        parent = self._get(workflow_id)
        if parent is None:
            raise LookupError("validated workflow not found")
        if parent.revision_id is None:
            raise ValueError("a candidate revision is required before bounded revision")
        base_revision = self.db.get(Revision, parent.revision_id)
        if base_revision is None or not base_revision.is_accepted:
            raise ValueError("bounded revision requires an accepted candidate")
        revision_instruction = self._revision_instruction(payload)
        operation = self._begin_operation(
            "start_revision",
            idempotency_key,
            {"workflow_id": workflow_id, **payload.model_dump(mode="json")},
            project_id=parent.project_id,
            workflow_id=parent.id,
        )
        if operation.workflow_id and operation.workflow_id != parent.id:
            return self.read(operation.workflow_id)
        if operation.status == "running" and operation.workflow_id == parent.id:
            return self.read(parent.id)
        if operation.status in {"completed", "failed"} and operation.workflow_id:
            child = self._get(operation.workflow_id)
            if child is not None:
                return self.read(child.id)
        child = ValidatedCadQueryWorkflow(
            project_id=parent.project_id,
            owner_id=self.owner_id,
            parent_workflow_id=parent.id,
            parent_revision_id=base_revision.id,
            state="plan_ready",
            route=self.route,
            user_instruction=revision_instruction,
            provenance_json=json.dumps(
                {
                    "selected_route": "validated_t2_t0_t5_cadquery",
                    "feature_flag": "VOLUNDR_VALIDATED_CADQUERY_FLOW_ENABLED",
                    "prior_revision_id": base_revision.id,
                    "prior_source_hash": base_revision.source_hash,
                    "prior_verification_authority": "accepted_revision_and_output_verification",
                    "protected_facts": payload.protected_facts,
                    "requested_dimension_changes": payload.dimension_changes,
                    "requested_feature_additions": payload.added_features,
                },
                sort_keys=True,
            ),
        )
        self.db.add(child)
        self.db.commit()
        operation.workflow_id = child.id
        operation.status = "running"
        self.db.commit()
        try:
            self._active_workflow_id = child.id
            project_service = self._project_service()
            plan = await project_service.create_revision_plan(
                parent.project_id,
                RevisionPlanCreate(
                    user_instruction=revision_instruction,
                    base_revision_id=base_revision.id,
                    reason="bounded_product_revision",
                ),
            )
            if plan is None:
                raise ValueError("bounded revision plan was not created")
            child.plan_json = json.dumps(plan.revision_plan, sort_keys=True, default=str)
            if plan.clarification_required:
                child.state = "awaiting_clarification"
                self.db.commit()
                self._complete_operation(operation)
                self.db.commit()
                return self.read(child.id)
            if getattr(plan.review_state, "value", plan.review_state) == "pending_review":
                project_service.approve_revision_plan(plan.id)
            child.state = "geometry_generating"
            self.db.commit()
            revision = await project_service.generate_from_revision_plan(plan.id)
            if revision is None:
                raise ValueError("bounded revision candidate was not created")
            revision_model = self.db.get(Revision, revision.id)
            if revision_model is None:
                raise ValueError("bounded revision candidate disappeared before state materialization")
            child.state = "worker_running"
            self.db.commit()
            self.sync_outputs(child, revision_model)
            if child.state == "candidate_ready":
                child.state = "revision_ready"
            child.verification_json = json.dumps(
                {
                    **_json_object(child.verification_json),
                    "prior_revision_id": base_revision.id,
                    "preserved_output_ids": [output.output_id for output in revision_model.outputs],
                    "output_identity_preserved": {output.output_id for output in revision_model.outputs}
                    == {output.output_id for output in base_revision.outputs},
                },
                sort_keys=True,
            )
            self._record_generation_provenance(child, revision_model)
            self.db.commit()
            self._complete_operation(operation)
            self.db.commit()
            return self.read(child.id)
        except Exception as exc:
            result = self._fail(child, exc)
            operation.status = "failed"
            self.db.commit()
            return result

    def accept_candidate(
        self,
        workflow_id: str,
        *,
        idempotency_key: str | None = None,
    ) -> ValidatedWorkflowRead:
        workflow = self._get(workflow_id)
        if workflow is None:
            raise LookupError("validated workflow not found")
        if workflow.revision_id is None:
            raise ValueError("workflow has no candidate revision")
        self.require_enabled()
        operation = self._begin_operation(
            "accept_candidate",
            idempotency_key,
            {"workflow_id": workflow_id},
            project_id=workflow.project_id,
            workflow_id=workflow.id,
        )
        if operation.status == "completed":
            return self.read(workflow.id)
        if operation.status == "running":
            return self.read(workflow.id)
        revision = self._project_service().accept_candidate(workflow.revision_id, commit=False)
        if revision is None:
            raise ValueError("candidate revision not found")
        provenance = _json_object(workflow.provenance_json)
        provenance["accepted_revision_id"] = revision.id
        workflow.provenance_json = json.dumps(provenance, sort_keys=True)
        self.db.commit()
        try:
            self._create_package(workflow, self.db.get(Revision, revision.id))
            self._complete_operation(operation)
            self.db.commit()
        except Exception as exc:
            workflow.diagnostics_json = json.dumps(
                {"kind": "package_generation", "message": safe_diagnostic(str(exc))}, sort_keys=True
            )
            workflow.state = "failed"
            operation.status = "failed"
            self.db.commit()
        return self.read(workflow.id)

    def create_package(
        self,
        workflow_id: str,
        *,
        idempotency_key: str | None = None,
    ) -> ValidatedWorkflowRead:
        workflow = self._get(workflow_id)
        if workflow is None:
            raise LookupError("validated workflow not found")
        self.require_enabled()
        operation = self._begin_operation(
            "create_package",
            idempotency_key,
            {"workflow_id": workflow_id},
            project_id=workflow.project_id,
            workflow_id=workflow.id,
        )
        if operation.status == "completed" and workflow.package_path:
            return self.read(workflow.id)
        if operation.status == "running" and not workflow.package_path:
            return self.read(workflow.id)
        self._create_package(workflow, self.db.get(Revision, workflow.revision_id))
        self._complete_operation(operation)
        self.db.commit()
        return self.read(workflow.id)

    def continue_generation(self, workflow_id: str) -> ValidatedWorkflowRead:
        workflow = self._get(workflow_id)
        if workflow is None:
            raise LookupError("validated workflow not found")
        self.require_enabled()
        self.reconcile_workflow(workflow)
        self.db.commit()
        return self.read(workflow.id)

    def read(self, workflow_id: str, *, project_id: str | None = None) -> ValidatedWorkflowRead:
        workflow = self._get(workflow_id, project_id=project_id)
        if workflow is None:
            raise LookupError("validated workflow not found")
        self._observe_feature_flag(workflow)
        outputs = [
            ValidatedOutputRead(
                output_id=output.output_id,
                required=output.required,
                generation_status=output.generation_status,
                worker_status=output.worker_status,
                state=output.state,
                solid_count=output.solid_count,
                topology_status=output.topology_status,
                semantic_verification=output.semantic_verification,
                artifact_available=output.artifact_available,
                failure_owner=output.failure_owner,
                safe_diagnostic=output.safe_diagnostic,
                artifact_metadata=_product_artifact_metadata(output.artifact_metadata_json),
            )
            for output in workflow.outputs
        ]
        package_path = self._resolve_optional(workflow.package_path)
        provenance = _json_object(workflow.provenance_json)
        provenance.pop("selected_route", None)
        return ValidatedWorkflowRead(
            id=workflow.id,
            project_id=workflow.project_id,
            parent_workflow_id=workflow.parent_workflow_id,
            parent_revision_id=workflow.parent_revision_id,
            revision_id=workflow.revision_id,
            state=workflow.state,
            route="validated_cadquery",
            user_instruction=workflow.user_instruction,
            requirements=_json_object(workflow.requirements_json),
            plan=_json_object(workflow.plan_json),
            provenance=provenance,
            verification=_json_object(workflow.verification_json),
            diagnostics=_json_object(workflow.diagnostics_json),
            package_manifest=_json_object(workflow.package_manifest_json),
            package_available=package_path is not None,
            outputs=outputs,
            created_at=workflow.created_at,
            updated_at=workflow.updated_at,
        )

    def requirements(self, workflow_id: str, *, project_id: str | None = None) -> ValidatedRequirementsRead:
        workflow = self._require_workflow(workflow_id, project_id=project_id)
        return ValidatedRequirementsRead(workflow_id=workflow.id, requirements=_json_object(workflow.requirements_json))

    def plan(self, workflow_id: str, *, project_id: str | None = None) -> ValidatedPlanRead:
        workflow = self._require_workflow(workflow_id, project_id=project_id)
        return ValidatedPlanRead(workflow_id=workflow.id, plan=_json_object(workflow.plan_json))

    def verification(self, workflow_id: str, *, project_id: str | None = None) -> ValidatedVerificationRead:
        workflow = self._require_workflow(workflow_id, project_id=project_id)
        state = self.read(workflow.id)
        return ValidatedVerificationRead(
            workflow_id=workflow.id,
            state=workflow.state,
            verification=state.verification,
            outputs=state.outputs,
        )

    def diagnostics(self, workflow_id: str, *, project_id: str | None = None) -> ValidatedDiagnosticsRead:
        workflow = self._require_workflow(workflow_id, project_id=project_id)
        return ValidatedDiagnosticsRead(workflow_id=workflow.id, diagnostics=_json_object(workflow.diagnostics_json))

    def artifacts(self, workflow_id: str, *, project_id: str | None = None) -> list[ValidatedArtifactRead]:
        workflow = self._require_workflow(workflow_id, project_id=project_id)
        self.reconcile_artifacts(workflow)
        self.db.commit()
        result: list[ValidatedArtifactRead] = []
        revision = self.db.get(Revision, workflow.revision_id) if workflow.revision_id else None
        if revision is not None:
            for output in revision.outputs:
                for kind, relative, digest, media_type in (
                    ("step", output.step_path, output.step_hash, "model/step"),
                    ("stl", output.stl_path, output.stl_hash, "model/stl"),
                    ("brep", output.brep_path, output.brep_hash, "model/brep"),
                ):
                    try:
                        path = self._resolve_optional(relative)
                    except ValueError:
                        path = None
                    available = bool(path and digest and _sha256(path) == digest)
                    if not relative or not digest:
                        continue
                    result.append(
                        ValidatedArtifactRead(
                            artifact_id=f"{output.output_id}:{kind}",
                            kind=kind,
                            output_id=output.output_id,
                            filename=path.name if path is not None else "unavailable",
                            media_type=media_type,
                            size_bytes=path.stat().st_size if available and path is not None else 0,
                            sha256=digest,
                            available=available,
                            download_url=f"/api/validated-cadquery/workflows/{workflow.id}/artifacts/{output.output_id}:{kind}/download",
                        )
                    )
        package_path = self._resolve_optional(workflow.package_path)
        if package_path is not None:
            result.append(
                ValidatedArtifactRead(
                    artifact_id="design-package",
                    kind="design_package",
                    filename=package_path.name,
                    media_type="application/zip",
                    size_bytes=package_path.stat().st_size,
                    sha256=_sha256(package_path),
                    available=True,
                    download_url=f"/api/validated-cadquery/workflows/{workflow.id}/artifacts/design-package/download",
                )
            )
        return result

    def resolve_artifact(
        self,
        workflow_id: str,
        artifact_id: str,
        *,
        project_id: str | None = None,
    ) -> tuple[Path, str] | None:
        workflow = self._require_workflow(workflow_id, project_id=project_id)
        if artifact_id == "design-package":
            path = self._resolve_optional(workflow.package_path)
            return (path, "application/zip") if path and self._package_is_safe(path) else None
        output_id, separator, kind = artifact_id.partition(":")
        if not separator or kind not in {"stl", "step", "brep"} or workflow.revision_id is None:
            return None
        revision = self.db.get(Revision, workflow.revision_id)
        if revision is None or revision.project_id != workflow.project_id:
            return None
        output = next((item for item in revision.outputs if item.output_id == output_id), None)
        if output is None:
            return None
        relative = getattr(output, f"{kind}_path")
        path = self._resolve_optional(relative)
        media_type = {"stl": "model/stl", "step": "model/step", "brep": "model/brep"}[kind]
        digest = getattr(output, f"{kind}_hash")
        return (path, media_type) if path and digest and _sha256(path) == digest else None

    @staticmethod
    def _package_is_safe(path: Path) -> bool:
        try:
            with zipfile.ZipFile(path) as archive:
                return all(
                    not normalized.startswith("/")
                    and "\x00" not in normalized
                    and ".." not in Path(normalized).parts
                    for name in archive.namelist()
                    for normalized in (name.replace("\\", "/"),)
                )
        except (OSError, zipfile.BadZipFile):
            return False

    def _validate_package_archive(self, path: Path) -> None:
        forbidden = [
            secret.encode("utf-8")
            for secret in (settings.gemini_api_key, settings.gemini_api_key_2)
            if secret
        ]
        forbidden.append(str(self.data_dir.resolve()).encode("utf-8"))
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                normalized = name.replace("\\", "/")
                if normalized.startswith("/") or "\x00" in normalized or ".." in Path(normalized).parts:
                    raise ValueError("package contains an unsafe archive path")
                content = archive.read(name)
                if any(marker in content for marker in forbidden):
                    raise ValueError("package contains restricted credential or host-path material")

    def _create_package(self, workflow: ValidatedCadQueryWorkflow, revision: Revision | None) -> None:
        if revision is None:
            raise ValueError("accepted revision is missing")
        existing_package = self._resolve_optional(workflow.package_path)
        if existing_package is not None and workflow.package_manifest_json not in {"", "{}"}:
            return
        base_export = ExportService(db=self.db, data_dir=self.data_dir).create(
            project_id=workflow.project_id,
            revision_id=revision.id,
            export_type="project_package",
        )
        export_path = self._resolve_optional(base_export.output_path)
        if export_path is None:
            raise ValueError("base project package is unavailable")
        package_dir = self.data_dir / "projects" / workflow.project_id / "validated-packages"
        package_dir.mkdir(parents=True, exist_ok=True)
        package_path = package_dir / f"validated-cadquery-{workflow.id}.zip"
        manifest = self._package_manifest(workflow, revision, base_export, export_path)
        try:
            with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True, default=str))
                source = self._resolve_optional(revision.source_path)
                if source is not None:
                    archive.write(source, "source/model.py")
                for output in revision.outputs:
                    output_slug = self._archive_slug(output.output_id)
                    for kind in ("step", "stl", "brep"):
                        path = self._resolve_optional(getattr(output, f"{kind}_path"))
                        if path is not None:
                            archive.write(path, f"artifacts/{output_slug}/{path.name}")
                archive.write(export_path, "exports/base-project-package.zip")
            self._validate_package_archive(package_path)
        except Exception:
            package_path.unlink(missing_ok=True)
            raise
        workflow.package_path = str(package_path.resolve().relative_to(self.data_dir.resolve()))
        workflow.package_manifest_json = json.dumps(manifest, sort_keys=True, default=str)

    def cleanup_artifacts(self, *, older_than: float, dry_run: bool = False) -> list[str]:
        """Remove only unreferenced validated package files after a safe delay."""

        root = (self.data_dir / "projects").resolve()
        if not root.is_dir():
            return []
        referenced: set[Path] = set()
        for workflow in self.db.scalars(select(ValidatedCadQueryWorkflow)):
            if workflow.package_path:
                try:
                    referenced.add(self._resolve_optional(workflow.package_path) or Path())
                except ValueError:
                    continue
        removed: list[str] = []
        for path in root.glob("*/validated-packages/*.zip"):
            resolved = path.resolve()
            if resolved in referenced or path.stat().st_mtime >= older_than:
                continue
            if not safe_relative_artifact_path(root, str(resolved.relative_to(root))):
                continue
            removed.append(str(resolved.relative_to(self.data_dir.resolve())))
            if not dry_run:
                path.unlink(missing_ok=True)
        return removed

    def _package_manifest(self, workflow: ValidatedCadQueryWorkflow, revision: Revision, base_export: Any, export_path: Path) -> dict[str, Any]:
        provenance = _json_object(workflow.provenance_json)
        provenance.pop("selected_route", None)
        return {
            "schema_version": "validated-cadquery-design-package-v1",
            "project_id": workflow.project_id,
            "revision_id": revision.id,
            "prior_revision_relationship": {
                "parent_revision_id": revision.parent_revision_id,
                "workflow_parent_id": workflow.parent_workflow_id,
            },
            "authoritative_requirements": _json_object(workflow.requirements_json),
            "accepted_plan": _json_object(workflow.plan_json),
            "canonical_output_ids": [output.output_id for output in revision.outputs],
            "cadquery_source": {"path": "source/model.py", "sha256": revision.source_hash},
            "parameter_values": {
                str(parameter.get("id")): parameter.get("value")
                for parameter in _json_object(workflow.plan_json).get("parameters", [])
                if isinstance(parameter, dict) and parameter.get("id")
            },
            "artifacts": [
                {
                    "output_id": output.output_id,
                    "step": {"path": self._package_artifact_ref(output, "step"), "sha256": output.step_hash},
                    "stl": {"path": self._package_artifact_ref(output, "stl"), "sha256": output.stl_hash},
                    "brep": {"path": self._package_artifact_ref(output, "brep"), "sha256": output.brep_hash},
                    "topology": _json_object(output.topology_metadata_json),
                }
                for output in revision.outputs
            ],
            "topology_metadata": {
                output.output_id: _json_object(output.topology_metadata_json) for output in revision.outputs
            },
            "semantic_verification": _json_object(workflow.verification_json),
            "worker_timing_summary": {
                output.output_id: {"compile_ms": output.compile_ms} for output in revision.outputs
            },
            "warnings": [],
            "provider_and_contract_provenance": provenance,
            "base_export": {"export_id": base_export.id, "sha256": base_export.sha256, "path": "exports/base-project-package.zip"},
        }

    def _record_generation_provenance(self, workflow: ValidatedCadQueryWorkflow, revision: Revision) -> None:
        provenance = _json_object(workflow.provenance_json)
        provenance.update(
            {
                "revision_id": revision.id,
                "source_hash": revision.source_hash,
                "cad_backend": revision.cad_backend,
                "source_contract_version": revision.source_contract_version,
                "output_ids": [output.output_id for output in revision.outputs],
                "provider": self._latest_provider(revision.project_id),
            }
        )
        workflow.provenance_json = json.dumps(provenance, sort_keys=True, default=str)

    def _latest_provider(self, project_id: str) -> str | None:
        from app.models.generation_attempt import GenerationAttempt

        attempt = self.db.scalar(
            select(GenerationAttempt)
            .where(GenerationAttempt.project_id == project_id)
            .order_by(GenerationAttempt.started_at.desc())
        )
        return attempt.provider_id if attempt is not None else None

    def _fail(
        self,
        workflow: ValidatedCadQueryWorkflow,
        exc: Exception,
        *,
        boundary: str = "workflow_failure",
    ) -> ValidatedWorkflowRead:
        workflow.state = "failed"
        if workflow.failure_boundary is None:
            workflow.failure_boundary = boundary
        workflow.diagnostics_json = json.dumps(
            {
                "kind": workflow.failure_boundary,
                "message": safe_diagnostic(str(exc)),
                "first_incorrect_boundary": workflow.failure_boundary,
            },
            sort_keys=True,
        )
        workflow.state_version += 1
        self.db.commit()
        return self.read(workflow.id)

    def _project_service(self) -> ProjectService:
        return ProjectService(
            db=self.db,
            data_dir=self.data_dir,
            ai_provider=self.ai_provider,
            cad_runner=self.cad_runner,
        )

    def _persist_provider_attempt(self, attempt: dict[str, Any]) -> None:
        workflow = self.db.get(ValidatedCadQueryWorkflow, self._active_workflow_id) if self._active_workflow_id else None
        record = ValidatedCadQueryProviderAttempt(
            project_id=workflow.project_id if workflow is not None else None,
            workflow_id=workflow.id if workflow is not None else None,
            logical_operation_id=str(attempt.get("logical_operation_id") or "unknown"),
            attempt_id=str(attempt.get("attempt_id") or "unknown"),
            credential_slot=str(attempt.get("credential_slot") or "unknown"),
            credential_env_var=str(attempt.get("credential_env_var") or "unknown"),
            credential_present=bool(attempt.get("credential_present")),
            request_hash=str(attempt.get("request_hash") or ""),
            status_code=int(attempt["status_code"]) if attempt.get("status_code") is not None else None,
            failure_class=str(attempt["failure_class"]) if attempt.get("failure_class") else None,
            retry_delay_seconds=float(attempt["retry_delay_seconds"]) if attempt.get("retry_delay_seconds") is not None else None,
        )
        self.db.add(record)
        # The 429 attempt must survive the mandatory delay and any later
        # fallback failure, so persist this metadata before returning control.
        self.db.commit()

    def _begin_operation(
        self,
        operation_type: str,
        idempotency_key: str | None,
        payload: object,
        *,
        project_id: str | None = None,
        workflow_id: str | None = None,
    ) -> ValidatedCadQueryOperation:
        self._ensure_sqlite_transaction()
        key = (idempotency_key or "").strip() or "auto-" + canonical_idempotency_hash(operation_type, "", payload)
        if len(key) > 240:
            raise ValueError("idempotency key is too long")
        payload_hash = canonical_idempotency_hash(operation_type, key, payload)
        existing = self.db.scalar(
            select(ValidatedCadQueryOperation)
            .where(ValidatedCadQueryOperation.owner_id == self.owner_id)
            .where(ValidatedCadQueryOperation.operation_type == operation_type)
            .where(ValidatedCadQueryOperation.idempotency_key == key)
        )
        if existing is not None:
            if existing.payload_hash != payload_hash:
                raise ValueError("idempotency key was already used with a different request")
            if existing.status == "completed" and existing.workflow_id is None:
                raise ValueError("completed operation has no linked workflow")
            return existing
        operation = ValidatedCadQueryOperation(
            owner_id=self.owner_id,
            operation_type=operation_type,
            idempotency_key=key,
            payload_hash=payload_hash,
            project_id=project_id,
            workflow_id=workflow_id,
            status="started",
        )
        try:
            with self.db.begin_nested():
                self.db.add(operation)
                self.db.flush()
        except IntegrityError:
            existing = self.db.scalar(
                select(ValidatedCadQueryOperation)
                .where(ValidatedCadQueryOperation.owner_id == self.owner_id)
                .where(ValidatedCadQueryOperation.operation_type == operation_type)
                .where(ValidatedCadQueryOperation.idempotency_key == key)
            )
            if existing is None or existing.payload_hash != payload_hash:
                raise ValueError("idempotency key was already used with a different request")
            return existing
        return operation

    def _ensure_sqlite_transaction(self) -> None:
        """Make savepoint-backed operation creation atomic on SQLite too.

        Python's sqlite3 driver can leave a savepoint outside a physical
        transaction when the session has only performed reads. Releasing
        that savepoint would make the operation durable before the workflow
        transaction begins. Start the driver transaction before the nested
        insert so the surrounding rollback has one atomic boundary.
        """
        bind = self.db.get_bind()
        if bind.dialect.name != "sqlite":
            return
        connection = self.db.connection()
        raw_connection = connection.connection
        if not raw_connection.in_transaction:
            connection.exec_driver_sql("BEGIN")

    def _start_design_checkpoint(self, _name: str) -> None:
        """Test-injectable crash boundary; production behavior is a no-op."""

    @staticmethod
    def _complete_operation(operation: ValidatedCadQueryOperation) -> None:
        if operation.workflow_id is None:
            raise ValueError("operation cannot complete without a linked workflow")
        operation.status = "completed"

    def _get(
        self,
        workflow_id: str,
        *,
        project_id: str | None = None,
    ) -> ValidatedCadQueryWorkflow | None:
        workflow = self.db.get(ValidatedCadQueryWorkflow, workflow_id)
        if workflow is None or workflow.owner_id != self.owner_id:
            return None
        project = self.db.get(Project, workflow.project_id)
        if project is None or project.status in {"archived", "deleted"}:
            return None
        if project_id is not None and workflow.project_id != project_id:
            return None
        return workflow

    def _require_workflow(
        self,
        workflow_id: str,
        *,
        project_id: str | None = None,
    ) -> ValidatedCadQueryWorkflow:
        workflow = self._get(workflow_id, project_id=project_id)
        if workflow is None:
            raise LookupError("validated workflow not found")
        return workflow

    def _resolve_optional(self, relative: str | None) -> Path | None:
        if not relative:
            return None
        candidate = safe_relative_artifact_path(self.data_dir, relative)
        return candidate if candidate.is_file() else None

    @staticmethod
    def _archive_slug(value: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
        if not slug or slug in {".", ".."}:
            raise ValueError("output identity is not safe for packaging")
        return slug[:120]

    def _package_artifact_ref(self, output: RevisionOutput, kind: str) -> str | None:
        relative = getattr(output, f"{kind}_path")
        if not relative:
            return None
        path = self._resolve_optional(relative)
        if path is None:
            return None
        return f"artifacts/{self._archive_slug(output.output_id)}/{path.name}"

    @staticmethod
    def _revision_instruction(payload: ValidatedBoundedRevision) -> str:
        pieces = [payload.instruction.strip()]
        if payload.dimension_changes:
            pieces.append("Dimension changes: " + json.dumps(payload.dimension_changes, sort_keys=True))
        if payload.added_features:
            pieces.append("Add features: " + json.dumps(payload.added_features, sort_keys=True))
        if payload.protected_facts:
            pieces.append("Preserve: " + ", ".join(payload.protected_facts))
        return "\n".join(pieces)

    def require_enabled(self) -> None:
        if not settings.validated_cadquery_flow_enabled:
            raise ValueError("validated CadQuery workflow is disabled")

    def _observe_feature_flag(self, workflow: ValidatedCadQueryWorkflow) -> None:
        if settings.validated_cadquery_flow_enabled:
            return
        if workflow.state in {"candidate_ready", "revision_ready", "failed", "verification_failed", "partially_completed"}:
            return
        if workflow.routing_state == "disabled_after_start":
            return
        workflow.routing_state = "disabled_after_start"
        diagnostics = _json_object(workflow.diagnostics_json)
        diagnostics.update(
            {
                "kind": "feature_flag_disabled_during_workflow",
                "message": "This validated design is paused because the staging workflow is disabled.",
            }
        )
        workflow.diagnostics_json = json.dumps(diagnostics, sort_keys=True)
        workflow.state_version += 1
        self.db.commit()

    def reconcile_workflow(self, workflow: ValidatedCadQueryWorkflow) -> None:
        if workflow.revision_id:
            revision = self.db.get(Revision, workflow.revision_id)
            if revision is not None:
                self.sync_outputs(workflow, revision)
                return
        if workflow.state in {"geometry_generating", "worker_running"}:
            self._fail(workflow, RuntimeError("restart reconciliation found no durable candidate revision"), boundary="restart_reconciliation")

    @classmethod
    def reconcile_after_restart(cls, *, db: Session, data_dir: Path) -> None:
        workflows = list(
            db.scalars(
                select(ValidatedCadQueryWorkflow).where(
                    ValidatedCadQueryWorkflow.state.in_({"geometry_generating", "worker_running"})
                )
            )
        )
        for workflow in workflows:
            service = cls(db=db, data_dir=data_dir, owner_id=workflow.owner_id)
            service.reconcile_workflow(workflow)
            db.commit()

    def reconcile_artifacts(self, workflow: ValidatedCadQueryWorkflow) -> None:
        revision = self.db.get(Revision, workflow.revision_id) if workflow.revision_id else None
        if revision is None:
            return
        product_outputs = {
            output.output_id: output
            for output in self.db.scalars(
                select(ValidatedCadQueryOutput).where(ValidatedCadQueryOutput.workflow_id == workflow.id)
            )
        }
        changed = False
        for revision_output in revision.outputs:
            product_output = product_outputs.get(revision_output.output_id)
            if product_output is None or not product_output.artifact_available:
                continue
            missing_artifact = False
            for kind in ("stl", "step"):
                relative = getattr(revision_output, f"{kind}_path")
                if not relative:
                    missing_artifact = True
                    break
                try:
                    resolved = self._resolve_optional(relative)
                except ValueError:
                    resolved = None
                if resolved is None or not getattr(revision_output, f"{kind}_hash") or _sha256(resolved) != getattr(revision_output, f"{kind}_hash"):
                    missing_artifact = True
                    break
            if missing_artifact:
                product_output.artifact_available = False
                product_output.state = "export_failed"
                product_output.failure_owner = "artifact"
                product_output.safe_diagnostic = "A registered download is missing and must be regenerated."
                changed = True
        if changed:
            outputs = [
                {"required": output.required, "state": output.state}
                for output in product_outputs.values()
            ]
            workflow.state = derive_validated_workflow_state(outputs)
            workflow.diagnostics_json = json.dumps(
                {"kind": "missing_artifact", "message": "One or more registered downloads are unavailable."},
                sort_keys=True,
            )
            workflow.state_version += 1
            self.db.flush()

    def sync_outputs(self, workflow: ValidatedCadQueryWorkflow, revision: Revision) -> None:
        existing = {
            output.output_id: output
            for output in self.db.scalars(
                select(ValidatedCadQueryOutput).where(ValidatedCadQueryOutput.workflow_id == workflow.id)
            )
        }
        revision_outputs = list(
            self.db.scalars(
                select(RevisionOutput)
                .where(RevisionOutput.revision_id == revision.id)
                .order_by(RevisionOutput.output_id.asc())
            )
        )
        for revision_output in revision_outputs:
            summary = _json_object(revision_output.validation_summary_json)
            topology = _json_object(revision_output.topology_metadata_json)
            artifact_available = bool(revision_output.stl_path and revision_output.step_path)
            worker_completed = revision_output.execution_state in {"ready", "ready_with_warnings"}
            if (
                revision_output.execution_state == "blocked"
                and artifact_available
                and topology.get("valid") is True
                and summary.get("blocking_count", 0)
            ):
                worker_completed = True
            payload = {
                "success": worker_completed,
                "failure_class": "timeout" if "timeout" in (revision_output.compile_error or "").lower() else None,
                "compile_error": revision_output.compile_error,
                "topology_metadata": topology,
                "semantic_verification": {
                    "status": "failed" if summary.get("blocking_count", 0) else "passed",
                },
                "stl_path": revision_output.stl_path,
                "step_path": revision_output.step_path,
                "brep_path": revision_output.brep_path,
                "stl_hash": revision_output.stl_hash,
                "step_hash": revision_output.step_hash,
                "brep_hash": revision_output.brep_hash,
            }
            classification = classify_validated_output(payload, required=revision_output.required)
            product_output = existing.get(revision_output.output_id)
            if product_output is None:
                product_output = ValidatedCadQueryOutput(
                    workflow_id=workflow.id,
                    output_id=revision_output.output_id,
                    required=revision_output.required,
                )
                self.db.add(product_output)
            product_output.revision_output_id = revision_output.id
            product_output.required = revision_output.required
            product_output.generation_status = classification.generation_status
            product_output.worker_status = classification.worker_status
            product_output.state = classification.state
            product_output.solid_count = classification.solid_count
            product_output.topology_status = classification.topology_status
            product_output.semantic_verification = classification.semantic_verification
            product_output.artifact_available = classification.artifact_available
            product_output.failure_owner = classification.failure_owner
            product_output.safe_diagnostic = classification.safe_diagnostic
            product_output.artifact_metadata_json = json.dumps(classification.artifact_metadata, sort_keys=True)

        self.db.flush()
        product_outputs = list(
            self.db.scalars(
                select(ValidatedCadQueryOutput)
                .where(ValidatedCadQueryOutput.workflow_id == workflow.id)
                .order_by(ValidatedCadQueryOutput.output_id.asc())
            )
        )
        states = [output.state for output in product_outputs]
        workflow.state = derive_validated_workflow_state(
            [{"required": output.required, "state": output.state} for output in product_outputs]
        )
        if not product_outputs:
            workflow.state = "failed" if revision.status == "failed" else "worker_running"
        workflow.revision_id = revision.id
        workflow.state_version += 1
        workflow.verification_json = json.dumps(
            {
                "revision_id": revision.id,
                "status": "passed" if workflow.state == "candidate_ready" else "partial" if workflow.state == "partially_completed" else "failed",
                "output_states": {output.output_id: output.state for output in product_outputs},
            },
            sort_keys=True,
        )
        self.db.flush()


def _json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _product_artifact_metadata(raw: str | None) -> dict[str, Any]:
    value = _json_object(raw)
    return {
        key: value[key]
        for key in ("stl_hash", "step_hash", "brep_hash")
        if value.get(key)
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
