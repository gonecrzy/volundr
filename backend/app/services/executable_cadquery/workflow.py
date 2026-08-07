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

    def accept_candidate(
        self,
        workflow_id: str,
        *,
        idempotency_key: str | None = None,
    ):
        """Accept through the existing service and recover package creation once.

        Package creation remains owned by ``ValidatedCadQueryWorkflowService``;
        this override only records and routes a package-service failure before
        asking that existing service to retry it.
        """

        super().accept_candidate(workflow_id, idempotency_key=idempotency_key)
        workflow = self._get(workflow_id)
        if workflow is not None and self._package_generation_failed(workflow):
            self._recover_package_generation(workflow)
        return self.read(workflow_id)

    def create_package(
        self,
        workflow_id: str,
        *,
        idempotency_key: str | None = None,
    ):
        """Retry package generation through the durable recovery decision."""

        workflow = self._get(workflow_id)
        if workflow is None:
            raise LookupError("validated workflow not found")
        if self._package_generation_failed(workflow):
            self._recover_package_generation(workflow)
            return self.read(workflow_id)
        try:
            return super().create_package(workflow_id, idempotency_key=idempotency_key)
        except Exception as exc:
            workflow = self._get(workflow_id)
            if workflow is None:
                raise
            self._recover_package_generation(workflow, error=exc)
            return self.read(workflow_id)

    def _package_generation_failed(self, workflow: ValidatedCadQueryWorkflow) -> bool:
        return (
            self._resolve_optional(workflow.package_path) is None
            and self._json(workflow.diagnostics_json).get("kind") == "package_generation"
        )

    def _recover_package_generation(
        self,
        workflow: ValidatedCadQueryWorkflow,
        *,
        error: Exception | None = None,
    ) -> None:
        if self._resolve_optional(workflow.package_path) is not None:
            return
        diagnostics = self._json(workflow.diagnostics_json)
        prior = diagnostics.get("latest_recovery_decision")
        prior_observation = prior.get("observation") if isinstance(prior, Mapping) else None
        prior_failure = (
            prior_observation.get("failure_class")
            if isinstance(prior_observation, Mapping)
            else None
        )
        prior_attempt = (
            int(prior_observation.get("attempt_ordinal") or 0)
            if isinstance(prior_observation, Mapping)
            else 0
        )
        attempt_ordinal = prior_attempt + 1 if prior_failure == "package_generation_failure" else 1
        observation = FailureObservation(
            observed_stage="package_generation",
            failure_class="package_generation_failure",
            evidence={
                "package_available": False,
                "package_valid": False,
                "package_diagnostic": safe_diagnostic(str(error)) if error else diagnostics.get("message"),
            },
            attempt_ordinal=attempt_ordinal,
        )
        decision = self._recovery_router.route(observation)
        self._persist_recovery_decision(workflow, decision)
        self.db.commit()
        if decision.terminal or decision.recommended_action != "retry_stage":
            workflow.state = "failed"
            workflow.state_version += 1
            self.db.commit()
            return

        execution_record = {
            "action": decision.recommended_action,
            "executed": False,
            "provider_calls": 0,
            "worker_calls": 0,
            "diagnostic": None,
            "package_available": False,
        }
        self._persist_recovery_execution(workflow, execution_record)
        self.db.commit()
        revision = self.db.get(Revision, workflow.revision_id) if workflow.revision_id else None
        try:
            self._create_package(workflow, revision)
            execution_record["executed"] = True
            execution_record["package_available"] = self._resolve_optional(workflow.package_path) is not None
            self._replace_last_recovery_execution(workflow, execution_record)
            workflow.state = "candidate_ready"
            workflow.state_version += 1
            self.db.commit()
            return
        except Exception as exc:
            execution_record["executed"] = True
            execution_record["diagnostic"] = safe_diagnostic(str(exc))
            self._replace_last_recovery_execution(workflow, execution_record)
            self.db.commit()

        terminal_observation = FailureObservation(
            observed_stage="package_generation",
            failure_class="package_generation_failure",
            evidence={
                "package_available": False,
                "package_valid": False,
                "package_diagnostic": execution_record["diagnostic"],
            },
            attempt_ordinal=decision.attempt_ordinal + 1,
        )
        terminal_decision = self._recovery_router.route(terminal_observation)
        self._persist_recovery_decision(workflow, terminal_decision)
        workflow.state = "failed"
        workflow.state_version += 1
        self.db.commit()

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

    async def recover_persisted_execution_failure(
        self,
        workflow_id: str,
        *,
        idempotency_key: str | None = None,
        provider_operation_limit: int = 1,
    ):
        """Resume a durable worker failure through the existing repair ladder.

        The persisted worker manifest is the observation.  This method owns
        the orchestration boundary: it records the router decision and a
        dispatch checkpoint before allowing the provider ladder to run.  The
        router itself remains policy-only, and the parent source/contract are
        passed unchanged to the existing complete-source repair path.
        """

        self.require_enabled()
        if provider_operation_limit < 1:
            raise ValueError("provider_operation_limit must be positive")
        workflow = self._get(workflow_id)
        if workflow is None:
            raise LookupError("validated workflow not found")
        latest_revision_id = self._latest_persisted_revision_id(workflow)
        if latest_revision_id is None:
            raise ValueError("persisted execution recovery requires a revision")
        revision = self.db.get(Revision, latest_revision_id)
        if revision is None:
            raise ValueError("persisted execution recovery revision not found")
        workflow.revision_id = revision.id
        provenance = self._json(workflow.provenance_json)
        contract_payload = provenance.get("executable_design_contract")
        if not isinstance(contract_payload, Mapping):
            raise ValueError("persisted execution recovery requires a durable design contract")
        contract = validate_executable_cadquery_design_contract(deepcopy(dict(contract_payload)))
        persisted_failure = self._persisted_worker_failure(revision)
        diagnostics = self._persisted_worker_diagnostics(revision)
        if persisted_failure is None or not diagnostics:
            raise ValueError("persisted execution recovery requires structured worker failure evidence")
        failure_boundary, failure_class = persisted_failure
        operation_payload = {
            "workflow_id": workflow.id,
            "revision_id": revision.id,
            "source_hash": revision.source_hash,
            "provider_operation_limit": provider_operation_limit,
        }
        operation = self._begin_operation(
            "recover_persisted_execution_failure",
            idempotency_key,
            operation_payload,
            project_id=workflow.project_id,
            workflow_id=workflow.id,
        )
        if operation.status in {"completed", "failed"}:
            return self.read(workflow.id)

        operation_id = str(operation.id)
        existing_execution = next(
            (
                item
                for item in provenance.get("recovery_executions", [])
                if isinstance(item, Mapping) and item.get("operation_id") == operation_id
            ),
            None,
        )
        if isinstance(existing_execution, Mapping) and existing_execution.get("status") == "dispatching":
            # A process may have stopped after the external call was
            # dispatched but before its result was committed.  Do not issue a
            # second provider operation on restart; the durable record is the
            # safe handoff point for later reconciliation.
            return self.read(workflow.id)
        reuse_ready_execution = (
            isinstance(existing_execution, Mapping)
            and existing_execution.get("status") == "ready_to_dispatch"
        )

        seed, comparison_facts = self._build_persisted_execution_seed(
            revision=revision,
            failure_boundary=failure_boundary,
            failure_class=failure_class,
            diagnostics=diagnostics,
        )
        matching_attempts = [
            item
            for item in provenance.get("recovery_decisions", [])
            if isinstance(item, Mapping)
            and isinstance(item.get("observation"), Mapping)
            and item["observation"].get("failure_class") == failure_class
            and item.get("recommended_action") != "require_review"
            and item.get("terminal") is not True
            and (
                not isinstance(item["observation"].get("evidence"), Mapping)
                or not item["observation"]["evidence"].get("source_hash")
                or item["observation"]["evidence"].get("source_hash")
                == revision.source_hash
            )
        ]
        prior_attempt_ordinal = len(matching_attempts)
        existing_decision = next(
            (
                item
                for item in provenance.get("recovery_decisions", [])
                if isinstance(item, Mapping)
                and isinstance(item.get("observation"), Mapping)
                and isinstance(item["observation"].get("evidence"), Mapping)
                and item["observation"]["evidence"].get("recovery_operation_id")
                == operation_id
            ),
            None,
        )
        if reuse_ready_execution and not isinstance(existing_decision, Mapping):
            raise ValueError("persisted recovery dispatch checkpoint has no router decision")
        if isinstance(existing_decision, Mapping):
            prior_attempt_ordinal = int(
                existing_decision["observation"].get("attempt_ordinal") or prior_attempt_ordinal
            )
        observation = FailureObservation(
            observed_stage=self._recovery_router.earliest_stage(
                failure_boundary,
                failure_class,
            ),
            failure_class=failure_class,
            evidence={
                **comparison_facts,
                "failure_boundary": failure_boundary,
                "normalized_error": seed["normalized_error"],
                "diagnostic": diagnostics,
                "recovery_operation_id": operation_id,
            },
            attempt_ordinal=prior_attempt_ordinal + 1,
            progress=seed["progress"],
        )
        decision = self._recovery_router.route(observation)
        workflow.failure_boundary = failure_boundary
        if reuse_ready_execution:
            execution_record = dict(existing_execution)
        else:
            self._persist_recovery_decision(workflow, decision)
            execution_record = {
                "operation_id": operation_id,
                "action": decision.recommended_action,
                "status": "ready_to_dispatch",
                "executed": False,
                "provider_calls": 0,
                "worker_calls": 0,
                "diagnostic": seed["diagnostic"],
                "source_hash": revision.source_hash,
                "restart_stage": decision.restart_stage,
                "invalidates": list(decision.invalidates),
            }
            self._persist_recovery_execution(workflow, execution_record)
        operation.status = "running"
        self.db.commit()

        provider_actions = {
            "gemini_contract_repair",
            "gemini_execution_repair",
            "gemini_topology_repair",
            "gemini_semantic_repair",
        }
        if decision.terminal:
            execution_record["status"] = "terminal"
            execution_record["executed"] = False
            self._replace_last_recovery_execution(workflow, execution_record)
            operation.status = "failed"
            workflow.state = "failed"
            workflow.state_version += 1
            self.db.commit()
            return self.read(workflow.id)

        if decision.recommended_action not in provider_actions:
            # Persisted recovery can observe a worker-owned failure after a
            # provider repair.  Route that decision through the existing
            # worker/verifier executor before considering another provider
            # operation; the router remains policy-only.
            execution_record["status"] = "dispatching"
            execution_record["executed"] = True
            self._replace_last_recovery_execution(workflow, execution_record)
            self.db.commit()
            try:
                recovery_execution = await self._recovery_executor.execute(
                    decision,
                    revision=revision,
                    contract=contract,
                    project_service=self._project_service(),
                )
                execution_record.update(recovery_execution.to_record())
                execution_record["status"] = (
                    "completed" if recovery_execution.executed else "failed"
                )
                self._replace_last_recovery_execution(workflow, execution_record)
                self.db.commit()
            except Exception as exc:
                execution_record["status"] = "failed"
                execution_record["diagnostic"] = safe_diagnostic(str(exc))
                self._replace_last_recovery_execution(workflow, execution_record)
                operation.status = "failed"
                workflow.state = "failed"
                workflow.state_version += 1
                self.db.commit()
                raise

            if not recovery_execution.executed:
                operation.status = "failed"
                workflow.state = "failed"
                workflow.state_version += 1
                self.db.commit()
                return self.read(workflow.id)

            reevaluation = self._reevaluate_revision_evidence(revision, contract)
            execution_record["reevaluation"] = reevaluation["record"]
            self._replace_last_recovery_execution(workflow, execution_record)
            self.db.commit()
            if reevaluation["status"] == "passed":
                self._clear_semantic_blocks(revision)
                self.sync_outputs(workflow, revision)
                self._merge_verification(workflow, reevaluation["semantic_result"])
                provenance = self._json(workflow.provenance_json)
                history = provenance.get("repair_history")
                history = list(history) if isinstance(history, list) else []
                history.append(
                    {
                        "operation_id": operation_id,
                        "attempt_number": decision.attempt_ordinal,
                        "repair_level": decision.repair_level,
                        "failure_boundary": None,
                        "failure_class": None,
                        "source_hash": reevaluation["source_hash"],
                        "result_hash": reevaluation["result_hash"],
                        "recovery_action": decision.recommended_action,
                        "progress": {"measurable_progress": True},
                    }
                )
                self._record_executable_provenance(
                    workflow,
                    attempt_count=int(
                        provenance.get("automatic_provider_operation_count") or 0
                    ),
                    history=history,
                    source_hash=reevaluation["source_hash"],
                    semantic_result=reevaluation["semantic_result"],
                    provider_budget=int(
                        provenance.get("automatic_provider_operation_budget")
                        or AUTOMATIC_PROVIDER_OPERATION_BUDGET
                    ),
                )
                operation.status = "completed"
                self.db.commit()
                return self.read(workflow.id)

            recheck_facts = dict(reevaluation["comparison_facts"])
            same_source_hash = recheck_facts.get("extracted_source_hash") == seed["source_hash"]
            same_error_state = (
                bool(seed.get("normalized_error"))
                and seed.get("normalized_error") == reevaluation.get("normalized_error")
            )
            recheck_facts["same_source_hash"] = same_source_hash
            recheck_facts["same_error_state"] = same_error_state
            recheck_progress = compare_executable_progress(
                decision.repair_level or "L1",
                previous=comparison_facts,
                current=recheck_facts,
            )
            recheck_progress["same_source_hash"] = same_source_hash
            recheck_progress["same_error_state"] = same_error_state
            next_observation = FailureObservation(
                observed_stage=self._recovery_router.earliest_stage(
                    reevaluation["failure_boundary"],
                    reevaluation["failure_class"],
                ),
                failure_class=reevaluation["failure_class"],
                evidence={
                    **recheck_facts,
                    "failure_boundary": reevaluation["failure_boundary"],
                    "normalized_error": reevaluation["normalized_error"],
                    "diagnostic": reevaluation["diagnostic"],
                },
                attempt_ordinal=decision.attempt_ordinal + 1,
                progress=recheck_progress,
            )
            next_decision = self._recovery_router.route(next_observation)
            self._persist_recovery_decision(workflow, next_decision)
            provenance = self._json(workflow.provenance_json)
            history = provenance.get("repair_history")
            history = list(history) if isinstance(history, list) else []
            history.append(
                {
                    "operation_id": f"{operation_id}:recheck",
                    "attempt_number": decision.attempt_ordinal,
                    "repair_level": next_decision.repair_level or decision.repair_level,
                    "failure_boundary": reevaluation["failure_boundary"],
                    "failure_class": reevaluation["failure_class"],
                    "source_hash": reevaluation["source_hash"],
                    "result_hash": reevaluation["result_hash"],
                    "raw_response_hash": None,
                    "provider_attempt": {},
                    "normalized_error": reevaluation["normalized_error"],
                    "worker_result": reevaluation["worker_result"],
                    "topology_result": reevaluation["topology_result"],
                    "semantic_result": reevaluation["semantic_result"],
                    "diagnostic": reevaluation["diagnostic"],
                    "progress": recheck_progress,
                    "revision_id": revision.id,
                    "recovery_action": decision.recommended_action,
                }
            )
            self._record_executable_provenance(
                workflow,
                attempt_count=int(
                    provenance.get("automatic_provider_operation_count") or 0
                ),
                history=history,
                source_hash=reevaluation["source_hash"],
                semantic_result=reevaluation["semantic_result"],
                terminal_reason=next_decision.terminal_reason,
                provider_budget=int(
                    provenance.get("automatic_provider_operation_budget")
                    or AUTOMATIC_PROVIDER_OPERATION_BUDGET
                ),
            )
            workflow.failure_boundary = reevaluation["failure_boundary"]
            diagnostics = self._json(workflow.diagnostics_json)
            diagnostics.update(
                {
                    "kind": reevaluation["failure_class"],
                    "message": safe_diagnostic(
                        str(
                            reevaluation["normalized_error"]
                            or reevaluation["diagnostic"].get("message")
                            or "Executable recovery did not resolve the failure."
                        )
                    ),
                    "latest_recovery_decision": next_decision.to_record(),
                }
            )
            workflow.diagnostics_json = json.dumps(diagnostics, sort_keys=True)
            workflow.state = "failed"
            workflow.state_version += 1
            operation.status = "completed"
            self.db.commit()
            return self.read(workflow.id)

        execution_record["status"] = "dispatching"
        execution_record["executed"] = True
        execution_record["provider_calls"] = 1
        self._replace_last_recovery_execution(workflow, execution_record)
        self.db.commit()
        self._active_workflow_id = workflow.id
        try:
            result = await self._generate_with_repair_ladder(
                workflow,
                contract,
                requested_delta=None,
                parent_revision_id=revision.id,
                starting_level=decision.repair_level or "L1",
                initial_history=[seed],
                initial_comparison_facts=comparison_facts,
                provider_operation_limit=provider_operation_limit,
            )
            execution_record["status"] = "completed"
            self._replace_last_recovery_execution(workflow, execution_record)
            operation.status = "completed"
            self.db.commit()
            return result
        except Exception as exc:
            execution_record["status"] = "failed"
            execution_record["diagnostic"] = safe_diagnostic(str(exc))
            self._replace_last_recovery_execution(workflow, execution_record)
            operation.status = "failed"
            self.db.commit()
            raise

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
        candidate_outputs = [
            {
                "output_id": output.output_id,
                "required": output.required,
                "state": output.state,
                "worker_status": output.worker_status,
                "topology_status": output.topology_status,
                "artifact_available": output.artifact_available,
            }
            for output in workflow.outputs
        ]
        package_path = self._resolve_optional(workflow.package_path)
        artifact_evidence = {
            "package_required": True,
            "package_available": package_path is not None,
            "valid": None if package_path is None else self._package_is_safe(package_path),
        }
        pre_review_candidate = derive_candidate_policy(
            outputs=candidate_outputs,
            semantic_verification=semantic,
            artifacts=artifact_evidence,
        )
        verification["independent_final_review"] = review
        verification["candidate_policy"] = derive_candidate_policy(
            outputs=candidate_outputs,
            semantic_verification=semantic,
            artifacts=artifact_evidence,
            independent_review={"verdict": review.get("final_verdict")},
        )
        workflow.verification_json = json.dumps(verification, sort_keys=True, default=str)
        diagnostics = self._json(workflow.diagnostics_json)
        diagnostics["latest_independent_review"] = review
        if verdict == "FAIL" and not pre_review_candidate.get("blockers"):
            failed_requirement_ids = [
                str(item.get("requirement_id"))
                for item in review.get("requirements", [])
                if isinstance(item, Mapping)
                and item.get("requirement_id")
                and str(item.get("verdict") or "").casefold()
                in {"fail", "failed", "violated"}
            ]
            recovery_observation = FailureObservation(
                observed_stage="independent_final_review",
                failure_class="semantic_requirement_failed",
                evidence={
                    "failed_requirement_ids": failed_requirement_ids,
                    "measurement_available": bool(failed_requirement_ids),
                    "review_cycle": review_cycle,
                    "reviewer": review["reviewer"],
                },
                attempt_ordinal=review_cycle,
            )
            recovery_decision = self._recovery_router.route(recovery_observation)
            self._persist_recovery_decision(workflow, recovery_decision)
            diagnostics["review_recovery_decision"] = recovery_decision.to_record()
            workflow.failure_boundary = recovery_decision.observed_stage
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
        initial_history: list[dict[str, Any]] | None = None,
        initial_comparison_facts: Mapping[str, Any] | None = None,
        provider_operation_limit: int | None = None,
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
        history: list[dict[str, Any]] = deepcopy(initial_history or [])
        level = starting_level
        repair_ordinals = {"L0": 0, "L1": 0, "L2": 0, "L3": 0, "L4": 1 if starting_level == "L4" else 0}
        for item in history:
            repair_level = str(item.get("repair_level") or "")
            if repair_level in repair_ordinals:
                repair_ordinals[repair_level] = max(
                    repair_ordinals[repair_level],
                    sum(
                        1
                        for prior in history
                        if str(prior.get("repair_level") or "") == repair_level
                    ),
                )
        if starting_level != "initial" and repair_ordinals.get(starting_level, 0) == 0:
            repair_ordinals[starting_level] = 1
        previous_failure_class: str | None = None
        previous_comparison_facts: dict[str, Any] = dict(initial_comparison_facts or {})
        if history:
            previous_normalized_error = history[-1].get("normalized_error") or previous_normalized_error
            previous_result_hash = history[-1].get("result_hash") or previous_result_hash
            previous_failure_class = history[-1].get("failure_class")
        attempt_count = 0
        provider_budget = AUTOMATIC_PROVIDER_OPERATION_BUDGET
        if provider_operation_limit is not None:
            if provider_operation_limit < 1:
                raise ValueError("provider_operation_limit must be positive")
            provider_budget = min(provider_budget, provider_operation_limit)

        while attempt_count < provider_budget:
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
            if envelope is not None:
                # Keep the exact fact envelope beside the durable attempt
                # record so a restart/audit can prove what the provider saw.
                # It contains source, contract, and neutral measurements only;
                # credentials are owned exclusively by the transport.
                provider_attempt["repair_envelope"] = envelope
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
                workflow.revision_id = revision.id
                output = next(iter(revision.outputs), None)
                worker_result = {
                    "phase": "completed" if revision.status == "succeeded" else "failed",
                    "output_ids": [item.output_id for item in revision.outputs],
                    "revision_id": revision.id,
                    "execution_diagnostics": self._persisted_worker_diagnostics(revision),
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
                persisted_worker_failure = self._persisted_worker_failure(revision)
                topology_invalid = topology_result.get("valid") is False
                if persisted_worker_failure is not None:
                    failure_boundary, failure_class = persisted_worker_failure
                    worker_diagnostics = self._persisted_worker_diagnostics(revision)
                    provider_attempt["diagnostic"] = worker_diagnostics
                    normalized_error = safe_diagnostic(
                        str(
                            worker_diagnostics.get("failure_message")
                            or worker_diagnostics.get("message")
                            or ""
                        )
                    ) or None
                elif topology_invalid:
                    failure_boundary = "topology"
                    topology_evidence = topology_result
                    if len(topology_by_output) == 1:
                        topology_evidence = next(iter(topology_by_output.values()), topology_result)
                    failure_class = classify_executable_failure("topology", topology_evidence)
                elif output is None or len(stl_paths) != len(revision.outputs):
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
                            provider_budget=provider_budget,
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
                    for key in (
                        "code",
                        "line",
                        "column",
                        "node_type",
                        "enclosing_scope",
                        "message",
                        "active_phase",
                        "failure_phase",
                        "failure_operation",
                        "failure_exception_type",
                        "failure_message",
                        "failure_source_function",
                        "failure_source_line",
                    )
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
                    "repair_envelope": envelope,
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
            if not can_execute_provider_repair or attempt_count >= provider_budget:
                recovery_execution = None
                if not can_execute_provider_repair and not recovery_decision.terminal:
                    revision_for_recovery = self.db.get(Revision, revision_id) if revision_id else None
                    recovery_execution = await self._recovery_executor.execute(
                        recovery_decision,
                        revision=revision_for_recovery,
                        contract=contract,
                        project_service=self._project_service(),
                    )
                    execution_record = recovery_execution.to_record()
                    self._persist_recovery_execution(workflow, execution_record)
                    # The existing worker/verifier operation commits its own
                    # result. Commit the durable execution record before
                    # asking the recovery router to inspect that result.
                    self.db.commit()
                    if (
                        recovery_execution.executed
                        and recovery_decision.recommended_action != "require_review"
                        and revision_for_recovery is not None
                    ):
                        reevaluation = self._reevaluate_revision_evidence(
                            revision_for_recovery,
                            contract,
                        )
                        execution_record["reevaluation"] = reevaluation["record"]
                        self._replace_last_recovery_execution(workflow, execution_record)
                        self.db.commit()
                        semantic_result = reevaluation["semantic_result"]
                        if reevaluation["status"] == "passed":
                            self._clear_semantic_blocks(revision_for_recovery)
                            self.sync_outputs(workflow, revision_for_recovery)
                            self._merge_verification(workflow, semantic_result)
                            self._record_executable_provenance(
                                workflow,
                                attempt_count=attempt_count,
                                history=history,
                                source_hash=previous_source_hash,
                                semantic_result=semantic_result,
                                provider_budget=provider_budget,
                            )
                            self.db.commit()
                            return self.read(workflow.id)

                        recheck_facts = reevaluation["comparison_facts"]
                        recheck_progress = compare_executable_progress(
                            level if level != "initial" else "L0",
                            previous=previous_comparison_facts,
                            current=recheck_facts,
                        )
                        recheck_facts["no_violation_decrease_streak"] = recheck_progress.get(
                            "no_violation_decrease_streak", 0
                        )
                        next_observation = FailureObservation(
                            observed_stage=self._recovery_router.earliest_stage(
                                reevaluation["failure_boundary"],
                                reevaluation["failure_class"],
                            ),
                            failure_class=reevaluation["failure_class"],
                            evidence={
                                **recheck_facts,
                                "failure_boundary": reevaluation["failure_boundary"],
                                "normalized_error": reevaluation["normalized_error"],
                                "diagnostic": reevaluation["diagnostic"],
                                "semantic_policy": semantic_result.get("policy_summary"),
                            },
                            attempt_ordinal=recovery_decision.attempt_ordinal + 1,
                            progress=recheck_progress,
                        )
                        next_decision = self._recovery_router.route(next_observation)
                        self._persist_recovery_decision(workflow, next_decision)
                        self.db.commit()
                        next_provider_repair = (
                            next_decision.recommended_action in provider_repair_actions
                            and next_decision.repair_level is not None
                            and not next_decision.terminal
                        )
                        history.append(
                            {
                                "operation_id": f"{workflow.id}:recovery-recheck:{attempt_count}",
                                "attempt_number": attempt_count,
                                "repair_level": next_decision.repair_level or level,
                                "failure_boundary": reevaluation["failure_boundary"],
                                "failure_class": reevaluation["failure_class"],
                                "source_hash": reevaluation["source_hash"],
                                "extracted_source_hash": reevaluation["source_hash"],
                                "raw_response_hash": None,
                                "extraction_succeeded": True,
                                "syntax_valid": True,
                                "source_contract_valid": True,
                                "diagnostic": reevaluation["diagnostic"],
                                "result_hash": reevaluation["result_hash"],
                                "provider_attempt": {},
                                "normalized_error": reevaluation["normalized_error"],
                                "worker_result": reevaluation["worker_result"],
                                "topology_result": reevaluation["topology_result"],
                                "semantic_result": semantic_result,
                                "progress": recheck_progress,
                                "revision_id": revision_for_recovery.id,
                                "recovery_action": recovery_decision.recommended_action,
                            }
                        )
                        if next_provider_repair:
                            previous_source = self._source_for_revision(revision_for_recovery.id)
                            previous_source_hash = reevaluation["source_hash"]
                            previous_result_hash = reevaluation["result_hash"]
                            previous_normalized_error = reevaluation["normalized_error"]
                            previous_failure_class = reevaluation["failure_class"]
                            previous_comparison_facts = recheck_facts
                            level = next_decision.repair_level
                            repair_ordinals[level] = repair_ordinals.get(level, 0) + 1
                            recovery_decision = next_decision
                            continue
                        recovery_decision = next_decision
                        failure_boundary = reevaluation["failure_boundary"]
                        failure_class = reevaluation["failure_class"]
                        current_source_hash = reevaluation["source_hash"]
                        current_result_hash = reevaluation["result_hash"]
                        topology_result = reevaluation["topology_result"]
                        diagnostic = reevaluation["diagnostic"]
                        normalized_error = reevaluation["normalized_error"]
                        comparison_facts = recheck_facts
                if attempt_count >= provider_budget:
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
                    provider_budget=provider_budget,
                )
                if revision_id:
                    revision = self.db.get(Revision, revision_id)
                    if revision is not None:
                        workflow.revision_id = revision.id
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
            raise ValueError(
                "executable CadQuery flow requires an explicit persisted design contract"
            )
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

    def _persisted_worker_failure(self, revision: Revision) -> tuple[str, str] | None:
        """Classify the worker's first failed phase before inferring export loss.

        A failed output with no STL is not by itself an export failure: the CAD
        worker may have failed while importing or building the source, or while
        validating topology. The worker's persisted execution manifest is the
        authoritative boundary evidence when it exists.
        """

        manifest_path = self._resolve_optional(getattr(revision, "execution_manifest_path", None))
        if manifest_path is None:
            return None
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        diagnostics = payload.get("diagnostics") if isinstance(payload, Mapping) else None
        if not isinstance(diagnostics, Mapping):
            return None

        phase = str(diagnostics.get("active_phase") or "").lower()
        message = str(
            diagnostics.get("failure_message")
            or diagnostics.get("message")
            or ""
        )
        exception_type = str(diagnostics.get("failure_exception_type") or "")
        if diagnostics.get("timed_out") is True or str(
            diagnostics.get("failure_class") or ""
        ).lower() in {"timeout", "worker_timeout", "cadquery_timeout"}:
            return (
                "execution",
                classify_executable_failure(
                    "execution",
                    {
                        "timed_out": True,
                        "message": safe_diagnostic(message),
                    },
                ),
            )
        if phase in {"build_function", "module_import", "source_execution", "execution"}:
            exception_match = re.search(
                r"\b([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception))\b",
                message,
            )
            evidence = {
                "message": safe_diagnostic(message),
                "exception_type": exception_type or (exception_match.group(1) if exception_match else None),
            }
            return (
                "execution",
                classify_executable_failure("execution", evidence),
            )
        if phase == "topology_analysis":
            per_output = diagnostics.get("per_output_results")
            statuses = (
                [str(item.get("status") or "").lower() for item in per_output.values()]
                if isinstance(per_output, Mapping)
                else []
            )
            if any(status in {"invalid_shape", "solid_count_mismatch"} for status in statuses):
                return (
                    "topology",
                    classify_executable_failure(
                        "topology",
                        {"invalid": True, "message": safe_diagnostic(message)},
                    ),
                )
        if phase in {"artifact_export", "stl_export", "step_export", "artifact"}:
            return (
                "artifact",
                classify_executable_failure(
                    "artifact",
                    {"stl_failure": "stl" in phase, "step_failure": "step" in phase},
                ),
            )
        return None

    def _latest_persisted_revision_id(
        self,
        workflow: ValidatedCadQueryWorkflow,
    ) -> str | None:
        provenance = self._json(workflow.provenance_json)
        history = provenance.get("repair_history")
        if isinstance(history, list):
            for item in reversed(history):
                if not isinstance(item, Mapping) or not item.get("revision_id"):
                    continue
                revision_id = str(item["revision_id"])
                if self.db.get(Revision, revision_id) is not None:
                    return revision_id
        return workflow.revision_id

    @staticmethod
    def _build_persisted_execution_seed(
        *,
        revision: Revision,
        failure_boundary: str,
        failure_class: str,
        diagnostics: Mapping[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Convert persisted worker evidence into the first repair-ladder observation."""

        diagnostic = dict(diagnostics)
        normalized_error = safe_diagnostic(
            str(
                diagnostic.get("failure_message")
                or diagnostic.get("message")
                or ""
            )
        ) or None
        worker_result = {
            "phase": diagnostic.get("failure_phase") or diagnostic.get("active_phase"),
            "output_ids": list(diagnostic.get("completed_output_ids") or []),
            "revision_id": revision.id,
            "execution_diagnostics": diagnostic,
        }
        topology_result: dict[str, Any] = {}
        semantic_result: dict[str, Any] = {}
        diagnostic_signature = json.dumps(
            {
                key: diagnostic.get(key)
                for key in (
                    "active_phase",
                    "failure_phase",
                    "failure_operation",
                    "failure_exception_type",
                    "failure_message",
                    "failure_source_function",
                    "failure_source_line",
                )
            },
            sort_keys=True,
        )
        comparison_facts = {
            "contract_valid": True,
            "extracted_source_hash": revision.source_hash,
            "diagnostic_signature": diagnostic_signature,
            "failure_signature": normalized_error,
            "violation_count": None,
            "syntax_valid": True,
            "phase_index": 0,
            "completed_output_ids": worker_result["output_ids"],
            "valid": None,
            "detected_solid_count": None,
            "expected_solid_count": None,
            "failed_requirement_ids": [],
            "unverifiable_requirement_ids": [],
            "passed_requirement_ids": [],
        }
        seed = {
            "operation_id": f"{revision.id}:persisted-execution-failure",
            "attempt_number": 0,
            "repair_level": "initial",
            "failure_boundary": failure_boundary,
            "failure_class": failure_class,
            "source_hash": revision.source_hash,
            "extracted_source_hash": revision.source_hash,
            "raw_response_hash": None,
            "extraction_succeeded": True,
            "syntax_valid": True,
            "source_contract_valid": True,
            "diagnostic": diagnostic,
            "result_hash": source_result_hash(
                {
                    "worker": worker_result,
                    "topology": topology_result,
                    "semantic": semantic_result,
                }
            ),
            "provider_attempt": {
                "status": "persisted_failure",
                "diagnostic": diagnostic,
            },
            "normalized_error": normalized_error,
            "worker_result": worker_result,
            "topology_result": topology_result,
            "semantic_result": semantic_result,
            "progress": {
                "measurable_progress": False,
                "progress_result": "persisted_failure_observation",
            },
            "revision_id": revision.id,
        }
        return seed, comparison_facts

    def _persisted_worker_diagnostics(self, revision: Revision) -> dict[str, Any]:
        manifest_path = self._resolve_optional(getattr(revision, "execution_manifest_path", None))
        if manifest_path is None:
            return {}
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        diagnostics = payload.get("diagnostics") if isinstance(payload, Mapping) else None
        return dict(diagnostics) if isinstance(diagnostics, Mapping) else {}

    def _reevaluate_revision_evidence(
        self,
        revision: Revision,
        contract: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Recompute downstream evidence after an existing-stage recovery.

        This deliberately reuses the worker's persisted topology/artifact
        records and the existing semantic verifier. It never calls Gemini or
        chooses geometry operations; the caller routes the resulting failure
        back through ``RecoveryRouter``.
        """

        outputs = list(revision.outputs)
        topology_by_output = {
            item.output_id: self._json(item.topology_metadata_json)
            for item in outputs
        }
        if len(topology_by_output) == 1:
            topology_result: dict[str, Any] = next(iter(topology_by_output.values()), {})
        else:
            topology_result = {
                "valid": bool(topology_by_output)
                and all(item.get("valid") is True for item in topology_by_output.values()),
                "outputs": topology_by_output,
                "output_ids": sorted(topology_by_output),
            }
        worker_result = {
            "phase": "completed" if revision.status == "succeeded" else "failed",
            "output_ids": [item.output_id for item in outputs],
            "revision_id": revision.id,
            "execution_diagnostics": self._persisted_worker_diagnostics(revision),
        }
        stl_paths: dict[str, Path] = {}
        for output in outputs:
            if not output.stl_path or not output.step_path:
                continue
            stl_paths[output.output_id] = safe_relative_artifact_path(
                self.data_dir,
                output.stl_path,
            )

        semantic_result: dict[str, Any] = {}
        failure_boundary: str
        failure_class: str
        diagnostic: dict[str, Any] = {}
        normalized_error: str | None = None
        persisted_worker_failure = self._persisted_worker_failure(revision)
        if persisted_worker_failure is not None:
            failure_boundary, failure_class = persisted_worker_failure
            diagnostic = self._persisted_worker_diagnostics(revision)
            normalized_error = safe_diagnostic(
                str(diagnostic.get("failure_message") or diagnostic.get("message") or "")
            ) or None
        elif topology_result.get("valid") is False:
            failure_boundary = "topology"
            topology_evidence: Mapping[str, Any] = topology_result
            for item in topology_by_output.values():
                if item.get("valid") is False:
                    topology_evidence = item
                    break
            failure_class = classify_executable_failure("topology", topology_evidence)
        elif not outputs or len(stl_paths) != len(outputs):
            failure_boundary = "artifact"
            failure_class = classify_executable_failure("artifact", {"stl_failure": True})
        else:
            semantic_result = complete_executable_semantic_coverage(
                evaluate_executable_cadquery_semantics_for_outputs(
                    stl_paths=stl_paths,
                    design_contract=contract,
                ),
                contract,
            )
            if semantic_result.get("status") == "passed":
                return {
                    "status": "passed",
                    "failure_boundary": None,
                    "failure_class": None,
                    "source_hash": self._source_hash_for_revision(revision),
                    "result_hash": source_result_hash(
                        {
                            "worker": worker_result,
                            "topology": topology_result,
                            "semantic": semantic_result,
                        }
                    ),
                    "worker_result": worker_result,
                    "topology_result": topology_result,
                    "semantic_result": semantic_result,
                    "diagnostic": diagnostic,
                    "normalized_error": normalized_error,
                    "comparison_facts": {
                        "contract_valid": True,
                        "extracted_source_hash": self._source_hash_for_revision(revision),
                        "diagnostic_signature": None,
                        "failure_signature": None,
                        "violation_count": None,
                        "syntax_valid": True,
                        "phase_index": 2,
                        "completed_output_ids": worker_result["output_ids"],
                        "valid": topology_result.get("valid"),
                        "detected_solid_count": topology_result.get("detected_solid_count"),
                        "expected_solid_count": topology_result.get("expected_solid_count"),
                        "failed_requirement_ids": [],
                        "unverifiable_requirement_ids": semantic_result.get("unverifiable", []),
                        "passed_requirement_ids": semantic_result.get("passed", []),
                    },
                    "record": {
                        "status": "passed",
                        "source_hash": self._source_hash_for_revision(revision),
                        "result_hash": source_result_hash(
                            {
                                "worker": worker_result,
                                "topology": topology_result,
                                "semantic": semantic_result,
                            }
                        ),
                        "failure_boundary": None,
                        "failure_class": None,
                    },
                }
            failure_boundary = "semantic"
            failure_class = classify_executable_failure(
                "semantic",
                {
                    "failed": semantic_result.get("failed"),
                    "unverifiable": semantic_result.get("unverifiable"),
                },
            )

        source_hash = self._source_hash_for_revision(revision)
        result_hash = source_result_hash(
            {
                "worker": worker_result,
                "topology": topology_result,
                "semantic": semantic_result,
            }
        )
        comparison_facts = {
            "contract_valid": True,
            "extracted_source_hash": source_hash,
            "diagnostic_signature": None,
            "failure_signature": normalized_error,
            "violation_count": diagnostic.get("violation_count"),
            "syntax_valid": True,
            "phase_index": 2 if worker_result.get("phase") == "completed" else 0,
            "completed_output_ids": worker_result.get("output_ids", []),
            "valid": topology_result.get("valid"),
            "detected_solid_count": topology_result.get("detected_solid_count"),
            "expected_solid_count": topology_result.get("expected_solid_count"),
            "failed_requirement_ids": semantic_result.get("failed", []),
            "unverifiable_requirement_ids": semantic_result.get("unverifiable", []),
            "passed_requirement_ids": semantic_result.get("passed", []),
        }
        return {
            "status": "failed",
            "failure_boundary": failure_boundary,
            "failure_class": failure_class,
            "source_hash": source_hash,
            "result_hash": result_hash,
            "worker_result": worker_result,
            "topology_result": topology_result,
            "semantic_result": semantic_result,
            "diagnostic": diagnostic,
            "normalized_error": normalized_error,
            "comparison_facts": comparison_facts,
            "record": {
                "status": "failed",
                "source_hash": source_hash,
                "result_hash": result_hash,
                "failure_boundary": failure_boundary,
                "failure_class": failure_class,
                "failed_requirement_ids": semantic_result.get("failed", []),
            },
        }

    def _source_hash_for_revision(self, revision: Revision) -> str | None:
        source = self._source_for_revision(revision.id)
        return hashlib.sha256(source.encode("utf-8")).hexdigest() if source is not None else revision.source_hash

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
    def _clear_semantic_blocks(revision: Revision) -> None:
        for output in revision.outputs:
            summary = _json_dict(output.validation_summary_json)
            summary.pop("blocking_count", None)
            summary.pop("executable_semantic", None)
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
        provider_budget: int = AUTOMATIC_PROVIDER_OPERATION_BUDGET,
    ) -> None:
        provenance = self._json(workflow.provenance_json)
        provenance.update(
            {
                "source_hash": source_hash,
                "automatic_provider_operation_count": attempt_count,
                "automatic_provider_operation_budget": provider_budget,
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
    def _replace_last_recovery_execution(
        workflow: ValidatedCadQueryWorkflow,
        record: dict[str, Any],
    ) -> None:
        provenance = _json_dict(workflow.provenance_json)
        executions = provenance.get("recovery_executions")
        if not isinstance(executions, list) or not executions:
            executions = [record]
        else:
            executions[-1] = record
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
