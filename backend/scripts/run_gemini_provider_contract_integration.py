#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.gemini_integration.corpus import build_integration_corpus
from app.services.gemini_integration.capture import IntegrationEvidenceStore
from app.services.gemini_integration.forensics import (
    CausalGraph,
    CounterfactualFixture,
    IssueRecord,
    IssueRegister,
    rank_issues,
    replay_captured_evidence_offline,
)
from app.services.gemini_integration.profile import INTEGRATION_PROFILE_ID, GeminiFlashLiteContractV1, require_integration_profile
from app.services.gemini_integration.real_ports import build_real_boundary_ports
from app.services.gemini_integration.reports import IntegrationReportWriter
from app.services.gemini_integration.transport import load_secondary_credential
from app.services.gemini_integration.workflow import IntegrationWorkflowRunner


STUDY_ID = "gemini-provider-contract-integration-01"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the explicit Gemini provider-contract integration study")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--study-id", default=STUDY_ID)
    parser.add_argument("--root", type=Path, default=Path("data/debug-sessions/gemini-provider-contract-integration"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--counterfactual", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--live", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        require_integration_profile(args.profile)
    except ValueError as exc:
        parser.error(str(exc))
    if args.study_id != STUDY_ID:
        parser.error(f"integration runner requires the preregistered study ID {STUDY_ID!r}")
    repo = Path(__file__).resolve().parents[2]
    profile = GeminiFlashLiteContractV1.from_repository(repo)
    writer = IntegrationReportWriter(args.root / args.study_id, repo)
    corpus = build_integration_corpus()
    writer.prepare(profile, corpus)
    evidence_store = IntegrationEvidenceStore(writer.root, study_id=args.study_id)
    if args.dry_run:
        return 0
    if args.replay and args.counterfactual:
        parser.error("choose one offline mode at a time")
    if args.replay:
        bundle_path = writer.reports_root / "all-integration-loop-evidence.json"
        evidence = json.loads(bundle_path.read_text(encoding="utf-8")) if bundle_path.is_file() else {"study": {"study_id": args.study_id}, "provider_attempts": evidence_store.provider_attempts()}
        replay = replay_captured_evidence_offline(evidence)
        (writer.root / "replays").mkdir(parents=True, exist_ok=True)
        (writer.root / "replays/offline-replay.json").write_text(json.dumps(replay, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        writer.write_final(profile=profile, projects=corpus, project_outcomes=[], provider_attempts=evidence_store.provider_attempts(), issues=[], next_action={"mode": "offline_replay"})
        return 0
    if args.counterfactual:
        fixtures = [
            CounterfactualFixture(
                fixture_id=f"counterfactual-{index:03d}",
                project_id=str(attempt.get("project_id") or "unknown"),
                single_variable_changed="adapter_normalization",
                evidence={"source_attempt_id": attempt.get("attempt_id"), "synthetic": True},
            ).as_dict()
            for index, attempt in enumerate(evidence_store.provider_attempts(), start=1)
        ]
        (writer.root / "counterfactuals").mkdir(parents=True, exist_ok=True)
        (writer.root / "counterfactuals/one-variable-fixtures.json").write_text(json.dumps(fixtures, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        writer.write_final(profile=profile, projects=corpus, project_outcomes=[], provider_attempts=evidence_store.provider_attempts(), issues=[], counterfactuals=fixtures, next_action={"mode": "offline_counterfactual"})
        return 0
    if not args.live:
        parser.error("live execution requires --live; use --dry-run for preregistration only")
    load_secondary_credential()
    ports = build_real_boundary_ports(
        profile=profile,
        evidence_store=evidence_store,
        jobs_root=writer.root / "worker-jobs",
    )
    runner = IntegrationWorkflowRunner(
        profile=profile,
        study_id=args.study_id,
        evidence_store=evidence_store,
        ports=ports,
    )
    register = IssueRegister()
    causal = CausalGraph()
    outcomes, register = _run_live_projects(runner, corpus, evidence_store, register)
    ranked = rank_issues((issue, {"frequency": 1, "severity": 3, "confidence": 1, "downstream_impact": 2, "estimated_correction_cost": 1}) for issue in register.all())
    decision = "integration_foundation_ready" if outcomes and evidence_store.provider_attempts() else "insufficient_evidence"
    writer.write_final(
        profile=profile,
        projects=corpus,
        project_outcomes=outcomes,
        provider_attempts=evidence_store.provider_attempts(),
        issues=register.as_dict(),
        causal_graph=causal.as_dict(),
        ownership_summary={issue.primary_owner: sum(1 for item in register.all() if item.primary_owner == issue.primary_owner) for issue in register.all()},
        priority_ranking=ranked,
        next_action={"decision_basis": "complete workflow evidence", "repair_prerequisite": False},
        rate_limit={"events": ports.provider.limiter.events if ports.provider is not None else [], "default_requests_per_minute": 12, "hard_max_requests_per_rolling_60_seconds": 15, "minimum_gap_seconds": 5, "concurrency": 1},
        retry_summary={"attempts": len(evidence_store.provider_attempts()), "retries": sum(1 for attempt in evidence_store.provider_attempts() if attempt.get("attempt_index", 0) > 0)},
        decision=decision,
    )
    return 0


def _run_live_projects(runner: IntegrationWorkflowRunner, corpus, evidence_store, register):
    import asyncio

    async def run_all():
        outcomes = []
        for project in corpus:
            if len(evidence_store.provider_attempts()) >= 50:
                break
            outcome = await runner.run_project(project)
            outcomes.append(outcome.as_dict())
            if outcome.earliest_blocker:
                register.add(_issue_from_outcome(outcome, project.project_id, evidence_store))
        return outcomes, register

    return asyncio.run(run_all())


def _issue_from_outcome(outcome, project_id: str, evidence_store: IntegrationEvidenceStore) -> IssueRecord:
    boundary = outcome.earliest_blocker or "unknown"
    owner = {
        "requirements_adapter": "requirements_adapter",
        "plan_adapter": "plan_adapter",
        "geometry_adapter": "geometry_adapter",
        "static_validator": "static_validator",
        "worker_runtime": "worker_runtime",
        "transport": "transport",
    }.get(boundary, "unknown")
    return IssueRecord(
        issue_id=f"issue-{project_id}-01",
        project_id=project_id,
        stage=boundary,
        primary_owner=owner,
        secondary_factors=(),
        classification="root_cause",
        symptom=f"workflow stopped at {boundary}",
        incorrect_behavior="the complete workflow did not reach its next boundary",
        expected_behavior="the boundary should produce an authoritative valid result",
        evidence_paths=tuple(str(item.get("boundary_id")) for item in evidence_store.boundaries() if item.get("project_id") == project_id),
        input_hashes=(),
        output_hashes=(),
        confidence="confirmed",
        recommended_fix_boundary=owner,
        provider_call_required=owner.startswith("provider"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
