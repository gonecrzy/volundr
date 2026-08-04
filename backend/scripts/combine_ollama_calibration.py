"""Combine authoritative per-model Ollama calibration runs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ollama_benchmark.report import combine_calibration_runs


def main() -> int:
    parser = argparse.ArgumentParser(description="Combine Ollama calibration evidence")
    parser.add_argument("--run-root", action="append", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    result = combine_calibration_runs(run_roots=args.run_root, output_root=args.output_root)
    print(f"models={len(result['models'])}")
    print(f"formal_benchmark_authorized={result['admission']['formal_benchmark_authorized']}")
    print(f"blocking_models={len(result['admission']['blocking_model_ids'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
