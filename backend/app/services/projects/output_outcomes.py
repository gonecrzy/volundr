"""Authoritative output and candidate outcome resolution.

This module deliberately consumes persisted evidence rather than trusting a
materialized status field.  Reports, candidate promotion, exports, and the
debug-batch surfaces can therefore agree when a derived manifest is stale.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence


OUTPUT_OUTCOME_STATES = frozenset(
    {
        "source_blocked",
        "worker_failed",
        "missing_required_output",
        "incomplete_artifacts",
        "invalid_topology",
        "valid_geometry_unverified",
        "verification_blocked",
        "artifact_readiness_blocked",
        "candidate_ready",
        "candidate_ready_with_warnings",
        "candidate_blocked",
        "interrupted",
    }
)

READY_OUTCOME_STATES = frozenset(
    {"candidate_ready", "candidate_ready_with_warnings", "valid_geometry_unverified"}
)
STALE_DERIVED_RULES = frozenset(
    {"design_artifact.manifest_required_output_not_ready"}
)


@dataclass(frozen=True)
class OutputOutcome:
    state: str
    worker_reached: bool
    source_valid: bool | None
    expected_output_ids: tuple[str, ...] = ()
    missing_output_ids: tuple[str, ...] = ()
    incomplete_output_ids: tuple[str, ...] = ()
    invalid_topology_output_ids: tuple[str, ...] = ()
    blocking_rule_ids: tuple[str, ...] = ()
    integrity_findings: tuple[dict[str, Any], ...] = ()
    parent_current_revision_id: str | None = None
    revision_id: str | None = None
    verification_status: str = "unverified"

    @property
    def is_candidate_eligible(self) -> bool:
        return self.state in READY_OUTCOME_STATES

    @property
    def has_valid_geometry(self) -> bool:
        return self.state in READY_OUTCOME_STATES or self.state in {
            "verification_blocked",
            "candidate_blocked",
            "artifact_readiness_blocked",
        }


def resolve_output_outcome(
    *,
    expected_outputs: Sequence[Any],
    worker_status: str | None,
    registered_artifacts: Sequence[Any] | None = None,
    artifact_readiness_findings: Iterable[Any] = (),
    verification_findings: Iterable[Any] = (),
    candidate_findings: Iterable[Any] = (),
    source_valid: bool | None = True,
    source_blocked: bool = False,
    parent_current_revision_id: str | None = None,
    revision_id: str | None = None,
    verification_status: str | None = None,
) -> OutputOutcome:
    """Resolve one canonical state from expected and observed output evidence."""

    expected = [_as_mapping(item) for item in expected_outputs]
    artifacts = {_value(item, "output_id"): item for item in (registered_artifacts or expected)}
    artifact_findings = list(artifact_readiness_findings)
    candidate_finding_items = list(candidate_findings)
    expected_ids = tuple(
        str(_value(item, "output_id"))
        for item in expected
        if _value(item, "output_id")
    )
    worker_reached = worker_status in {"succeeded", "failed"}
    if source_blocked or source_valid is False:
        return _outcome(
            "source_blocked",
            worker_reached=False,
            source_valid=source_valid,
            expected_output_ids=expected_ids,
            parent_current_revision_id=parent_current_revision_id,
            revision_id=revision_id,
        )
    if worker_status in {None, "pending", "queued", "running", "compiling"}:
        return _outcome(
            "interrupted",
            worker_reached=worker_reached,
            source_valid=source_valid,
            expected_output_ids=expected_ids,
            parent_current_revision_id=parent_current_revision_id,
            revision_id=revision_id,
        )
    if worker_status != "succeeded":
        return _outcome(
            "worker_failed",
            worker_reached=True,
            source_valid=source_valid,
            expected_output_ids=expected_ids,
            blocking_rule_ids=("cad_execution.failed",),
            parent_current_revision_id=parent_current_revision_id,
            revision_id=revision_id,
        )

    missing: list[str] = []
    incomplete: list[str] = []
    invalid_topology: list[str] = []
    for item in expected:
        output_id = str(_value(item, "output_id") or "")
        if not output_id or output_id not in artifacts:
            if _bool(item, "required", default=True):
                missing.append(output_id)
            continue
        artifact = artifacts[output_id]
        if _value(artifact, "compile_error") and not _has_any_artifact(artifact):
            if _bool(item, "required", default=True):
                incomplete.append(output_id)
            continue
        if not _artifacts_complete(item, artifact):
            if _bool(item, "required", default=True):
                incomplete.append(output_id)
            continue
        topology = _topology(artifact)
        expected_solids = _value(item, "expected_solid_count")
        detected_solids = topology.get("detected_solid_count")
        topology_valid = topology.get("valid") is not False
        if (
            expected_solids is not None
            and detected_solids is not None
            and int(expected_solids) != int(detected_solids)
            and not _bool(item, "allow_disconnected_solids", default=False)
        ):
            topology_valid = False
        if not topology_valid:
            invalid_topology.append(output_id)

    if missing:
        return _outcome(
            "missing_required_output",
            worker_reached=True,
            source_valid=source_valid,
            expected_output_ids=expected_ids,
            missing_output_ids=tuple(missing),
            parent_current_revision_id=parent_current_revision_id,
            revision_id=revision_id,
        )
    if incomplete:
        return _outcome(
            "incomplete_artifacts",
            worker_reached=True,
            source_valid=source_valid,
            expected_output_ids=expected_ids,
            incomplete_output_ids=tuple(incomplete),
            parent_current_revision_id=parent_current_revision_id,
            revision_id=revision_id,
        )
    if invalid_topology:
        return _outcome(
            "invalid_topology",
            worker_reached=True,
            source_valid=source_valid,
            expected_output_ids=expected_ids,
            invalid_topology_output_ids=tuple(invalid_topology),
            parent_current_revision_id=parent_current_revision_id,
            revision_id=revision_id,
        )

    integrity_findings: list[dict[str, Any]] = []
    actual_artifact_blockers: list[str] = []
    for finding in artifact_findings:
        rule_id = str(_value(finding, "rule_id") or "artifact_readiness.blocked")
        if _is_blocking(finding):
            if rule_id in STALE_DERIVED_RULES:
                integrity_findings.append(
                    {
                        "rule_id": "integrity.stale_output_manifest_state",
                        "severity": "warning",
                        "blocking": False,
                        "message": "A materialized output state was stale; canonical output evidence passed.",
                        "source_rule_id": rule_id,
                    }
                )
            else:
                actual_artifact_blockers.append(rule_id)
    if actual_artifact_blockers:
        return _outcome(
            "artifact_readiness_blocked",
            worker_reached=True,
            source_valid=source_valid,
            expected_output_ids=expected_ids,
            blocking_rule_ids=tuple(actual_artifact_blockers),
            integrity_findings=tuple(integrity_findings),
            parent_current_revision_id=parent_current_revision_id,
            revision_id=revision_id,
        )

    verification = list(verification_findings)
    verification_blockers = [
        str(_value(item, "rule_id") or "functional.verification_blocked")
        for item in verification
        if _is_blocking(item)
    ]
    if verification_blockers:
        return _outcome(
            "verification_blocked",
            worker_reached=True,
            source_valid=source_valid,
            expected_output_ids=expected_ids,
            blocking_rule_ids=tuple(verification_blockers),
            integrity_findings=tuple(integrity_findings),
            parent_current_revision_id=parent_current_revision_id,
            revision_id=revision_id,
            verification_status="blocked",
        )

    candidate_blockers = [
        str(_value(item, "rule_id") or "candidate.blocked")
        for item in candidate_finding_items
        if _is_blocking(item) and str(_value(item, "rule_id") or "") not in STALE_DERIVED_RULES
    ]
    if candidate_blockers:
        return _outcome(
            "candidate_blocked",
            worker_reached=True,
            source_valid=source_valid,
            expected_output_ids=expected_ids,
            blocking_rule_ids=tuple(candidate_blockers),
            integrity_findings=tuple(integrity_findings),
            parent_current_revision_id=parent_current_revision_id,
            revision_id=revision_id,
        )

    status = verification_status or ("verified" if verification else "unverified")
    warnings = any(
        not _is_blocking(item)
        for item in (*verification, *artifact_findings, *candidate_finding_items)
    )
    state = (
        "candidate_ready_with_warnings"
        if warnings
        else "candidate_ready"
        if status == "verified"
        else "valid_geometry_unverified"
    )
    return _outcome(
        state,
        worker_reached=True,
        source_valid=source_valid,
        expected_output_ids=expected_ids,
        integrity_findings=tuple(integrity_findings),
        parent_current_revision_id=parent_current_revision_id,
        revision_id=revision_id,
        verification_status=status,
    )


def _outcome(state: str, **kwargs: Any) -> OutputOutcome:
    if state not in OUTPUT_OUTCOME_STATES:
        raise ValueError(f"unsupported output outcome state: {state}")
    return OutputOutcome(state=state, **kwargs)


def _as_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        return value
    return value


def _value(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _bool(value: Any, name: str, *, default: bool = False) -> bool:
    raw = _value(value, name, default)
    return raw if isinstance(raw, bool) else bool(raw)


def _is_blocking(value: Any) -> bool:
    return bool(_value(value, "is_blocking", _value(value, "blocking", False)))


def _topology(value: Any) -> dict[str, Any]:
    raw = _value(value, "topology_metadata", None)
    if raw is None:
        raw = _value(value, "topology", None)
    if raw is None:
        raw = _value(value, "topology_metadata_json", None)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return raw if isinstance(raw, dict) else {}


def _required_formats(expected: Any) -> tuple[str, ...]:
    formats = _value(expected, "required_artifact_formats", None)
    if formats is None and isinstance(expected, dict):
        formats = expected.get("artifact_formats")
    if formats is None:
        return ("stl",)
    return tuple(str(item).lower() for item in formats if item)


def _artifact_node(value: Any, name: str) -> tuple[Any, Any]:
    path = _value(value, f"{name}_path", None)
    digest = _value(value, f"{name}_hash", None)
    if isinstance(value, dict):
        node = value.get(name)
        if isinstance(node, dict):
            path = node.get("path", path)
            digest = node.get("sha256", digest)
    return path, digest


def _has_any_artifact(value: Any) -> bool:
    return any(_artifact_node(value, name)[0] for name in ("stl", "step", "brep"))


def _artifacts_complete(expected: Any, artifact: Any) -> bool:
    for name in _required_formats(expected):
        path, digest = _artifact_node(artifact, name)
        if not path:
            return False
        if digest is not None and not digest:
            return False
    return True
