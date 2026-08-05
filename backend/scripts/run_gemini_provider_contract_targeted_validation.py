#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.services.gemini_integration.profile import GeminiFlashLiteContractV1, require_integration_profile
from app.services.gemini_integration.targeted_validation import (
    STUDY_ID,
    TARGETED_REPORTS,
    TargetedValidationRunner,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the preregistered six-operation Gemini provider validation")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--study-id", default=STUDY_ID)
    parser.add_argument(
        "--study-root",
        type=Path,
        default=Path("data/debug-sessions/gemini-provider-contract-integration/gemini-provider-contract-integration-01"),
    )
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--resume", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        require_integration_profile(args.profile)
    except ValueError as exc:
        parser.error(str(exc))
    if args.study_id != STUDY_ID:
        parser.error(f"targeted validation requires the preserved study ID {STUDY_ID!r}")
    if not args.live and not args.resume:
        parser.error("targeted execution requires --live; use --resume for an idempotent completed-run read")
    repository_root = Path(__file__).resolve().parents[2]
    study_root = args.study_root if args.study_root.is_absolute() else repository_root / args.study_root
    profile = GeminiFlashLiteContractV1.from_repository(repository_root)
    runner = TargetedValidationRunner(repository_root, study_root, profile)
    report_root = runner.report_root
    if args.resume:
        result_path = report_root / "integration-decision.json"
        if not result_path.is_file():
            parser.error("--resume requires completed targeted validation reports")
        # Read-only resume: no provider, worker, capture, or report writes.
        document = json.loads(result_path.read_text(encoding="utf-8"))
        if document.get("validation_id") != "targeted-provider-validation-01":
            parser.error("targeted validation report identity does not match")
        return 0
    runner.preregister()
    payload = asyncio.run(runner.run_live())
    if len(payload.get("results", [])) != 6:
        raise RuntimeError("targeted validation did not evaluate exactly six logical operations")
    if not all((runner.report_root / name).is_file() for name in TARGETED_REPORTS):
        raise RuntimeError("targeted validation did not produce all required reports")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
