#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.gemini_integration.geometry_prompt_narrow_fix import (
    NARROW_FIX_ID,
    REPORT_NAMES,
    GeometryPromptNarrowFixRunner,
)
from app.services.gemini_integration.profile import (
    GeminiFlashLiteContractV1,
    require_integration_profile,
)


STUDY_ID = "gemini-provider-contract-integration-01"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the isolated T5 Gemini geometry prompt qualification")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--study-id", default=STUDY_ID)
    parser.add_argument(
        "--study-root",
        type=Path,
        default=Path("data/debug-sessions/gemini-provider-contract-integration/gemini-provider-contract-integration-01"),
    )
    parser.add_argument("--live", action="store_true", help="run exactly the preregistered six geometry operations")
    parser.add_argument("--resume", action="store_true", help="read the completed isolated result without provider calls")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        require_integration_profile(args.profile)
    except ValueError as exc:
        parser.error(str(exc))
    if args.study_id != STUDY_ID:
        parser.error(f"geometry narrow-fix runner requires the preserved study ID {STUDY_ID!r}")
    if args.live and args.resume:
        parser.error("choose --live or --resume, not both")
    repository_root = Path(__file__).resolve().parents[2]
    study_root = args.study_root if args.study_root.is_absolute() else repository_root / args.study_root
    profile = GeminiFlashLiteContractV1.from_repository(repository_root)
    runner = GeometryPromptNarrowFixRunner(repository_root, study_root, profile)
    report_root = runner.report_root
    if args.resume:
        result_path = report_root / "integration-decision.json"
        if not result_path.is_file():
            parser.error("--resume requires completed geometry narrow-fix reports")
        document = json.loads(result_path.read_text(encoding="utf-8"))
        if document.get("validation_id") != NARROW_FIX_ID:
            parser.error("geometry narrow-fix report identity does not match")
        return 0
    result = runner.run(live=args.live)
    if args.live:
        if not all((report_root / name).is_file() for name in REPORT_NAMES):
            raise RuntimeError("geometry narrow-fix did not produce all required reports")
        if result.get("geometry_decision", {}).get("logical_operations") != 6:
            raise RuntimeError("geometry narrow-fix did not evaluate exactly six logical operations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
