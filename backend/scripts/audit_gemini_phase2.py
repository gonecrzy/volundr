#!/usr/bin/env python3
"""Audit preserved Gemini Phase 2 evidence without provider or worker access."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.gemini_consistency.phase2_audit import write_phase2_audit_reports, write_pre_phase2_audit_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("data/debug-sessions/gemini-profile-ablation/gemini-profile-ablation-01"))
    parser.add_argument("--study-root", type=Path, default=Path("data/debug-sessions/gemini-flash-lite-study/gemini-flash-lite-study-01"))
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    args = parser.parse_args()
    snapshot = write_pre_phase2_audit_snapshot(args.output_root, args.repo_root)
    result = write_phase2_audit_reports(args.output_root, args.study_root, args.repo_root)
    print(json.dumps({"snapshot": snapshot, "audit": result}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
