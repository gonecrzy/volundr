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
    replay_preserved_evidence,
)
from app.services.gemini_consistency.buildability_reanalysis import RollingWindowRateLimiter
from app.services.workflow.redaction import RedactionService


STUDY_ID = "gemini-system-boundary-methods-01"
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
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


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


async def _run_factorial_arm(
    *,
    arm_id: str,
    provider_profile: str,
    processing: str,
    cases: list[dict[str, Any]],
    output_root: Path,
    backend_root: Path,
    limiter: Any,
) -> dict[str, Any]:
    from run_gemini_buildability_phase2 import _start_proxy
    from run_live_bottle_holder_workflow import terminate_process, wait_for_health
    from run_live_multi_design_evaluation import run_case

    data_root = output_root / "factorial" / "live-data" / arm_id
    data_root.mkdir(parents=True, exist_ok=True)
    proxy, proxy_thread = _start_proxy(provider_profile, limiter)
    env = os.environ.copy()
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
        headers = {
            "X-Volundr-Benchmark-Provider": "gemini_api",
            "X-Volundr-Benchmark-Model": "gemini-3.5-flash-lite",
            "X-Volundr-Benchmark-Processing": processing,
        }
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}/api", timeout=600, headers=headers) as client:
            for case in cases:
                results.append(await run_case(client, case))
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
    return {
        "arm_id": arm_id,
        "provider_profile": provider_profile,
        "processing": processing,
        "project_operations": len(results),
        "cases": results,
        "provider_calls": len(proxy.events),
        "quota_exhausted": proxy.quota_exhausted,
        "rate_limit_events": proxy.events,
        "provider_interactions": _provider_interactions(data_root, output_root),
        "data_root": str(data_root.relative_to(output_root)),
    }


async def run_factorial(output_root: Path, profile_root: Path, study_root: Path, repo_root: Path) -> dict[str, Any]:
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
    arms: list[dict[str, Any]] = []
    for arm_id, profile, processing in (
        ("A-current-p0", "current-production", "P0"),
        ("B-profile-b-p0", "profile-b-sampling", "P0"),
        ("C-current-p3", "current-production", selected_method),
        ("D-profile-b-p3", "profile-b-sampling", selected_method),
    ):
        arms.append(await _run_factorial_arm(arm_id=arm_id, provider_profile=profile, processing=processing, cases=cases, output_root=output_root, backend_root=backend_root, limiter=limiter))
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
    }
    _write_redacted(output_root / "reports/provider-processing-factorial-results.json", report, output_root)
    _write_redacted(output_root / "reports/gemini-rate-limit-report.json", limiter.report(), output_root)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("prepare", "offline", "factorial"), default="offline")
    parser.add_argument("--output-root", type=Path, default=Path("data/debug-sessions/gemini-system-boundary-methods/gemini-system-boundary-methods-01"))
    parser.add_argument("--profile-ablation-root", type=Path, default=Path("data/debug-sessions/gemini-profile-ablation/gemini-profile-ablation-01"))
    parser.add_argument("--study-root", type=Path, default=Path("data/debug-sessions/gemini-flash-lite-study/gemini-flash-lite-study-01"))
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    args = parser.parse_args()
    prepared = prepare_study(args.output_root, args.profile_ablation_root, args.study_root, args.repo_root)
    if args.phase == "prepare":
        print(json.dumps(prepared, indent=2, sort_keys=True))
        return 0
    if args.phase == "factorial":
        result = asyncio.run(run_factorial(args.output_root, args.profile_ablation_root, args.study_root, args.repo_root))
        print(json.dumps({"factorial": {"run": result.get("run", True), "arms": [arm.get("arm_id") for arm in result.get("arms", [])], "provider_calls": result.get("provider_calls", 0), "worker_calls": result.get("worker_calls", 0)}}, indent=2, sort_keys=True))
        return 0
    result = run_offline(args.output_root, args.profile_ablation_root, args.study_root)
    print(json.dumps({"prepared": prepared, "offline": {"phase1": result["replay"]["preserved_phase1_records"], "phase2_calls": result["replay"]["preserved_phase2_provider_calls"], "selected_method": result["decision"]["selected_method"], "provider_calls": 0, "worker_calls": 0}}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
