"""Deterministic chat-to-workflow orchestration.

This module only routes user intent.  Requirement extraction, planning, CAD
generation, worker execution, and candidate gates remain owned by
``ProjectService``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.design_plan import DesignPlan
from app.models.design_specification import DesignSpecification
from app.models.generation_attempt import GenerationAttempt
from app.models.project import Project
from app.models.project_message import ProjectMessage
from app.models.revision import Revision
from app.models.revision_plan import RevisionPlan
from app.models.validation_finding import ValidationFinding
from app.models.workflow import WorkflowArtifact, WorkflowRun
from app.schemas.project import (
    ChatMessageCreate,
    ChatWorkflowResponse,
    ClarificationAnswersCreate,
    ClarificationAnswerCreate,
    ConfigurationChangeCreate,
    GenerationCreate,
    RequirementExtractionCreate,
    RevisionPlanCreate,
)
from app.services.projects.service import ProjectService
from app.services.projects.requirement_ledger import (
    RequirementLedgerStore,
    active_requirements,
    requirement_delta_for_message,
)


NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


@dataclass(frozen=True)
class RoutedIntent:
    action: str
    parameter_values: dict[str, Any] | None = None


class ChatIntentRouter:
    """Choose safe, deterministic outcomes before any provider call."""

    def __init__(self, service: ProjectService):
        self.service = service

    def classify(self, project: Project, message: str) -> RoutedIntent:
        normalized = message.strip().lower()
        if re.search(r"\b(start over|try a different approach|branch from)", normalized):
            return RoutedIntent("start_over")
        if re.search(r"\b(export|download)\b", normalized):
            return RoutedIntent("export_request")

        if project.active_revision_id is None:
            return RoutedIntent("requirement_answer" if self._waiting_for_clarification(project) else "initial_design")

        if re.search(
            r"\b(?:expose|adjustable|configurable|parametric|parameterized|reusable\s+template|"
            r"let\s+me\s+(?:change|adjust|set|choose))\b",
            normalized,
        ):
            return RoutedIntent("control_request")
        parameter_values = self._parameter_change(project.id, message)
        if parameter_values:
            return RoutedIntent("parameter_change", parameter_values)
        if re.search(
            r"\b(?:too\s+tight|clearance|flex(?:es)?|thicker|reinforce|reinforcement|"
            r"test\s+print|obstruction|broke|cracked|does\s+not\s+seat)\b",
            normalized,
        ):
            return RoutedIntent("structural_revision")
        if re.search(r"\b(lid|snap|strap|drain|hole|mount|retention|component|part)\b", normalized):
            return RoutedIntent("component_revision" if "component" in normalized or "part" in normalized else "structural_revision")
        if re.search(r"\b(?:to|by)\s+(?:\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten)\b", normalized):
            return RoutedIntent("structural_revision")
        if re.search(r"\b(change|move|replace|add|remove|make|set)\b", normalized):
            return RoutedIntent("clarification_needed")
        return RoutedIntent("unsupported")

    def _waiting_for_clarification(self, project: Project) -> bool:
        specification = self.service.get_current_design_specification(project.id)
        if specification is not None and specification.clarification_required:
            return True
        plan = self.service.get_current_design_plan(project.id)
        if plan is not None and plan.clarification_required:
            return True
        revision_plan = self.service.get_current_revision_plan(project.id)
        return revision_plan is not None and revision_plan.clarification_required

    def _parameter_change(self, project_id: str, message: str) -> dict[str, Any]:
        try:
            parameters = self.service.list_configuration_parameters(project_id) or []
            current_plan = self.service.get_current_design_plan(project_id)
        except (ValueError, RuntimeError):
            return {}
        plan_payload = current_plan.plan if current_plan is not None else None
        exposed_ids = None
        if isinstance(plan_payload, dict) and "exposed_controls" in plan_payload:
            exposed_ids = {
                str(control if isinstance(control, str) else control.get("parameter_id"))
                for control in plan_payload.get("exposed_controls", []) or []
                if (isinstance(control, str) and control)
                or (isinstance(control, dict) and control.get("parameter_id"))
            }
            parameters = [parameter for parameter in parameters if parameter.id in exposed_ids]
        match = re.search(r"\bto\s+([a-z0-9_.-]+)", message.lower())
        if match is None:
            return {}
        value = _parse_scalar(match.group(1).rstrip(".,!?"))
        if value is None:
            return {}
        normalized = re.sub(r"[^a-z0-9]+", " ", message.lower()).strip()
        message_words = {_word_root(word) for word in normalized.split()}
        for parameter in parameters:
            label = re.sub(r"[^a-z0-9]+", " ", parameter.label.lower()).strip()
            parameter_id = parameter.id.lower().replace("_", " ")
            label_words = {_word_root(word) for word in label.split() if len(word) > 2}
            parameter_words = {_word_root(word) for word in parameter_id.split() if len(word) > 2}
            if (label and label in normalized) or parameter_id in normalized or message_words.intersection(label_words | parameter_words):
                return {parameter.id: value}
        return {}


def _parse_scalar(value: str) -> int | float | str | bool | None:
    if value in NUMBER_WORDS:
        return NUMBER_WORDS[value]
    if value in {"true", "false"}:
        return value == "true"
    try:
        return int(value) if "." not in value else float(value)
    except ValueError:
        return None


def _word_root(value: str) -> str:
    return value[:-1] if value.endswith("s") and len(value) > 3 else value


class ChatWorkflowService:
    def __init__(self, db: Session, *, data_dir, ai_provider=None, cad_runner=None):
        self.db = db
        self.service = ProjectService(
            db=db,
            data_dir=data_dir,
            ai_provider=ai_provider,
            cad_runner=cad_runner,
        )
        self.requirement_store = RequirementLedgerStore(db)

    async def submit(self, project_id: str, payload: ChatMessageCreate) -> ChatWorkflowResponse:
        project = self.db.get(Project, project_id)
        if project is None:
            raise LookupError("project not found")
        if payload.client_message_id:
            previous = self.db.scalar(
                select(ProjectMessage)
                .where(ProjectMessage.project_id == project_id)
                .where(ProjectMessage.client_message_id == payload.client_message_id)
            )
            if previous is not None and previous.chat_response_json:
                return ChatWorkflowResponse.model_validate(json.loads(previous.chat_response_json))

        if project.status == "draft":
            project.name = _project_name(payload.message)
            project.slug = self.service._unique_slug(project.name, exclude_project_id=project.id)
            project.original_intent = payload.message.strip()
            project.status = "active"

        user_message = ProjectMessage(
            project_id=project.id,
            role="user",
            content=payload.message.strip(),
            client_message_id=payload.client_message_id,
        )
        self.db.add(user_message)
        self.db.flush()
        self._active_user_message_id = user_message.id
        workflow_run = self.service._ensure_initial_workflow_run(project)
        self._event(workflow_run, "chat.message.submitted", "Chat message submitted.", "chat_message_submitted")

        intent = ChatIntentRouter(self.service).classify(project, payload.message)
        self._event(workflow_run, "chat.intent.classified", f"Intent classified as {intent.action}.", "intent_classified", metadata={"action": intent.action})
        try:
            response = await self._dispatch(project, workflow_run, intent, payload.message)
        except (RuntimeError, ValueError) as exc:
            # Generation and source-gate failures are workflow outcomes, not
            # malformed chat requests. Preserve the technical failure in the
            # attempt/workflow records and keep the chat API on its one
            # authoritative response contract.
            response = self._blocked_generation_response(
                project,
                workflow_run,
                action=intent.action,
                error=exc,
            )
        if response.revision_id:
            user_message.revision_id = response.revision_id
            duplicate_revision_message = self.db.scalar(
                select(ProjectMessage)
                .where(ProjectMessage.project_id == project.id)
                .where(ProjectMessage.revision_id == response.revision_id)
                .where(ProjectMessage.role == "user")
                .where(ProjectMessage.content == payload.message.strip())
                .where(ProjectMessage.id != user_message.id)
            )
            if duplicate_revision_message is not None:
                self.db.delete(duplicate_revision_message)
        user_message.chat_response_json = response.model_dump_json()
        self.db.add(
            ProjectMessage(
                project_id=project.id,
                revision_id=response.revision_id or response.current_working_revision_id,
                role=_assistant_message_role(response),
                content=response.assistant_message,
            )
        )
        self.db.commit()
        return response

    def _blocked_generation_response(
        self,
        project: Project,
        workflow_run: WorkflowRun,
        *,
        action: str,
        error: Exception,
    ) -> ChatWorkflowResponse:
        attempt = self.db.scalar(
            select(GenerationAttempt)
            .where(GenerationAttempt.project_id == project.id)
            .order_by(GenerationAttempt.started_at.desc())
        )
        blocked_attempt = {
            "attempt_id": attempt.id if attempt is not None else None,
            "status": attempt.status if attempt is not None else "failed",
            "failure_class": attempt.failure_class if attempt is not None else "workflow_failure",
            "error_message": attempt.error_message if attempt is not None and attempt.error_message else str(error),
            "review_state": "blocked",
        }
        self._event(
            workflow_run,
            "blocked_attempt.preserved",
            "Blocked generation attempt preserved; Current working version unchanged.",
            "blocked_attempt_preserved",
            metadata=blocked_attempt,
        )
        self.service._complete_workflow_lineage(workflow_run, status="failed")
        # A failure can occur while a generation child is being prepared,
        # before that child reaches the service-level cleanup path. Do not
        # leave an orphaned running child that makes the next chat message
        # look like an unrelated in-flight workflow.
        for child_run in self.db.scalars(
            select(WorkflowRun)
            .where(WorkflowRun.project_id == project.id)
            .where(WorkflowRun.status == "running")
        ):
            self.service._workflow_recorder().complete_run(child_run, status="failed")
        current = self.db.get(Project, project.id)
        plan = self.service.get_current_design_plan(project.id)
        planning_depth = (
            self.service._planning_depth_for_plan(plan.plan)
            if plan is not None
            else None
        )
        if planning_depth is None:
            route_artifact = self.db.scalar(
                select(WorkflowArtifact)
                .where(WorkflowArtifact.workflow_run_id == workflow_run.id)
                .where(WorkflowArtifact.artifact_type == "planning_route_decision")
                .order_by(WorkflowArtifact.created_at.desc())
            )
            if route_artifact is not None:
                route_path = self.service.data_dir / route_artifact.path
                if route_path.is_file():
                    try:
                        planning_depth = json.loads(route_path.read_text(encoding="utf-8")).get("outcome")
                    except (OSError, json.JSONDecodeError):
                        planning_depth = None
        current_revision_id = current.active_revision_id if current is not None else None
        if attempt is not None and attempt.failure_class == "design_plan_invalid":
            message = (
                "Volundr could not create a valid design plan for this request. "
                f"{_working_version_state_message(current_revision_id)}"
            )
        else:
            message = _blocked_version_message(current_revision_id)
        return self._response(
            workflow_run,
            action,
            "blocked_attempt",
            False,
            message,
            current_revision_id=current_revision_id,
            blocked_attempt=blocked_attempt,
            design_plan_id=plan.id if plan is not None else None,
            planning_depth=planning_depth,
        )

    async def _dispatch(
        self,
        project: Project,
        workflow_run: WorkflowRun,
        intent: RoutedIntent,
        message: str,
        *,
        user_message_id: str | None = None,
    ) -> ChatWorkflowResponse:
        user_message_id = user_message_id or getattr(self, "_active_user_message_id", None)
        if intent.action == "export_request":
            self._event(workflow_run, "export.requested", "Export requested from chat.", "export_requested")
            revision_id = project.active_revision_id
            if revision_id is None:
                return self._response(workflow_run, "export_request", "requirements", True, "Create a working version before exporting.")
            return self._response(
                workflow_run,
                "export_request",
                "export",
                False,
                "Your current working version is ready to export.",
                current_revision_id=revision_id,
            )
        if intent.action == "unsupported":
            return self._response(workflow_run, "unsupported", "conversation", True, "Tell me what should change, or describe the design you want to create.")
        if intent.action == "clarification_needed":
            return self._response(workflow_run, "clarification_needed", "conversation", True, "What specific part or value should I change? This avoids changing the wrong geometry.")
        if intent.action == "parameter_change":
            self._event(workflow_run, "parameter_update.routed", "Chat message routed to deterministic parameter configuration.", "parameter_update_routed")
            change = self.service.preview_configuration_change(
                project.id,
                ConfigurationChangeCreate(
                    base_revision_id=project.active_revision_id,
                    reason="parameter_change",
                    parameter_values=intent.parameter_values or {},
                ),
            )
            if change.validation_state.value != "configuration_ready":
                return self._response(workflow_run, "parameter_change", "configuration", True, "That parameter change needs clarification before I can create a version.", configuration_change_id=change.id)
            revision = await self.service.generate_from_configuration_change(change.id)
            return self._generated_response(workflow_run, "parameter_change", revision, base_revision_id=change.base_revision_id, configuration_change_id=change.id)
        if intent.action == "start_over":
            self._event(workflow_run, "start_over.branch_created", "A new design lineage was started while preserving previous versions.", "start_over_branch_created")
            return await self._initial_design(
                project,
                workflow_run,
                message,
                action="start_over",
                user_message_id=user_message_id,
            )
        if intent.action in {"structural_revision", "component_revision", "control_request"}:
            revision_action = "structural_revision" if intent.action == "control_request" else intent.action
            self._event(workflow_run, f"{intent.action}.routed", f"Chat message routed to {intent.action.replace('_', ' ')}.", f"{intent.action}_routed")
            if intent.action != "control_request":
                delta, _observation = requirement_delta_for_message(message)
                if not delta and _observation is not None:
                    self.requirement_store.apply_delta(
                        project_id=project.id,
                        changes=[],
                        originating_message=message,
                        observation=_observation,
                    )
                    self._event(
                        workflow_run,
                        "physical_feedback.recorded",
                        "Physical-test feedback was recorded for a future revision.",
                        "physical_feedback_recorded",
                    )
                    return self._response(
                        workflow_run,
                        intent.action,
                        "conversation",
                        False,
                        "I recorded the test result. Tell me what you want changed when you are ready for a new version.",
                        current_revision_id=project.active_revision_id,
                    )
                if delta:
                    deterministic_plan, route = self.service.create_deterministic_revision_brief(
                        project.id,
                        RevisionPlanCreate(
                            user_instruction=message,
                            base_revision_id=project.active_revision_id,
                            reason=intent.action,
                        ),
                        workflow_run=workflow_run,
                    )
                    if deterministic_plan is not None:
                        self._event(
                            workflow_run,
                            "revision_plan.progressed",
                            "A narrow revision brief was prepared automatically.",
                            "automatic_revision_plan_progressed",
                            revision_plan_id=deterministic_plan.id,
                            metadata={"planning_depth": route.outcome.value},
                        )
                        revision = await self.service.generate_from_revision_plan(
                            deterministic_plan.id,
                            user_message_id=user_message_id,
                        )
                        return self._generated_response(
                            workflow_run,
                            revision_action,
                            revision,
                            base_revision_id=project.active_revision_id,
                            revision_plan_id=deterministic_plan.id,
                            planning_depth=route.outcome.value,
                        )
            plan = await self.service.create_revision_plan(
                project.id,
                RevisionPlanCreate(
                    user_instruction=message,
                    base_revision_id=project.active_revision_id,
                    reason=intent.action,
                ),
            )
            if plan is None:
                raise LookupError("project not found")
            if plan.clarification_required:
                self._event(workflow_run, "clarification.requested", "Revision clarification requested.", "clarification_requested")
                return self._response(workflow_run, intent.action, "revision_planning", True, _first_question(plan.clarification_questions), revision_plan_id=plan.id, current_revision_id=project.active_revision_id)
            approved = self.service.approve_revision_plan(plan.id)
            if approved is None:
                raise LookupError("Revision Plan not found")
            revision = await self.service.generate_from_revision_plan(
                plan.id,
                user_message_id=user_message_id,
            )
            return self._generated_response(workflow_run, revision_action, revision, base_revision_id=project.active_revision_id, revision_plan_id=plan.id)

        return await self._resume_or_initial(
            project,
            workflow_run,
            message,
            user_message_id=user_message_id,
        )

    async def _resume_or_initial(
        self,
        project: Project,
        workflow_run: WorkflowRun,
        message: str,
        *,
        user_message_id: str | None = None,
    ) -> ChatWorkflowResponse:
        specification = self.service.get_current_design_specification(project.id)
        if specification is not None and specification.clarification_required:
            answered = await self.service.submit_clarification_answers(
                specification.id,
                ClarificationAnswersCreate(
                    answers=[ClarificationAnswerCreate(question_id=q.id, answer=message) for q in specification.clarification_questions],
                ),
            )
            self._event(workflow_run, "clarification.answered", "Requirement clarification answered.", "clarification_answered", metadata={"kind": "requirements"})
            if answered is None or answered.clarification_required:
                return self._response(workflow_run, "requirement_answer", "requirements", True, _first_question(answered.clarification_questions if answered else []), design_specification_id=answered.id if answered else specification.id)
            self.requirement_store.merge_from_specification(
                project_id=project.id,
                specification=answered.specification,
                originating_message=message,
                source="clarification_user",
                project_message_id=user_message_id,
            )
            self._event(workflow_run, "requirements.progressed", "Requirements progressed after clarification.", "automatic_requirements_progressed", design_specification_id=answered.id)
            return await self._plan_and_generate(
                project,
                workflow_run,
                answered,
                action="initial_design",
                user_message_id=user_message_id,
            )
        plan = self.service.get_current_design_plan(project.id)
        if plan is not None and plan.clarification_required:
            answered = await self.service.submit_design_plan_clarification_answers(
                plan.id,
                ClarificationAnswersCreate(
                    answers=[ClarificationAnswerCreate(question_id=q.id, answer=message) for q in plan.clarification_questions],
                ),
                strict_parameter_trace=False,
            )
            self._event(workflow_run, "clarification.answered", "Design Plan clarification answered.", "clarification_answered", metadata={"kind": "design_plan"})
            if answered is None or answered.clarification_required:
                return self._response(workflow_run, "requirement_answer", "design_planning", True, _first_question(answered.clarification_questions if answered else []), design_plan_id=answered.id if answered else plan.id)
            approved = self.service.approve_design_plan(answered.id)
            revision = await self.service.generate_from_design_plan(
                approved.id,
                user_message_id=user_message_id,
            )
            return self._generated_response(workflow_run, "initial_design", revision, base_revision_id=project.active_revision_id, design_plan_id=approved.id)
        revision_plan = self.service.get_current_revision_plan(project.id)
        if revision_plan is not None and revision_plan.clarification_required:
            answered = await self.service.submit_revision_plan_clarification_answers(
                revision_plan.id,
                ClarificationAnswersCreate(
                    answers=[ClarificationAnswerCreate(question_id=q.id, answer=message) for q in revision_plan.clarification_questions],
                ),
            )
            self._event(workflow_run, "clarification.answered", "Revision clarification answered.", "clarification_answered", metadata={"kind": "revision"})
            if answered is None or answered.clarification_required:
                return self._response(workflow_run, "requirement_answer", "revision_planning", True, _first_question(answered.clarification_questions if answered else []), revision_plan_id=answered.id if answered else revision_plan.id)
            approved = self.service.approve_revision_plan(answered.id)
            revision = await self.service.generate_from_revision_plan(
                approved.id,
                user_message_id=user_message_id,
            )
            return self._generated_response(workflow_run, "structural_revision", revision, base_revision_id=project.active_revision_id, revision_plan_id=approved.id)
        return await self._initial_design(
            project,
            workflow_run,
            message,
            user_message_id=user_message_id,
        )

    async def _initial_design(
        self,
        project: Project,
        workflow_run: WorkflowRun,
        message: str,
        *,
        action: str = "initial_design",
        user_message_id: str | None = None,
    ) -> ChatWorkflowResponse:
        specification = await self.service.extract_requirements(project.id, RequirementExtractionCreate(user_instruction=message))
        if specification is None:
            raise LookupError("project not found")
        if action == "start_over":
            self.requirement_store.merge_from_specification(
                project_id=project.id,
                specification=specification.specification,
                originating_message=message,
                source="revision_user",
                project_message_id=user_message_id,
            )
            changes, observation = requirement_delta_for_message(message)
            if changes:
                self.requirement_store.apply_delta(
                    project_id=project.id,
                    changes=changes,
                    originating_message=message,
                    observation=observation,
                )
        else:
            self.requirement_store.ensure_from_specification(
                project_id=project.id,
                specification=specification.specification,
                originating_message=message,
            )
        if specification.clarification_required:
            self._event(workflow_run, "clarification.requested", "Requirement clarification requested.", "clarification_requested")
            return self._response(workflow_run, action, "requirements", True, _first_question(specification.clarification_questions), design_specification_id=specification.id)
        self._event(workflow_run, "requirements.progressed", "Requirements progressed automatically.", "automatic_requirements_progressed", design_specification_id=specification.id)
        return await self._plan_and_generate(
            project,
            workflow_run,
            specification,
            action=action,
            user_message_id=user_message_id,
        )

    async def _plan_and_generate(
        self,
        project: Project,
        workflow_run: WorkflowRun,
        specification,
        *,
        action: str,
        user_message_id: str | None = None,
    ) -> ChatWorkflowResponse:
        plan, route = await self.service.create_proportional_plan_from_specification(
            specification.id,
            workflow_run=workflow_run,
        )
        if plan is None:
            self._event(
                workflow_run,
                "clarification.requested",
                "Planning clarification requested.",
                "clarification_requested",
                metadata=route.to_payload(),
            )
            return self._response(
                workflow_run,
                action,
                "planning",
                True,
                _first_missing_information(route.missing_information),
                design_specification_id=specification.id,
                planning_depth=route.outcome.value,
            )
        if plan.clarification_required:
            self._event(workflow_run, "clarification.requested", "Design Plan clarification requested.", "clarification_requested")
            return self._response(workflow_run, action, "design_planning", True, _first_question(plan.clarification_questions), design_specification_id=specification.id, design_plan_id=plan.id, planning_depth=route.outcome.value)
        approved = plan
        if plan.review_state.value != "approved":
            approved = self.service.approve_design_plan(plan.id)
        if approved is None:
            raise LookupError("Design Plan not found")
        self._event(
            workflow_run,
            "design_plan.progressed",
            "Planning progressed automatically.",
            "automatic_design_plan_progressed",
            design_plan_id=approved.id,
            metadata={"planning_depth": route.outcome.value, "route_policy_version": route.policy_version},
        )
        self._event(workflow_run, "generation.started", "First-draft generation started automatically.", "automatic_generation_started", design_plan_id=approved.id)
        revision = await self.service.generate_from_design_plan(
            approved.id,
            user_message_id=user_message_id,
        )
        return self._generated_response(workflow_run, action, revision, base_revision_id=project.active_revision_id, design_specification_id=specification.id, design_plan_id=approved.id, planning_depth=route.outcome.value)

    def _generated_response(self, workflow_run: WorkflowRun, action: str, revision, *, base_revision_id: str | None, **ids) -> ChatWorkflowResponse:
        if revision is None:
            raise LookupError("generated revision not found")
        if revision.is_accepted:
            self.service._complete_workflow_lineage(workflow_run, status="completed")
            return self._response(workflow_run, action, "working_version", False, "Your current working version is ready.", current_revision_id=revision.id, revision_id=revision.id, **ids)
        if revision.status == "succeeded" and revision.review_state in {"ready", "ready_with_warnings"}:
            current = self.db.get(Project, revision.project_id)
            if current is not None and current.active_revision_id == base_revision_id:
                accepted = self.service.accept_candidate(revision.id)
                if accepted is not None:
                    self.service._complete_workflow_lineage(workflow_run, status="completed")
                    self._event(workflow_run, "working_version.promoted", "Passing draft promoted to Current working version.", "working_version_promoted", revision_id=revision.id)
                    return self._response(workflow_run, action, "working_version", False, "Your new version passed validation and is now the Current working version.", current_revision_id=accepted.id, revision_id=accepted.id, **ids)
        blocked = {
            "revision_id": revision.id,
            "status": revision.status,
            "review_state": revision.review_state,
            "functional_status": revision.functional_status,
            "validation_summary": revision.validation_summary.model_dump(),
            "error_message": revision.error_message,
        }
        attempt = self.db.scalar(
            select(GenerationAttempt)
            .where(GenerationAttempt.resulting_revision_id == revision.id)
            .order_by(GenerationAttempt.started_at.desc())
        )
        blocking_findings = list(
            self.db.scalars(
                select(ValidationFinding)
                .where(ValidationFinding.revision_id == revision.id)
                .where(ValidationFinding.is_blocking.is_(True))
                .order_by(ValidationFinding.created_at.asc(), ValidationFinding.rule_id.asc())
            )
        )
        failure_class = attempt.failure_class if attempt is not None else "unknown_failure"
        failure_stage = _failure_stage_for_blocked_attempt(failure_class)
        blocked_event_metadata = {
            **blocked,
            "attempt_id": attempt.id if attempt is not None else None,
            "failure_class": failure_class,
            "failure_stage": failure_stage,
            "error_message": revision.error_message
            or (blocking_findings[0].explanation if blocking_findings else None),
            "provider_response_received": bool(attempt and attempt.raw_output_path),
            "geometry_generation_attempted": failure_stage != "plan_validation",
            "worker_reached": failure_stage in {"worker_execution", "topology_validation", "functional_validation"},
            "current_working_version_unchanged": True,
            "blocking_findings": [
                {
                    "id": finding.id,
                    "rule_id": finding.rule_id,
                    "category": finding.category,
                    "severity": finding.severity,
                    "explanation": finding.explanation,
                }
                for finding in blocking_findings
            ],
        }
        self._event(
            workflow_run,
            "blocked_attempt.preserved",
            "Blocked attempt preserved; Current working version unchanged.",
            "blocked_attempt_preserved",
            generation_attempt_id=attempt.id if attempt is not None else None,
            revision_id=revision.id,
            metadata=blocked_event_metadata,
        )
        self.service._complete_workflow_lineage(workflow_run, status="failed")
        current_revision_id = self.db.get(Project, revision.project_id).active_revision_id
        return self._response(
            workflow_run,
            action,
            "blocked_attempt",
            False,
            _blocked_version_message(current_revision_id),
            current_revision_id=current_revision_id,
            revision_id=revision.id,
            blocked_attempt=blocked,
            **ids,
        )

    def _response(self, workflow_run: WorkflowRun, action: str, stage: str, input_required: bool, message: str, *, current_revision_id: str | None = None, revision_id: str | None = None, blocked_attempt: dict[str, Any] | None = None, **ids) -> ChatWorkflowResponse:
        self.db.flush()
        return ChatWorkflowResponse(
            workflow_run_id=workflow_run.id if workflow_run else None,
            action=action,
            current_stage=stage,
            input_required=input_required,
            assistant_message=message,
            current_working_revision_id=current_revision_id,
            active_generation_run=(
                {"workflow_run_id": workflow_run.id, "status": workflow_run.status, "stage": stage}
                if workflow_run
                else None
            ),
            blocked_attempt=blocked_attempt,
            revision_id=revision_id,
            active_requirements=(
                active_requirements(self.requirement_store.load(workflow_run.project_id))
                if workflow_run is not None
                else []
            ),
            **ids,
        )

    def _event(self, workflow_run: WorkflowRun, event_type: str, message: str, action: str, *, metadata: dict[str, Any] | None = None, **ids) -> None:
        self.service._record_workflow_event(
            workflow_run,
            stage="chat_workflow",
            event_type=event_type,
            severity="summary",
            message=message,
            deduplication_key=f"chat-{workflow_run.id}-{action}-{self.db.query(ProjectMessage).count()}",
            metadata=metadata,
            **ids,
        )


def _first_question(questions: list[Any]) -> str:
    if not questions:
        return "Please clarify the design choice that matters most before I generate a version."
    question = questions[0]
    return getattr(question, "question", None) or question.get("question", "Please clarify this design choice.")


def _blocked_version_message(current_revision_id: str | None) -> str:
    if current_revision_id:
        return "Volundr could not create a valid new version. Your Current working version is unchanged."
    return "Volundr could not create a valid new version. No working version has been created yet."


def _working_version_state_message(current_revision_id: str | None) -> str:
    return (
        "Your Current working version is unchanged."
        if current_revision_id
        else "No working version has been created yet."
    )


def _first_missing_information(items: list[dict[str, Any]]) -> str:
    if not items:
        return "Please clarify the design information that matters most before I generate a version."
    item = items[0]
    requirement_id = item.get("requirement_id") or "this requirement"
    return f"Please clarify {requirement_id}. {item.get('reason') or 'This affects the geometry and cannot be safely proposed yet.'}"


def _project_name(message: str) -> str:
    words = re.sub(r"[^A-Za-z0-9 ]+", " ", message).split()
    return " ".join(words[:8]).title() or "Untitled design"


def _assistant_message_role(response: ChatWorkflowResponse) -> str:
    """Persist semantic chat roles without exposing internal workflow events."""
    if response.blocked_attempt is not None or response.current_stage == "blocked_attempt":
        return "assistant_blocked"
    if response.input_required:
        return "assistant_clarification"
    if response.current_stage == "working_version":
        return "assistant_success"
    return "assistant_information"


def _failure_stage_for_blocked_attempt(failure_class: str) -> str:
    return {
        "design_plan_invalid": "plan_validation",
        "design_artifact_inconsistent": "artifact_consistency",
        "source_extraction_failure": "source_extraction",
        "geometry_body_failure": "source_contract_validation",
        "source_contract_hard_rejection": "source_contract_validation",
        "cadquery_compile_failure": "worker_execution",
        "cadquery_timeout": "worker_execution",
        "mesh_invalid": "topology_validation",
        "mesh_empty_or_zero_volume": "topology_validation",
        "mesh_non_watertight": "topology_validation",
    }.get(failure_class, "candidate_validation")
