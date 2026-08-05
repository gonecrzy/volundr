#!/usr/bin/env python3
"""Run and analyze a manifest-driven representative CAD workflow wave."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from app.services.gemini_integration.forensics import CounterfactualFixture, replay_captured_evidence_offline
from app.services.gemini_integration.profile import GeminiFlashLiteContractV1, require_integration_profile
from app.services.gemini_integration.real_ports import build_real_boundary_ports
from app.services.gemini_integration.representative_waves import (
    WAVE_PROVENANCE_MARKER,
    WaveEvidenceStore,
    WaveRunner,
    analyze_wave_issues,
    build_wave_bundle,
    cluster_wave_issues,
    initialize_wave,
    load_wave_manifest,
    load_wave_state,
    rank_wave_issues,
    read_wave_report,
    write_wave_report,
)
from app.services.gemini_integration.transport import load_secondary_credential
from app.services.gemini_integration.workflow import IntegrationWorkflowRunner


DEFAULT_MANIFEST = Path("data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01/wave-manifest.json")
DEFAULT_ROOT = Path("data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a repeatable manifest-driven representative workflow wave")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--profile", default="gemini_flash_lite_contract_v1")
    parser.add_argument("--prepare", action="store_true", help="write preregistration and empty report tree without calls")
    parser.add_argument("--baseline", action="store_true", help="run every preregistered project through the real workflow")
    parser.add_argument("--live", action="store_true", help="authorize provider and worker calls for --baseline")
    parser.add_argument("--analyze", action="store_true", help="diagnose all preserved baseline evidence offline")
    parser.add_argument("--replay", action="store_true", help="replay captured provider responses offline")
    parser.add_argument("--counterfactual", action="store_true", help="run one-variable adapter counterfactuals offline")
    parser.add_argument("--resume", action="store_true", help="resume an interrupted baseline idempotently")
    return parser


def _resolve(path: Path, repository_root: Path) -> Path:
    return path if path.is_absolute() else repository_root / path


def _previous_plan(store: WaveEvidenceStore, project) -> dict[str, Any] | None:
    if not project.revision_of:
        return None
    candidates = [
        boundary for boundary in store.boundaries()
        if boundary.get("project_id") == project.revision_of and boundary.get("boundary") == "plan_adapter"
    ]
    if not candidates:
        return None
    normalized = (candidates[-1].get("output") or {}).get("normalized")
    return normalized if isinstance(normalized, dict) else None


def _write_execution_reports(manifest, root: Path, store: WaveEvidenceStore, outcomes: list[dict[str, Any]], *, ports=None) -> None:
    provider_attempts = store.provider_attempts()
    worker_jobs = store.worker_jobs()
    write_wave_report(root, "provider-attempts.json", provider_attempts)
    write_wave_report(root, "worker-jobs.json", worker_jobs)
    write_wave_report(root, "project-outcomes.json", outcomes)
    rate_limit = {
        "events": list(getattr(getattr(ports, "provider", None), "limiter", None).events)
        if getattr(getattr(ports, "provider", None), "limiter", None) is not None else [],
        "default_request_starts_per_rolling_60_seconds": 12,
        "hard_max_request_starts_per_rolling_60_seconds": 15,
        "minimum_start_gap_seconds": 5,
        "concurrency": 1,
    }
    retry_summary = {
        "logical_operations": len({str(item.get("operation_id")) for item in provider_attempts}),
        "attempts": len(provider_attempts),
        "retries": sum(1 for item in provider_attempts if int(item.get("attempt_index", 0)) > 0),
        "max_attempts_per_logical_operation": 2,
    }
    write_wave_report(root, "rate-limit-report.json", rate_limit)
    write_wave_report(root, "retry-report.json", retry_summary)
    bundle = build_wave_bundle(
        manifest,
        store,
        outcomes=outcomes,
        rate_limit=rate_limit,
        retry_summary=retry_summary,
    )
    write_wave_report(root, "combined-wave-evidence.json", bundle)


async def _run_baseline(manifest, root: Path, repository_root: Path, *, resume: bool) -> int:
    load_secondary_credential()
    store = WaveEvidenceStore(root, wave_id=manifest.wave_id)
    coordinator = WaveRunner(manifest, root)
    load_wave_state(coordinator)
    outcomes = list(read_wave_report(root, "project-outcomes.json", []))
    known_outcomes = {str(item.get("project_id")): item for item in outcomes}
    profile = GeminiFlashLiteContractV1.from_repository(repository_root)
    ports = build_real_boundary_ports(profile=profile, evidence_store=store, jobs_root=root / "worker-jobs")
    workflow = IntegrationWorkflowRunner(
        profile=profile,
        study_id=f"representative-workflow-{manifest.wave_id}",
        wave_id=manifest.wave_id,
        provenance_marker=WAVE_PROVENANCE_MARKER,
        evidence_store=store,
        ports=ports,
    )
    for project in manifest.projects:
        if resume and project.project_id in known_outcomes and project.project_id in coordinator.state.completed_project_ids:
            continue
        try:
            outcome = await workflow.run_project(project, previous_design_plan=_previous_plan(store, project))
            outcome_record = outcome.as_dict()
        except Exception as exc:  # preserve a confirmed harness boundary and continue the preregistered wave
            boundary_id = f"{project.project_id}:{project.project_id}:harness"
            store.record_boundary({
                "boundary_id": boundary_id,
                "boundary": "harness",
                "project_id": project.project_id,
                "failure_class": "harness_or_fixture",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "provenance": {
                    "wave_id": manifest.wave_id,
                    "project_id": project.project_id,
                    "provenance_marker": WAVE_PROVENANCE_MARKER,
                },
            })
            outcome_record = {
                "project_id": project.project_id,
                "revision_id": f"{project.project_id}:revision-001",
                "earliest_blocker": "harness_or_fixture",
                "furthest_valid_stage": "input",
                "candidate_decision": None,
                "boundary_ids": [boundary_id],
                "provider_attempt_ids": [],
                "worker_jobs": [],
            }
        known_outcomes[project.project_id] = outcome_record
        outcomes = [known_outcomes[item.project_id] for item in manifest.projects if item.project_id in known_outcomes]
        coordinator.record_baseline_project(project.project_id)
        coordinator.save_state()
        _write_execution_reports(manifest, root, store, outcomes, ports=ports)
    if set(coordinator.state.completed_project_ids) != {project.project_id for project in manifest.projects}:
        raise RuntimeError("baseline wave did not complete every preregistered project")
    _write_execution_reports(manifest, root, store, outcomes, ports=ports)
    return 0


def _offline_replay(manifest, root: Path, *, counterfactual: bool) -> int:
    store = WaveEvidenceStore(root, wave_id=manifest.wave_id)
    bundle = read_wave_report(root, "combined-wave-evidence.json", {})
    result = replay_captured_evidence_offline(bundle, boundaries=store.boundaries())
    root.joinpath("replays").mkdir(parents=True, exist_ok=True)
    root.joinpath("replays/offline-replay.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if counterfactual:
        fixtures = [
            CounterfactualFixture(
                fixture_id=f"{manifest.wave_id}-counterfactual-{index:03d}",
                project_id=str(attempt.get("project_id") or "unknown"),
                single_variable_changed="original_response_through_original_adapter",
                evidence={"source_attempt_id": attempt.get("attempt_id"), "synthetic": True},
            ).as_dict()
            for index, attempt in enumerate(bundle.get("provider_attempts", []) or [], start=1)
        ]
        result = {**result, "fixtures": fixtures, "provider_successes": 0}
    write_wave_report(root, "counterfactual-replays.json", result)
    return 0


def _analyze(manifest, root: Path) -> int:
    store = WaveEvidenceStore(root, wave_id=manifest.wave_id)
    outcomes = read_wave_report(root, "project-outcomes.json", [])
    coordinator = WaveRunner(manifest, root)
    load_wave_state(coordinator)
    analysis = analyze_wave_issues(manifest, outcomes, store)
    clusters = cluster_wave_issues(analysis["issues"])
    ranking = rank_wave_issues(analysis["issues"], clusters)
    write_wave_report(root, "issue-register.json", analysis["issues"])
    write_wave_report(root, "issue-causal-graph.json", analysis["causal_graph"])
    write_wave_report(root, "cross-project-issue-clusters.json", clusters)
    write_wave_report(root, "issue-priority-ranking.json", ranking)
    write_wave_report(root, "ownership-summary.json", {
        owner: sum(1 for issue in analysis["issues"] if issue.get("primary_owner") == owner)
        for owner in sorted({str(issue.get("primary_owner")) for issue in analysis["issues"]})
    })
    write_wave_report(root, "unresolved-unknowns.json", [
        issue for issue in analysis["issues"] if issue.get("confidence") == "unknown"
    ])
    coordinator.mark_analysis_complete(
        issues_registered=True,
        clusters_complete=True,
        priority_complete=True,
    )
    bundle = build_wave_bundle(
        manifest,
        store,
        outcomes=outcomes,
        issues=analysis["issues"],
        causal_graph=analysis["causal_graph"],
        clusters=clusters,
        ranking=ranking,
    )
    write_wave_report(root, "combined-wave-evidence.json", bundle)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    selected = sum(bool(value) for value in (args.prepare, args.baseline, args.analyze, args.replay, args.counterfactual))
    if selected != 1:
        parser.error("choose exactly one of --prepare, --baseline, --analyze, --replay, or --counterfactual")
    if args.baseline and not args.live:
        parser.error("baseline execution requires --live; use --prepare for provider-free preregistration")
    if args.resume and not args.baseline:
        parser.error("--resume is only valid with --baseline")
    try:
        require_integration_profile(args.profile)
    except ValueError as exc:
        parser.error(str(exc))
    repository_root = Path(__file__).resolve().parents[2]
    manifest_path = _resolve(args.manifest, repository_root)
    root = _resolve(args.root, repository_root)
    manifest = load_wave_manifest(manifest_path)
    if manifest.provider_profile != args.profile:
        parser.error("manifest provider_profile does not match --profile")
    if args.prepare or (args.baseline and not args.resume):
        initialize_wave(root, manifest, repository_root=repository_root)
    if args.prepare:
        return 0
    if args.baseline:
        return asyncio.run(_run_baseline(manifest, root, repository_root, resume=args.resume))
    if args.analyze:
        return _analyze(manifest, root)
    return _offline_replay(manifest, root, counterfactual=args.counterfactual)


if __name__ == "__main__":
    raise SystemExit(main())
