from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.ollama_benchmark.holdout_anatomy import analyze_frozen_evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze frozen Ollama holdout evidence without executing providers or workers.")
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = analyze_frozen_evidence(args.evidence_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
