from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from app.services.gemini_integration.adapters import (
    GeminiGeometryContractAdapter,
    GeminiPlanContractAdapter,
    GeminiRequirementsContractAdapter,
)
from app.services.gemini_consistency.provider_contract import canonical_hash


STAGE_ORDER = {
    "input": 0,
    "requirements": 1,
    "plan": 2,
    "geometry": 3,
    "source_assembly": 4,
    "static_validation": 5,
    "worker": 6,
    "artifacts": 7,
    "topology": 8,
    "verification": 9,
    "candidate": 10,
}
RELATIONSHIPS = {"caused_by", "contributes_to", "masks", "blocked_by", "exposed_after", "independent_of", "duplicate_of"}
CONFIDENCE_FACTOR = {"confirmed": 1.0, "high_confidence": 0.8, "probable": 0.6, "possible": 0.35, "unknown": 0.1}


@dataclass(frozen=True)
class IssueRecord:
    issue_id: str
    project_id: str
    stage: str
    primary_owner: str
    secondary_factors: tuple[str, ...]
    classification: str
    symptom: str
    incorrect_behavior: str
    expected_behavior: str
    evidence_paths: tuple[str, ...]
    input_hashes: tuple[str, ...]
    output_hashes: tuple[str, ...]
    confidence: str
    recommended_fix_boundary: str
    provider_call_required: bool
    caused_by: tuple[str, ...] = ()
    contributes_to: tuple[str, ...] = ()
    masks: tuple[str, ...] = ()
    blocked_by: tuple[str, ...] = ()
    exposed_after: tuple[str, ...] = ()
    independent_of: tuple[str, ...] = ()
    counterfactual: dict[str, Any] = field(default_factory=lambda: {"run": False, "single_variable_changed": None, "result": None})
    reproduction: dict[str, Any] = field(default_factory=lambda: {"deterministic": False, "steps": []})
    status: str = "open"

    def as_dict(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "project_id": self.project_id,
            "stage": self.stage,
            "primary_owner": self.primary_owner,
            "secondary_factors": list(self.secondary_factors),
            "classification": self.classification,
            "symptom": self.symptom,
            "incorrect_behavior": self.incorrect_behavior,
            "expected_behavior": self.expected_behavior,
            "evidence_paths": list(self.evidence_paths),
            "input_hashes": list(self.input_hashes),
            "output_hashes": list(self.output_hashes),
            "caused_by": list(self.caused_by),
            "contributes_to": list(self.contributes_to),
            "masks": list(self.masks),
            "blocked_by": list(self.blocked_by),
            "exposed_after": list(self.exposed_after),
            "independent_of": list(self.independent_of),
            "counterfactual": dict(self.counterfactual),
            "reproduction": dict(self.reproduction),
            "confidence": self.confidence,
            "recommended_fix_boundary": self.recommended_fix_boundary,
            "provider_call_required": self.provider_call_required,
            "status": self.status,
        }


class IssueRegister:
    def __init__(self) -> None:
        self._issues: dict[str, IssueRecord] = {}

    def add(self, issue: IssueRecord) -> IssueRecord:
        if issue.issue_id in self._issues:
            raise ValueError(f"issue ID already exists: {issue.issue_id}")
        self._issues[issue.issue_id] = issue
        return issue

    def all(self) -> list[IssueRecord]:
        return list(self._issues.values())

    def for_project(self, project_id: str) -> list[IssueRecord]:
        return [issue for issue in self._issues.values() if issue.project_id == project_id]

    def earliest_blocker(self, project_id: str) -> IssueRecord | None:
        issues = self.for_project(project_id)
        if not issues:
            return None
        return min(issues, key=lambda issue: (STAGE_ORDER.get(issue.stage, 99), issue.issue_id))

    def as_dict(self) -> list[dict[str, Any]]:
        return [issue.as_dict() for issue in self._issues.values()]


class CausalGraph:
    def __init__(self) -> None:
        self._nodes: set[str] = set()
        self._edges: list[dict[str, str]] = []

    def add(self, source: str, target: str, relationship: str) -> None:
        if relationship not in RELATIONSHIPS:
            raise ValueError(f"unsupported causal relationship: {relationship}")
        self._nodes.update((source, target))
        edge = {"source": source, "target": target, "relationship": relationship}
        if edge not in self._edges:
            self._edges.append(edge)

    def as_dict(self) -> dict[str, Any]:
        return {"nodes": sorted(self._nodes), "edges": list(self._edges)}


