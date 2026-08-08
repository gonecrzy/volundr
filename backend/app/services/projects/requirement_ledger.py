"""Requirement authority and revision-delta helpers.

The ledger describes the product that must be built.  It deliberately does
not mirror the CadQuery parameter graph: source implementation is one
possible realization of the requirements, not their authority.
"""

from __future__ import annotations

import re
import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.requirement_ledger import (
    PhysicalTestObservation,
    RequirementDelta,
    RequirementLedgerEntry,
)
from app.models.clarification_answer import ClarificationAnswer
from app.models.project_message import ProjectMessage
from app.services.requirements.trace import (
    build_explicit_requirement_inventory,
    canonicalize_dimension_envelopes,
    normalize_requirement_semantics,
)


REQUIREMENT_LEDGER_VERSION = "requirement-ledger-v1"
ACTIVE = "active"
SUPERSEDED = "superseded"
REMOVED = "removed"
VALID_STATUSES = {ACTIVE, SUPERSEDED, REMOVED}
VALID_SOURCES = {
    "initial_user",
    "clarification_user",
    "revision_user",
    "derived_functional_necessity",
    "volundr_proposal",
    "physical_test_feedback",
}


def build_requirement_ledger(
    requirements: list[dict[str, Any]],
    *,
    project_id: str | None = None,
    originating_message: str | None = None,
    originating_revision_id: str | None = None,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for item in canonicalize_dimension_envelopes(requirements):
        normalized = _normalize_requirement(
            item,
            default_source="initial_user",
            originating_message=originating_message,
            originating_revision_id=originating_revision_id,
        )
        if normalized is not None:
            records.append(normalized)
    return {
        "schema_version": REQUIREMENT_LEDGER_VERSION,
        "project_id": project_id,
        "updated_at": _now(),
        "requirements": _dedupe_active(records),
    }


def apply_requirement_delta(
    ledger: dict[str, Any],
    changes: list[dict[str, Any]],
    *,
    originating_message: str | None = None,
    originating_revision_id: str | None = None,
) -> dict[str, Any]:
    result = deepcopy(ledger)
    result.setdefault("schema_version", REQUIREMENT_LEDGER_VERSION)
    records = [deepcopy(item) for item in result.get("requirements", []) if isinstance(item, dict)]
    for change in changes:
        if not isinstance(change, dict):
            continue
        operation = str(change.get("operation") or "add")
        requirement_id = _requirement_id(change)
        if not requirement_id:
            continue
        current = [
            item
            for item in records
            if item.get("requirement_id") == requirement_id and item.get("status") == ACTIVE
        ]
        if operation in {"change", "supersede", "remove"}:
            replacement_id = str(change.get("replacement_requirement_id") or requirement_id)
            for item in current:
                item["status"] = REMOVED if operation == "remove" else SUPERSEDED
                item["superseded_by"] = replacement_id if operation != "remove" else None
                item["updated_at"] = _now()
        if operation == "remove":
            continue
        normalized = _normalize_requirement(
            {
                **change,
                "requirement_id": str(change.get("replacement_requirement_id") or requirement_id),
                "source": change.get("source") or "revision_user",
                "status": ACTIVE,
                "supersedes_requirement_id": requirement_id if current else None,
            },
            default_source="revision_user",
            originating_message=originating_message,
            originating_revision_id=originating_revision_id,
        )
        if normalized is not None:
            records.append(normalized)
    result["requirements"] = records
    result["updated_at"] = _now()
    return result


def active_requirements(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        deepcopy(item)
        for item in ledger.get("requirements", [])
        if isinstance(item, dict) and item.get("status") == ACTIVE
    ]


def requirement_delta_for_message(
    message: str,
    *,
    source: str = "revision_user",
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Parse common revision/feedback language conservatively.

    Ambiguous requests return no destructive delta; the existing revision
    planner remains responsible for clarification.
    """

    text = message.strip()
    lowered = text.lower()
    observation: dict[str, Any] | None = None
    changes: list[dict[str, Any]] = []
    semantic_changes = _semantic_revision_changes(text, source=source)
    physical_feedback_signal = bool(
        re.search(
            r"\b(?:too\s+tight|too\s+loose|too\s+stiff|flex(?:es|ed)?|cracked|broke|"
            r"does\s+not\s+seat|test\s+print|interferes?)\b",
            lowered,
        )
    )
    if semantic_changes and not physical_feedback_signal:
        changes.extend(semantic_changes)
    elif "too tight" in lowered and "diameter" in lowered:
        observation = _observation(text, "fit_too_tight", "physical_test_feedback")
        match = re.search(r"to\s+([0-9]+(?:\.[0-9]+)?)\s*mm", lowered)
        changes.append(
            {
                "operation": "change",
                "requirement_id": "hole_diameter",
                "type": "exact_dimension",
                "value": float(match.group(1)) if match else None,
                "unit": "mm" if match else None,
                "source": "physical_test_feedback",
                "explicit": True,
                "target": "mounting_holes",
            }
        )
    elif "too tight" in lowered and "clearance" in lowered:
        observation = _observation(text, "fit_too_tight", "physical_test_feedback")
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*mm\s*clearance", lowered)
        changes.append(
            {
                "operation": "change",
                "requirement_id": "fit_clearance_per_side",
                "type": "clearance",
                "value": float(match.group(1)) if match else None,
                "unit": "mm" if match else None,
                "source": "physical_test_feedback",
                "explicit": True,
            }
        )
    elif "flex" in lowered and ("thicker" in lowered or "reinforce" in lowered):
        observation = _observation(text, "mounting_plate_flexes", "physical_test_feedback")
        changes.extend(
            [
                {
                    "operation": "add",
                    "requirement_id": "mounting_plate_thickness",
                    "type": "minimum_dimension",
                    "value": None,
                    "source": source,
                    "explicit": True,
                    "target": "mounting_plate",
                },
                {
                    "operation": "add",
                    "requirement_id": "mounting_plate_reinforcement",
                    "type": "relationship",
                    "value": "reinforced against flex",
                    "source": source,
                    "explicit": True,
                    "target": "mounting_plate",
                },
            ]
        )
    elif "lower mounting hole" in lowered and "left" in lowered:
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*mm\s*left", lowered)
        changes.append(
            {
                "operation": "change",
                "requirement_id": "lower_mounting_hole_position",
                "type": "position",
                "value": {"axis": "X", "offset": -(float(match.group(1)) if match else 0.0)},
                "unit": "mm",
                "source": source,
                "explicit": True,
                "target": "lower_mounting_hole",
            }
        )
    elif "snap arm" in lowered and ("broke" in lowered or "redesign" in lowered):
        observation = _observation(text, "snap_arm_failed_test", "physical_test_feedback") if "broke" in lowered else None
        changes.extend(
            [
                {
                    "operation": "change",
                    "requirement_id": "retention_strategy",
                    "type": "retention",
                    "value": "stronger retention solution",
                    "source": source,
                    "explicit": True,
                    "target": "retention",
                },
                {
                    "operation": "add",
                    "requirement_id": "retention_test_review",
                    "type": "qualitative_behavior",
                    "value": "review after test print",
                    "source": "physical_test_feedback" if observation else source,
                    "explicit": True,
                    "target": "retention",
                },
            ]
        )
    elif "strap" in lowered and ("start over" in lowered or "replace" in lowered or "instead" in lowered):
        changes.extend(
            [
                {
                    "operation": "change",
                    "requirement_id": "retention_strategy",
                    "type": "retention",
                    "value": "strap slot",
                    "source": source,
                    "explicit": True,
                    "target": "retention",
                },
                {
                    "operation": "add",
                    "requirement_id": "retention_remains_revisionable",
                    "type": "qualitative_behavior",
                    "value": "retention must remain accessible for future revisions",
                    "source": source,
                    "explicit": False,
                    "target": "retention",
                },
            ]
        )
    if not changes:
        match = re.search(
            r"\b(?:change|set|make)\s+(?:the\s+)?([a-z][a-z0-9 _-]{1,50})\s+to\s+([0-9]+(?:\.[0-9]+)?)\s*mm\b",
            lowered,
        )
        if match:
            label = re.sub(r"\s+", " ", match.group(1)).strip(" _-")
            requirement_id = re.sub(r"[^a-z0-9]+", "_", label).strip("_")
            if requirement_id:
                changes.append(
                    {
                        "operation": "change",
                        "requirement_id": requirement_id,
                        "type": "exact_dimension",
                        "value": float(match.group(2)),
                        "unit": "mm",
                        "source": source,
                        "explicit": True,
                    }
                )
    if observation is None and not changes and re.search(
        r"\b(?:too\s+tight|too\s+loose|too\s+stiff|flex(?:es|ed)?|cracked|broke|"
        r"does\s+not\s+seat|test\s+print|interferes?)\b",
        lowered,
    ):
        observation = _observation(text, "physical_test_observation", "physical_test_feedback")
    return changes, observation


def _semantic_revision_changes(message: str, *, source: str) -> list[dict[str, Any]]:
    """Extract only unambiguous semantic deltas from ordinary revision text.

    This intentionally returns requirement deltas, not exposed controls.  The
    active ledger remains the authority for matching an existing requirement
    when a user uses a shorter label such as ``capacity``.
    """

    extracted = build_explicit_requirement_inventory(message)
    semantic_items = [
        item for item in extracted
        if item.get("kind") in {"capacity", "feature"}
        and item.get("operator") in {"up_to", "at_least", "exact", "range", "present", "absent"}
    ]
    if semantic_items:
        return [
            {
                **item,
                "operation": "change",
                "source": source,
                "explicit": True,
            }
            for item in semantic_items
        ]

    approximate = re.search(
        r"\b(?:make|set|change)\s+(?:the\s+)?(?P<label>[a-z][a-z0-9 _-]*?)\s+"
        r"(?P<operator>approximately|about|approx)\s+(?P<value>[0-9]+(?:\.[0-9]+)?)\s*"
        r"(?P<unit>[a-z]+)?\b",
        message.lower(),
    )
    if approximate:
        return [_numeric_revision_change(
            label=approximate.group("label"),
            value=float(approximate.group("value")),
            unit=approximate.group("unit"),
            operator="approximately",
            source=source,
        )]

    numeric = re.search(
        r"\b(?:increase|raise|reduce|decrease|lower|change|set|make)\s+(?:the\s+)?"
        r"(?P<label>[a-z][a-z0-9 _-]*?)\s+(?:from\s+[^\d]+[0-9]+(?:\.[0-9]+)?\s*[a-z]+\s+)?"
        r"to\s+(?P<value>[0-9]+(?:\.[0-9]+)?)\s*(?P<unit>[a-z]+)?\b",
        message.lower(),
    )
    if not numeric:
        return []
    return [_numeric_revision_change(
        label=numeric.group("label"),
        value=float(numeric.group("value")),
        unit=numeric.group("unit"),
        operator=None,
        source=source,
    )]


def _numeric_revision_change(
    *,
    label: str,
    value: float,
    unit: str | None,
    operator: str | None,
    source: str,
) -> dict[str, Any]:
    clean_label = re.sub(r"\s+from\s+.*$", "", label).strip(" _-")
    qualifier = None
    qualifier_match = re.match(r"^(maximum|minimum)\s+(.+)$", clean_label)
    if qualifier_match:
        qualifier = qualifier_match.group(1)
        clean_label = qualifier_match.group(2).strip()
    requirement_id = re.sub(r"[^a-z0-9]+", "_", clean_label).strip("_")
    is_capacity = "capacity" in requirement_id
    resolved_operator = operator or qualifier or "exact"
    return {
        "operation": "change",
        "requirement_id": requirement_id,
        "type": "capacity" if is_capacity else (
            "maximum_dimension" if resolved_operator == "maximum" else
            "minimum_dimension" if resolved_operator == "minimum" else
            "exact_dimension"
        ),
        "kind": "capacity" if is_capacity else "dimension",
        "operator": resolved_operator,
        "value": int(value) if value.is_integer() else value,
        "unit": unit or ("count" if is_capacity else None),
        "source": source,
        "explicit": True,
        "target": requirement_id,
    }


class RequirementLedgerStore:
    """Persistence adapter for the authoritative project requirement ledger."""

    def __init__(self, db: Session):
        self.db = db

    def load(self, project_id: str) -> dict[str, Any]:
        rows = list(
            self.db.scalars(
                select(RequirementLedgerEntry)
                .where(RequirementLedgerEntry.project_id == project_id)
                .order_by(RequirementLedgerEntry.created_at.asc(), RequirementLedgerEntry.id.asc())
            )
        )
        return {
            "schema_version": REQUIREMENT_LEDGER_VERSION,
            "project_id": project_id,
            "updated_at": _now(),
            "requirements": [_entry_payload(row) for row in rows],
        }

    def reconcile_clarification_provenance(self, project_id: str) -> int:
        """Correct legacy proposal labels when one clarification answer is unambiguous.

        Older workflow runs persisted the answer-derived requirement as a
        Volundr proposal.  This repair keeps the raw wording and answer
        records, but restores explicit user provenance using the existing
        clarification and client-message identities.
        """

        answers = list(
            self.db.scalars(
                select(ClarificationAnswer).where(ClarificationAnswer.project_id == project_id)
            )
        )
        if not answers:
            return 0
        messages = list(
            self.db.scalars(
                select(ProjectMessage)
                .where(ProjectMessage.project_id == project_id)
                .where(ProjectMessage.role == "user")
                .where(ProjectMessage.client_message_id.is_not(None))
            )
        )
        rows = list(
            self.db.scalars(
                select(RequirementLedgerEntry)
                .where(RequirementLedgerEntry.project_id == project_id)
                .where(RequirementLedgerEntry.source == "volundr_proposal")
            )
        )
        corrected = 0
        for answer in answers:
            matching_messages = [
                message for message in messages if message.content.strip() == answer.answer.strip()
            ]
            matching_rows = [
                row for row in rows if (row.originating_message or "").strip() == answer.answer.strip()
            ]
            if len(matching_messages) != 1 or len(matching_rows) != 1:
                continue
            row = matching_rows[0]
            row.source = "clarification_user"
            row.explicit = True
            evidence = _parse_json(row.verification_evidence_json)
            if not isinstance(evidence, dict):
                evidence = {"evidence": evidence}
            evidence["provenance"] = {
                "source": "clarification_user",
                "clarification_answer_id": answer.id,
                "clarification_question_id": answer.question_id,
                "project_message_id": matching_messages[0].id,
                "normalization_rule": "legacy_clarification_provenance_reconciled",
            }
            row.verification_evidence_json = _json_value(evidence)
            corrected += 1
            rows.remove(row)
        if corrected:
            self.db.flush()
        return corrected

    def ensure_from_specification(
        self,
        *,
        project_id: str,
        specification: dict[str, Any],
        originating_message: str | None = None,
    ) -> dict[str, Any]:
        current = self.load(project_id)
        if current["requirements"]:
            semantic_changes = _semantic_reconciliation_changes(
                current,
                _requirements_from_specification(specification),
            )
            if semantic_changes:
                return self.apply_delta(
                    project_id=project_id,
                    changes=semantic_changes,
                    originating_message=originating_message or "",
                )
            return current
        requirements = _requirements_from_specification(specification)
        ledger = build_requirement_ledger(
            requirements,
            project_id=project_id,
            originating_message=originating_message,
        )
        self._persist_entries(project_id, ledger)
        return ledger

    def merge_from_specification(
        self,
        *,
        project_id: str,
        specification: dict[str, Any],
        originating_message: str | None = None,
        source: str | None = None,
        project_message_id: str | None = None,
    ) -> dict[str, Any]:
        """Add newly interpreted requirements without rewriting active history."""

        current = self.load(project_id)
        existing_ids = {
            str(item.get("requirement_id"))
            for item in active_requirements(current)
            if item.get("requirement_id")
        }
        additions = [
            {
                **item,
                "operation": "add",
                **({"source": source, "explicit": True} if source else {}),
                **({"project_message_id": project_message_id} if project_message_id else {}),
            }
            for item in _requirements_from_specification(specification)
            if str(item.get("requirement_id") or "") not in existing_ids
        ]
        if not additions:
            return current
        return self.apply_delta(
            project_id=project_id,
            changes=additions,
            originating_message=originating_message or "",
            project_message_id=project_message_id,
        )

    def apply_delta(
        self,
        *,
        project_id: str,
        changes: list[dict[str, Any]],
        originating_message: str,
        revision_plan_id: str | None = None,
        revision_id: str | None = None,
        project_message_id: str | None = None,
        observation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current = self.load(project_id)
        ledger = apply_requirement_delta(
            current,
            changes,
            originating_message=originating_message,
            originating_revision_id=revision_id,
        )
        for change in changes:
            if not isinstance(change, dict) or not change.get("requirement_id"):
                continue
            self.db.add(
                RequirementDelta(
                    project_id=project_id,
                    revision_plan_id=revision_plan_id,
                    revision_id=revision_id,
                    project_message_id=project_message_id,
                    operation=str(change.get("operation") or "add"),
                    requirement_id=str(change["requirement_id"]),
                    source=str(change.get("source") or "revision_user"),
                    payload_json=json.dumps(change, sort_keys=True, default=str),
                    originating_message=originating_message,
                )
            )
        self._persist_entries(project_id, ledger, revision_id=revision_id)
        if observation is not None:
            self.db.add(
                PhysicalTestObservation(
                    project_id=project_id,
                    revision_id=revision_id,
                    source=str(observation.get("source") or "physical_test_feedback"),
                    observation_type=str(observation.get("observation_type") or "physical_feedback"),
                    observation=str(observation.get("observation") or originating_message),
                    interpretation_json=json.dumps(observation, sort_keys=True, default=str),
                )
            )
        self.db.flush()
        return ledger

    def _persist_entries(
        self,
        project_id: str,
        ledger: dict[str, Any],
        *,
        revision_id: str | None = None,
    ) -> None:
        existing = {
            row.id: row
            for row in self.db.scalars(
                select(RequirementLedgerEntry).where(RequirementLedgerEntry.project_id == project_id)
            )
        }
        for item in ledger.get("requirements", []) or []:
            if not isinstance(item, dict) or not item.get("record_id"):
                continue
            row = existing.get(str(item["record_id"]))
            if row is None:
                row = RequirementLedgerEntry(
                    id=str(item["record_id"]),
                    project_id=project_id,
                    revision_id=revision_id,
                )
                self.db.add(row)
            row.revision_id = revision_id or row.revision_id
            row.requirement_id = str(item["requirement_id"])
            row.source = str(item["source"])
            row.target_json = _json_value(item.get("target"))
            row.requirement_type = str(item.get("type") or "qualitative_behavior")
            row.value_json = _json_value(item.get("value"))
            row.unit = item.get("unit")
            row.tolerance_json = _json_value(item.get("tolerance"))
            row.explicit = bool(item.get("explicit"))
            row.status = str(item.get("status") or ACTIVE)
            row.originating_message = item.get("originating_message")
            row.originating_revision_id = item.get("originating_revision_id")
            row.supersedes_requirement_id = item.get("supersedes_requirement_id")
            row.superseded_by = item.get("superseded_by")
            row.verification_evidence_json = _json_value(
                {
                    "evidence": item.get("verification_evidence"),
                    "semantic": {
                        key: item.get(key)
                        for key in (
                            "kind",
                            "operator",
                            "subject",
                            "object_type",
                            "raw_evidence",
                            "source_fact_id",
                            "source_fact_type",
                            "source_fact_evidence",
                            "classification",
                            "policy",
                            "verification_policy",
                        )
                        if item.get(key) is not None
                    },
                    "provenance": item.get("provenance"),
                }
            )
        self.db.flush()


def _requirements_from_specification(specification: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in specification.get("explicit_requirements", []) or []:
        if isinstance(item, dict):
            items.append({**item, "source": "initial_user", "explicit": True})
    critical_dimensions = canonicalize_dimension_envelopes(
        [item for item in specification.get("critical_dimensions", []) or [] if isinstance(item, dict)]
    )
    for collection_name, default_type, collection in (
        ("critical_dimensions", "exact_dimension", critical_dimensions),
        ("functional_requirements", "qualitative_behavior", specification.get("functional_requirements", []) or []),
    ):
        for item in collection:
            if not isinstance(item, dict):
                continue
            raw_value = item.get("value")
            items.append(
                {
                    **{
                        key: item.get(key)
                        for key in (
                            "kind",
                            "operator",
                            "subject",
                            "object_type",
                            "raw_evidence",
                            "source_fact_id",
                            "source_fact_type",
                            "source_fact_evidence",
                            "classification",
                            "policy",
                            "verification_policy",
                            "provenance",
                        )
                        if item.get(key) is not None
                    },
                    "requirement_id": item.get("requirement_id") or item.get("id"),
                    "target": item.get("target") or item.get("component_id"),
                    "type": item.get("type") or default_type,
                    "value": raw_value if raw_value is not None else item.get("description"),
                    "unit": item.get("unit"),
                    "tolerance": item.get("tolerance"),
                    "source": "initial_user" if item.get("source") == "user" else "volundr_proposal",
                    "explicit": item.get("source") == "user",
                }
            )
    return items


def _semantic_reconciliation_changes(
    ledger: dict[str, Any],
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Supersede stale interpretations when an authoritative specification adds meaning.

    This is deliberately limited to explicit/clarified requirements.  Proposal
    records never rewrite user history, and an unchanged semantic payload is
    idempotent.
    """

    active = {
        str(item.get("requirement_id")): item
        for item in active_requirements(ledger)
        if item.get("requirement_id")
    }
    changes: list[dict[str, Any]] = []
    for item in incoming:
        requirement_id = str(item.get("requirement_id") or "")
        existing = active.get(requirement_id)
        if not requirement_id or existing is None:
            continue
        if item.get("source") not in {"initial_user", "clarification", "clarification_user", "physical_test_feedback"}:
            continue
        incoming_semantic = {
            key: item.get(key)
            for key in ("kind", "operator", "subject", "object_type", "target", "raw_evidence")
            if item.get(key) is not None
        }
        existing_semantic = {
            key: existing.get(key)
            for key in ("kind", "operator", "subject", "object_type", "target", "raw_evidence")
            if existing.get(key) is not None
        }
        if not incoming_semantic or incoming_semantic == existing_semantic:
            continue
        changes.append(
            {
                **item,
                "operation": "change",
                "requirement_id": requirement_id,
                "source": item.get("source"),
                "explicit": True,
            }
        )
    return changes


def _entry_payload(row: RequirementLedgerEntry) -> dict[str, Any]:
    verification_evidence = _parse_json(row.verification_evidence_json)
    semantic = (
        verification_evidence.get("semantic")
        if isinstance(verification_evidence, dict)
        else None
    )
    if not isinstance(semantic, dict):
        semantic = {}
    evidence = (
        verification_evidence.get("evidence")
        if isinstance(verification_evidence, dict) and "evidence" in verification_evidence
        else verification_evidence
    )
    provenance = (
        verification_evidence.get("provenance")
        if isinstance(verification_evidence, dict)
        else None
    )
    return normalize_requirement_semantics({
        "record_id": row.id,
        "requirement_id": row.requirement_id,
        "source": row.source,
        "target": _parse_json(row.target_json),
        "type": row.requirement_type,
        "value": _parse_json(row.value_json),
        "unit": row.unit,
        "tolerance": _parse_json(row.tolerance_json),
        "explicit": row.explicit,
        "status": row.status,
        "originating_message": row.originating_message,
        "originating_revision_id": row.originating_revision_id,
        "supersedes_requirement_id": row.supersedes_requirement_id,
        "superseded_by": row.superseded_by,
        "verification_evidence": evidence,
        "provenance": provenance,
        "kind": semantic.get("kind") or _kind_from_legacy_row(row),
        "operator": semantic.get("operator") or _operator_from_legacy_row(row),
                        "subject": semantic.get("subject"),
                        "object_type": semantic.get("object_type"),
                        "raw_evidence": semantic.get("raw_evidence"),
                        "source_fact_id": semantic.get("source_fact_id"),
                        "source_fact_type": semantic.get("source_fact_type"),
                        "source_fact_evidence": semantic.get("source_fact_evidence"),
                        "classification": semantic.get("classification"),
        "policy": semantic.get("policy"),
        "verification_policy": semantic.get("verification_policy"),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    })


def _json_value(value: Any) -> str | None:
    return None if value is None else json.dumps(value, sort_keys=True, default=str)


def _parse_json(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _kind_from_legacy_row(row: RequirementLedgerEntry) -> str:
    requirement_type = str(row.requirement_type or "qualitative_behavior")
    if requirement_type in {"capacity", "minimum_capacity", "maximum_capacity"}:
        return "capacity"
    if "count" in requirement_type or row.unit == "count":
        return "count"
    if "dimension" in requirement_type or requirement_type in {"clearance", "fit", "spacing", "position"}:
        return "dimension" if requirement_type.endswith("dimension") else requirement_type
    if requirement_type in {"explicit_feature", "feature_presence", "feature_absence"}:
        return "feature"
    return requirement_type


def _operator_from_legacy_row(row: RequirementLedgerEntry) -> str:
    requirement_type = str(row.requirement_type or "qualitative_behavior")
    if "maximum" in requirement_type:
        return "maximum"
    if "minimum" in requirement_type:
        return "minimum"
    if requirement_type in {"qualitative_behavior"}:
        return "qualitative"
    if requirement_type == "explicit_feature":
        return "present" if _parse_json(row.value_json) is True else "absent"
    return "exact"


def _normalize_requirement(
    item: dict[str, Any],
    *,
    default_source: str,
    originating_message: str | None,
    originating_revision_id: str | None,
) -> dict[str, Any] | None:
    requirement_id = _requirement_id(item)
    if not requirement_id:
        return None
    source = str(item.get("source") or default_source)
    if source not in VALID_SOURCES:
        source = default_source
    status = str(item.get("status") or ACTIVE)
    if status not in VALID_STATUSES:
        status = ACTIVE
    now = _now()
    normalized = {
        "record_id": str(item.get("record_id") or uuid4()),
        "requirement_id": requirement_id,
        "source": source,
        "target": item.get("target"),
        "type": str(item.get("type") or item.get("requirement_type") or "qualitative_behavior"),
        "value": item.get("value"),
        "unit": item.get("unit"),
        "tolerance": item.get("tolerance"),
        "explicit": bool(item.get("explicit", item.get("authority") == "explicit")),
        "status": status,
        "originating_message": item.get("originating_message") or originating_message,
        "originating_revision_id": item.get("originating_revision_id") or originating_revision_id,
        "supersedes_requirement_id": item.get("supersedes_requirement_id"),
        "superseded_by": item.get("superseded_by"),
        "verification_evidence": item.get("verification_evidence"),
        "created_at": item.get("created_at") or now,
        "updated_at": now,
    }
    for key in (
        "kind",
        "operator",
        "subject",
        "object_type",
        "raw_evidence",
        "source_fact_id",
        "source_fact_type",
        "source_fact_evidence",
        "classification",
        "policy",
        "verification_policy",
    ):
        if item.get(key) is not None:
            normalized[key] = item[key]
    if item.get("provenance") is not None:
        normalized["provenance"] = item["provenance"]
    return normalize_requirement_semantics(normalized)


def _dedupe_active(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in records:
        requirement_id = str(item.get("requirement_id") or "")
        if not requirement_id or requirement_id in seen:
            continue
        seen.add(requirement_id)
        result.append(item)
    return result


def _requirement_id(item: dict[str, Any]) -> str:
    return str(item.get("requirement_id") or item.get("id") or "").strip()


def _observation(message: str, observation_type: str, source: str) -> dict[str, Any]:
    return {
        "observation_id": str(uuid4()),
        "source": source,
        "observation_type": observation_type,
        "observation": message,
        "created_at": _now(),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
