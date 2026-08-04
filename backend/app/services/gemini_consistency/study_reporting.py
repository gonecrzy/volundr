"""Stage-level reporting for the Flash Lite three-repetition study."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from app.services.gemini_consistency.comparison import failure_signature, semantic_equal
from app.services.workflow.redaction import RedactionService


STUDY_KIND = "before-and-after product correction study"
STAGES = (
    "requirement_consistency",
    "clarification_consistency",
    "planning_consistency",
    "response_structure_consistency",
    "execution_consistency",
    "topology_consistency",
    "verification_consistency",
    "final_outcome_consistency",
)


def _write_json(root: Path, relative: str, value: Any) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    redactor = RedactionService()
    safe, _ = redactor.redact_evidence_value(value, data_root=root, evidence_root=root)
    redactor.assert_json_redacted(safe)
    path.write_text(json.dumps(safe, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _load_evidence(root: Path, round_name: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((root / round_name).glob("repetition-*/projects/*/*/evidence.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def _stage_value(evidence: dict[str, Any], stage: str) -> Any:
    workspace = evidence.get("workspace") if isinstance(evidence.get("workspace"), dict) else {}
    return {
        "requirement_consistency": evidence.get("requirements") or evidence.get("design_specification"),
        "clarification_consistency": evidence.get("chat_responses"),
        "planning_consistency": evidence.get("planning") or evidence.get("design_plan"),
        "response_structure_consistency": evidence.get("generation_attempts"),
        "execution_consistency": {"workflow_events": evidence.get("workflow_events"), "attempts": evidence.get("generation_attempts")},
        "topology_consistency": evidence.get("topology") or workspace.get("topology"),
        "verification_consistency": evidence.get("verification") or evidence.get("feature_measurements"),
        "final_outcome_consistency": {
            "outcome_category": evidence.get("outcome_category"),
            "outcome_state": evidence.get("outcome_state"),
            "workspace": evidence.get("workspace"),
        },
    }.get(stage)


def _three_run_classification(values: list[Any], evidences: list[dict[str, Any]]) -> str:
    if len(values) != 3:
        return "evidence_insufficient"
    signatures = [failure_signature(item) for item in evidences]
    if all(signature for signature in signatures) and len(set(signatures)) == 1:
        return "repeated_failure"
    if all(semantic_equal(values[0], value) for value in values[1:]):
        return "identical"
    if any(semantic_equal(left, right) for index, left in enumerate(values) for right in values[index + 1:]):
        return "acceptably_variable"
    return "three_different_outcomes"


def _consistency_score(classification: str) -> float:
    return {
        "identical": 1.0,
        "semantically_equivalent": 1.0,
        "acceptably_variable": 0.75,
        "repeated_failure": 0.5,
        "evidence_insufficient": 0.0,
        "three_different_outcomes": 0.0,
    }.get(classification, 0.0)


def _primary_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    def has_event(item: dict[str, Any], marker: str) -> bool:
        events = item.get("workflow_events")
        values = [event for batch in events.values() for event in (batch if isinstance(batch, list) else [])] if isinstance(events, dict) else []
        return any(marker in str(event.get("stage", "")) or marker in str(event.get("event_type", "")) for event in values if isinstance(event, dict))

    source_valid = sum(any(str(attempt.get("status")) == "succeeded" for attempt in item.get("generation_attempts", []) if isinstance(attempt, dict)) for item in records)
    worker_reached = sum(has_event(item, "worker") for item in records)
    topology_success = sum(has_event(item, "topology") or bool(item.get("topology_success")) for item in records)
    feature_evidence = sum(bool(item.get("feature_measurements") or item.get("verification")) for item in records)
    candidate_ready = sum(bool(item.get("workspace", {}).get("current_working_revision_id")) or str(item.get("outcome_category")) in {"candidate", "candidate_ready"} for item in records)
    provider_calls = sum(int(attempt.get("provider_call_count") or 0) for item in records for attempt in item.get("generation_attempts", []) if isinstance(attempt, dict))
    return {
        "project_count": len(records),
        "projects_reaching_valid_source": source_valid,
        "projects_reaching_worker": worker_reached,
        "projects_producing_valid_topology": topology_success,
        "projects_with_measured_feature_evidence": feature_evidence,
        "projects_candidate_ready_or_warning": candidate_ready,
        "candidate_readiness": candidate_ready,
        "provider_calls": provider_calls,
        "repair_calls": sum(int(attempt.get("content_repair_count") or 0) for item in records for attempt in item.get("generation_attempts", []) if isinstance(attempt, dict)),
    }


def _round_report(root: Path, round_name: str) -> dict[str, Any]:
    records = _load_evidence(root, round_name)
    by_case: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    for item in records:
        by_case[str(item.get("case_id"))][int(item.get("repetition") or 0)] = item
    consistency: dict[str, dict[str, Any]] = {}
    for stage in STAGES:
        classifications: list[str] = []
        for case_id, repetitions in sorted(by_case.items()):
            ordered = [repetitions.get(index, {}) for index in (1, 2, 3)]
            classification = _three_run_classification([_stage_value(item, stage) for item in ordered], ordered)
            classifications.append(classification)
        score = sum(_consistency_score(item) for item in classifications) / len(classifications) if classifications else 0.0
        consistency[stage] = {"case_count": len(classifications), "classifications": Counter(classifications), "score": round(score, 4)}
    signatures = Counter(signature for item in records if (signature := failure_signature(item)))
    report = {
        "round": round_name,
        "study_kind": STUDY_KIND,
        "record_count": len(records),
        "consistency_scores": consistency,
        "primary_metrics": _primary_metrics(records),
        "failure_signatures": dict(signatures),
        "repeated_generic_issues": [
            {"signature": signature, "count": count, "eligible": count >= 2}
            for signature, count in sorted(signatures.items())
        ],
    }
    _write_json(root, f"reports/{round_name}.json", report)
    return report


def build_study_reports(study_root: Path) -> dict[str, Any]:
    rounds = {round_name: _round_report(study_root, round_name) for round_name in ("baseline", "validation") if (study_root / round_name).is_dir()}
    result: dict[str, Any] = {"study_kind": STUDY_KIND, "rounds": rounds}
    if "baseline" in rounds:
        cleanup = {
            "study_kind": STUDY_KIND,
            "selection_policy": "generic issue must recur across projects/repetitions or pose integrity/safety risk",
            "eligible_signatures": rounds["baseline"]["repeated_generic_issues"],
            "production_corrections_allowed": 3,
            "prompt_changes_per_stage_allowed": 1,
            "provider_calls_during_cleanup": 0,
        }
        _write_json(study_root, "cleanup/analysis.json", cleanup)
        _write_json(study_root, "cleanup/selected-corrections.json", {**cleanup, "selected": []})
    if "baseline" in rounds and "validation" in rounds:
        before_after = {
            "study_kind": STUDY_KIND,
            "controlled_pair": False,
            "label": STUDY_KIND,
            "baseline": rounds["baseline"],
            "validation": rounds["validation"],
        }
        _write_json(study_root, "comparisons/before-after.json", before_after)
        result["before_after"] = before_after
    _write_json(study_root, "reports/study-summary.json", result)
    return result
