from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol

from app.services.ai.provider import DesignPlanRequest, ModelGenerationRequest, RequirementExtractionRequest
from app.services.cad.geometry_slots import build_geometry_slot_manifest
from app.services.gemini_integration.adapters import (
    AdapterEvidence,
    GeminiGeometryContractAdapter,
    GeminiPlanContractAdapter,
    GeminiRequirementsContractAdapter,
)
from app.services.gemini_integration.capture import IntegrationEvidenceStore
from app.services.gemini_integration.corpus import IntegrationProject
from app.services.gemini_integration.profile import GeminiFlashLiteContractV1, require_integration_profile
from app.services.gemini_integration.prompts import render_integration_prompt
from app.services.gemini_integration.transport import ProviderCallResult


ProviderCall = Callable[..., Awaitable[ProviderCallResult]]
BoundaryCall = Callable[..., Awaitable[dict[str, Any]]]


@dataclass
class IntegrationBoundaryPorts:
    provider_call: ProviderCall
    assemble_source: BoundaryCall
    static_validate: BoundaryCall
    worker_submit: BoundaryCall
    collect_artifacts: BoundaryCall
    inspect_topology: BoundaryCall
    verify_requirements: BoundaryCall
    decide_candidate: BoundaryCall
    calls: list[str] = field(default_factory=list)
    provider: Any = None


@dataclass(frozen=True)
class IntegrationWorkflowOutcome:
    project_id: str
    revision_id: str
    earliest_blocker: str | None
    furthest_valid_stage: str
    candidate_decision: str | None
    boundary_ids: tuple[str, ...]
    provider_attempt_ids: tuple[str, ...]
    worker_jobs: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "revision_id": self.revision_id,
            "earliest_blocker": self.earliest_blocker,
            "furthest_valid_stage": self.furthest_valid_stage,
            "candidate_decision": self.candidate_decision,
            "boundary_ids": list(self.boundary_ids),
            "provider_attempt_ids": list(self.provider_attempt_ids),
            "worker_jobs": list(self.worker_jobs),
        }


