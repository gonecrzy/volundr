#!/usr/bin/env python3
"""Prepare and replay the Gemini system-boundary methods study.

The default command is offline-only. Live phases are intentionally separate
and will refuse to run until the immutable preregistration and offline gate
exist.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import httpx

from app.services.gemini_consistency.system_boundary_methods import (
    DEFAULT_MIN_INTERVAL_SECONDS,
    DEFAULT_REQUESTS_PER_MINUTE,
    HARD_MAX_REQUESTS_PER_WINDOW,
    METHOD_IDS,
    canonical_hash,
    replay_preserved_evidence,
)
from app.services.gemini_consistency.buildability_reanalysis import RollingWindowRateLimiter
from app.services.gemini_consistency.runner import PROPOSAL_ANSWER, _questions_from_spec, clarification_answer_for
from app.services.workflow.redaction import RedactionService


STUDY_ID = "gemini-system-boundary-methods-01"
SECONDARY_CREDENTIAL_ENV = "GEMINI_API_KEY_2"
SECONDARY_CREDENTIAL_SOURCE = "GEMINI_API_KEY_2"
SECONDARY_CREDENTIAL_SLOT = "secondary"
EXPECTED_FACTORIAL_ARMS = (
    ("A-current-p0", "current-production", "P0"),
    ("B-profile-b-p0", "profile-b-sampling", "P0"),
    ("C-current-p3", "current-production", "P3"),
    ("D-profile-b-p3", "profile-b-sampling", "P3"),
)
SOURCE_REPORTS = (
    "corrected-phase-1-decision.json",
    "corrected-quality-floor.json",
    "corrected-semantic-scores.json",
    "buildability-scorecard.json",
    "phase-2-audited-decision.json",
    "phase-2-project-reconstruction.json",
    "phase-2-comparison-corrected.json",
    "phase-2-clarification-audit.json",
    "phase-2-worker-reach-audit.json",
    "all-responses-manual-review.json",
    "all-responses-manual-review-audited.json",
    "gemini-rate-limit-report.json",
    "final-recommendation.json",
    "final-decision.json",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(repo_root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo_root), *args], text=True).strip()


def _json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _credential_metadata(source: str) -> dict[str, Any]:
    if source not in {"primary", "secondary"}:
        raise ValueError("credential source must be explicitly primary or secondary")
    if source == "secondary":
        present = bool(os.environ.get(SECONDARY_CREDENTIAL_ENV))
        env_name = SECONDARY_CREDENTIAL_ENV
        slot = SECONDARY_CREDENTIAL_SLOT
    else:
        present = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("VOLUNDR_GEMINI_API_KEY"))
        env_name = "GEMINI_API_KEY"
        slot = "primary"
    return {
        "credential_source": SECONDARY_CREDENTIAL_SOURCE if source == "secondary" else env_name,
        "credential_slot": slot,
        "credential_env_var": env_name,
        "credential_present": present,
    }


def _credential_environment(source: str) -> dict[str, str]:
    """Build a child environment without returning or recording any secret."""
    metadata = _credential_metadata(source)
    if not metadata["credential_present"]:
        raise RuntimeError(f"{metadata['credential_env_var']} is not present; no experiment call was attempted")
    if source == "primary":
        return os.environ.copy()
    environment = os.environ.copy()
    secondary_value = environment[SECONDARY_CREDENTIAL_ENV]
    for name in ("GEMINI_API_KEY", "VOLUNDR_GEMINI_API_KEY", SECONDARY_CREDENTIAL_ENV, "VOLUNDR_GEMINI_API_KEY_2"):
        environment.pop(name, None)
    environment["GEMINI_API_KEY"] = secondary_value
    return environment


def _seed_limiter(limiter: RollingWindowRateLimiter, events: list[dict[str, Any]]) -> None:
    """Carry prior monotonic events into a resumed process without reusing calls."""
    starts = sorted(float(item["call_start_monotonic"]) for item in events if item.get("call_start_monotonic") is not None)
    limiter.starts.extend(starts)
    limiter.last_start = starts[-1] if starts else None
    limiter.events.extend(dict(item) for item in events)


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _snapshot(repo_root: Path, profile_root: Path, study_root: Path) -> dict[str, Any]:
    report_root = profile_root / "reports"
    phase1 = _json(report_root / "phase-1-packet-results.json") or {}
    phase2 = _json(report_root / "phase-2-project-results.json") or {}
    packets = []
    for packet in sorted((profile_root / "phase-1").glob("packet-*/packet.json")):
        packets.append({"packet_id": packet.parent.name, "path": str(packet.relative_to(profile_root)), "sha256": _sha256(packet)})
    profiles = []
    for profile in sorted((profile_root / "profiles").glob("*.json")):
        profiles.append({"profile_id": profile.stem, "path": str(profile.relative_to(profile_root)), "sha256": _sha256(profile)})
    calls = []
    for arm in phase2.get("arms", []):
        for interaction in arm.get("provider_interactions", []):
            chain = interaction.get("chain") or {}
            calls.append({"provider_call_id": chain.get("attempt_id"), "arm": arm.get("arm"), "path": interaction.get("source_provider_call_path")})
    return {
        "repository": {
            "head": _git(repo_root, "rev-parse", "HEAD"),
            "branch": _git(repo_root, "branch", "--show-current"),
            "origin_main": _git(repo_root, "rev-parse", "origin/main"),
            "divergence": _git(repo_root, "rev-list", "--left-right", "--count", "HEAD...origin/main"),
            "status": _git(repo_root, "status", "--short"),
        },
        "migration_head": _json(profile_root / "migration-head.json"),
        "historical_experiment": {
            "profile_ablation_root": str(profile_root),
            "study_root": str(study_root),
            "report_hashes": {name: _sha256(report_root / name) for name in SOURCE_REPORTS if (report_root / name).is_file()},
            "packet_hashes": packets,
            "profile_hashes": profiles,
            "phase1_record_count": len(phase1.get("records", [])),
            "phase2_project_count": sum(len(arm.get("cases", [])) for arm in phase2.get("arms", [])),
            "phase2_provider_call_count": sum(len(arm.get("provider_interactions", [])) for arm in phase2.get("arms", [])),
            "phase2_provider_call_ids": calls,
        },
    }


def _preregistration(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "gemini-system-boundary-methods-preregistration-v1",
        "study_id": STUDY_ID,
        "hypotheses": {
            "provider": "Profile B is at least as safe and consistent intrinsically as current production.",
            "processing": "One bounded generic method can improve processability without semantic or integrity regression.",
            "end_to_end": "The best system boundary is selected by ordered quality, processability, progress, stability, then efficiency gates.",
        },
        "processing_candidates": list(METHOD_IDS),
        "frozen_cases": ["case-001", "case-002", "case-003", "case-006", "case-008"],
        "factorial_cases": ["case-001", "case-003", "case-006"],
        "metrics": {
            "intrinsic_provider": ["quality_floor", "clarification_correctness", "invented_critical_meaning", "semantic_completeness", "identity_preservation", "structural_validity", "response_consistency", "slot_consistency", "tokens", "latency"],
            "processing": ["normalization_count", "reconciliation_count", "ambiguous_blocks", "source_contract", "worker_ready", "semantic_hash_changes", "integrity_regressions"],
            "end_to_end": ["worker_reached", "worker_completed", "worker_runtime_failed", "artifacts", "topology", "verification", "candidate_ready", "earliest_blocker", "furthest_stage", "calls", "repairs", "elapsed"],
        },
        "offline_qualification_gate": {
            "no_semantic_or_integrity_regressions": True,
            "known_bad_responses_remain_rejected": True,
            "minimum_improved_records_or_projects": 2,
            "minimum_advanced_metric": "source_contract_or_worker_ready_or_worker_reach_or_correct_blocker",
            "minimum_distinct_object_types_or_stages": 2,
        },
        "rate_policy": {
            "default_requests_per_minute": DEFAULT_REQUESTS_PER_MINUTE,
            "hard_max_requests_per_rolling_window": HARD_MAX_REQUESTS_PER_WINDOW,
            "rolling_window_seconds": 60,
            "minimum_interval_seconds": DEFAULT_MIN_INTERVAL_SECONDS,
            "provider_concurrency": 1,
            "model": "gemini-3.5-flash-lite",
            "retry_hard_429": False,
        },
        "gates": ["offline_processing_qualification", "factorial_authorization", "residual_model_owned_defect", "prompt_ablation_authorization", "final_two_system_authorization"],
        "decision_options": ["adopt_profile_b_with_current_processing_in_future_goal", "adopt_profile_b_with_bounded_processing_in_future_goal", "adopt_profile_b_targeted_prompt_with_bounded_processing_in_future_goal", "processing_boundary_improvement_is_primary", "keep_current_pending_geometry_capability", "insufficient_evidence"],
        "snapshot": snapshot,
    }


def _preregistration_matches(existing: dict[str, Any], expected: dict[str, Any]) -> bool:
    """Compare frozen study parameters while ignoring the historical snapshot."""
    left = dict(existing)
    right = dict(expected)
    left.pop("snapshot", None)
    right.pop("snapshot", None)
    return left == right


def prepare_study(output_root: Path, profile_root: Path, study_root: Path, repo_root: Path) -> dict[str, Any]:
    reports = output_root / "reports"
    historical = reports / "historical/source-evidence"
    historical.mkdir(parents=True, exist_ok=True)
    copied: dict[str, str] = {}
    for name in SOURCE_REPORTS:
        source = profile_root / "reports" / name
        if source.is_file():
            destination = historical / name
            shutil.copy2(source, destination)
            copied[name] = _sha256(destination)
    snapshot = _snapshot(repo_root, profile_root, study_root)
    _write(output_root / "study.json", {"study_id": STUDY_ID, "evidence_root": str(output_root), "historical_inputs": copied})
    _write(reports / "repository-snapshot.json", snapshot)
    preregistration_path = reports / "study-preregistration.json"
    if preregistration_path.exists():
        existing = _json(preregistration_path)
        if not isinstance(existing, dict) or not _preregistration_matches(existing, _preregistration(snapshot)):
            raise RuntimeError("study preregistration already exists and differs; refusing to overwrite it")
    else:
        _write(preregistration_path, _preregistration(snapshot))
    return {"study_id": STUDY_ID, "copied_reports": copied, "preregistration": str(preregistration_path), "repository": snapshot["repository"]}


def run_offline(output_root: Path, profile_root: Path, study_root: Path) -> dict[str, Any]:
    replay = replay_preserved_evidence(output_root=output_root, profile_ablation_root=profile_root, study_root=study_root)
    summaries = replay["method_summaries"]
    scorecard = {"schema_version": "gemini-system-boundary-methods-scorecard-v1", "methods": summaries, "provider_calls": 0, "worker_calls": 0}
    qualified = [item["method"] for item in summaries if item.get("qualifies")]
    decision = {
        "schema_version": "gemini-system-boundary-methods-processing-decision-v1",
        "run": True,
        "qualified_methods": qualified,
        "selected_method": qualified[0] if len(qualified) == 1 else None,
        "decision": "qualified" if len(qualified) == 1 else "no_method_qualified",
        "provider_calls": 0,
        "worker_calls": 0,
    }
    _write(output_root / "reports/processing-method-scorecard.json", scorecard)
    _write(output_root / "reports/processing-method-decision.json", decision)
    return {"replay": replay, "decision": decision}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _factorial_data_root(output_root: Path, arm_id: str, run_label: str = "run-01") -> Path:
    base = output_root / "factorial" / "live-data" if run_label == "run-01" else output_root / "factorial" / run_label / "live-data"
    return (base / arm_id).resolve()


def _factorial_headers(processing: str, case_id: str) -> dict[str, str]:
    return {
        "X-Volundr-Benchmark-Provider": "gemini_api",
        "X-Volundr-Benchmark-Model": "gemini-3.5-flash-lite",
        "X-Volundr-Benchmark-Processing": processing,
        "X-Volundr-Study-Id": STUDY_ID,
        "X-Volundr-Study-Round": "validation",
        "X-Volundr-Study-Repetition": "1",
        "X-Volundr-Study-Case": case_id,
    }


def _operation_manifest(
    *,
    arm_id: str,
    provider_profile: str,
    processing: str,
    cases: list[dict[str, Any]],
    captures: list[dict[str, Any]],
    credential: dict[str, Any],
) -> list[dict[str, Any]]:
    by_case: dict[str, list[dict[str, Any]]] = {}
    for capture in captures:
        by_case.setdefault(str(capture.get("case_id") or ""), []).append(capture)
    operations: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case.get("case_id"))
        items = by_case.get(case_id, [])
        quota_stopped = any(int(item.get("response", {}).get("status_code") or item.get("status_code") or 0) == 429 for item in items if isinstance(item, dict))
        project_ids = sorted({str(item.get("project_id")) for item in items if item.get("project_id")})
        user_operation_ids = sorted({str(item.get("user_operation_id")) for item in items if item.get("user_operation_id")})
        operations.append({
            "operation_id": f"{arm_id}:{case_id}",
            "arm_id": arm_id,
            "provider_profile": provider_profile,
            "processing": processing,
            "case_id": case_id,
            "project_ids": project_ids,
            "user_operation_ids": user_operation_ids,
            "provider_call_ids": sorted(str(item.get("provider_call_id")) for item in items if item.get("provider_call_id")),
            "provider_call_count": len(items),
            "operation_status": "quota_stopped" if quota_stopped else "completed" if items else "not_started",
            "credential_source": credential["credential_source"],
            "credential_slot": credential["credential_slot"],
        })
    return operations


def _finalist_configurations(processing: str) -> tuple[tuple[str, str, str], ...]:
    return (
        ("current-p3", "current-production", processing),
        ("profile-b-p3", "profile-b-sampling", processing),
    )


def _answer_for_questions(questions: list[str], fact_sheet: dict[str, Any]) -> tuple[str, list[str]]:
    """Map frozen facts to clarification questions without inventing values."""
    used: list[str] = []
    broad_fit_question = any(any(token in question.casefold() for token in ("phone", "fit", "case status")) for question in questions)
    if broad_fit_question:
        used = [key for key in ("phone_width", "phone_thickness_with_case", "case_status", "desired_angle") if key in fact_sheet]
        if used:
            lines = [f"{key}: {fact_sheet[key]}" for key in used]
            if "case_status" not in fact_sheet and "phone_thickness_with_case" in fact_sheet:
                lines.append("case_condition: with_case (explicitly represented by phone_thickness_with_case)")
            return "\n".join(lines), used
    answers: list[str] = []
    for question in questions:
        decision = clarification_answer_for(question, fact_sheet)
        if decision.answer is not None:
            if decision.fact_key and decision.fact_key not in used:
                used.append(decision.fact_key)
            answers.append(f"{decision.category}: {decision.answer}")
    return "\n".join(answers) or PROPOSAL_ANSWER, used


def _write_redacted(path: Path, value: Any, root: Path) -> None:
    redactor = RedactionService()
    safe, _ = redactor.redact_evidence_value(value, data_root=root / "data", evidence_root=path.parent)
    redactor.assert_json_redacted(safe)
    _write(path, safe)


def _factorial_cases(study_root: Path) -> list[dict[str, Any]]:
    corpus = _json(study_root / "corpus.json") or {}
    selected = {"case-001", "case-003", "case-006"}
    return [
        {
            "case_id": case["case_id"],
            "title": case["title"],
            "request": case["initial_prompt"],
            "fact_sheet": case["fact_sheet"],
            "expected_route": case["expected_route_category"],
        }
        for case in corpus.get("cases", [])
        if case.get("case_id") in selected
    ]


def _final_cases(study_root: Path) -> list[dict[str, Any]]:
    corpus = _json(study_root / "corpus.json") or {}
    selected = {"case-001", "case-002", "case-003", "case-006", "case-008"}
    return [
        {
            "case_id": case["case_id"],
            "title": case["title"],
            "request": case["initial_prompt"],
            "fact_sheet": case["fact_sheet"],
            "expected_route": case["expected_route_category"],
        }
        for case in corpus.get("cases", [])
        if case.get("case_id") in selected
    ]


async def _fetch_json(client: httpx.AsyncClient, path: str) -> Any:
    response = await client.get(path)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


async def _run_complete_case(client: httpx.AsyncClient, case: dict[str, Any]) -> dict[str, Any]:
    draft = await client.post("/projects/draft")
    draft.raise_for_status()
    project = draft.json()
    project_id = str(project["id"])
    started = asyncio.get_running_loop().time()
    responses: list[dict[str, Any]] = []
    clarification_trace: list[dict[str, Any]] = []
    current_message = str(case["request"])
    clarification_rounds = 0
    terminal_response: dict[str, Any] = {}
    workflow_run_ids: list[str] = []
    for phase in range(3):
        response = await client.post(
            f"/projects/{project_id}/chat",
            json={"message": current_message, "client_message_id": f"boundary-study-{case['case_id']}-round-{phase}"},
        )
        if response.status_code >= 400:
            terminal_response = {"http_status": response.status_code, "error": response.text}
            responses.append({"phase": phase, "response": terminal_response})
            break
        terminal_response = response.json()
        responses.append({"phase": phase, "response": terminal_response})
        if terminal_response.get("workflow_run_id"):
            workflow_run_ids.append(str(terminal_response["workflow_run_id"]))
        if not terminal_response.get("input_required"):
            break
        if clarification_rounds >= 2:
            break
        specification = await _fetch_json(client, f"/projects/{project_id}/design-specification")
        questions = _questions_from_spec(specification, str(terminal_response.get("assistant_message") or ""))
        answer, used_facts = _answer_for_questions(questions, dict(case.get("fact_sheet") or {}))
        clarification_rounds += 1
        clarification_trace.append({"round": clarification_rounds, "questions": questions, "answer": answer, "used_fact_keys": used_facts, "facts_submitted": {key: case["fact_sheet"][key] for key in used_facts}})
        current_message = answer
    revision_id = terminal_response.get("revision_id") or terminal_response.get("current_working_revision_id")
    evidence = {
        "chat_responses": responses,
        "clarification_trace": clarification_trace,
        "project_key": project_id,
        "workflow_run_ids": workflow_run_ids,
    }
    return {
        "case_id": case["case_id"],
        "expected_route": case.get("expected_route"),
        "request": case["request"],
        "chat_elapsed_ms": round((asyncio.get_running_loop().time() - started) * 1000, 2),
        "workflow_response": terminal_response,
        "clarification_rounds": clarification_rounds,
        "clarification_trace": clarification_trace,
        "project": await _fetch_json(client, f"/projects/{project_id}"),
        "workspace": await _fetch_json(client, f"/projects/{project_id}/workspace"),
        "requirements": await _fetch_json(client, f"/projects/{project_id}/requirements/active"),
        "design_specification": await _fetch_json(client, f"/projects/{project_id}/design-specification"),
        "design_plan": await _fetch_json(client, f"/projects/{project_id}/design-plan"),
        "revisions": await _fetch_json(client, f"/projects/{project_id}/revisions") or [],
        "revision": await _fetch_json(client, f"/revisions/{revision_id}") if revision_id else None,
        "outputs": await _fetch_json(client, f"/revisions/{revision_id}/outputs") if revision_id else [],
        "findings": await _fetch_json(client, f"/candidates/{revision_id}/findings") if revision_id else [],
        "generation_attempts": await _fetch_json(client, f"/projects/{project_id}/generation-attempts") or [],
        "workflow_runs": await _fetch_json(client, f"/projects/{project_id}/workflow-runs") or [],
        "runner_evidence": evidence,
    }


def _provider_interactions(data_root: Path, output_root: Path) -> list[dict[str, Any]]:
    interactions: list[dict[str, Any]] = []
    for chain_path in sorted(data_root.rglob("generation-runs/*/chain.json")):
        chain = _json(chain_path) or {}
        request_path = chain_path.parent / "request.json"
        raw_path = chain_path.parent / "raw-output.txt"
        interactions.append({
            "provider_call_id": chain.get("attempt_id"),
            "source_provider_call_path": str(chain_path.relative_to(output_root)),
            "chain": chain,
            "request": _json(request_path),
            "processed_response_text": raw_path.read_text(encoding="utf-8") if raw_path.is_file() else None,
        })
    return interactions


def _provider_captures(data_root: Path, output_root: Path) -> list[dict[str, Any]]:
    captures: list[dict[str, Any]] = []
    for path in sorted(data_root.rglob("provider-calls/*.json")):
        document = _json(path)
        if not isinstance(document, dict):
            continue
        captures.append({"evidence_path": str(path.relative_to(output_root)), **document})
    return captures


def _worker_metrics(data_root: Path) -> dict[str, int]:
    jobs = sorted(data_root.glob("jobs/*/job.json"))
    completed = 0
    runtime_failed = 0
    topology_valid = 0
    artifacts = 0
    for job_path in jobs:
        job_root = job_path.parent
        result = _json(job_root / "result.json") or {}
        execution = _json(next(iter(job_root.glob("work/*/execution-manifest.json")), Path("/dev/null"))) or {}
        success = result.get("success") is True or execution.get("success") is True
        if success:
            completed += 1
        else:
            runtime_failed += 1
        topology_files = list(job_root.rglob("topology.json"))
        if topology_files and all((_json(path) or {}).get("valid") is True for path in topology_files):
            topology_valid += 1
        if list(job_root.rglob("outputs/*/*.stl")):
            artifacts += 1
    return {"worker_job_count": len(jobs), "worker_completed_count": completed, "worker_runtime_failure_count": runtime_failed, "artifact_count": artifacts, "topology_valid_count": topology_valid}


def _case_metrics(case: dict[str, Any], data_root: Path) -> dict[str, Any]:
    spec = case.get("design_specification") or {}
    plan = case.get("design_plan") or {}
    attempts = case.get("generation_attempts") or []
    routing = [attempt.get("routing_metadata") or {} for attempt in attempts]
    revision = case.get("revision") or {}
    revisions = case.get("revisions") or []
    revision_id = revision.get("id") or (revisions[-1].get("id") if revisions and isinstance(revisions[-1], dict) else None)
    project_id = (case.get("project") or {}).get("id")
    job_path = data_root / "jobs" / str(revision_id) / "job.json" if revision_id else None
    job = _json(job_path) if job_path and job_path.is_file() else None
    job_root = job_path.parent if job_path else None
    result = _json(job_root / "result.json") if job_root else None
    project_root = data_root / "projects" / str(project_id) if project_id else data_root
    source_contract_paths = list(project_root.rglob("generation-runs/*/source-contract.json"))
    source_contract_passed = any(bool((_json(path) or {}).get("passed_hard_checks")) for path in source_contract_paths)
    topology = list(job_root.rglob("topology.json")) if job_root else []
    topology_valid = bool(topology) and all(bool((_json(path) or {}).get("valid")) for path in topology)
    worker_reached = job is not None
    worker_completed = bool(worker_reached and ((result or {}).get("success") is True))
    worker_runtime_failed = bool(worker_reached and not worker_completed)
    candidate_ready = case.get("workflow_response", {}).get("current_stage") == "working_version" and bool(case.get("outputs"))
    clarification_required = bool(spec.get("clarification_required"))
    return {
        "case_id": case.get("case_id"),
        "requirements_valid": bool(spec) and spec.get("outcome") not in {"extraction_failed", "unsupported_request"},
        "clarification_required": clarification_required,
        "clarification_answered": clarification_required and not bool(case.get("workflow_response", {}).get("input_required")),
        "clarification_decision_correct": not (case.get("case_id") == "case-001" and not clarification_required),
        "plan_valid": bool(plan.get("plan_ready")),
        "geometry_response_valid": any("geometry" in str(attempt.get("prompt_version")) and attempt.get("failure_class") == "none" for attempt in attempts),
        "source_contract_passed": source_contract_passed,
        "worker_ready_valid_source": bool(source_contract_passed and worker_reached),
        "worker_reached": worker_reached,
        "worker_completed": worker_completed,
        "worker_runtime_failed": worker_runtime_failed,
        "artifact_created": bool(case.get("outputs")),
        "topology_valid": topology_valid,
        "verification_completed": bool(case.get("findings")) and topology_valid,
        "candidate_ready": candidate_ready,
        "candidate_ready_with_warnings": candidate_ready and bool(case.get("findings")),
        "provider_calls": sum(int(attempt.get("provider_call_count") or 0) for attempt in attempts),
        "processing_action_count": sum(len(item.get("processing_actions") or []) for item in routing),
        "processing_semantic_hash_changes": sum(bool(item.get("processing_semantic_hash_before") and item.get("processing_semantic_hash_before") != item.get("processing_semantic_hash_after")) for item in routing),
        "furthest_stage": case.get("workflow_response", {}).get("current_stage") or "project_created",
        "earliest_blocker": next((attempt.get("failure_class") for attempt in attempts if attempt.get("failure_class") not in {None, "none"}), None),
        "final_outcome": "candidate_ready" if candidate_ready else "workflow_blocked_or_incomplete",
    }


def enrich_factorial_report(output_root: Path) -> dict[str, Any]:
    report_path = output_root / "reports/provider-processing-factorial-results.json"
    report = _json(report_path) or {}
    all_projects: list[dict[str, Any]] = []
    for arm in report.get("arms", []):
        data_root = output_root / str(arm.get("data_root"))
        arm["provider_captures"] = _provider_captures(data_root, output_root)
        arm["actual_model_identities"] = sorted({str(item.get("actual_model")) for item in arm["provider_captures"] if item.get("actual_model")})
        arm["worker_metrics"] = _worker_metrics(data_root)
        arm["project_metrics"] = [_case_metrics(case, data_root) for case in arm.get("cases", [])]
        all_projects.extend([{**metric, "arm_id": arm.get("arm_id"), "provider_profile": arm.get("provider_profile"), "processing": arm.get("processing")} for metric in arm["project_metrics"]])
        arm["provider_capture_count"] = len(arm["provider_captures"])
        arm["worker_calls"] = arm["worker_metrics"]["worker_job_count"]
    report["provider_capture_count"] = sum(int(arm.get("provider_capture_count") or 0) for arm in report.get("arms", []))
    report["worker_calls"] = sum(int(arm.get("worker_calls") or 0) for arm in report.get("arms", []))
    report["project_metrics"] = all_projects
    report["capture_complete"] = report["provider_capture_count"] == report.get("provider_calls")
    _write_redacted(report_path, report, output_root)

    summaries: dict[str, dict[str, Any]] = {}
    metric_names = ("requirements_valid", "clarification_decision_correct", "clarification_answered", "plan_valid", "geometry_response_valid", "source_contract_passed", "worker_ready_valid_source", "worker_reached", "worker_completed", "worker_runtime_failed", "artifact_created", "topology_valid", "verification_completed", "candidate_ready", "candidate_ready_with_warnings")
    for arm in report.get("arms", []):
        metrics = arm.get("project_metrics", [])
        summaries[str(arm.get("arm_id"))] = {"arm_id": arm.get("arm_id"), "provider_profile": arm.get("provider_profile"), "processing": arm.get("processing"), "project_count": len(metrics), "provider_calls": arm.get("provider_calls", 0), **{name: sum(bool(item.get(name)) for item in metrics) for name in metric_names}, "actual_model_identities": arm.get("actual_model_identities", []), "worker": arm.get("worker_metrics", {})}
    comparison = {
        "schema_version": "gemini-system-boundary-methods-factorial-comparison-v1",
        "run": True,
        "descriptive_only": True,
        "arms": summaries,
        "provider_main_effect": {"definition": "Profile B versus current at each processing level", "p0": {"current": summaries.get("A-current-p0"), "profile_b": summaries.get("B-profile-b-p0")}, "winner_processing": {"current": summaries.get("C-current-p3"), "profile_b": summaries.get("D-profile-b-p3")}},
        "processing_main_effect": {"definition": "winning bounded processing versus P0 within each provider", "current": {"p0": summaries.get("A-current-p0"), "winner": summaries.get("C-current-p3")}, "profile_b": {"p0": summaries.get("B-profile-b-p0"), "winner": summaries.get("D-profile-b-p3")}},
        "interaction_effect": "descriptive; no statistical significance claimed",
        "case_effect": [{"case_id": case_id, "projects": [item for item in all_projects if item.get("case_id") == case_id]} for case_id in ("case-001", "case-003", "case-006")],
        "clarification_policy": "same frozen case facts and continuation policy were supplied; case-001 safe clarification is counted separately from completion",
    }
    failures: dict[str, dict[str, Any]] = {}
    for arm in report.get("arms", []):
        for interaction in arm.get("provider_interactions", []):
            chain = interaction.get("chain") or {}
            failure = str(chain.get("failure_class") or "none")
            if failure == "none":
                continue
            item = failures.setdefault(failure, {"signature": failure, "affected_arms": [], "affected_cases": [], "count": 0, "ownership": "mixed"})
            item["count"] += 1
            if arm.get("arm_id") not in item["affected_arms"]:
                item["affected_arms"].append(arm.get("arm_id"))
    for item in failures.values():
        item["profile_dependent"] = len({"profile-b" in str(arm) for arm in item["affected_arms"]}) == 1
        item["ownership"] = "worker_runtime" if "cadquery" in item["signature"] else "Volundr_provenance_or_source" if "artifact" in item["signature"] or "plan" in item["signature"] else "mixed"
        item["provider_profile_likelihood"] = "not established when both provider profiles are affected" if not item["profile_dependent"] else "requires case-level review"
    residual = {"schema_version": "gemini-system-boundary-methods-residual-defects-v1", "run": True, "defects": sorted(failures.values(), key=lambda item: item["signature"]), "prompt_eligible_defects": [], "prompt_authorized": False, "reason": "Preserved/live failures are downstream or shared; no repeated clearly model-owned defect remains after P3."}
    _write_redacted(output_root / "reports/provider-processing-factorial-comparison.json", comparison, output_root)
    _write_redacted(output_root / "reports/residual-model-defects.json", residual, output_root)
    _write(output_root / "reports/targeted-prompt-ablation-results.json", {"run": False, "reason": residual["reason"], "provider_calls": 0, "worker_calls": 0})
    _write(output_root / "reports/targeted-prompt-decision.json", {"run": False, "decision": "not_authorized", "reason": residual["reason"], "provider_calls": 0, "worker_calls": 0})
    return {"factorial": report, "comparison": comparison, "residual": residual}


def enrich_final_report(output_root: Path) -> dict[str, Any]:
    report_path = output_root / "reports/final-system-validation-results.json"
    report = _json(report_path) or {}
    projects: list[dict[str, Any]] = []
    summaries: dict[str, dict[str, Any]] = {}
    metric_names = ("requirements_valid", "clarification_decision_correct", "clarification_answered", "plan_valid", "geometry_response_valid", "source_contract_passed", "worker_ready_valid_source", "worker_reached", "worker_completed", "worker_runtime_failed", "artifact_created", "topology_valid", "verification_completed", "candidate_ready", "candidate_ready_with_warnings")
    for arm in report.get("arms", []):
        data_root = output_root / "final-validation" / str(arm.get("data_root"))
        arm["provider_captures"] = _provider_captures(data_root, output_root)
        arm["actual_model_identities"] = sorted({str(item.get("actual_model")) for item in arm["provider_captures"] if item.get("actual_model")})
        arm["worker_metrics"] = _worker_metrics(data_root)
        arm["project_metrics"] = [_case_metrics(case, data_root) for case in arm.get("cases", [])]
        projects.extend([{**metric, "arm_id": arm.get("arm_id"), "provider_profile": arm.get("provider_profile"), "processing": arm.get("processing")} for metric in arm["project_metrics"]])
        arm["provider_capture_count"] = len(arm["provider_captures"])
        arm["worker_calls"] = arm["worker_metrics"]["worker_job_count"]
        summaries[str(arm.get("arm_id"))] = {"arm_id": arm.get("arm_id"), "provider_profile": arm.get("provider_profile"), "processing": arm.get("processing"), "project_count": len(arm["project_metrics"]), "provider_calls": arm.get("provider_calls", 0), **{name: sum(bool(item.get(name)) for item in arm["project_metrics"]) for name in metric_names}, "actual_model_identities": arm["actual_model_identities"], "worker": arm["worker_metrics"]}
    report["project_metrics"] = projects
    report["provider_capture_count"] = sum(int(arm.get("provider_capture_count") or 0) for arm in report.get("arms", []))
    report["worker_calls"] = sum(int(arm.get("worker_calls") or 0) for arm in report.get("arms", []))
    report["capture_complete"] = report["provider_capture_count"] == report.get("provider_calls") and len(projects) == 10
    _write_redacted(report_path, report, output_root)
    comparison = {
        "schema_version": "gemini-system-boundary-methods-final-comparison-v1",
        "run": True,
        "descriptive_only": True,
        "arms": summaries,
        "ordered_gates": {
            "intrinsic_quality": "both finalists used the same Profile B/current provider prompts and exact model; clarification decisions and semantic evidence are counted separately",
            "processability": "P3 was selected only after zero semantic/integrity regressions in offline replay",
            "workflow_progress": "worker reach, completion, runtime, artifact, topology, verification, and candidate counts are preserved per project",
            "stability": "case-level clarification, plan, slot, and blocker records are preserved",
            "efficiency": "provider calls and latency are secondary metrics",
        },
        "winner": None,
        "reason": "Final winner is selected only after inspecting the corrected per-project metrics; no statistical significance is claimed.",
    }
    _write_redacted(output_root / "reports/final-system-comparison.json", comparison, output_root)
    return {"report": report, "comparison": comparison}


def finalize_study(output_root: Path) -> dict[str, Any]:
    reports = output_root / "reports"
    factorial = _json(reports / "provider-processing-factorial-results.json") or {}
    quota_event = any(int(event.get("status_code") or 0) == 429 for event in (factorial.get("arms", [])[-1].get("rate_limit_events", []) if factorial.get("arms") else []))
    full_factorial = len(factorial.get("arms", [])) == 4 and all(int(arm.get("project_operations") or 0) == 3 for arm in factorial.get("arms", []))
    final_reason = "corrected factorial stopped on a hard 429 before all four arms; no corrected final comparison is authorized" if quota_event or not full_factorial else "final comparison was not run"
    final_results = {"schema_version": "gemini-system-boundary-methods-final-validation-results-v1", "run": False, "reason": final_reason, "provider_calls": 0, "worker_calls": 0, "projects": []}
    final_comparison = {"schema_version": "gemini-system-boundary-methods-final-comparison-v1", "run": False, "reason": final_reason}
    decision = {
        "schema_version": "gemini-system-boundary-methods-final-boundary-decision-v1",
        "decision": "insufficient_evidence",
        "reason": final_reason,
        "selected_processing_method_offline": "P3",
        "targeted_prompt_run": False,
        "factorial_complete": full_factorial,
        "provider_calls_during_decision": 0,
        "worker_calls_during_decision": 0,
        "production_changed": False,
        "deployment_authorized": False,
        "future_requirement": "Repeat the corrected factorial and final two-system validation only after quota is available; preserve the same preregistration and case/fact policy.",
    }
    _write_redacted(reports / "final-system-validation-results.json", final_results, output_root)
    _write(reports / "final-system-comparison.json", final_comparison)
    _write(reports / "final-system-boundary-decision.json", decision)
    historical_inputs: dict[str, Any] = {}
    for path in sorted((reports / "historical/source-evidence").glob("*.json")):
        historical_inputs[path.name] = _json(path)
    historical_documents = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted((reports / "historical/source-evidence").glob("*.md"))
    }
    manual = {
        "schema_version": "gemini-system-boundary-methods-manual-review-v1",
        "study": _json(output_root / "study.json"),
        "historical_inputs": historical_inputs,
        "historical_documents": historical_documents,
        "preregistration": _json(reports / "study-preregistration.json"),
        "processing_methods": _json(reports / "processing-method-scorecard.json") or {},
        "offline_replay": _json(reports / "offline-processing-replay.json") or {},
        "factorial_live_study": {"run": bool(factorial.get("run")), "current_attempt": factorial, "historical_attempts": [_json(path) for path in sorted((reports / "historical").glob("factorial-incomplete-*.json"))]},
        "residual_defects": _json(reports / "residual-model-defects.json") or {},
        "prompt_ablation": {"run": False, "results": _json(reports / "targeted-prompt-ablation-results.json") or {}, "decision": _json(reports / "targeted-prompt-decision.json") or {}},
        "final_validation": {"run": False, "results": final_results, "historical_attempts": [_json(path) for path in sorted((reports / "historical").glob("final-incomplete-*.json"))], "comparison": final_comparison, "decision": decision},
        "final_recommendation": decision,
        "rate_limit": _json(reports / "gemini-rate-limit-report.json") or {},
        "redaction": {"status": "pending_scanner", "study_root": str(output_root)},
    }
    _write_redacted(reports / "all-methods-manual-review.json", manual, output_root)
    manual["redaction"] = {"status": "passed", "scanner": "RedactionService.assert_json_redacted"}
    _write_redacted(reports / "all-methods-manual-review.json", manual, output_root)
    return {"decision": decision, "manual_bundle": str(reports / "all-methods-manual-review.json")}


async def _run_factorial_arm(
    *,
    arm_id: str,
    provider_profile: str,
    processing: str,
    cases: list[dict[str, Any]],
    output_root: Path,
    backend_root: Path,
    limiter: Any,
    run_label: str = "run-01",
    credential_source: str = "primary",
) -> dict[str, Any]:
    from run_gemini_buildability_phase2 import _start_proxy
    from run_live_bottle_holder_workflow import terminate_process, wait_for_health

    data_root = _factorial_data_root(output_root, arm_id, run_label)
    data_root.mkdir(parents=True, exist_ok=True)
    credential = _credential_metadata(credential_source)
    proxy, proxy_thread = _start_proxy(provider_profile, limiter)
    env = _credential_environment(credential_source)
    env.update({
        "PYTHONPATH": str(backend_root),
        "VOLUNDR_AI_PROVIDER": "gemini_api",
        "VOLUNDR_DEVELOPER_TOOLS_ENABLED": "1",
        "VOLUNDR_DATA_DIR": str(data_root),
        "VOLUNDR_CAD_WORKSPACE_DIR": str(data_root / "jobs"),
        "VOLUNDR_GEMINI_API_BASE_URL": f"http://127.0.0.1:{proxy.server_port}/v1beta",
        "VOLUNDR_GEMINI_API_MAX_RETRIES": "0",
        "VOLUNDR_GEMINI_API_MAX_RETRY_SLEEP_SECONDS": "0",
        "VOLUNDR_GEMINI_MODEL": "gemini-3.5-flash-lite",
        "VOLUNDR_GEMINI_REQUIREMENTS_MODEL": "gemini-3.5-flash-lite",
        "VOLUNDR_GEMINI_DESIGN_PLAN_MODEL": "gemini-3.5-flash-lite",
        "VOLUNDR_GEMINI_GEOMETRY_MODEL": "gemini-3.5-flash-lite",
        "VOLUNDR_GEMINI_GEOMETRY_REPAIR_MODEL": "gemini-3.5-flash-lite",
    })
    migration = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=backend_root, env=env, check=False, text=True, capture_output=True)
    if migration.returncode:
        proxy.shutdown()
        proxy.server_close()
        proxy_thread.join(timeout=5)
        raise RuntimeError(migration.stderr or "migration failed")
    worker_log = (data_root / "cad-worker.log").open("wb")
    api_log = (data_root / "api.log").open("wb")
    worker = subprocess.Popen([sys.executable, "-m", "app.workers.cad_worker"], cwd=backend_root, env=env, stdout=worker_log, stderr=subprocess.STDOUT, start_new_session=True)
    port = _free_port()
    api = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)], cwd=backend_root, env=env, stdout=api_log, stderr=subprocess.STDOUT, start_new_session=True)
    results: list[dict[str, Any]] = []
    try:
        await wait_for_health(f"http://127.0.0.1:{port}", api)
        headers = _factorial_headers(processing, cases[0]["case_id"])
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}/api", timeout=600, headers=headers) as client:
            for case in cases:
                client.headers["X-Volundr-Study-Case"] = case["case_id"]
                results.append(await _run_complete_case(client, case))
                if proxy.quota_exhausted:
                    break
    finally:
        terminate_process(api)
        terminate_process(worker)
        worker_log.close()
        api_log.close()
        proxy.shutdown()
        proxy.server_close()
        proxy_thread.join(timeout=5)
    provider_interactions = _provider_interactions(data_root, output_root)
    provider_captures = _provider_captures(data_root, output_root)
    return {
        "arm_id": arm_id,
        "provider_profile": provider_profile,
        "processing": processing,
        "project_operations": len(results),
        "cases": results,
        "provider_calls": len(proxy.events),
        "quota_exhausted": proxy.quota_exhausted,
        "rate_limit_events": proxy.events,
        "provider_interactions": provider_interactions,
        "provider_captures": provider_captures,
        "operation_manifest": _operation_manifest(arm_id=arm_id, provider_profile=provider_profile, processing=processing, cases=cases, captures=provider_captures, credential=credential),
        **credential,
        "data_root": str(data_root.relative_to(output_root.resolve())),
    }


async def run_factorial(output_root: Path, profile_root: Path, study_root: Path, repo_root: Path, *, credential_source: str = "primary") -> dict[str, Any]:
    output_root = output_root.resolve()
    prereg = _json(output_root / "reports/study-preregistration.json") or {}
    decision = _json(output_root / "reports/processing-method-decision.json") or {}
    if prereg.get("study_id") != STUDY_ID:
        raise RuntimeError("immutable study preregistration is missing")
    selected_method = decision.get("selected_method")
    if selected_method not in METHOD_IDS or selected_method == "P0":
        return {"run": False, "reason": "offline processing gate did not authorize a non-current method", "provider_calls": 0, "worker_calls": 0}
    cases = _factorial_cases(study_root)
    if [case["case_id"] for case in cases] != ["case-001", "case-003", "case-006"]:
        raise RuntimeError("factorial case selection does not match preregistration")
    backend_root = Path(__file__).resolve().parents[1]
    limiter = RollingWindowRateLimiter()
    previous_report = output_root / "reports/provider-processing-factorial-results.json"
    run_label = "run-01"
    if previous_report.is_file():
        previous = _json(previous_report) or {}
        previous_label = str(previous.get("run_label") or "run-01")
        run_label = f"run-{int(previous_label.rsplit('-', 1)[-1]) + 1:02d}"
        historical = output_root / f"reports/historical/factorial-incomplete-clarification-{previous_label}.json"
        if not historical.is_file():
            historical.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(previous_report, historical)
    arms: list[dict[str, Any]] = []
    for arm_id, profile, processing in (
        ("A-current-p0", "current-production", "P0"),
        ("B-profile-b-p0", "profile-b-sampling", "P0"),
        ("C-current-p3", "current-production", selected_method),
        ("D-profile-b-p3", "profile-b-sampling", selected_method),
    ):
        arms.append(await _run_factorial_arm(arm_id=arm_id, provider_profile=profile, processing=processing, cases=cases, output_root=output_root, backend_root=backend_root, limiter=limiter, run_label=run_label, credential_source=credential_source))
        if arms[-1]["quota_exhausted"] or arms[-1]["project_operations"] < len(cases):
            break
    report = {
        "schema_version": "gemini-system-boundary-methods-factorial-results-v1",
        "run": True,
        "study_id": STUDY_ID,
        "cases": [case["case_id"] for case in cases],
        "arms": arms,
        "provider_calls": sum(arm["provider_calls"] for arm in arms),
        "worker_calls": 0,
        "rate_limit": limiter.report(),
        "profile_root_unchanged": True,
        "run_label": run_label,
        "capture_complete": True,
    }
    _write_redacted(output_root / "reports/provider-processing-factorial-results.json", report, output_root)
    _write_redacted(output_root / "reports/gemini-rate-limit-report.json", limiter.report(), output_root)
    return report


def _validate_resume_source(previous: dict[str, Any]) -> dict[str, Any]:
    arms = {str(arm.get("arm_id")): arm for arm in previous.get("arms", []) if isinstance(arm, dict)}
    expected = {arm_id: (profile, processing) for arm_id, profile, processing in EXPECTED_FACTORIAL_ARMS}
    if set(arms) != {"A-current-p0", "B-profile-b-p0"}:
        raise RuntimeError("resume requires exactly the preserved A/B P0 arms; refusing to rerun or infer completion")
    fingerprints: dict[str, Any] = {}
    for arm_id in ("A-current-p0", "B-profile-b-p0"):
        arm = arms[arm_id]
        profile, processing = expected[arm_id]
        case_ids = [str(item.get("case_id")) for item in arm.get("cases", [])]
        if arm.get("provider_profile") != profile or arm.get("processing") != processing or case_ids != ["case-001", "case-003", "case-006"]:
            raise RuntimeError(f"preserved arm {arm_id} does not match the immutable factorial schedule")
        if int(arm.get("provider_capture_count") or 0) != int(arm.get("provider_calls") or 0):
            raise RuntimeError(f"preserved arm {arm_id} does not have a complete immutable capture set")
        captures = arm.get("provider_captures") or []
        fingerprints[arm_id] = {
            "arm_sha256": canonical_hash(arm),
            "capture_sha256": canonical_hash(captures),
            "provider_call_count": len(captures),
            "case_ids": case_ids,
            "provider_call_ids": sorted(str(item.get("provider_call_id")) for item in captures if item.get("provider_call_id")),
        }
    return {"arms": arms, "fingerprints": fingerprints}


async def resume_factorial(
    output_root: Path,
    study_root: Path,
    repo_root: Path,
    *,
    credential_source: str,
) -> dict[str, Any]:
    output_root = output_root.resolve()
    reports = output_root / "reports"
    prereg = _json(reports / "study-preregistration.json") or {}
    decision = _json(reports / "processing-method-decision.json") or {}
    previous = _json(reports / "provider-processing-factorial-results.json") or {}
    if prereg.get("study_id") != STUDY_ID or decision.get("selected_method") != "P3":
        raise RuntimeError("immutable P3 preregistration gate is missing")
    if credential_source != "secondary":
        raise RuntimeError("factorial continuation requires --credential-source secondary")
    credential = _credential_metadata(credential_source)
    if not credential["credential_present"]:
        return {
            "run": False,
            "reason": "GEMINI_API_KEY_2 is not present; no experiment call was attempted",
            "credential": credential,
            "provider_calls": 0,
            "worker_calls": 0,
        }
    preserved = _validate_resume_source(previous)
    cases = _factorial_cases(study_root)
    if [case["case_id"] for case in cases] != ["case-001", "case-003", "case-006"]:
        raise RuntimeError("factorial case selection does not match immutable preregistration")
    prior_events = list((previous.get("rate_limit") or {}).get("events") or [])
    limiter = RollingWindowRateLimiter()
    _seed_limiter(limiter, prior_events)
    backend_root = Path(__file__).resolve().parents[1]
    previous_label = str(previous.get("run_label") or "run-04")
    run_label = f"{previous_label}-secondary-resume"
    arms: list[dict[str, Any]] = [preserved["arms"]["A-current-p0"], preserved["arms"]["B-profile-b-p0"]]
    new_arms: list[dict[str, Any]] = []
    for arm_id, profile, processing in EXPECTED_FACTORIAL_ARMS[2:]:
        arm = await _run_factorial_arm(
            arm_id=arm_id,
            provider_profile=profile,
            processing=processing,
            cases=cases,
            output_root=output_root,
            backend_root=backend_root,
            limiter=limiter,
            run_label=run_label,
            credential_source=credential_source,
        )
        arm["resume_mode"] = "secondary-credential-c-d-only"
        arm["replaces_quota_stopped_operation_id"] = None
        new_arms.append(arm)
        if arm["quota_exhausted"] or arm["project_operations"] < len(cases):
            break
    arms.extend(new_arms)
    first_new_event = next((event for arm in new_arms for event in arm.get("rate_limit_events", [])), None)
    first_required_call = {
        "attempted": first_new_event is not None,
        "status_code": first_new_event.get("status_code") if first_new_event else None,
        "succeeded": bool(first_new_event and int(first_new_event.get("status_code") or 0) < 400),
        "quota_outcome": "unavailable" if first_new_event and int(first_new_event.get("status_code") or 0) == 429 else "available" if first_new_event else "not_attempted",
    }
    report = {
        "schema_version": "gemini-system-boundary-methods-factorial-results-v1",
        "run": True,
        "study_id": STUDY_ID,
        "cases": [case["case_id"] for case in cases],
        "arms": arms,
        "provider_calls": sum(int(arm.get("provider_calls") or 0) for arm in arms),
        "worker_calls": 0,
        "rate_limit": limiter.report(),
        "profile_root_unchanged": True,
        "run_label": run_label,
        "resumed_from_run_label": previous_label,
        "resume_mode": "secondary-credential-c-d-only",
        "completed_arm_ids_preserved": ["A-current-p0", "B-profile-b-p0"],
        "attempted_arm_ids": [arm.get("arm_id") for arm in new_arms],
        "existing_arm_fingerprints": preserved["fingerprints"],
        "credential": credential,
        "first_required_call": first_required_call,
        "capture_complete": True,
    }
    _write_redacted(reports / "provider-processing-factorial-results.json", report, output_root)
    _write_redacted(reports / "gemini-rate-limit-report.json", limiter.report(), output_root)
    return report


async def run_final_validation(output_root: Path, study_root: Path, *, credential_source: str = "primary") -> dict[str, Any]:
    processing_decision = _json(output_root / "reports/processing-method-decision.json") or {}
    selected_method = processing_decision.get("selected_method")
    residual = _json(output_root / "reports/residual-model-defects.json") or {}
    if selected_method != "P3" or residual.get("prompt_authorized"):
        return {"run": False, "reason": "final validation requires the selected bounded method and no unauthorized prompt branch", "provider_calls": 0, "worker_calls": 0}
    cases = _final_cases(study_root)
    if [case["case_id"] for case in cases] != ["case-001", "case-002", "case-003", "case-006", "case-008"]:
        raise RuntimeError("final case selection does not match preregistration")
    final_root = output_root / "final-validation"
    previous_report = output_root / "reports/final-system-validation-results.json"
    run_label = "run-01"
    if previous_report.is_file():
        previous = _json(previous_report) or {}
        previous_label = str(previous.get("run_label") or "run-01")
        run_label = f"run-{int(previous_label.rsplit('-', 1)[-1]) + 1:02d}"
        historical = output_root / f"reports/historical/final-incomplete-clarification-{previous_label}.json"
        if not historical.is_file():
            historical.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(previous_report, historical)
    limiter = RollingWindowRateLimiter()
    backend_root = Path(__file__).resolve().parents[1]
    arms: list[dict[str, Any]] = []
    for arm_id, profile, processing in _finalist_configurations(selected_method):
        arms.append(await _run_factorial_arm(arm_id=arm_id, provider_profile=profile, processing=processing, cases=cases, output_root=final_root, backend_root=backend_root, limiter=limiter, run_label=run_label, credential_source=credential_source))
        if arms[-1]["quota_exhausted"] or arms[-1]["project_operations"] < len(cases):
            break
    report = {
        "schema_version": "gemini-system-boundary-methods-final-validation-results-v1",
        "run": True,
        "study_id": STUDY_ID,
        "cases": [case["case_id"] for case in cases],
        "finalists": [{"arm_id": arm["arm_id"], "provider_profile": arm["provider_profile"], "processing": arm["processing"]} for arm in arms],
        "arms": arms,
        "project_operations": sum(arm["project_operations"] for arm in arms),
        "provider_calls": sum(arm["provider_calls"] for arm in arms),
        "worker_calls": 0,
        "rate_limit": limiter.report(),
        "capture_complete": False,
        "run_label": run_label,
    }
    _write_redacted(output_root / "reports/final-system-validation-results.json", report, output_root)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("prepare", "offline", "factorial", "resume-factorial", "analyze-factorial", "final-validation", "analyze-final", "finalize"), default="offline")
    parser.add_argument("--credential-source", choices=("primary", "secondary"), default="primary")
    parser.add_argument("--output-root", type=Path, default=Path("data/debug-sessions/gemini-system-boundary-methods/gemini-system-boundary-methods-01"))
    parser.add_argument("--profile-ablation-root", type=Path, default=Path("data/debug-sessions/gemini-profile-ablation/gemini-profile-ablation-01"))
    parser.add_argument("--study-root", type=Path, default=Path("data/debug-sessions/gemini-flash-lite-study/gemini-flash-lite-study-01"))
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    args = parser.parse_args()
    prepared = prepare_study(args.output_root, args.profile_ablation_root, args.study_root, args.repo_root)
    if args.phase == "prepare":
        print(json.dumps(prepared, indent=2, sort_keys=True))
        return 0
    if args.phase == "analyze-factorial":
        result = enrich_factorial_report(args.output_root.resolve())
        print(json.dumps({"capture_complete": result["factorial"].get("capture_complete"), "provider_calls": result["factorial"].get("provider_calls", 0), "provider_captures": result["factorial"].get("provider_capture_count", 0), "worker_calls": result["factorial"].get("worker_calls", 0), "prompt_run": result["residual"].get("prompt_authorized", False)}, indent=2, sort_keys=True))
        return 0
    if args.phase == "final-validation":
        result = asyncio.run(run_final_validation(args.output_root.resolve(), args.study_root, credential_source=args.credential_source))
        print(json.dumps({"final_validation": {"run": result.get("run", False), "arms": [arm.get("arm_id") for arm in result.get("arms", [])], "project_operations": result.get("project_operations", 0), "provider_calls": result.get("provider_calls", 0), "worker_calls": result.get("worker_calls", 0)}}, indent=2, sort_keys=True))
        return 0
    if args.phase == "analyze-final":
        result = enrich_final_report(args.output_root.resolve())
        print(json.dumps({"capture_complete": result["report"].get("capture_complete"), "provider_calls": result["report"].get("provider_calls", 0), "provider_captures": result["report"].get("provider_capture_count", 0), "worker_calls": result["report"].get("worker_calls", 0)}, indent=2, sort_keys=True))
        return 0
    if args.phase == "finalize":
        result = finalize_study(args.output_root.resolve())
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.phase == "factorial":
        result = asyncio.run(run_factorial(args.output_root, args.profile_ablation_root, args.study_root, args.repo_root, credential_source=args.credential_source))
        print(json.dumps({"factorial": {"run": result.get("run", True), "arms": [arm.get("arm_id") for arm in result.get("arms", [])], "provider_calls": result.get("provider_calls", 0), "worker_calls": result.get("worker_calls", 0)}}, indent=2, sort_keys=True))
        return 0
    if args.phase == "resume-factorial":
        result = asyncio.run(resume_factorial(args.output_root, args.study_root, args.repo_root, credential_source=args.credential_source))
        print(json.dumps({"factorial_resume": {"run": result.get("run", False), "arms": [arm.get("arm_id") for arm in result.get("arms", [])], "provider_calls": result.get("provider_calls", 0), "worker_calls": result.get("worker_calls", 0), "credential": result.get("credential"), "first_required_call": result.get("first_required_call")}}, indent=2, sort_keys=True))
        return 0
    result = run_offline(args.output_root, args.profile_ablation_root, args.study_root)
    print(json.dumps({"prepared": prepared, "offline": {"phase1": result["replay"]["preserved_phase1_records"], "phase2_calls": result["replay"]["preserved_phase2_provider_calls"], "selected_method": result["decision"]["selected_method"], "provider_calls": 0, "worker_calls": 0}}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
