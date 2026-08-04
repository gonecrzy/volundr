"""Resolve an existing Ollama calibration queue without model calls."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ollama_benchmark.resolution import resolve_existing_evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Reprocess existing Ollama calibration evidence")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--profiles-dir", type=Path, default=Path("benchmarks/ollama-prompts/profiles"))
    args = parser.parse_args()
    result = asyncio.run(resolve_existing_evidence(source_root=args.source_root, output_root=args.output_root, profiles_dir=args.profiles_dir))
    print(f"resolved_original_issues={result['experiment']['original_issue_count']}")
    print(f"new_worker_findings={result['experiment']['new_issue_count']}")
    print(f"aggregate_signatures={len(result['aggregates'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