@dataclass(frozen=True)
class CounterfactualFixture:
    fixture_id: str
    project_id: str
    single_variable_changed: str
    evidence: dict[str, Any]
    provider_success_eligible: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "project_id": self.project_id,
            "single_variable_changed": self.single_variable_changed,
            "evidence": {**self.evidence, "synthetic": True},
            "provider_success_eligible": False,
        }


@dataclass(frozen=True)
class DifferentialReplay:
    before: dict[str, Any]
    after: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        fields = ("semantic_hash", "adapter_actions", "source", "furthest_valid_stage", "worker_result", "artifact_result", "topology", "verification", "issues")
        changed = [field for field in fields if self.before.get(field) != self.after.get(field)]
        before_issues = set(self.before.get("issues") or [])
        after_issues = set(self.after.get("issues") or [])
        issue_removed = sorted(before_issues - after_issues)
        return {
            "changed_outcomes": changed,
            "attribution": [field for field in changed if field != "issues" or issue_removed],
            "issue_removed": issue_removed,
            "fix_confirmed": bool(issue_removed),
            "before": self.before,
            "after": self.after,
        }


def count_provider_successes(records: Iterable[Any]) -> int:
    return sum(
        1
        for record in records
        if isinstance(record, dict) and record.get("success") is True and record.get("provider_success_eligible", True) is True and not (record.get("evidence") or {}).get("synthetic", False)
    )


def replay_evidence_offline(evidence: dict[str, Any], *, validators: Iterable[Callable[[Any], Any]] = ()) -> dict[str, Any]:
    records = []
    for outcome in evidence.get("project_outcomes", []) or []:
        validated = [validator(outcome) for validator in validators]
        records.append({"outcome": outcome, "validation": validated})
    return {
        "offline_only": True,
        "provider_calls": 0,
        "worker_calls": 0,
        "records": records,
        "preserved_attempt_count": len(evidence.get("provider_attempts", []) or []),
    }


