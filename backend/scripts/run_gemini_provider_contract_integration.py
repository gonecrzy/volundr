#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from app.services.gemini_integration.corpus import build_integration_corpus
from app.services.gemini_integration.profile import INTEGRATION_PROFILE_ID, GeminiFlashLiteContractV1, require_integration_profile
from app.services.gemini_integration.reports import IntegrationReportWriter


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
    if args.dry_run:
        return 0
    if args.replay or args.counterfactual:
        raise RuntimeError("replay and counterfactual execution are implemented by the offline evidence runner")
    if not args.live:
        parser.error("live execution requires --live; use --dry-run for preregistration only")
    raise RuntimeError("real boundary wiring is required for live integration execution")


if __name__ == "__main__":
    raise SystemExit(main())

