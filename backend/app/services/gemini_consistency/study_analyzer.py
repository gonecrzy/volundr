"""Offline, evidence-first analysis for the Gemini Flash Lite study.

This module only reads captured evidence.  It never constructs a provider and
never treats a generated identifier, response wording, or operational timing
field as semantic product behavior.
"""

from __future__ import annotations

import json
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from app.services.workflow.redaction import RedactionService


CANONICAL_STAGES = (
    "requirements",
    "clarification",
    "planning",
    "geometry_contract",
    "slots_source",
    "source_validation",
    "worker",
    "artifacts",
    "topology",
    "feature_verification",
    "candidate_resolution",
)

FINAL_OUTCOMES = {
    "blocked_before_provider",
    "blocked_provider_content",
    "blocked_planning",
    "blocked_source",
    "blocked_worker",
    "blocked_topology",
    "blocked_verification",
    "blocked_artifact_readiness",
    "candidate_ready_with_warnings",
    "candidate_ready",
    "interrupted",
}

_VOLATILE_EXACT = {
    "id",
    "project_id",
    "workflow_id",
    "workflow_run_id",
    "message_id",
    "client_message_id",
    "attempt_id",
    "provider_call_id",
    "provider_request_id",
    "record_id",
    "revision_id",
    "generation_run_id",
    "configuration_change_id",
    "content_hash",
    "raw_hash",
    "normalized_hash",
    "source_hash",
    "response_hash",
    "created_at",
    "updated_at",
    "started_at",
    "completed_at",
    "accepted_at",
    "occurred_at",
    "recorded_at",
    "duration_ms",
    "latency_ms",
    "provider_latency_ms",
    "estimated_prompt_tokens",
    "estimated_output_tokens",
    "token_count",
    "provider_usage",
    "raw_response_path",
    "source_path",
    "artifact_path",
    "compile_log_path",
    "execution_manifest_path",
    "output_manifest_path",
    "ai_output_path",
    "stl_path",
    "specification_path",
}

_WORDING_KEYS = {
    "message",
    "assistant_message",
    "question",
    "description",
    "explanation",
    "raw_evidence",
    "originating_message",
    "user_instruction",
    "suggested_correction",
}


def _is_volatile_key(key: str) -> bool:
    normalized = key.casefold()
    return (
        normalized in _VOLATILE_EXACT
        or normalized.endswith("_id")
        or normalized.endswith("_at")
        or normalized.endswith("_hash")
        or normalized.endswith("_path")
        or normalized.endswith("_timestamp")
        or normalized.startswith("timestamp")
    )


def canonical_semantic_value(value: Any, *, ignore_wording: bool = True) -> Any:
    """Return a stable semantic representation of captured JSON."""

    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            key_string = str(key)
            if _is_volatile_key(key_string) or (ignore_wording and key_string.casefold() in _WORDING_KEYS):
                continue
            result[key_string] = canonical_semantic_value(child, ignore_wording=ignore_wording)
        return {key: result[key] for key in sorted(result)}
    if isinstance(value, list):
        normalized = [canonical_semantic_value(item, ignore_wording=ignore_wording) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True, default=str))
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    return value


def _semantic_equal(left: Any, right: Any) -> bool:
    return canonical_semantic_value(left) == canonical_semantic_value(right)


def _events(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for batch in (evidence.get("workflow_events") or {}).values():
        if isinstance(batch, list):
            result.extend(item for item in batch if isinstance(item, dict))
    return sorted(
        result,
        key=lambda item: (
            str(item.get("occurred_at") or item.get("recorded_at") or ""),
            int(item.get("sequence_number") or 0),
            str(item.get("event_type") or ""),
        ),
    )


def _event_types(evidence: dict[str, Any]) -> set[str]:
    return {str(item.get("event_type") or "") for item in _events(evidence)}


def _requirements(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    value = evidence.get("requirements")
    if isinstance(value, dict):
        value = value.get("requirements")
    if not isinstance(value, list):
        value = []
    normalized = []
    for item in value:
        if not isinstance(item, dict):
            continue
        provenance = item.get("provenance")
        provenance_category = provenance.get("source") if isinstance(provenance, dict) else item.get("source")
        normalized.append(
            {
                "kind": item.get("kind"),
                "type": item.get("type"),
                "operator": item.get("operator"),
                "value": canonical_semantic_value(item.get("value"), ignore_wording=False),
                "unit": item.get("unit"),
                "tolerance": item.get("tolerance"),
                "provenance_category": provenance_category,
                "status": item.get("status") or ("superseded" if item.get("superseded_by") else "active"),
                "subject": item.get("subject"),
                "target": item.get("target"),
                "object_type": item.get("object_type"),
            }
        )
    return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True, default=str))