def replay_captured_evidence_offline(
    evidence: dict[str, Any],
    *,
    boundaries: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Re-run stage adapters over captured provider responses without I/O."""

    adapters = {
        "requirements": GeminiRequirementsContractAdapter(),
        "plan": GeminiPlanContractAdapter(),
        "geometry": GeminiGeometryContractAdapter(),
    }
    boundary_records = list(boundaries or [])
    project_records = {
        str(item.get("project_id")): item
        for item in evidence.get("projects", []) or []
        if isinstance(item, dict) and item.get("project_id") is not None
    }
    provider_boundary_by_attempt: dict[str, dict[str, Any]] = {}
    adapter_boundaries_by_project: dict[str, list[dict[str, Any]]] = {}
    for boundary in boundary_records:
        project_id = str(boundary.get("project_id") or "")
        adapter_boundaries_by_project.setdefault(project_id, []).append(boundary)
        if not str(boundary.get("boundary") or "").startswith("provider_"):
            continue
        output = boundary.get("output") or {}
        for attempt_id in output.get("attempt_ids", []) or []:
            provider_boundary_by_attempt[str(attempt_id)] = boundary

    def project_context(project_id: str) -> dict[str, Any]:
        project = project_records.get(project_id) or {}
        return {
            "fit_critical_missing": list(project.get("fit_critical_missing", []) or []),
        }

    def requirement_ids(project_id: str) -> list[str]:
        for boundary in adapter_boundaries_by_project.get(project_id, []):
            if boundary.get("boundary") != "requirements_adapter":
                continue
            output = boundary.get("output") or {}
            if output.get("accepted") is not True:
                continue
            normalized = output.get("normalized") or {}
            return [
                str(item.get("id"))
                for item in normalized.get("requirements", []) or []
                if isinstance(item, dict) and item.get("id") is not None
            ]
        return []

    def authoritative_geometry_context(attempt: dict[str, Any], project_id: str) -> dict[str, Any]:
        provider_boundary = provider_boundary_by_attempt.get(str(attempt.get("attempt_id")))
        request = ((provider_boundary or {}).get("input") or {}).get("request") or {}
        manifest = request.get("geometry_slot_manifest") if isinstance(request, dict) else None
        if not isinstance(manifest, dict):
            return {}
        allowed_names = {"body", "cq", "params", "cutter"}
        for slot in manifest.get("slots", []) or []:
            if not isinstance(slot, dict):
                continue
            allowed_names.update(str(item) for item in slot.get("authorized_parameter_ids", []) or [])
            allowed_names.update(str(item) for item in slot.get("approved_helpers", []) or [])
        return {
            "expected_slot_ids": [
                item.get("slot_id")
                for item in manifest.get("slots", []) or []
                if isinstance(item, dict) and item.get("slot_id") is not None
            ],
            "allowed_names": sorted(allowed_names),
            "manifest_hash": canonical_hash(manifest),
            "prompt_hash": ((provider_boundary or {}).get("input") or {}).get("prompt_hash"),
        }

    records: list[dict[str, Any]] = []
    for attempt in evidence.get("provider_attempts", []) or []:
        stage = str(attempt.get("stage") or "")
        response = attempt.get("response") or {}
        raw = _response_text_from_payload(response) if isinstance(response, dict) else None
        adapter = adapters.get(stage)
        if adapter is None or raw is None:
            records.append({"attempt_id": attempt.get("attempt_id"), "stage": stage, "replayed": False, "reason": "no replayable content"})
            continue
        context = {
            "project_id": attempt.get("project_id"),
            "revision_id": attempt.get("revision_id"),
            "provenance": {"study_id": (evidence.get("study") or {}).get("study_id"), "synthetic": False},
        }
        project_id = str(attempt.get("project_id") or "")
        context.update(project_context(project_id))
        if stage == "plan":
            project = project_records.get(project_id) or {}
            context["expected_output_count"] = project.get("expected_output_count")
            context["required_requirement_ids"] = requirement_ids(project_id)
        if stage == "geometry":
            authoritative = authoritative_geometry_context(attempt, project_id)
            if authoritative:
                context.update(authoritative)
            else:
                try:
                    parsed = json.loads(raw)
                    context["expected_slot_ids"] = [item.get("slot_id") for item in parsed.get("slots", []) if isinstance(item, dict)]
                except (TypeError, ValueError):
                    context["expected_slot_ids"] = []
        result = adapter.adapt(raw, context)
        records.append({
            "attempt_id": attempt.get("attempt_id"),
            "stage": stage,
            "replayed": True,
            "provider_success_eligible": False,
            "authoritative_context": {
                key: context[key]
                for key in ("expected_output_count", "required_requirement_ids", "fit_critical_missing", "expected_slot_ids", "allowed_names", "manifest_hash", "prompt_hash")
                if key in context
            },
            "adapter": result.as_dict(),
        })
    return {"offline_only": True, "provider_calls": 0, "worker_calls": 0, "records": records}


def _response_text_from_payload(payload: dict[str, Any]) -> str | None:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return None
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list):
            continue
        text = "".join(str(item.get("text")) for item in parts if isinstance(item, dict) and item.get("text") is not None)
        if text:
            return text
    return None


def rank_issues(issues: Iterable[tuple[IssueRecord, dict[str, float]]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for issue, factors in issues:
        confidence = factors.get("confidence", CONFIDENCE_FACTOR.get(issue.confidence, 0.1))
        cost = max(float(factors.get("estimated_correction_cost", 1.0)), 0.000001)
        score = (
            float(factors.get("frequency", 0.0))
            * float(factors.get("severity", 0.0))
            * confidence
            * float(factors.get("downstream_impact", 0.0))
            / cost
        )
        ranked.append({"issue_id": issue.issue_id, "raw_factors": dict(factors), "raw_score": round(score, 6)})
    return sorted(ranked, key=lambda item: (-item["raw_score"], item["issue_id"]))


__all__ = [
    "CausalGraph",
    "CounterfactualFixture",
    "DifferentialReplay",
    "IssueRecord",
    "IssueRegister",
    "count_provider_successes",
    "rank_issues",
    "replay_captured_evidence_offline",
    "replay_evidence_offline",
]
