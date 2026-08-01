"""Deterministic planning-depth selection.

The router deliberately reasons about the requirement ledger and project state,
not the name of the requested object.  Its output is an execution decision;
the ledger remains authoritative for what the design must satisfy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Iterable


class PlanningDepth(StrEnum):
    CLARIFICATION_REQUIRED = "clarification_required"
    DIRECT_BRIEF = "direct_brief"
    COMPACT_PLAN = "compact_plan"
    DETAILED_PLAN = "detailed_plan"


@dataclass(frozen=True)
class PlanningRouteDecision:
    outcome: PlanningDepth
    policy_version: str = "planning-depth-v1"
    reasons: list[str] = field(default_factory=list)
    ambiguous_factors: list[dict[str, Any]] = field(default_factory=list)
    missing_information: list[dict[str, Any]] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": "planning-route-decision-v1",
            "outcome": self.outcome.value,
            "policy_version": self.policy_version,
            "reasons": list(self.reasons),
            "ambiguous_factors": list(self.ambiguous_factors),
            "missing_information": list(self.missing_information),
        }


class PlanningDepthRouter:
    """Select the smallest sufficient planning contract."""

    _INTERACTING_TYPES = {
        "fit",
        "clearance",
        "support",
        "retention",
        "removal_access",
        "containment",
        "mounting_interface",
        "relationship",
        "process_constraint",
    }
    _CRITICAL_MISSING_TYPES = {
        "fit",
        "clearance",
        "containment",
        "mounting_interface",
        "position",
        "orientation",
        "relationship",
    }

    def route(
        self,
        *,
        active_requirements: Iterable[dict[str, Any]],
        project_state: dict[str, Any] | None = None,
        specification: dict[str, Any] | None = None,
        revision_scope: dict[str, Any] | None = None,
    ) -> PlanningRouteDecision:
        requirements = [item for item in active_requirements if isinstance(item, dict)]
        state = project_state or {}
        spec = specification or {}
        revision = revision_scope or {}

        missing = self._missing_critical_information(requirements, spec)
        conflicts = self._conflicts(spec, requirements)
        if missing or conflicts:
            reasons = []
            if missing:
                reasons.append("critical information is missing from the active requirement ledger")
            if conflicts:
                reasons.append("active requirements contain a contradiction that needs resolution")
            return PlanningRouteDecision(
                PlanningDepth.CLARIFICATION_REQUIRED,
                reasons=reasons,
                ambiguous_factors=conflicts,
                missing_information=missing,
            )

        component_count = self._count(state, "printable_component_count", "components")
        output_count = self._count(state, "output_count", "printable_outputs")
        relationships = self._items(
            state.get("assembly_relationships"),
            state.get("moving_interfaces"),
            state.get("mating_interfaces"),
            revision.get("preserved_relationships"),
        )
        if component_count > 1 or output_count > 1 or relationships:
            return PlanningRouteDecision(
                PlanningDepth.DETAILED_PLAN,
                reasons=["multiple printable components or preserved assembly relationships require a detailed plan"],
            )

        types = {str(item.get("type") or item.get("requirement_type")) for item in requirements}
        functional_types = types & self._INTERACTING_TYPES
        feature_count = self._count(state, "functional_feature_count", "functional_features")
        if len(functional_types) >= 2 or feature_count >= 2 or revision.get("interacting_features"):
            return PlanningRouteDecision(
                PlanningDepth.COMPACT_PLAN,
                reasons=["interacting functional features require a compact plan"],
            )

        return PlanningRouteDecision(
            PlanningDepth.DIRECT_BRIEF,
            reasons=["single printable component with sufficiently specified requirements can use a deterministic direct brief"],
        )

    def route_revision(
        self,
        *,
        active_requirements: Iterable[dict[str, Any]],
        revision_delta: Iterable[dict[str, Any]],
        project_state: dict[str, Any] | None = None,
        preserved_relationships: Iterable[dict[str, Any]] = (),
    ) -> PlanningRouteDecision:
        delta = [item for item in revision_delta if isinstance(item, dict)]
        affected_types = {str(item.get("type") or item.get("requirement_type")) for item in delta}
        state = dict(project_state or {})
        state["functional_feature_count"] = max(
            int(state.get("functional_feature_count") or 0),
            len(affected_types),
        )
        return self.route(
            active_requirements=active_requirements,
            project_state=state,
            revision_scope={
                "interacting_features": len(affected_types) >= 2,
                "preserved_relationships": list(preserved_relationships),
            },
        )

    @staticmethod
    def _count(state: dict[str, Any], scalar_key: str, collection_key: str) -> int:
        value = state.get(scalar_key)
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return max(0, int(value))
        collection = state.get(collection_key)
        return len(collection) if isinstance(collection, (list, tuple, set, dict)) else 0

    @staticmethod
    def _items(*values: Any) -> list[Any]:
        result: list[Any] = []
        for value in values:
            if isinstance(value, (list, tuple, set)):
                result.extend(value)
            elif value:
                result.append(value)
        return result

    def _missing_critical_information(
        self,
        requirements: list[dict[str, Any]],
        specification: dict[str, Any],
    ) -> list[dict[str, Any]]:
        missing: list[dict[str, Any]] = []
        declared = specification.get("missing_requirements") or []
        for item in requirements:
            requirement_type = str(item.get("type") or item.get("requirement_type") or "")
            importance = str(item.get("importance") or item.get("priority") or "").lower()
            value = item.get("value", item.get("expected_value"))
            if importance not in {"critical", "must", "blocking"}:
                continue
            if requirement_type not in self._CRITICAL_MISSING_TYPES:
                continue
            if value is None or value == "":
                missing.append({
                    "requirement_id": item.get("requirement_id") or item.get("id"),
                    "type": requirement_type,
                    "reason": "a critical fit or interface value is not supplied",
                })
        for item in declared:
            if not isinstance(item, dict):
                continue
            importance = str(item.get("importance") or item.get("priority") or "").lower()
            if importance in {"critical", "must", "blocking"}:
                requirement_id = item.get("requirement_id") or item.get("id")
                if not any(entry.get("requirement_id") == requirement_id for entry in missing):
                    missing.append({
                        "requirement_id": requirement_id,
                        "type": item.get("type") or item.get("requirement_type"),
                        "reason": item.get("reason") or "critical information is missing",
                    })
        return missing

    @staticmethod
    def _conflicts(specification: dict[str, Any], requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
        conflicts = specification.get("conflicts") or []
        result = [item for item in conflicts if isinstance(item, dict)]
        result.extend(
            item for item in requirements
            if isinstance(item, dict) and str(item.get("status") or "").lower() == "conflict"
        )
        return result