class IntegrationWorkflowRunner:
    def __init__(self, *, profile: GeminiFlashLiteContractV1, study_id: str, evidence_store: IntegrationEvidenceStore, ports: IntegrationBoundaryPorts) -> None:
        require_integration_profile(profile.profile_id)
        if study_id != "gemini-provider-contract-integration-01":
            raise ValueError("integration runner requires the preregistered integration study ID")
        self.profile = profile
        self.study_id = study_id
        self.evidence_store = evidence_store
        self.ports = ports
        self.requirements_adapter = GeminiRequirementsContractAdapter()
        self.plan_adapter = GeminiPlanContractAdapter()
        self.geometry_adapter = GeminiGeometryContractAdapter()

    @property
    def provenance(self) -> dict[str, Any]:
        return {"study_id": self.study_id, "provenance_marker": "volundr-provider-contract-integration"}

    async def run_project(self, project: IntegrationProject) -> IntegrationWorkflowOutcome:
        revision_id = f"{project.project_id}:revision-001"
        boundary_ids: list[str] = []
        attempt_ids: list[str] = []
        worker_jobs: list[dict[str, Any]] = []
        furthest = "input"
        earliest: str | None = None

        async def provider(stage: str, request: Any, operation_suffix: str) -> ProviderCallResult | None:
            nonlocal earliest, furthest
            rendered = render_integration_prompt(self.profile, stage, request)
            operation_id = f"{self.study_id}:{project.project_id}:{revision_id}:{operation_suffix}"
            result = await self.ports.provider_call(stage=stage, prompt=rendered.prompt, operation_id=operation_id)
            for attempt in result.attempts:
                enriched = {**attempt, "project_id": project.project_id, "revision_id": revision_id, "prompt_hash": rendered.prompt_hash, "prompt_version": rendered.prompt_version, "provenance": self._provenance(project.project_id, revision_id)}
                self.evidence_store.record_provider_attempt(enriched)
                if attempt.get("attempt_id"):
                    attempt_ids.append(str(attempt["attempt_id"]))
            boundary_ids.append(self._capture_boundary(
                project, revision_id, f"provider_{stage}",
                {"prompt_hash": rendered.prompt_hash, "prompt_version": rendered.prompt_version, "request": request.__dict__},
                {"attempt_ids": [item.get("attempt_id") for item in result.attempts], "complete": result.complete, "text": result.text},
            ))
            if not result.complete or not result.text:
                earliest = earliest or "transport"
                return None
            furthest = stage
            return result

        requirement_request = RequirementExtractionRequest(
            project_name=project.title,
            original_intent=project.user_request,
            user_instruction=project.user_request,
        )
        requirement_result = await provider("requirements", requirement_request, "requirements")
        if requirement_result is None:
            return self._outcome(project, revision_id, earliest, furthest, None, boundary_ids, attempt_ids, worker_jobs)
        requirement_evidence = self.requirements_adapter.adapt(
            requirement_result.text,
            {**self._context(project, revision_id), "fit_critical_missing": list(project.fit_critical_missing)},
        )
        boundary_ids.append(self._capture_adapter(project, revision_id, "requirements_adapter", requirement_evidence))
        if not requirement_evidence.accepted:
            earliest = earliest or "requirements_adapter"
            return self._outcome(project, revision_id, earliest, furthest, None, boundary_ids, attempt_ids, worker_jobs)
        specification = requirement_evidence.normalized
        if specification.get("clarification_required") is True:
            continuation = RequirementExtractionRequest(
                project_name=project.title,
                original_intent=project.user_request,
                user_instruction=project.user_request,
                previous_specification=specification,
                clarification_answers=list(project.clarification_answers),
            )
            continuation_result = await provider("requirements", continuation, "requirements-continuation")
            if continuation_result is None:
                return self._outcome(project, revision_id, earliest, furthest, None, boundary_ids, attempt_ids, worker_jobs)
            continuation_evidence = self.requirements_adapter.adapt(
                continuation_result.text,
                {**self._context(project, revision_id), "fit_critical_missing": [], "frozen_clarification_answers": list(project.clarification_answers)},
            )
            boundary_ids.append(self._capture_adapter(project, revision_id, "requirements_adapter_continuation", continuation_evidence))
            if not continuation_evidence.accepted:
                earliest = earliest or "requirements_adapter"
                return self._outcome(project, revision_id, earliest, furthest, None, boundary_ids, attempt_ids, worker_jobs)
            specification = continuation_evidence.normalized
        plan_request = DesignPlanRequest(
            project_name=project.title,
            original_intent=project.user_request,
            user_instruction=project.user_request,
            design_specification=specification,
            active_requirements=list(specification.get("requirements", [])),
        )
        plan_result = await provider("plan", plan_request, "plan")
        if plan_result is None:
            return self._outcome(project, revision_id, earliest, furthest, None, boundary_ids, attempt_ids, worker_jobs)
        plan_evidence = self.plan_adapter.adapt(
            plan_result.text,
            {**self._context(project, revision_id), "expected_output_count": project.expected_output_count, "required_requirement_ids": [str(item.get("id")) for item in specification.get("requirements", []) if isinstance(item, dict) and item.get("id")]},
        )
        boundary_ids.append(self._capture_adapter(project, revision_id, "plan_adapter", plan_evidence))
        if not plan_evidence.accepted:
            earliest = earliest or "plan_adapter"
            return self._outcome(project, revision_id, earliest, furthest, None, boundary_ids, attempt_ids, worker_jobs)
        plan = plan_evidence.normalized
        manifest = build_geometry_slot_manifest(plan, planning_depth="detailed_plan")
        geometry_request = ModelGenerationRequest(
            project_name=project.title,
            original_intent=project.user_request,
            user_instruction=project.user_request,
            design_plan=plan,
            geometry_slot_manifest=manifest,
            geometry_contract="volundr-geometry-slots-v1",
        )
        geometry_result = await provider("geometry", geometry_request, "geometry")
        if geometry_result is None:
            return self._outcome(project, revision_id, earliest, furthest, None, boundary_ids, attempt_ids, worker_jobs)
        allowed_names = {"body", "cq", "params", "cutter"}
        for slot in manifest.get("slots", []) or []:
            if isinstance(slot, dict):
                allowed_names.update(str(value) for value in slot.get("authorized_parameter_ids", []) or [])
                allowed_names.update(str(value) for value in slot.get("approved_helpers", []) or [])
        geometry_evidence = self.geometry_adapter.adapt(
            geometry_result.text,
            {**self._context(project, revision_id), "expected_slot_ids": [item.get("slot_id") for item in manifest.get("slots", [])], "allowed_names": sorted(allowed_names)},
        )
        boundary_ids.append(self._capture_adapter(project, revision_id, "geometry_adapter", geometry_evidence))
        if not geometry_evidence.accepted:
            earliest = earliest or "geometry_adapter"
            return self._outcome(project, revision_id, earliest, furthest, None, boundary_ids, attempt_ids, worker_jobs)
        furthest = "geometry_adapter"
        source_result = await self.ports.assemble_source(project=project, plan=plan, geometry=geometry_evidence.normalized, provenance=self._provenance(project.project_id, revision_id))
        boundary_ids.append(self._capture_boundary(project, revision_id, "source_assembly", {"plan": plan, "geometry": geometry_evidence.normalized}, source_result))
        source = str(source_result.get("source") or "")
        static_result = await self.ports.static_validate(source=source, provenance=self._provenance(project.project_id, revision_id))
        boundary_ids.append(self._capture_boundary(project, revision_id, "static_validation", {"source": source}, static_result))
        if not static_result.get("valid", False):
            return self._outcome(project, revision_id, "static_validator", "static_validation", None, boundary_ids, attempt_ids, worker_jobs)
        worker_result = await self.ports.worker_submit(source=source, output_manifest=source_result.get("output_manifest", []), provenance=self._provenance(project.project_id, revision_id))
        worker_jobs.append(worker_result)
        boundary_ids.append(self._capture_boundary(project, revision_id, "worker", {"source": source}, worker_result))
        if not worker_result.get("success", False):
            return self._outcome(project, revision_id, "worker_runtime", "worker", None, boundary_ids, attempt_ids, worker_jobs)
        artifacts = await self.ports.collect_artifacts(worker_result=worker_result, provenance=self._provenance(project.project_id, revision_id))
        boundary_ids.append(self._capture_boundary(project, revision_id, "artifacts", worker_result, artifacts))
        topology = await self.ports.inspect_topology(artifacts=artifacts, provenance=self._provenance(project.project_id, revision_id))
        boundary_ids.append(self._capture_boundary(project, revision_id, "topology", artifacts, topology))
        verification = await self.ports.verify_requirements(project=project, plan=plan, topology=topology, provenance=self._provenance(project.project_id, revision_id))
        boundary_ids.append(self._capture_boundary(project, revision_id, "verification", {"plan": plan, "topology": topology}, verification))
        candidate = await self.ports.decide_candidate(project=project, verification=verification, provenance=self._provenance(project.project_id, revision_id))
        boundary_ids.append(self._capture_boundary(project, revision_id, "candidate", verification, candidate))
        return self._outcome(project, revision_id, None, "candidate", candidate.get("decision"), boundary_ids, attempt_ids, worker_jobs)

    def _context(self, project: IntegrationProject, revision_id: str) -> dict[str, Any]:
        return {"project_id": project.project_id, "revision_id": revision_id, "operation_id": f"{self.study_id}:{project.project_id}", "provenance": self._provenance(project.project_id, revision_id)}

    def _provenance(self, project_id: str, revision_id: str) -> dict[str, Any]:
        return {**self.provenance, "project_id": project_id, "revision_id": revision_id}

    def _capture_boundary(self, project: IntegrationProject, revision_id: str, boundary: str, input_value: Any, output_value: Any) -> str:
        boundary_id = f"{project.project_id}:{revision_id}:{boundary}"
        self.evidence_store.record_boundary({
            "boundary_id": boundary_id,
            "boundary": boundary,
            "project_id": project.project_id,
            "revision_id": revision_id,
            "input_hash": hashlib.sha256(json.dumps(input_value, sort_keys=True, default=str).encode()).hexdigest(),
            "output_hash": hashlib.sha256(json.dumps(output_value, sort_keys=True, default=str).encode()).hexdigest(),
            "input": input_value,
            "output": output_value,
            "provenance": self._provenance(project.project_id, revision_id),
        })
        return boundary_id

    def _capture_adapter(self, project: IntegrationProject, revision_id: str, boundary: str, evidence: AdapterEvidence) -> str:
        return self._capture_boundary(project, revision_id, boundary, {"input_hash": evidence.input_hash}, evidence.as_dict())

    @staticmethod
    def _outcome(project: IntegrationProject, revision_id: str, earliest: str | None, furthest: str, candidate: str | None, boundaries: list[str], attempts: list[str], jobs: list[dict[str, Any]]) -> IntegrationWorkflowOutcome:
        return IntegrationWorkflowOutcome(project.project_id, revision_id, earliest, furthest, candidate, tuple(boundaries), tuple(attempts), tuple(jobs))


__all__ = ["IntegrationBoundaryPorts", "IntegrationWorkflowOutcome", "IntegrationWorkflowRunner"]
