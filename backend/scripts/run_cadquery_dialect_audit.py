"""Run the historical CadQuery dialect audit without provider or production calls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.gemini_integration.cadquery_dialect_audit import build_audit_reports


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("../data/debug-sessions"),
        help="historical debug-session root",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("../data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01/reports/cadquery-dialect-audit-02"),
    )
    parser.add_argument(
        "--wave-evidence",
        type=Path,
        default=Path("../data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01/reports/combined-wave-evidence.json"),
    )
    args = parser.parse_args()
    existing = None
    if args.wave_evidence.exists():
        existing = json.loads(args.wave_evidence.read_text(encoding="utf-8"))
    reports = build_audit_reports(args.data_root, args.report_dir, existing_combined=existing)
    decision = reports["architecture-decision.json"]["decision"]
    print(json.dumps({
        "report_dir": str(args.report_dir),
        "report_count": len(reports),
        "architecture_decision": decision,
        "wave02_provider_calls_authorized": reports["wave-02-gate.json"]["provider_calls_allowed"],
        "corpus_occurrences": reports["corpus-index.json"]["occurrence_count"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
