from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.generation_attempt import GenerationAttempt
from app.models.validation_finding import ValidationFinding
from app.models.workflow import WorkflowDiagnosis, WorkflowEvent, WorkflowRun


class WorkflowDiagnosisService:
    def __init__(self, *, db: Session) -> None:
        self.db = db

    def diagnose(self, workflow_run_id: str) -> WorkflowDiagnosis:
        run = self.db.get(WorkflowRun, workflow_run_id)
        if run is None:
            raise ValueError("workflow run not found")
        root_id = run.root_workflow_run_id or run.id
        events = list(
            self.db.scalars(
                select(WorkflowEvent)
                .join(WorkflowRun, WorkflowEvent.workflow_run_id == WorkflowRun.id)
                .where(WorkflowEvent.root_workflow_run_id == root_id)
                .order_by(
                    WorkflowRun.started_at.asc(),
                    WorkflowEvent.workflow_run_id.asc(),
                    WorkflowEvent.sequence_number.asc(),
                    WorkflowEvent.recorded_at.asc(),
                )
            )
        )
        plan_findings = self._plan_findings(events)
        root_event, confidence, basis = self._root_event(events)
        downstream_effects = self._downstream_effects(events, root_event)
        repairs = self._repairs(events)
        if root_event is None and plan_findings:
            root_cause = self._finding_root_cause(plan_findings[0], run, confidence="confirmed")
        else:
            root_cause = self._root_cause_payload(root_event, confidence, basis, findings=plan_findings)
        diagnosis = WorkflowDiagnosis(
            workflow_run_id=workflow_run_id,
            schema_version=run.diagnosis_version,
            root_cause_json=json.dumps(
                root_cause,
                sort_keys=True,
                default=str,
            ),
            repairs_json=json.dumps(repairs, sort_keys=True, default=str),
            downstream_effects_json=json.dumps(downstream_effects, sort_keys=True, default=str),
            final_outcome=run.status,
            basis_json=json.dumps(basis, sort_keys=True, default=str),
        )
        self.db.add(diagnosis)
        self.db.commit()
        self.db.refresh(diagnosis)
        return diagnosis

    def _plan_findings(self, events: list[WorkflowEvent]) -> list[ValidationFinding]:
        attempt_ids = {
            event.generation_attempt_id
            for event in events
            if event.generation_attempt_id
        }
        events_by_id = {event.id: event for event in events}
        resolved_attempt_ids = {
            events_by_id[event.caused_by_event_id].generation_attempt_id
            for event in events
            if event.caused_by_event_id
            and event.caused_by_event_id in events_by_id
            and event.event_type.endswith(".succeeded")
            and events_by_id[event.caused_by_event_id].generation_attempt_id
        }
        attempt_ids -= resolved_attempt_ids
        if not attempt_ids:
            return []
        return list(
            self.db.scalars(
                select(ValidationFinding)
                .where(ValidationFinding.generation_attempt_id.in_(attempt_ids))
                .where(ValidationFinding.is_blocking.is_(True))
                .where(ValidationFinding.category.in_(("plan", "plan_pattern")))
                .order_by(ValidationFinding.created_at.asc(), ValidationFinding.rule_id.asc())
            )
        )

    def _finding_root_cause(
        self,
        finding: ValidationFinding,
        run: WorkflowRun,
        *,
        confidence: str,
    ) -> dict[str, Any]:
        metadata = json.loads(finding.metadata_json or "{}")
        attempt = self.db.get(GenerationAttempt, finding.generation_attempt_id) if finding.generation_attempt_id else None
        return {
            "stage": "plan_validation",
            "rule_id": finding.rule_id,
            "event_id": None,
            "artifact_id": metadata.get("plan_artifact_id"),
            "summary": finding.explanation,
            "confidence": confidence,
            "basis": {
                "reason": "typed_plan_validation_finding",
                "provider_response_received": bool(attempt and attempt.raw_output_path),
                "geometry_attempted": False,
                "worker_reached": False,
                "current_working_version_unchanged": True,
                "workflow_run_id": run.id,
            },
            "findings": [self._finding_summary(finding)],
        }

    @staticmethod
    def _finding_summary(finding: ValidationFinding) -> dict[str, Any]:
        metadata = json.loads(finding.metadata_json or "{}")
        return {
            "id": finding.id,
            "rule_id": finding.rule_id,
            "severity": finding.severity,
            "blocking": finding.is_blocking,
            "explanation": finding.explanation,
            "pattern_index": metadata.get("pattern_index"),
            "pattern_id": metadata.get("pattern_id"),
        }

    def _root_event(
        self,
        events: list[WorkflowEvent],
    ) -> tuple[WorkflowEvent | None, str, dict[str, Any]]:
        resolved_event_ids = {
            event.caused_by_event_id
            for event in events
            if event.caused_by_event_id
            and (
                event.event_type.endswith(".succeeded")
                or event.event_type.endswith(".resolved")
            )
        }
        blocking = [
            event
            for event in events
            if event.blocking and event.id not in resolved_event_ids
        ]
        if not blocking:
            legacy_block = next(
                (
                    event
                    for event in events
                    if event.event_type == "blocked_attempt.preserved"
                    and self._legacy_block_contains_failure(event)
                ),
                None,
            )
            if legacy_block is not None:
                return legacy_block, "probable", {"reason": "legacy_blocked_attempt_metadata"}
            return None, "unknown", {"reason": "no_blocking_events"}
        explicit_root = next((event for event in blocking if event.is_root_failure), None)
        if explicit_root is not None:
            return explicit_root, "confirmed", {"reason": "event_marked_root_failure"}
        caused_ids = {event.caused_by_event_id for event in blocking if event.caused_by_event_id}
        linked_cause = next((event for event in blocking if event.id in caused_ids), None)
        if linked_cause is not None:
            return linked_cause, "confirmed", {"reason": "explicit_caused_by_event_link"}
        uncaused_blocking = [event for event in blocking if event.id not in caused_ids and not event.is_downstream_symptom]
        if uncaused_blocking:
            event = uncaused_blocking[0]
            confidence = "confirmed" if any(item.caused_by_event_id == event.id for item in blocking) else "probable"
            return event, confidence, {
                "reason": "blocking_event_has_downstream_links"
                if confidence == "confirmed"
                else "earliest_unlinked_blocking_event",
            }
        return blocking[0], "possible", {"reason": "sequence_order_fallback"}

    def _root_cause_payload(
        self,
        event: WorkflowEvent | None,
        confidence: str,
        basis: dict[str, Any],
        *,
        findings: list[ValidationFinding] | None = None,
    ) -> dict[str, Any]:
        if event is None:
            return {
                "stage": None,
                "rule_id": None,
                "event_id": None,
                "artifact_id": None,
                "summary": "No blocking event was recorded.",
                "confidence": confidence,
                "basis": basis,
                "findings": [self._finding_summary(item) for item in (findings or [])],
            }
        event.is_root_failure = True
        self.db.flush()
        if event.event_type == "blocked_attempt.preserved":
            metadata = json.loads(event.metadata_json or "{}")
            attempt_id = metadata.get("attempt_id") or event.generation_attempt_id
            attempt = self.db.get(GenerationAttempt, attempt_id) if attempt_id else None
            revision_id = metadata.get("revision_id") or event.revision_id
            if revision_id is None and attempt is not None:
                revision_id = attempt.resulting_revision_id
            blocked_findings = self._blocked_attempt_findings(
                attempt_id=attempt_id,
                revision_id=revision_id,
            )
            if attempt_id is None and revision_id is not None:
                attempt = self.db.scalar(
                    select(GenerationAttempt)
                    .where(GenerationAttempt.resulting_revision_id == revision_id)
                    .order_by(GenerationAttempt.started_at.desc())
                )
                attempt_id = attempt.id if attempt is not None else None
            if attempt_id is None and blocked_findings:
                attempt_id = blocked_findings[0].generation_attempt_id
                attempt = self.db.get(GenerationAttempt, attempt_id) if attempt_id else None
            all_findings = list(findings or [])
            known_finding_ids = {item.id for item in all_findings}
            all_findings.extend(item for item in blocked_findings if item.id not in known_finding_ids)
            error_message = str(metadata.get("error_message") or "")
            failure_class = str(
                metadata.get("failure_class")
                or (attempt.failure_class if attempt is not None else "")
                or ""
            )
            failure_stage = str(
                metadata.get("failure_stage")
                or self._stage_for_failure_class(failure_class)
                or self._stage_for_finding(blocked_findings[0] if blocked_findings else None)
                or event.stage
            )
            first_finding = all_findings[0] if all_findings else None
            if first_finding is not None or error_message or failure_class:
                summary = (
                    first_finding.explanation
                    if first_finding is not None
                    else error_message
                    or "The generation attempt was blocked before a working version was created."
                )
                return {
                    "stage": failure_stage,
                    "rule_id": (
                        first_finding.rule_id
                        if first_finding is not None
                        else self._legacy_plan_rule_id(error_message)
                        if error_message
                        else self._failure_rule_id(failure_class)
                    ),
                    "event_id": event.id,
                    "artifact_id": metadata.get("plan_artifact_id") or event.source_artifact_id,
                    "summary": summary,
                    "confidence": "confirmed" if first_finding is not None else confidence,
                    "basis": {
                        **basis,
                        "attempt_id": attempt_id,
                        "failure_class": failure_class or None,
                        "provider_response_received": metadata.get(
                            "provider_response_received",
                            bool(attempt and attempt.raw_output_path),
                        ),
                        "geometry_attempted": metadata.get(
                            "geometry_generation_attempted",
                            not failure_stage.startswith("plan_"),
                        ),
                        "worker_reached": metadata.get("worker_reached", False),
                        "current_working_version_unchanged": metadata.get(
                            "current_working_version_unchanged",
                            True,
                        ),
                    },
                    "findings": [self._finding_summary(item) for item in all_findings],
                }
        payload = {
            "stage": event.stage,
            "rule_id": event.rule_id,
            "event_id": event.id,
            "artifact_id": event.source_artifact_id,
            "summary": event.message,
            "confidence": confidence,
            "basis": basis,
        }
        if findings:
            payload["findings"] = [self._finding_summary(item) for item in findings]
        return payload

    def _blocked_attempt_findings(
        self,
        *,
        attempt_id: str | None,
        revision_id: str | None,
    ) -> list[ValidationFinding]:
        if attempt_id is None and revision_id is None:
            return []
        query = select(ValidationFinding).where(ValidationFinding.is_blocking.is_(True))
        if attempt_id is not None and revision_id is not None:
            query = query.where(
                (ValidationFinding.generation_attempt_id == attempt_id)
                | (ValidationFinding.revision_id == revision_id)
            )
        elif attempt_id is not None:
            query = query.where(ValidationFinding.generation_attempt_id == attempt_id)
        else:
            query = query.where(ValidationFinding.revision_id == revision_id)
        return list(self.db.scalars(query.order_by(ValidationFinding.created_at.asc(), ValidationFinding.rule_id.asc())))

    @staticmethod
    def _stage_for_failure_class(failure_class: str) -> str | None:
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
        }.get(failure_class)

    @staticmethod
    def _stage_for_finding(finding: ValidationFinding | None) -> str | None:
        if finding is None:
            return None
        return {
            "plan": "plan_validation",
            "plan_pattern": "plan_validation",
            "design_artifact_consistency": "artifact_consistency",
            "source_contract": "source_contract_validation",
            "topology": "topology_validation",
            "functional": "functional_validation",
        }.get(finding.category)

    @staticmethod
    def _failure_rule_id(failure_class: str) -> str:
        return {
            "design_plan_invalid": "plan.contract_invalid",
            "design_artifact_inconsistent": "design_artifact.consistency",
            "source_contract_hard_rejection": "source_contract.hard_rejection",
            "cadquery_compile_failure": "worker.execution_failed",
        }.get(failure_class, "workflow.blocked")

    @staticmethod
    def _legacy_block_contains_failure(event: WorkflowEvent) -> bool:
        try:
            metadata = json.loads(event.metadata_json or "{}")
        except json.JSONDecodeError:
            return False
        return bool(
            metadata.get("error_message")
            or metadata.get("attempt_id")
            or metadata.get("failure_class")
            or metadata.get("revision_id")
            or event.generation_attempt_id
            or event.revision_id
        )

    @staticmethod
    def _legacy_plan_rule_id(error_message: str) -> str:
        lowered = error_message.lower()
        if "pattern_id is required" in lowered:
            return "plan.pattern_id_missing"
        if "unknown owning feature" in lowered:
            return "plan.pattern_owner_missing" if "``" in error_message else "plan.pattern_owner_unknown"
        if "unsupported pattern_type" in lowered:
            return "plan.pattern_type_missing" if "``" in error_message else "plan.pattern_type_unsupported"
        return "plan.contract_invalid"

    def _downstream_effects(
        self,
        events: list[WorkflowEvent],
        root_event: WorkflowEvent | None,
    ) -> list[dict[str, Any]]:
        if root_event is None:
            return []
        effects: list[dict[str, Any]] = []
        for event in events:
            if event.id == root_event.id:
                continue
            if event.caused_by_event_id == root_event.id or (
                event.sequence_number > root_event.sequence_number
                and event.blocking
                and event.stage in {"candidate_classification", "artifact_consistency", "topology_validation"}
            ):
                event.is_downstream_symptom = True
                effects.append(
                    {
                        "stage": event.stage,
                        "rule_id": event.rule_id,
                        "event_id": event.id,
                        "confidence": "confirmed"
                        if event.caused_by_event_id == root_event.id
                        else "possible",
                    }
                )
        self.db.flush()
        return effects

    def _repairs(self, events: list[WorkflowEvent]) -> list[dict[str, Any]]:
        repairs: list[dict[str, Any]] = []
        for event in events:
            if event.stage not in {"contract_repair", "execution_repair", "scope_correction"}:
                continue
            outcome = "unknown"
            if event.event_type.endswith(".succeeded") or event.event_type.endswith(".resolved"):
                outcome = "resolved"
            elif event.event_type.endswith(".failed"):
                outcome = "failed"
            repairs.append({"stage": event.stage, "outcome": outcome, "event_id": event.id})
        return repairs