def _clarification_record(evidence: dict[str, Any]) -> dict[str, Any]:
    types = _event_types(evidence)
    requested = "clarification.requested" in types
    answered = "clarification.answered" in types or "requirement_clarification.answers_submitted" in types
    intents: list[str] = []
    answers: list[Any] = []
    for item in evidence.get("chat_responses") or []:
        if not isinstance(item, dict):
            continue
        response = item.get("response") if isinstance(item.get("response"), dict) else item
        action = response.get("action") if isinstance(response, dict) else None
        if action:
            intents.append(str(action))
        if item.get("phase", "").startswith("clarification"):
            answers.append(canonical_semantic_value({"answer": item.get("answer"), "response": response}, ignore_wording=True))
    return {
        "required": requested,
        "intent_categories": sorted(set(intents)),
        "missing_fact_requested": "clarification_requested" if requested else None,
        "fact_sheet_answer_supplied": answered,
        "answers": answers,
    }


def _planning_record(evidence: dict[str, Any]) -> dict[str, Any]:
    value = evidence.get("planning") or evidence.get("design_plan")
    if isinstance(value, dict):
        return canonical_semantic_value(
            {
                key: value.get(key)
                for key in (
                    "route",
                    "component_count",
                    "output_count",
                    "required_features",
                    "component_relationships",
                    "layout_semantics",
                )
                if key in value
            }
        )
    routes = []
    for item in _events(evidence):
        if item.get("event_type") == "planning.route.selected":
            match = re.search(r":\s*([^\.]+)\.?$", str(item.get("message") or ""))
            routes.append(match.group(1).strip() if match else "route_selected")
    return {"routes": sorted(routes), "design_plan_progressed": "design_plan.progressed" in _event_types(evidence)}


