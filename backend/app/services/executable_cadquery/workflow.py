"""Experimental Gemini complete-source workflow backed by existing services."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from app.core.config import settings
from app.models.project import Project
from app.models.revision import Revision
from app.models.validated_cadquery_workflow import ValidatedCadQueryWorkflow
from app.schemas.project import ProjectCreate
from app.schemas.validated_cadquery import ValidatedBoundedRevision, ValidatedCadQueryStart
from app.services.ai.provider import ModelGenerationRequest
from app.services.executable_cadquery.contract import (
    ExecutableCadQueryContractError,
    parse_executable_cadquery_response,
    validate_executable_cadquery_design_contract,
)
from app.services.executable_cadquery.corpus import load_repeatability_contract
from app.services.executable_cadquery.evidence import persist_exact_provider_response
from app.services.executable_cadquery.fixtures import FROZEN_MOUNTING_BRACKET_CONTRACT
from app.services.executable_cadquery.dialect import (
    CADQUERY_V1_SOURCE_DIALECT_VERSION,
    cadquery_v1_source_dialect_hash,
    cadquery_v1_source_skeleton_hash,
)
from app.services.executable_cadquery.repair import (
    AUTOMATIC_PROVIDER_OPERATION_BUDGET,
    build_executable_cadquery_repair_envelope,
    classify_executable_failure,
    compare_executable_progress,
    source_result_hash,
)
from app.services.executable_cadquery.recovery import (
    FailureObservation,
    RecoveryDecision,
    RecoveryRouter,
)
from app.services.executable_cadquery.recovery_executor import RecoveryActionExecutor
from app.services.executable_cadquery.semantic import (
    evaluate_executable_cadquery_semantics_for_outputs,
)
from app.services.executable_cadquery.semantic_policy import (
    derive_candidate_policy,
    evaluate_semantic_policy,
)
from app.services.projects.service import ProjectService
from app.services.validated_cadquery_security import safe_relative_artifact_path
from app.services.validated_cadquery_workflow import ValidatedCadQueryWorkflowService, safe_diagnostic


class ExecutableCadQueryWorkflowService(ValidatedCadQueryWorkflowService):
    """Route complete Gemini source through the existing execution/persistence path."""

    route = "executable-cadquery-v1"

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self._recovery_router = RecoveryRouter()
        self._recovery_executor = RecoveryActionExecutor(data_dir=self.data_dir)

    def _provider_transport_id(self) -> str:
        return str(getattr(self.ai_provider, "provider_id", settings.ai_provider))

    async def start_design(
        self,
        payload: ValidatedCadQueryStart,
        *,
        idempotency_key: str | None = None,
    ):
        self.require_enabled()
        operation = self._begin_operation("start_design", idempotency_key, payload.model_dump(mode="json"))
        if operation.workflow_id:
            return self.read(operation.workflow_id)
        if operation.status == "completed":
            raise ValueError("completed start operation has no linked workflow")
        project_service = self._project_service()
        project = None
        workflow = None
        try:
            project = self.db.get(Project, operation.project_id) if operation.project_id else None
            if project is None:
                project = project_service.create_project(
                    ProjectCreate(name=payload.name, original_intent=payload.intent),
                    commit=False,
                )
            workflow = ValidatedCadQueryWorkflow(
                project_id=project.id,
                owner_id=self.owner_id,
                state="requirements_ready",
                route=self.route,
                user_instruction=payload.intent,
                requirements_json=json.dumps({"user_prompt": payload.intent}, sort_keys=True),
                provenance_json=json.dumps(
                    {
                        "selected_route": self.route,
                        "feature_flag": "VOLUNDR_EXECUTABLE_CADQUERY_FLOW_ENABLED",
                        "feature_flag_enabled": True,
                        "provider_transport": self._provider_transport_id(),
                        "provider_id": self._provider_transport_id(),
                        "contract_version": "executable-cadquery-design-contract-v1",
                        "source_generation_mode": "complete_source",
                        "codex_proxy_used": False,
                    },
                    sort_keys=True,
                ),
            )
            self.db.add(workflow)
            self.db.flush()
            contract = self._materialize_contract(
                project.id,
                workflow.id,
                ordinal=1,
                prompt=workflow.user_instruction,
            )
            workflow.plan_json = json.dumps(self._execution_plan(contract), sort_keys=True)
            provenance = self._json(workflow.provenance_json)
            provenance["executable_design_contract"] = contract
            workflow.provenance_json = json.dumps(provenance, sort_keys=True)
            operation.project_id = project.id
            operation.workflow_id = workflow.id
            operation.status = "running"
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        self._active_workflow_id = workflow.id
        try:
            result = await self._generate_with_repair_ladder(
                workflow,
                contract,
                requested_delta=None,
                parent_revision_id=None,
                starting_level="initial",
            )
            self._complete_operation(operation)
            self.db.commit()
            return result
        except Exception as exc:
            result = self._fail(workflow, exc, boundary="executable_workflow")
            operation.status = "failed"
            self.db.commit()
            return result

    async def start_bounded_revision(
        self,
        workflow_id: str,
        payload: ValidatedBoundedRevision,
        *,
        idempotency_key: str | None = None,
    ):
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
        if operation.status in {"completed", "failed"} and operation.workflow_id:
            child = self._get(operation.workflow_id)
            if child is not None:
                return self.read(child.id)
        if operation.status == "running" and operation.workflow_id == parent.id:
            return self.read(parent.id)

        parent_provenance = self._json(parent.provenance_json)
        previous_contract = parent_provenance.get("executable_design_contract")
        if not isinstance(previous_contract, dict):
            raise ValueError("accepted executable workflow has no durable design contract")
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
                    "selected_route": self.route,
                    "feature_flag": "VOLUNDR_EXECUTABLE_CADQUERY_FLOW_ENABLED",
                    "feature_flag_enabled": True,
                    "provider_transport": self._provider_transport_id(),
                    "provider_id": self._provider_transport_id(),
                    "source_generation_mode": "complete_source_revision",
                    "codex_proxy_used": False,
                    "prior_revision_id": base_revision.id,
                    "prior_source_hash": base_revision.source_hash,
                    "protected_facts": payload.protected_facts,
                },
                sort_keys=True,
            ),
        )
        self.db.add(child)
        self.db.flush()
        contract = self._revision_contract(
            previous_contract,
            project_id=parent.project_id,
            workflow_id=child.id,
            payload=payload,
        )
        child.requirements_json = json.dumps({"user_prompt": parent.user_instruction}, sort_keys=True)
        child.plan_json = json.dumps(self._execution_plan(contract), sort_keys=True)
        provenance = self._json(child.provenance_json)
        provenance["executable_design_contract"] = contract
        child.provenance_json = json.dumps(provenance, sort_keys=True)
        operation.workflow_id = child.id
        operation.status = "running"
        self.db.commit()
        self._active_workflow_id = child.id
        try:
            result = await self._generate_with_repair_ladder(
                child,
                contract,
                requested_delta=revision_instruction,
                parent_revision_id=base_revision.id,
                starting_level="L4",
            )
            verification = self._json(child.verification_json)
            verification.update(
                {
                    "prior_revision_id": base_revision.id,
                    "preserved_output_ids": [output.output_id for output in base_revision.outputs],
                    "output_identity_preserved": {
                        output.output_id for output in base_revision.outputs
                    }
                    == {output.output_id for output in self.db.get(Revision, child.revision_id).outputs}
                    if child.revision_id
                    else False,
                }
            )
            child.verification_json = json.dumps(verification, sort_keys=True)
            if child.state == "candidate_ready":
                child.state = "revision_ready"
            self._complete_operation(operation)
            self.db.commit()
            return self.read(child.id)
        except Exception as exc:
            result = self._fail(child, exc, boundary="executable_revision")
            operation.status = "failed"
            self.db.commit()
            return result

    def record_independent_review(
        self,
        workflow_id: str,
        review_record: Mapping[str, Any],
    ):
        """Persist a blind final-package review and rederive candidate state."""

        workflow = self._get(workflow_id)
        if workflow is None:
            raise LookupError("validated workflow not found")
        verification = self._json(workflow.verification_json)
        semantic = verification.get("semantic_verification")
        if not isinstance(semantic, Mapping):
            raise ValueError("workflow has no persisted semantic verification")
        review = dict(review_record)
        verdict = str(review.get("final_verdict") or "").upper()
        if verdict not in {"PASS", "FAIL", "UNCERTAIN"}:
            raise ValueError("independent review must provide PASS, FAIL, or UNCERTAIN")
        review["final_verdict"] = verdict
        review["reviewer"] = str(review.get("reviewer") or "blind_codex_cad_qa_v1")
        review_cycle = int(review.get("review_cycle") or 1)
        if not 1 <= review_cycle <= 3:
            raise ValueError("independent review cycle must be between 1 and 3")
        review["review_cycle"] = review_cycle
        verification["independent_final_review"] = review
        package_path = self._resolve_optional(workflow.package_path)
        verification["candidate_policy"] = derive_candidate_policy(
            outputs=[
                {
                    "output_id": output.output_id,
                    "required": output.required,
                    "state": output.state,
                    "worker_status": output.worker_status,
                    "topology_status": output.topology_status,
                    "artifact_available": output.artifact_available,
                }
                for output in workflow.outputs
            ],
            semantic_verification=semantic,
            artifacts={
                "package_required": True,
                "package_available": package_path is not None,
                "valid": None if package_path is None else self._package_is_safe(package_path),
            },
            independent_review={"verdict": review.get("final_verdict")},
        )
        workflow.verification_json = json.dumps(verification, sort_keys=True, default=str)
        diagnostics = self._json(workflow.diagnostics_json)
        diagnostics["latest_independent_review"] = review
        workflow.diagnostics_json = json.dumps(diagnostics, sort_keys=True, default=str)
        self.db.commit()
        return self.read(workflow.id)

    async def _generate_with_repair_ladder(
        self,
        workflow: ValidatedCadQueryWorkflow,
        contract: dict[str, Any],
        *,
        requested_delta: str | None,
        parent_revision_id: str | None,
        starting_level: str,
    ):
        project = self.db.get(Project, workflow.project_id)
        if project is None:
            raise ValueError("executable workflow project not found")
        previous_source: str | None = None
        previous_source_hash: str | None = None
        previous_result_hash: str | None = None
        previous_provider_response: str | None = None
        previous_normalized_error: str | None = None
        if parent_revision_id:
            parent_revision = self.db.get(Revision, parent_revision_id)
            if parent_revision is not None:
                source_path = self._resolve_optional(parent_revision.source_path)
                if source_path is not None:
                    previous_source = source_path.read_text(encoding="utf-8")
                    previous_source_hash = parent_revision.source_hash
        history: list[dict[str, Any]] = []
        level = starting_level
        repair_ordinals = {"L0": 0, "L1": 0, "L2": 0, "L3": 0, "L4": 1 if starting_level == "L4" else 0}
        previous_failure_class: str | None = None
        previous_comparison_facts: dict[str, Any] = {}
        attempt_count = 0

        while attempt_count < AUTOMATIC_PROVIDER_OPERATION_BUDGET:
            attempt_count += 1
            envelope = None
            if level != "initial":
                envelope = build_executable_cadquery_repair_envelope(
                    repair_level=level,
                    generation_session_id=workflow.id,
                    logical_operation_id=f"{workflow.id}:generation",
                    parent_operation_id=history[-1].get("operation_id") if history else None,
                    repair_ordinal=repair_ordinals[level],
                    previous_source=previous_source,
                    previous_source_hash=previous_source_hash,
                    previous_result_hash=previous_result_hash,
                    previous_provider_response=previous_provider_response,
                    previous_normalized_error=previous_normalized_error,
                    design_contract=contract,
                    provider_attempt=history[-1].get("provider_attempt") if history else None,
                    worker_result=history[-1].get("worker_result") if history else None,
                    topology_result=history[-1].get("topology_result") if history else None,
                    semantic_result=history[-1].get("semantic_result") if history else None,
                    protected_facts=contract.get("protected_facts", []),
                    repair_history=history,
                    requested_delta=requested_delta,
                )
            request = ModelGenerationRequest(
                project_name=project.name,
                original_intent=workflow.user_instruction,
                user_instruction=workflow.user_instruction,
                current_source=previous_source,
                executable_design_contract=contract,
                executable_repair_envelope=envelope,
            )
            provider_attempt: dict[str, Any] = {"attempt_number": attempt_count, "level": level}
            failure_class: str | None = None
            failure_boundary = "provider_response"
            worker_result: dict[str, Any] = {}
            topology_result: dict[str, Any] = {}
            semantic_result: dict[str, Any] = {}
            current_source_hash: str | None = None
            current_result_hash: str | None = None
            revision_id: str | None = None
            raw_output: str | None = None
            extracted_source: str | None = None
            normalized_error: str | None = None
            extraction_succeeded = False
            syntax_valid = False
            source_contract_valid = False
            try:
                if self.ai_provider is None:
                    raise ValueError("executable Gemini provider is unavailable")
                generation = await self.ai_provider.generate_cadquery_model(request)
                raw_output = generation.raw_output if isinstance(generation.raw_output, str) else ""
                response_evidence_path = persist_exact_provider_response(
                    self.data_dir,
                    workflow_id=workflow.id,
                    attempt_number=attempt_count,
                    raw_response=raw_output,
                )
                provider_attempt.update(
                    {
                        "provider": generation.provider,
                        "provider_model": generation.provider_model,
                        "status": "response_received",
                        "response_evidence_path": response_evidence_path.resolve().relative_to(self.data_dir.resolve()).as_posix(),
                        "response_length": len(raw_output),
                        "raw_response_hash": hashlib.sha256(raw_output.encode("utf-8")).hexdigest(),
                        "response_hash": hashlib.sha256(raw_output.encode("utf-8")).hexdigest(),
                    }
                )
                parsed = parse_executable_cadquery_response(raw_output, contract)
                generated = parsed.outputs[0]
                extracted_source = generated.source
                extraction_succeeded = True
                syntax_valid = True
                source_contract_valid = True
                current_source_hash = generated.source_hash
                provider_attempt.update(
                    {
                        "extracted_source_hash": current_source_hash,
                        "syntax_valid": True,
                        "source_contract_valid": True,
                        "diagnostic": None,
                    }
                )
                failure_boundary = "execution"
                revision_read = await self._project_service().create_complete_cadquery_revision(
                    project_id=workflow.project_id,
                    source=generated.source,
                    user_instruction=workflow.user_instruction,
                    design_plan_payload=self._execution_plan(contract),
                    raw_ai_output=raw_output,
                    parent_revision_id=parent_revision_id,
                )
                if revision_read is None:
                    raise ValueError("complete source did not produce a revision")
                revision_id = revision_read.id
                revision = self.db.get(Revision, revision_id)
                if revision is None:
                    raise ValueError("complete source revision disappeared")
                output = next(iter(revision.outputs), None)
                worker_result = {
                    "phase": "completed" if revision.status == "succeeded" else "failed",
                    "output_ids": [item.output_id for item in revision.outputs],
                    "revision_id": revision.id,
                }
                topology_by_output = {
                    item.output_id: self._json(item.topology_metadata_json)
                    for item in revision.outputs
                }
                topology_result = (
                    next(iter(topology_by_output.values()), {})
                    if len(topology_by_output) == 1
                    else {
                        "valid": bool(topology_by_output)
                        and all(item.get("valid") is True for item in topology_by_output.values()),
                        "outputs": topology_by_output,
                        "output_ids": sorted(topology_by_output),
                    }
                )
                stl_paths: dict[str, Path] = {}
                for revision_output in revision.outputs:
                    if not revision_output.stl_path or not revision_output.step_path:
                        continue
                    stl_paths[revision_output.output_id] = safe_relative_artifact_path(
                        self.data_dir,
                        revision_output.stl_path,
                    )
                if output is None or len(stl_paths) != len(revision.outputs):
                    failure_boundary = "artifact"
                    failure_class = classify_executable_failure("artifact", {"stl_failure": True})
                else:
                    semantic_result = evaluate_executable_cadquery_semantics_for_outputs(
                        stl_paths=stl_paths,
                        design_contract=contract,
                    )
                    semantic_result = complete_executable_semantic_coverage(
                        semantic_result,
                        contract,
                    )
                    current_result_hash = source_result_hash(
                        {
                            "worker": worker_result,
                            "topology": topology_result,
                            "semantic": semantic_result,
                        }
                    )
                    if semantic_result.get("status") != "passed":
                        failure_boundary = "semantic"
                        failure_class = classify_executable_failure(
                            "semantic",
                            {
                                "failed": semantic_result.get("failed"),
                                "unverifiable": semantic_result.get("unverifiable"),
                            },
                        )
                        for revision_output in revision.outputs:
                            self._set_semantic_block(revision_output, semantic_result)
                    else:
                        self.sync_outputs(workflow, revision)
                        self._merge_verification(workflow, semantic_result)
                        self._record_generation_provenance(workflow, revision)
                        self._record_executable_provenance(
                            workflow,
                            attempt_count=attempt_count,
                            history=history,
                            source_hash=current_source_hash,
                            semantic_result=semantic_result,
                        )
                        self.db.commit()
                        return self.read(workflow.id)
            except ExecutableCadQueryContractError as exc:
                failure_boundary = exc.boundary
                normalized_error = safe_diagnostic(str(exc))
                extracted_source = exc.extracted_source
                current_source_hash = exc.extracted_source_hash
                extraction_succeeded = bool(extracted_source)
                syntax_valid = bool(exc.syntax_valid)
                source_contract_valid = bool(exc.source_contract_valid)
                failure_class = classify_executable_failure(
                    exc.boundary,
                    {
                        "failure_kind": exc.failure_kind,
                        "normalized_error": normalized_error,
                        "schema_error": normalized_error if exc.boundary == "provider_response" else None,
                    },
                )
                provider_attempt["status"] = "contract_failure"
                provider_attempt["failure_class"] = failure_class
                provider_attempt["normalized_error"] = normalized_error
                provider_attempt.update(
                    {
                        "extracted_source_hash": current_source_hash,
                        "syntax_valid": syntax_valid,
                        "source_contract_valid": source_contract_valid,
                        "diagnostic": exc.diagnostic,
                    }
                )
            except Exception as exc:
                normalized_error = safe_diagnostic(str(exc))
                failure_class = failure_class or classify_executable_failure(
                    failure_boundary, {"message": normalized_error}
                )
                provider_attempt["status"] = "failed"
                provider_attempt["failure_class"] = failure_class
                provider_attempt["normalized_error"] = normalized_error

            failure_class = failure_class or "source_execution_error"
            current_result_hash = current_result_hash or source_result_hash(
                {"worker": worker_result, "topology": topology_result, "semantic": semantic_result}
            )
            diagnostic = provider_attempt.get("diagnostic") or {}
            diagnostic_signature = json.dumps(
                {
                    key: diagnostic.get(key)
                    for key in ("code", "line", "column", "node_type", "enclosing_scope", "message")
                },
                sort_keys=True,
            )
            comparison_facts = {
                "contract_valid": source_contract_valid,
                "extracted_source_hash": current_source_hash,
                "diagnostic_signature": diagnostic_signature if diagnostic else normalized_error,
                "failure_signature": normalized_error,
                "violation_count": diagnostic.get("violation_count") if diagnostic else None,
                "syntax_valid": syntax_valid,
                "phase_index": 2 if worker_result.get("phase") == "completed" else 0,
                "completed_output_ids": worker_result.get("output_ids", []),
                "valid": topology_result.get("valid"),
                "detected_solid_count": topology_result.get("detected_solid_count"),
                "expected_solid_count": topology_result.get("expected_solid_count"),
                "failed_requirement_ids": semantic_result.get("failed", []),
                "unverifiable_requirement_ids": semantic_result.get("unverifiable", []),
                "passed_requirement_ids": semantic_result.get("passed", []),
            }
            progress = compare_executable_progress(
                level if level != "initial" else "L0",
                previous=previous_comparison_facts,
                current=comparison_facts,
            )
            if not history:
                progress = {"measurable_progress": True, "progress_reasons": ["first_repair_after_failure"]}
            comparison_facts["no_violation_decrease_streak"] = progress.get(
                "no_violation_decrease_streak", 0
            )
            operation_id = f"{workflow.id}:attempt:{attempt_count}"
            history.append(
                {
                    "operation_id": operation_id,
                    "attempt_number": attempt_count,
                    "repair_level": level,
                    "failure_boundary": failure_boundary,
                    "failure_class": failure_class,
                    "source_hash": current_source_hash,
                    "extracted_source_hash": current_source_hash,
                    "raw_response_hash": provider_attempt.get("raw_response_hash"),
                    "extraction_succeeded": extraction_succeeded,
                    "syntax_valid": syntax_valid,
                    "source_contract_valid": source_contract_valid,
                    "diagnostic": diagnostic,
                    "result_hash": current_result_hash,
                    "provider_attempt": provider_attempt,
                    "normalized_error": normalized_error,
                    "worker_result": worker_result,
                    "topology_result": topology_result,
                    "semantic_result": semantic_result,
                    "progress": progress,
                    "revision_id": revision_id,
                }
            )
            decision_level = level if level != "initial" else self._next_repair_level(failure_boundary)
            recovery_observation = FailureObservation(
                observed_stage=self._recovery_router.earliest_stage(failure_boundary, failure_class),
                failure_class=failure_class,
                evidence={
                    **comparison_facts,
                    "failure_boundary": failure_boundary,
                    "normalized_error": normalized_error,
                    "diagnostic": diagnostic,
                    "semantic_policy": semantic_result.get("policy_summary"),
                },
                attempt_ordinal=repair_ordinals.get(decision_level, 0) + 1,
                progress=progress,
            )
            recovery_decision = self._recovery_router.route(recovery_observation)
            self._persist_recovery_decision(workflow, recovery_decision)
            # The decision must be durable before any subsequent provider or
            # subsystem action is allowed to run.
            self.db.commit()
            previous_source = self._source_for_revision(revision_id) or previous_source
            previous_source = extracted_source or previous_source
            previous_source_hash = current_source_hash or previous_source_hash
            previous_result_hash = current_result_hash
            previous_provider_response = raw_output
            previous_normalized_error = normalized_error
            previous_failure_class = failure_class
            previous_comparison_facts = comparison_facts
            provider_repair_actions = {
                "gemini_contract_repair",
                "gemini_execution_repair",
                "gemini_topology_repair",
                "gemini_semantic_repair",
            }
            can_execute_provider_repair = (
                recovery_decision.recommended_action in provider_repair_actions
                and recovery_decision.repair_level is not None
                and not recovery_decision.terminal
            )
            if not can_execute_provider_repair or attempt_count >= AUTOMATIC_PROVIDER_OPERATION_BUDGET:
                recovery_execution = None
                if not can_execute_provider_repair and not recovery_decision.terminal:
                    revision_for_recovery = self.db.get(Revision, revision_id) if revision_id else None
                    recovery_execution = await self._recovery_executor.execute(
                        recovery_decision,
                        revision=revision_for_recovery,
                        contract=contract,
                        project_service=self._project_service(),
                    )
                    self._persist_recovery_execution(workflow, recovery_execution.to_record())
                    if recovery_execution.semantic_result:
                        semantic_result = complete_executable_semantic_coverage(
                            recovery_execution.semantic_result,
                            contract,
                        )
                        if semantic_result.get("status") == "passed" and revision_for_recovery is not None:
                            self.sync_outputs(workflow, revision_for_recovery)
                            self._merge_verification(workflow, semantic_result)
                            self._record_executable_provenance(
                                workflow,
                                attempt_count=attempt_count,
                                history=history,
                                source_hash=previous_source_hash,
                                semantic_result=semantic_result,
                            )
                            self.db.commit()
                            return self.read(workflow.id)
                if attempt_count >= AUTOMATIC_PROVIDER_OPERATION_BUDGET:
                    terminal_reason = recovery_decision.terminal_reason or "operation_budget_exhausted"
                elif recovery_decision.recommended_action == "require_review":
                    terminal_reason = recovery_decision.terminal_reason
                elif recovery_execution is not None and recovery_execution.executed:
                    terminal_reason = recovery_decision.terminal_reason or "recovery_action_did_not_resolve_failure"
                else:
                    terminal_reason = recovery_decision.terminal_reason or "recovery_action_requires_execution_adapter"
                self._record_executable_provenance(
                    workflow,
                    attempt_count=attempt_count,
                    history=history,
                    source_hash=previous_source_hash,
                    semantic_result=semantic_result,
                    terminal_reason=terminal_reason,
                )
                if workflow.revision_id is None and revision_id:
                    revision = self.db.get(Revision, revision_id)
                    if revision is not None:
                        self.sync_outputs(workflow, revision)
                if revision_id:
                    self._merge_verification(workflow, semantic_result)
                workflow.failure_boundary = failure_boundary
                diagnostics = _json_dict(workflow.diagnostics_json)
                diagnostics.update(
                    {
                        "kind": failure_class,
                        "message": self._safe_failure_message(failure_class),
                        "first_incorrect_boundary": failure_boundary,
                        "repair_level": recovery_decision.repair_level or decision_level,
                        "repair_progress": progress.get("progress_result"),
                        "recovery_action": recovery_decision.recommended_action,
                        "recovery_terminal": recovery_decision.terminal,
                        "recovery_terminal_reason": recovery_decision.terminal_reason,
                        "diagnostic": diagnostic,
                        "raw_response_hash": provider_attempt.get("raw_response_hash"),
                        "extracted_source_hash": current_source_hash,
                        "extraction_succeeded": extraction_succeeded,
                        "syntax_valid": syntax_valid,
                        "source_contract_valid": source_contract_valid,
                    }
                )
                workflow.diagnostics_json = json.dumps(diagnostics, sort_keys=True, default=str)
                if workflow.state not in {"candidate_ready", "revision_ready"}:
                    workflow.state = "verification_failed" if failure_boundary in {"topology", "semantic"} else "failed"
                workflow.state_version += 1
                self.db.commit()
                return self.read(workflow.id)
            level = recovery_decision.repair_level or decision_level
            repair_ordinals[level] = repair_ordinals.get(level, 0) + 1

        raise ValueError("executable provider operation budget exhausted")

    def _materialize_contract(
        self,
        project_id: str,
        workflow_id: str,
        *,
        ordinal: int,
        prompt: str,
    ) -> dict[str, Any]:
        if settings.executable_cadquery_corpus_manifest_path is not None:
            _corpus_project_id, contract = load_repeatability_contract(
                settings.executable_cadquery_corpus_manifest_path,
                prompt=prompt,
            )
        else:
            contract = deepcopy(FROZEN_MOUNTING_BRACKET_CONTRACT)
        contract.update(
            {
                "project_id": project_id,
                "workflow_id": workflow_id,
                "revision_id": f"{workflow_id}:candidate:{ordinal}",
            }
        )
        return validate_executable_cadquery_design_contract(contract)

    def _revision_contract(
        self,
        previous: Mapping[str, Any],
        *,
        project_id: str,
        workflow_id: str,
        payload: ValidatedBoundedRevision,
    ) -> dict[str, Any]:
        contract = deepcopy(dict(previous))
        contract.update(
            {
                "project_id": project_id,
                "workflow_id": workflow_id,
                "revision_id": f"{workflow_id}:candidate:revision",
            }
        )
        width, depth = _extract_pocket_dimensions(payload)
        for requirement in contract.get("requirements", []):
            if not isinstance(requirement, dict) or requirement.get("requirement_id") != "centered_recessed_pocket":
                continue
            expected = requirement.get("expected")
            if isinstance(expected, dict):
                if width is not None:
                    expected["width"] = width
                if depth is not None:
                    expected["depth"] = depth
        return validate_executable_cadquery_design_contract(contract)

    @staticmethod
    def _execution_plan(contract: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "executable-cadquery-execution-plan-v1",
            "printable_outputs": [
                {
                    "id": item["output_id"],
                    "label": item["output_id"].replace("_", " ").title(),
                    "component_id": item["output_id"],
                    "component_ids": [item["output_id"]],
                    "entrypoint": item["output_id"],
                    "filename": f"{item['output_id']}.stl",
                    "required": item["required"],
                    "output_type": item["output_type"],
                    "expected_solid_count": item["expected_solid_count"],
                    "allow_disconnected_solids": False,
                }
                for item in contract.get("outputs", [])
                if isinstance(item, Mapping)
            ],
            "semantic_contract": deepcopy(dict(contract)),
        }

    @staticmethod
    def _next_repair_level(boundary: str) -> str:
        return {
            "provider_response": "L0",
            "source_contract": "L0",
            "execution": "L1",
            "topology": "L2",
            "semantic": "L3",
            "protected_facts": "L3",
            "artifact": "L1",
        }.get(boundary, "L1")

    def _source_for_revision(self, revision_id: str | None) -> str | None:
        if not revision_id:
            return None
        revision = self.db.get(Revision, revision_id)
        if revision is None:
            return None
        path = self._resolve_optional(revision.source_path)
        return path.read_text(encoding="utf-8") if path is not None else None

    @staticmethod
    def _set_semantic_block(output: Any, semantic: dict[str, Any]) -> None:
        summary = _json_dict(output.validation_summary_json)
        summary.update(
            {
                "blocking_count": 1,
                "executable_semantic": semantic,
            }
        )
        output.validation_summary_json = json.dumps(summary, sort_keys=True)

    @staticmethod
    def _merge_verification(workflow: ValidatedCadQueryWorkflow, semantic: dict[str, Any]) -> None:
        verification = _json_dict(workflow.verification_json)
        verification["semantic_verification"] = semantic
        verification["candidate_policy"] = derive_candidate_policy(
            outputs=[
                {
                    "output_id": output.output_id,
                    "required": output.required,
                    "state": output.state,
                    "worker_status": output.worker_status,
                    "topology_status": output.topology_status,
                    "artifact_available": output.artifact_available,
                }
                for output in workflow.outputs
            ],
            semantic_verification=semantic,
        )
        workflow.verification_json = json.dumps(verification, sort_keys=True)

    @staticmethod
    def _json(raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _record_executable_provenance(
        self,
        workflow: ValidatedCadQueryWorkflow,
        *,
        attempt_count: int,
        history: list[dict[str, Any]],
        source_hash: str | None,
        semantic_result: dict[str, Any],
        terminal_reason: str | None = None,
    ) -> None:
        provenance = self._json(workflow.provenance_json)
        provenance.update(
            {
                "source_hash": source_hash,
                "automatic_provider_operation_count": attempt_count,
                "automatic_provider_operation_budget": 9,
                "source_dialect_version": CADQUERY_V1_SOURCE_DIALECT_VERSION,
                "source_dialect_hash": cadquery_v1_source_dialect_hash(),
                "source_skeleton_hash": cadquery_v1_source_skeleton_hash(),
                "repair_history": history,
                "semantic_verification": semantic_result,
            }
        )
        if terminal_reason:
            provenance["terminal_reason"] = terminal_reason
        workflow.provenance_json = json.dumps(provenance, sort_keys=True, default=str)

    @staticmethod
    def _persist_recovery_decision(
        workflow: ValidatedCadQueryWorkflow,
        decision: RecoveryDecision,
    ) -> None:
        """Persist a router decision before its executor is invoked.

        The router remains side-effect free.  This orchestrator method is the
        durable boundary: callers commit the workflow transaction before
        dispatching any provider, worker, verifier, exporter, or preview work.
        """

        record = decision.to_record()
        provenance = _json_dict(workflow.provenance_json)
        history = provenance.get("recovery_decisions")
        if not isinstance(history, list):
            history = []
        history.append(record)
        provenance["recovery_decisions"] = history
        workflow.provenance_json = json.dumps(provenance, sort_keys=True, default=str)

        diagnostics = _json_dict(workflow.diagnostics_json)
        diagnostics["latest_recovery_decision"] = record
        workflow.diagnostics_json = json.dumps(diagnostics, sort_keys=True, default=str)

    @staticmethod
    def _persist_recovery_execution(
        workflow: ValidatedCadQueryWorkflow,
        record: dict[str, Any],
    ) -> None:
        provenance = _json_dict(workflow.provenance_json)
        executions = provenance.get("recovery_executions")
        if not isinstance(executions, list):
            executions = []
        executions.append(record)
        provenance["recovery_executions"] = executions
        workflow.provenance_json = json.dumps(provenance, sort_keys=True, default=str)

    @staticmethod
    def _safe_failure_message(failure_class: str) -> str:
        messages = {
            "provider_response_contract_failure": "Gemini did not return a compatible complete-source response.",
            "response_empty_or_extraction_failure": "Gemini did not return one complete Python module.",
            "authentication_failure": "Gemini authentication failed before source generation.",
            "missing_provider_credentials": "Gemini credentials are not configured.",
            "python_syntax_error": "The generated source did not satisfy the executable CadQuery source contract.",
            "source_contract_violation": "The generated source did not satisfy the executable CadQuery source contract.",
            "cadquery_api_error": "The CAD worker could not execute the generated source.",
            "worker_timeout": "The CAD worker did not finish within the bounded operation.",
            "solid_count_mismatch": "The final geometry did not satisfy the required solid count.",
            "semantic_requirement_failed": "Final geometry did not satisfy one or more design requirements.",
            "semantic_requirement_unverifiable": "Final geometry could not prove one or more design requirements.",
            "repair_budget_exhausted": "The bounded repair budget was exhausted without a verified candidate.",
        }
        return messages.get(failure_class, "The executable CadQuery operation did not produce a verified candidate.")


def _extract_pocket_dimensions(payload: ValidatedBoundedRevision) -> tuple[float | None, float | None]:
    values = {str(key).lower(): value for key, value in payload.dimension_changes.items()}
    width = _number(values.get("pocket_width") or values.get("pocket_width_mm"))
    depth = _number(values.get("pocket_depth") or values.get("pocket_depth_mm"))
    match = re.search(r"(\d+(?:\.\d+)?)\s*mm\s*[×x]\s*(\d+(?:\.\d+)?)\s*mm", payload.instruction)
    if match:
        width = width or float(match.group(1))
        depth = depth or float(match.group(2))
    return width, depth


def complete_executable_semantic_coverage(
    semantic_result: Mapping[str, Any],
    design_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply the authoritative semantic policy to verifier evidence."""

    return evaluate_semantic_policy(semantic_result, design_contract)


def _number(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _json_dict(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}
