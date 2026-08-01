"""Immutable normalized execution and prompt context contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable


def _canonical(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return [item for item in value]
    if isinstance(value, tuple):
        return list(value)
    return []


def normalize_geometry_execution_context(
    *,
    planning_depth: str,
    plan_artifact_id: str | None,
    plan: dict[str, Any],
    active_requirements: Iterable[dict[str, Any]] = (),
    revision_delta: Iterable[dict[str, Any]] = (),
    preserved_requirements: Iterable[dict[str, Any]] = (),
    source_plan_kind: str | None = None,
    source_plan_version: str | None = None,
) -> dict[str, Any]:
    components = _list(plan.get("components"))
    features = _list(plan.get("features") or plan.get("required_features"))
    outputs = plan.get("printable_outputs")
    if not outputs:
        outputs = plan.get("outputs") or []
    return {
        "schema_version": "geometry-execution-context-v1",
        "planning_depth": planning_depth,
        "source_plan": {
            "artifact_id": plan_artifact_id,
            "kind": source_plan_kind or plan.get("schema_version"),
            "schema_version": source_plan_version or plan.get("schema_version"),
        },
        "plan_artifact_id": plan_artifact_id,
        "active_requirements": [dict(item) for item in active_requirements if isinstance(item, dict)],
        "revision_delta": [dict(item) for item in revision_delta if isinstance(item, dict)],
        "preserve_requirements": [dict(item) for item in preserved_requirements if isinstance(item, dict)],
        "components": components,
        "features": features,
        "relationships": _list(plan.get("relationships")),
        "proposals": _list(plan.get("proposals")),
        "coordinate_frames": _list(plan.get("coordinate_frames") or plan.get("coordinate_systems")),
        "validation_targets": _list(plan.get("validation_targets")),
        "exposed_controls": _list(plan.get("exposed_controls")),
        "outputs": outputs,
    }


class PromptContextPackBuilder:
    """Select relevant immutable context for one generation or repair attempt."""

    def build(
        self,
        *,
        project_id: str,
        workflow_run_id: str,
        planning_depth: str,
        active_requirements: Iterable[dict[str, Any]],
        revision_delta: Iterable[dict[str, Any]],
        preserved_requirements: Iterable[dict[str, Any]],
        plan_artifact: dict[str, Any],
        selected_components: Iterable[str],
        selected_features: Iterable[str],
        current_revision_summary: dict[str, Any],
        relevant_findings: Iterable[dict[str, Any]],
        scaffold_contract: dict[str, Any],
        exposed_controls: Iterable[dict[str, Any]],
        unrelated_history: Iterable[dict[str, Any]] = (),
        prompt_version: str = "prompt-context-pack-v1",
        token_count: int | None = None,
    ) -> dict[str, Any]:
        requirements = [dict(item) for item in active_requirements if isinstance(item, dict)]
        delta = [dict(item) for item in revision_delta if isinstance(item, dict)]
        preserved = [dict(item) for item in preserved_requirements if isinstance(item, dict)]
        findings = [dict(item) for item in relevant_findings if isinstance(item, dict)]
        controls = [dict(item) for item in exposed_controls if isinstance(item, dict)]
        artifact_id = plan_artifact.get("artifact_id") if isinstance(plan_artifact, dict) else None
        selected = {
            "active_requirements": requirements,
            "revision_delta": delta,
            "preserved_requirements": preserved,
            "plan_artifact": plan_artifact,
            "selected_components": sorted({str(item) for item in selected_components}),
            "selected_features": sorted({str(item) for item in selected_features}),
            "current_revision_summary": current_revision_summary or {},
            "relevant_findings": findings,
            "scaffold_contract": scaffold_contract or {},
            "exposed_controls": controls,
        }
        pack = {
            "schema_version": "prompt-context-pack-v1",
            "project_id": project_id,
            "workflow_run_id": workflow_run_id,
            "planning_depth": planning_depth,
            "prompt_version": prompt_version,
            "included_artifact_ids": [artifact_id] if artifact_id else [],
            "included_requirement_ids": sorted({
                str(item.get("requirement_id") or item.get("id"))
                for item in [*requirements, *delta, *preserved]
                if item.get("requirement_id") or item.get("id")
            }),
            "included_context": selected,
            "excluded_context_categories": ["unrelated_history"],
            "inclusion_reasons": {
                "active_requirements": "authoritative active requirement ledger",
                "revision_delta": "current requested change, if any",
                "preserved_requirements": "requirements explicitly preserved across this attempt",
                "plan_artifact": "selected branch-specific execution plan",
                "scaffold_contract": "safe geometry assembly contract",
            },
            "exclusion_reasons": {
                "unrelated_history": "not relevant to the current branch or requested change",
            },
            "token_count": token_count,
        }
        pack["context_hash"] = hashlib.sha256(_canonical(pack).encode("utf-8")).hexdigest()
        return pack