def _response_structure_record(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for attempt in evidence.get("generation_attempts") or []:
        if not isinstance(attempt, dict):
            continue
        response = attempt.get("provider_response") if isinstance(attempt.get("provider_response"), dict) else {}
        result.append(
            {
                "status": attempt.get("status"),
                "failure_class": attempt.get("failure_class"),
                "classification": response.get("classification"),
                "schema_family": response.get("schema_family"),
                "normalization_required": response.get("deterministic_normalization"),
                "repair_eligibility": response.get("repair_eligibility"),
                "repair_attempted": response.get("repair_attempted"),
                "repair_outcome": response.get("repair_outcome"),
                "stage": response.get("stage"),
            }
        )
    return sorted(result, key=lambda item: json.dumps(item, sort_keys=True, default=str))


def _signature_for_text(text: str) -> str | None:
    value = text.casefold().replace("_", " ")
    if "quota" in value or "rate limit" in value or "429" in value:
        return "quota"
    if "transport" in value or "timeout" in value or "502" in value or "503" in value or "504" in value:
        return "provider_transport"
    if "provider" in value and ("schema" in value or "content" in value or "json" in value):
        return "provider_content"
    if "clarification" in value:
        return "clarification"
    if "requirement" in value and ("semantic" in value or "conflict" in value):
        return "requirement_semantics"
    if "provenance" in value:
        return "provenance"
    if "slot" in value and ("missing" in value or "incomplete" in value):
        return "missing_slots"
    if "slot" in value:
        return "geometry_slot_response"
    if "source contract" in value:
        return "source_contract"
    if "symbol" in value or "cadquery" in value or "geometry body" in value:
        return "source_symbols"
    if "worker" in value or "cad execution" in value:
        return "worker_runtime"
    if "topology" in value or "solid count" in value:
        return "topology"
    if "artifact" in value:
        return "artifact_completeness"
    if "verification" in value or "measurement" in value:
        return "feature_verification"
    if "candidate" in value:
        return "candidate_resolution"
    if "plan" in value or "layout" in value:
        return "planning_normalization"
    if "interrupted" in value or "cancelled" in value:
        return "interruption"
    return None


def _signature_for_event(event: dict[str, Any]) -> str:
    text = " ".join(str(event.get(key) or "") for key in ("stage", "event_type", "rule_id", "message"))
    signature = _signature_for_text(text)
    if signature:
        return signature
    return "integrity"


def _signature_for_attempt(attempt: dict[str, Any]) -> str | None:
    failure_class = str(attempt.get("failure_class") or "").casefold()
    direct = {
        "geometry_body_failure": "source_symbols",
        "cadquery_compile_failure": "worker_runtime",
        "cadquery_timeout": "worker_runtime",
        "design_artifact_inconsistent": "provenance",
        "design_plan_invalid": "planning_normalization",
        "source_contract_hard_rejection": "source_contract",
    }
    if failure_class in direct:
        return direct[failure_class]
    text = " ".join(str(attempt.get(key) or "") for key in ("failure_class", "error_category", "status"))
    return _signature_for_text(text)


def earliest_blocker(evidence: dict[str, Any]) -> dict[str, Any] | None:
    blocking_events = [item for item in _events(evidence) if item.get("blocking") is True]
    if blocking_events:
        event = min(
            blocking_events,
            key=lambda item: (
                CANONICAL_STAGES.index(_canonical_stage_for_event(item)),
                str(item.get("occurred_at") or item.get("recorded_at") or ""),
                int(item.get("sequence_number") or 0),
            ),
        )
        stage = _canonical_stage_for_event(event)
        return {
            "stage": stage,
            "event_type": event.get("event_type"),
            "rule_id": event.get("rule_id"),
            "signature": _signature_for_event(event),
            "sequence_number": event.get("sequence_number"),
            "occurred_at": event.get("occurred_at") or event.get("recorded_at"),
        }
    attempts = [item for item in evidence.get("generation_attempts") or [] if isinstance(item, dict)]
    failed_attempts = []
    for attempt in attempts:
        if attempt.get("status") == "failed" or (
            attempt.get("status") == "started"
            and isinstance(attempt.get("provider_response"), dict)
            and attempt["provider_response"].get("original_response_received") is False
        ):
            signature = _signature_for_attempt(attempt)
            if signature:
                failed_attempts.append((attempt, signature))
    if failed_attempts:
        attempt, signature = min(
            failed_attempts,
            key=lambda pair: (
                CANONICAL_STAGES.index(_canonical_stage_for_attempt(pair[0])),
                -int(pair[0].get("attempt_number") or 0),
            ),
        )
        return {
            "stage": _canonical_stage_for_attempt(attempt),
            "event_type": "provider.attempt.failed",
            "rule_id": None,
            "signature": signature,
            "sequence_number": attempt.get("attempt_number"),
            "occurred_at": attempt.get("started_at") or attempt.get("completed_at"),
        }
    category = str(evidence.get("outcome_category") or "").casefold()
    if "transport" in category or "timeout" in category or "quota" in category:
        return {
            "stage": "requirements",
            "event_type": "provider.transport.failed",
            "rule_id": None,
            "signature": "quota" if "quota" in category else "provider_transport",
            "sequence_number": None,
            "occurred_at": None,
        }
    if str(evidence.get("outcome_state") or "") in {"incomplete", "cancelled"}:
        return {
            "stage": "candidate_resolution",
            "event_type": "study.interrupted",
            "rule_id": None,
            "signature": "interruption",
            "sequence_number": None,
            "occurred_at": None,
        }
    if str(evidence.get("outcome_state") or "") not in {"working_version", "candidate_ready"}:
        return {
            "stage": "candidate_resolution",
            "event_type": "evidence.integrity.missing_blocker",
            "rule_id": None,
            "signature": "integrity",
            "sequence_number": None,
            "occurred_at": None,
        }
    return None


def _canonical_stage_for_event(event: dict[str, Any]) -> str:
    stage = str(event.get("stage") or "")
    event_type = str(event.get("event_type") or "")
    if "requirement" in stage or "requirement" in event_type:
        return "clarification" if "clarification" in event_type and "extraction" not in event_type else "requirements"
    if "plan" in stage or "planning" in stage or "plan" in event_type:
        return "planning"
    if "slot" in stage or "slot" in event_type:
        return "slots_source"
    if "source_contract" in stage or "source_contract" in event_type:
        return "source_validation"
    if "source" in stage or "source" in event_type or "geometry_body" in event_type:
        return "geometry_contract" if "contract" in event_type or "repair" in stage else "slots_source"
    if "worker" in stage or "cad_execution" in stage or "worker" in event_type:
        return "worker"
    if "artifact" in stage or "snapshot" in stage:
        return "artifacts"
    if "topology" in stage or "topology" in event_type:
        return "topology"
    if "verification" in stage or "functional" in event_type:
        return "feature_verification"
    if "candidate" in stage or "candidate" in event_type:
        return "candidate_resolution"
    return "candidate_resolution"


def _canonical_stage_for_attempt(attempt: dict[str, Any]) -> str:
    response = attempt.get("provider_response") if isinstance(attempt.get("provider_response"), dict) else {}
    stage = str(response.get("stage") or "")
    mode = str((attempt.get("routing_metadata") or {}).get("prompt_mode") or "")
    value = f"{stage} {mode}"
    if "requirement" in value:
        return "requirements"
    if "plan" in value:
        return "planning"
    if "source_contract" in value:
        return "source_validation"
    if "geometry" in value or "source" in value or "cadquery" in value:
        return "slots_source"
    return "requirements"


def _has(evidence: dict[str, Any], *event_types: str) -> bool:
    types = _event_types(evidence)
    return any(event_type in types for event_type in event_types)


def replay_feature_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    accepted = [
        item
        for item in evidence.get("revisions") or []
        if isinstance(item, dict) and item.get("is_accepted") is True and item.get("status") == "succeeded"
    ]
    measurements: list[Any] = []
    for revision in accepted:
        for key in ("feature_measurements", "verification_evidence", "feature_evidence"):
            value = revision.get(key)
            if isinstance(value, list):
                measurements.extend(value)
            elif isinstance(value, dict):
                measurements.append(value)
    if measurements:
        failed = any(isinstance(item, dict) and str(item.get("status") or "").casefold() in {"failed", "measurement_failed"} for item in measurements)
        return {"status": "measurement_failed" if failed else "measured", "measurements": measurements, "targets": len(measurements)}
    events = _event_types(evidence)
    if "functional.verification.completed" in events:
        return {"status": "measurement_failed", "measurements": [], "targets": 0}
    if not accepted:
        return {"status": "verification_not_run", "measurements": [], "targets": 0}
    targets = []
    specification = evidence.get("design_specification")
    if isinstance(specification, dict):
        nested = specification.get("specification")
        if isinstance(nested, dict) and isinstance(nested.get("functional_requirements"), list):
            targets = nested["functional_requirements"]
    if not targets and not any(
        isinstance(item, dict) and item.get("verification_evidence")
        for item in (evidence.get("requirements") or {}).get("requirements", [])
    ):
        return {"status": "no_verification_target", "measurements": [], "targets": 0}
    functional_status = [str(item.get("functional_status") or "") for item in accepted]
    if any(status for status in functional_status) or "snapshot.generated" in events:
        return {"status": "evidence_not_captured", "measurements": [], "targets": len(targets)}
    return {"status": "artifact_unavailable_for_replay", "measurements": [], "targets": 0}


def _stage_status(evidence: dict[str, Any], stage: str) -> dict[str, Any]:
    events = _events(evidence)
    types = {str(item.get("event_type")) for item in events}
    blocking_stage = next((item for item in events if item.get("blocking") and _canonical_stage_for_event(item) == stage), None)
    if blocking_stage:
        return {"status": "blocked", "event_type": blocking_stage.get("event_type"), "rule_id": blocking_stage.get("rule_id")}
    if stage == "requirements":
        passed = _has(evidence, "requirement_extraction.completed", "requirement_clarification.completed")
    elif stage == "clarification":
        if "clarification.requested" not in types:
            return {"status": "not_required"}
        passed = "clarification.answered" in types or "requirement_clarification.answers_submitted" in types
    elif stage == "planning":
        passed = bool(types & {"planning.route.selected", "design_plan.progressed", "design_plan_generation.completed"})
    elif stage == "geometry_contract":
        passed = bool(types & {"source_generation.started", "geometry_body.generated", "contract_repair.started", "contract_repair.completed"})
    elif stage == "slots_source":
        passed = bool(types & {"geometry_slots.completion_succeeded", "geometry_slots.legacy_fallback_completed", "source_generation.started"})
        if not passed and "geometry_slots.partial" in types:
            return {"status": "warning", "event_type": "geometry_slots.partial"}
    elif stage == "source_validation":
        passed = "source_contract.passed" in types and "worker.submitted" in types
    elif stage == "worker":
        passed = "worker.completed" in types
        if not passed and ("worker.submitted" in types or "execution.parameter_submitted" in types):
            return {"status": "reached", "event_type": "worker.submitted"}
    elif stage == "artifacts":
        revisions = [item for item in evidence.get("revisions") or [] if isinstance(item, dict) and item.get("is_accepted") is True]
        integrity = (evidence.get("workspace") or {}).get("artifact_integrity") or {}
        passed = bool(revisions and integrity.get("status") == "ok" and int(integrity.get("checked_count") or 0) > 0)
        if revisions and not passed:
            return {"status": "unavailable", "event_type": "artifact_integrity.incomplete"}
    elif stage == "topology":
        revisions = [item for item in evidence.get("revisions") or [] if isinstance(item, dict) and item.get("is_accepted") is True]
        passed = any(
            isinstance(item.get("metadata"), dict)
            and item["metadata"].get("connected_components") == 1
            and item["metadata"].get("is_watertight") is True
            for item in revisions
        ) or "topology.passed" in types
    elif stage == "feature_verification":
        feature = replay_feature_evidence(evidence)
        return {"status": feature["status"], "event_type": "feature_evidence.classified"}
    elif stage == "candidate_resolution":
        passed = "candidate.accepted" in types or str(evidence.get("outcome_state")) in {"working_version", "candidate_ready"}
    else:
        passed = False
    return {"status": "passed" if passed else "not_reached"}


def _final_outcome(evidence: dict[str, Any], blocker: dict[str, Any] | None, funnel: dict[str, dict[str, Any]]) -> str:
    if funnel["candidate_resolution"]["status"] == "passed":
        feature_status = funnel["feature_verification"]["status"]
        if feature_status in {"measured"} and funnel["artifacts"]["status"] == "passed":
            return "candidate_ready"
        return "candidate_ready_with_warnings"
    if blocker is None:
        return "interrupted"
    mapping = {
        "quota": "blocked_before_provider",
        "provider_transport": "blocked_before_provider",
        "provider_content": "blocked_provider_content",
        "clarification": "blocked_planning",
        "requirement_semantics": "blocked_planning",
        "planning_normalization": "blocked_planning",
        "provenance": "blocked_planning",
        "geometry_slot_response": "blocked_source",
        "missing_slots": "blocked_source",
        "source_contract": "blocked_source",
        "source_symbols": "blocked_source",
        "worker_runtime": "blocked_worker",
        "topology": "blocked_topology",
        "artifact_completeness": "blocked_artifact_readiness",
        "feature_verification": "blocked_verification",
        "candidate_resolution": "blocked_verification",
        "interruption": "interrupted",
        "integrity": "blocked_artifact_readiness",
    }
    return mapping.get(str(blocker.get("signature")), "blocked_artifact_readiness")


def canonical_project_record(evidence: dict[str, Any]) -> dict[str, Any]:
    funnel = {stage: _stage_status(evidence, stage) for stage in CANONICAL_STAGES}
    blocker = earliest_blocker(evidence)
    feature = replay_feature_evidence(evidence)
    accepted = [item for item in evidence.get("revisions") or [] if isinstance(item, dict) and item.get("is_accepted") is True]
    captured_provider_calls = sum(int(item.get("provider_call_count") or 0) for item in evidence.get("generation_attempts") or [] if isinstance(item, dict))
    return {
        "round": evidence.get("round"),
        "case_id": evidence.get("case_id"),
        "repetition": evidence.get("repetition"),
        "project_id": evidence.get("project_id"),
        "stage_funnel": funnel,
        "earliest_blocker": blocker,
        "final_outcome": _final_outcome(evidence, blocker, funnel),
        "feature_evidence": feature,
        "metrics": {
            "worker_ready_valid_source": funnel["source_validation"]["status"] == "passed",
            "worker_reached": funnel["worker"]["status"] in {"passed", "reached", "blocked"},
            "topology_valid": funnel["topology"]["status"] == "passed",
            "candidate_ready_or_warning": funnel["candidate_resolution"]["status"] == "passed",
            "accepted_revision_count": len(accepted),
            "captured_provider_calls": captured_provider_calls,
            "repair_calls": sum(int(item.get("content_repair_count") or 0) for item in evidence.get("generation_attempts") or [] if isinstance(item, dict)),
        },
        "semantic": {
            "requirements": _requirements(evidence),
            "clarification": _clarification_record(evidence),
            "planning": _planning_record(evidence),
            "response_structure": _response_structure_record(evidence),
            "execution": {
                "source_valid": funnel["source_validation"]["status"] == "passed",
                "worker_reached": funnel["worker"]["status"] in {"passed", "reached", "blocked"},
                "worker_status": funnel["worker"]["status"],
                "artifact_status": funnel["artifacts"]["status"],
                "repair_activity": sum(int(item.get("content_repair_count") or 0) for item in evidence.get("generation_attempts") or [] if isinstance(item, dict)) > 0,
                "earliest_blocker": blocker.get("signature") if blocker else None,
            },
            "topology": {"status": funnel["topology"]["status"]},
            "verification": feature,
            "final_outcome": _final_outcome(evidence, blocker, funnel),
        },
    }


def compare_study_evidence(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    left = (first if "semantic" in first else canonical_project_record(first))["semantic"]
    right = (second if "semantic" in second else canonical_project_record(second))["semantic"]
    fields: dict[str, dict[str, Any]] = {}
    for field in (
        "requirements",
        "clarification",
        "planning",
        "response_structure",
        "execution",
        "topology",
        "verification",
        "final_outcome",
    ):
        fields[field] = {"classification": "identical" if _semantic_equal(left[field], right[field]) else "materially_inconsistent"}
    scores = {field: {"score": 1.0 if value["classification"] == "identical" else 0.0, **value} for field, value in fields.items()}
    return {
        "schema_version": "gemini-flash-lite-semantic-comparison-v2",
        "fields": fields,
        "scores": scores,
        "overall_score": sum(item["score"] for item in scores.values()) / len(scores),
    }


def _classify_three(records: list[dict[str, Any]], field: str) -> str:
    if len(records) != 3:
        return "evidence_insufficient"
    values = [record["semantic"][field] for record in records]
    if all(_semantic_equal(values[0], value) for value in values[1:]):
        return "identical"
    if any(_semantic_equal(left, right) for index, left in enumerate(values) for right in values[index + 1:]):
        return "acceptably_variable"
    signatures = [record["earliest_blocker"]["signature"] if record["earliest_blocker"] else None for record in records]
    if all(signatures) and len(set(signatures)) == 1:
        return "repeated_failure"
    return "three_different_outcomes"


def _load_records(root: Path, round_name: str) -> list[dict[str, Any]]:
    records = []
    for path in sorted((root / round_name).glob("repetition-*/projects/*/*/evidence.json")):
        try:
            evidence = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(evidence, dict):
            records.append(canonical_project_record(evidence))
    return records


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    redactor = RedactionService()
    safe, _ = redactor.redact_evidence_value(value, data_root=path.parent, evidence_root=path.parent)
    redactor.assert_json_redacted(safe)
    path.write_text(json.dumps(safe, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _preserve_history(root: Path) -> None:
    history = root / "reports" / "historical" / "pre-correction"
    for relative in (
        "reports/baseline.json",
        "reports/validation.json",
        "reports/study-summary.json",
        "comparisons/before-after.json",
        "cleanup/analysis.json",
        "cleanup/selected-corrections.json",
    ):
        source = root / relative
        target = history / Path(relative).name
        if source.is_file() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def _round_report(root: Path, round_name: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    terminal = [record for record in records if not record["metrics"]["candidate_ready_or_warning"]]
    signatures = Counter(record["earliest_blocker"]["signature"] for record in terminal if record["earliest_blocker"])
    missing_blocker = sum(1 for record in terminal if record["earliest_blocker"] is None)
    metrics = {
        "project_count": len(records),
        "projects_reaching_worker": sum(record["metrics"]["worker_reached"] for record in records),
        "projects_worker_completed": sum(record["stage_funnel"]["worker"]["status"] == "passed" for record in records),
        "projects_worker_ready_valid_source": sum(record["metrics"]["worker_ready_valid_source"] for record in records),
        "projects_reaching_valid_source": sum(record["metrics"]["worker_ready_valid_source"] for record in records),
        "projects_producing_valid_topology": sum(record["metrics"]["topology_valid"] for record in records),
        "projects_with_measured_feature_evidence": sum(record["feature_evidence"]["status"] == "measured" for record in records),
        "projects_candidate_ready_or_warning": sum(record["metrics"]["candidate_ready_or_warning"] for record in records),
        "captured_provider_calls": sum(record["metrics"]["captured_provider_calls"] for record in records),
        "repair_calls": sum(record["metrics"]["repair_calls"] for record in records),
        "valid_source_semantics": "final assembled CadQuery source passed source-contract validation and was submitted to the worker",
    }
    return {
        "schema_version": "gemini-flash-lite-corrected-report-v1",
        "study_kind": "before-and-after product correction study",
        "round": round_name,
        "offline_required": True,
        "provider_calls": 0,
        "record_count": len(records),
        "primary_metrics": metrics,
        "failure_signatures": dict(signatures),
        "failure_signature_total": sum(signatures.values()),
        "terminal_project_count": len(terminal),
        "missing_blocker_count": missing_blocker,
        "projects": records,
    }


def build_corrected_study_reports(study_root: Path, *, preserve_history: bool = True) -> dict[str, Any]:
    """Regenerate every analyzer report from evidence without provider calls."""

    if preserve_history:
        _preserve_history(study_root)
    rounds = {
        round_name: _load_records(study_root, round_name)
        for round_name in ("baseline", "validation")
        if (study_root / round_name).is_dir()
    }
    reports = {name: _round_report(study_root, name, records) for name, records in rounds.items()}
    for name, report in reports.items():
        _write_json(study_root / "reports" / f"{name}.json", report)
        _write_json(study_root / "reports" / "corrected" / f"{name}.json", report)
        _write_json(study_root / "reports" / "funnel" / f"{name}.json", {"round": name, "projects": report["projects"]})
        _write_json(study_root / "reports" / "blockers" / f"{name}.json", {"round": name, "projects": [{"case_id": item["case_id"], "repetition": item["repetition"], "earliest_blocker": item["earliest_blocker"], "final_outcome": item["final_outcome"]} for item in report["projects"]]})
        _write_json(study_root / "reports" / "feature-evidence" / f"{name}.json", {"round": name, "status_counts": dict(Counter(item["feature_evidence"]["status"] for item in report["projects"])), "projects": [{"case_id": item["case_id"], "repetition": item["repetition"], "feature_evidence": item["feature_evidence"]} for item in report["projects"]]})
        _write_json(study_root / "reports" / "failure-signatures" / f"{name}.json", {"round": name, "signatures": report["failure_signatures"], "signature_total": report["failure_signature_total"], "terminal_project_count": report["terminal_project_count"]})

    by_case: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for round_name, records in rounds.items():
        for record in records:
            by_case[round_name][str(record["case_id"])].append(record)
    consistency: dict[str, Any] = {}
    per_case: dict[str, Any] = {}
    for round_name, cases in by_case.items():
        per_case[round_name] = {}
        stage_summary: dict[str, Counter[str]] = {stage: Counter() for stage in ("requirements", "clarification", "planning", "response_structure", "execution", "topology", "verification", "final_outcome")}
        for case_id, records in sorted(cases.items()):
            records = sorted(records, key=lambda item: int(item.get("repetition") or 0))
            fields = {stage: _classify_three(records, stage) for stage in stage_summary}
            for stage, classification in fields.items():
                stage_summary[stage][classification] += 1
            pairs = []
            for index, first in enumerate(records):
                for second in records[index + 1 :]:
                    pairs.append({"first_repetition": first["repetition"], "second_repetition": second["repetition"], "comparison": compare_study_evidence(first, second)})
            per_case[round_name][case_id] = {"repetition_count": len(records), "three_repetition": fields, "pairwise": pairs}
        consistency[round_name] = {stage: {"case_count": sum(counter.values()), "classifications": dict(counter), "score": round(sum({"identical": 1.0, "acceptably_variable": 0.75, "repeated_failure": 0.5, "three_different_outcomes": 0.0, "evidence_insufficient": 0.0}.get(key, 0.0) * value for key, value in counter.items()) / sum(counter.values()), 4) if counter else 0.0} for stage, counter in stage_summary.items()}
        consistency[round_name].update(
            {
                "requirement_consistency": consistency[round_name]["requirements"],
                "clarification_consistency": consistency[round_name]["clarification"],
                "planning_consistency": consistency[round_name]["planning"],
                "response_structure_consistency": consistency[round_name]["response_structure"],
                "execution_consistency": consistency[round_name]["execution"],
                "topology_consistency": consistency[round_name]["topology"],
                "verification_consistency": consistency[round_name]["verification"],
                "final_outcome_consistency": consistency[round_name]["final_outcome"],
            }
        )
    for name, report in reports.items():
        report["consistency_scores"] = consistency.get(name, {})
        report["primary_metrics"]["candidate_readiness"] = report["primary_metrics"].get("projects_candidate_ready_or_warning", 0)
        _write_json(study_root / "reports" / f"{name}.json", report)
        _write_json(study_root / "reports" / "corrected" / f"{name}.json", report)
    _write_json(study_root / "reports" / "three-repetition-consistency.json", {"schema_version": "gemini-flash-lite-three-repetition-v1", "offline_required": True, "provider_calls": 0, "rounds": consistency})
    _write_json(study_root / "comparisons" / "per-case.json", {"schema_version": "gemini-flash-lite-per-case-comparison-v1", "offline_required": True, "provider_calls": 0, "rounds": per_case})
    if "baseline" in reports and "validation" in reports:
        baseline_metrics = reports["baseline"]["primary_metrics"]
        validation_metrics = reports["validation"]["primary_metrics"]
        delta = {key: validation_metrics.get(key, 0) - baseline_metrics.get(key, 0) for key in set(baseline_metrics) | set(validation_metrics) if isinstance(validation_metrics.get(key, 0), (int, float)) and isinstance(baseline_metrics.get(key, 0), (int, float))}
        before_after = {"schema_version": "gemini-flash-lite-corrected-before-after-v1", "study_kind": "before-and-after product correction study", "controlled_pair": False, "label": "before-and-after product correction study", "offline_required": True, "provider_calls": 0, "baseline": baseline_metrics, "validation": validation_metrics, "metric_deltas": delta}
        _write_json(study_root / "comparisons" / "before-after.json", before_after)
    result = {"schema_version": "gemini-flash-lite-corrected-study-summary-v1", "study_kind": "before-and-after product correction study", "offline_required": True, "provider_calls": 0, "rounds": reports, "consistency": consistency, "historical_reports_preserved": preserve_history}
    _write_json(study_root / "reports" / "study-summary.json", result)
    _write_json(study_root / "reports" / "corrected" / "study-summary.json", result)
    return result
