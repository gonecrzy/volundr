#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from app.services.gemini_integration.narrow_fix import NarrowFixStudy
from app.services.gemini_integration.profile import INTEGRATION_PROFILE_ID, require_integration_profile


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the historical zero-call Gemini provider-contract narrow-fix audit; not the current integration runner"
    )
    parser.add_argument("--profile", required=True)
    parser.add_argument("--study-root", type=Path, default=Path("data/debug-sessions/gemini-provider-contract-integration/gemini-provider-contract-integration-01"))
    parser.add_argument("--output", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        require_integration_profile(args.profile)
    except ValueError as exc:
        parser.error(str(exc))
    repository_root = Path(__file__).resolve().parents[2]
    study_root = args.study_root if args.study_root.is_absolute() else repository_root / args.study_root
    output_root = args.output if args.output is not None else study_root / "reports/narrow-fix-01"
    if not output_root.is_absolute():
        output_root = repository_root / output_root
    NarrowFixStudy(repository_root, study_root).write_reports(output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
