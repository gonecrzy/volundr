#!/usr/bin/env python3
"""Prepare and replay the Gemini system-boundary methods study.

The default command is offline-only. Live phases are intentionally separate
and will refuse to run until the immutable preregistration and offline gate
exist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.services.gemini_consistency.system_boundary_methods import (
    DEFAULT_MIN_INTERVAL_SECONDS,
    DEFAULT_REQUESTS_PER_MINUTE,
    HARD_MAX_REQUESTS_PER_WINDOW,
    METHOD_IDS,
    replay_preserved_evidence,
)


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
        if existing != _preregistration(snapshot):
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("prepare", "offline"), default="offline")
    parser.add_argument("--output-root", type=Path, default=Path("data/debug-sessions/gemini-system-boundary-methods/gemini-system-boundary-methods-01"))
    parser.add_argument("--profile-ablation-root", type=Path, default=Path("data/debug-sessions/gemini-profile-ablation/gemini-profile-ablation-01"))
    parser.add_argument("--study-root", type=Path, default=Path("data/debug-sessions/gemini-flash-lite-study/gemini-flash-lite-study-01"))
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    args = parser.parse_args()
    prepared = prepare_study(args.output_root, args.profile_ablation_root, args.study_root, args.repo_root)
    if args.phase == "prepare":
        print(json.dumps(prepared, indent=2, sort_keys=True))
        return 0
    result = run_offline(args.output_root, args.profile_ablation_root, args.study_root)
    print(json.dumps({"prepared": prepared, "offline": {"phase1": result["replay"]["preserved_phase1_records"], "phase2_calls": result["replay"]["preserved_phase2_provider_calls"], "selected_method": result["decision"]["selected_method"], "provider_calls": 0, "worker_calls": 0}}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
