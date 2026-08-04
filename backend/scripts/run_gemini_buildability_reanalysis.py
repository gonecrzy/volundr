#!/usr/bin/env python3
"""Re-score the completed Gemini profile ablation without provider access."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.services.gemini_consistency.buildability_reanalysis import (
    DEFAULT_MIN_INTERVAL_SECONDS,
    DEFAULT_REQUESTS_PER_MINUTE,
    MAX_ROLLING_REQUESTS,
    RollingWindowRateLimiter,
    authoritative_packet_expectations,
    preserve_historical_reports,
    rescore_phase1_records,
    write_manual_review_bundle,
)
from app.services.workflow.redaction import RedactionService
from scripts.run_gemini_profile_ablation import repository_identity


def _read(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any, *, data_root: Path) -> None:
    redactor = RedactionService()
    safe, _ = redactor.redact_evidence_value(value, data_root=data_root, evidence_root=path.parent)
    redactor.assert_json_redacted(safe)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(safe, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_reanalysis_reports(*, output_root: Path, study_root: Path, repository_root: Path) -> dict[str, Any]:
    historical_root = output_root / "reports" / "historical" / "pre-buildability-reanalysis"
    source_reports = output_root / "reports"
    preserve_historical_reports(source_reports, historical_root)
    result = rescore_phase1_records(output_root)
    study = _read(output_root / "study.json", {})
    packets = [_read(path) for path in sorted(output_root.glob("phase-1/packet-*/packet.json"))]
    profiles = [_read(path) for path in sorted(output_root.glob("profiles/profile-*.json"))]
    historical_decision = _read(historical_root / "final-decision.json", {})
    repository = repository_identity(repository_root)
    expectations = authoritative_packet_expectations()
    limiter = RollingWindowRateLimiter()
    rate_limit_report = {
        **limiter.report(),
        "policy": "offline reanalysis made zero Gemini calls; any future focused validation must use this shared limiter",
        "new_provider_calls": 0,
        "hard_429_retry": False,
    }
    phase1 = {
        "records": result["records"],
        "profile_summaries": result["profile_summaries"],
        "comparisons": result["comparisons"],
        "decision": result["decision"],
        "records_count": len(result["records"]),
        "provider_calls": result["provider_calls"],
    }
    phase2 = {
        "run": False,
        "reason": "offline qualification authorizes focused validation; no live call was made by the offline reanalysis command",
        "records": [],
        "comparison": {},
        "decision": {},
    }
    final_recommendation = {
        "recommendation": "candidate_promising_but_needs_second_validation" if result["decision"]["qualifying_profiles"] else "keep_current_profile_and_build_processing_boundary",
        "offline_decision": result["decision"]["decision"],
        "candidate_profile": result["decision"]["qualifying_profiles"][0] if result["decision"]["qualifying_profiles"] else None,
        "production_deployment": False,
        "live_validation": "authorized_by_offline_evidence" if result["decision"]["qualifying_profiles"] else "not_authorized",
    }
    reports = {
        "corrected-quality-floor.json": {
            "schema_version": "gemini-profile-ablation-corrected-quality-floor-v1",
            "packet_expectations": expectations,
            "records": [{key: record[key] for key in ("profile_id", "packet_id", "repetition", "quality_floor", "corrected_score", "status_code", "error_category")} for record in result["records"]],
        },
        "corrected-semantic-scores.json": {
            "schema_version": "gemini-profile-ablation-corrected-semantic-scores-v1",
            "records": [{key: record[key] for key in ("profile_id", "packet_id", "repetition", "original_score", "corrected_score", "quality_floor")} for record in result["records"]],
            "profile_summaries": result["profile_summaries"],
        },
        "buildability-scorecard.json": {
            "schema_version": "gemini-profile-ablation-buildability-scorecard-v1",
            "weights": {"semantic_stability": 0.25, "structural_stability": 0.15, "identity_stability": 0.10, "clarification_stability": 0.10, "geometry_contract_stability": 0.15, "failure_predictability": 0.10, "repairability": 0.10, "efficiency": 0.05},
            "profiles": result["profile_summaries"],
        },
        "profile-comparisons.json": {"schema_version": "gemini-profile-ablation-profile-comparisons-v1", "comparisons": result["comparisons"]},
        "corrected-phase-1-decision.json": {"schema_version": "gemini-profile-ablation-corrected-phase-1-decision-v1", **result["decision"]},
        "gemini-rate-limit-report.json": {"schema_version": "gemini-profile-ablation-rate-limit-v1", **rate_limit_report},
        "final-buildability-decision.json": {"schema_version": "gemini-profile-ablation-final-buildability-decision-v1", "historical_decision": historical_decision.get("decision"), "offline_phase_1": result["decision"], "phase_2": phase2, "final_recommendation": final_recommendation},
    }
    for filename, payload in reports.items():
        _write(output_root / "reports" / filename, payload, data_root=repository_root / "data")
    write_manual_review_bundle(
        output_root / "reports" / "all-responses-manual-review.json",
        study=study,
        repository=repository,
        packets=packets,
        profiles=profiles,
        phase1=phase1,
        phase2=phase2,
        historical_decision={"decision": historical_decision.get("decision"), "source": "reports/historical/pre-buildability-reanalysis/final-decision.json"},
        final_recommendation=final_recommendation,
        rate_limit_policy=rate_limit_report,
    )
    return {"records": len(result["records"]), "provider_calls": result["provider_calls"], "decision": result["decision"], "final_recommendation": final_recommendation}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("data/debug-sessions/gemini-profile-ablation/gemini-profile-ablation-01"))
    parser.add_argument("--study-root", type=Path, default=Path("data/debug-sessions/gemini-flash-lite-study/gemini-flash-lite-study-01"))
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    args = parser.parse_args()
    print(json.dumps(write_reanalysis_reports(output_root=args.output_root, study_root=args.study_root, repository_root=args.repo_root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
