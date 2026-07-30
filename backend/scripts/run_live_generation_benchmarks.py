#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.generation.live_benchmarks import (  # noqa: E402
    LiveBenchmarkConfig,
    LiveBenchmarkRunner,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run controlled Volundr live-generation benchmark evaluations.",
    )
    parser.add_argument(
        "--suite",
        type=Path,
        default=BACKEND_ROOT / "tests" / "fixtures" / "generation_benchmarks" / "core.json",
        help="Path to a machine-readable benchmark suite JSON file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=BACKEND_ROOT.parent / "output" / "live-benchmarks",
        help="Directory where run artifacts are written.",
    )
    parser.add_argument("--run-label", default=None, help="Optional human label for the run ID.")
    parser.add_argument(
        "--benchmark-id",
        action="append",
        default=[],
        help="Benchmark ID to include. Repeat for multiple cases. Defaults to all selected cases.",
    )
    parser.add_argument("--max-cases", type=int, default=None, help="Limit selected cases.")
    parser.add_argument(
        "--runs-per-case",
        type=int,
        default=1,
        help="Optional repeated runs per selected benchmark.",
    )
    parser.add_argument(
        "--max-runs",
        type=int,
        default=10,
        help="Hard cap on total case runs.",
    )
    parser.add_argument(
        "--max-estimated-tokens",
        type=int,
        default=250_000,
        help="Hard cap on estimated prompt tokens before provider calls are allowed.",
    )
    parser.add_argument(
        "--cost-per-1k-tokens-usd",
        type=float,
        default=None,
        help="Optional user-supplied cost estimate used for preflight cost caps.",
    )
    parser.add_argument(
        "--max-estimated-cost-usd",
        type=float,
        default=None,
        help="Optional hard cap on estimated run cost when a token price is supplied.",
    )
    parser.add_argument(
        "--provider",
        choices=("dry-run", "gemini", "ollama"),
        default="dry-run",
        help="Provider mode. dry-run writes artifacts without provider calls.",
    )
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help="Required with --provider gemini to permit Gemini CLI calls. Ollama is local and does not require this flag.",
    )
    parser.add_argument(
        "--baseline-manifest",
        type=Path,
        default=None,
        help="Optional prior run-manifest.json for prompt-version comparison.",
    )
    parser.add_argument(
        "--phase-validation",
        action="store_true",
        help=(
            "Run the three quick phase-validation scenarios: creative fish bracket, "
            "honeycomb bracket, and threaded control knob. Cannot be combined with --benchmark-id."
        ),
    )
    parser.add_argument(
        "--source-probe",
        action="store_true",
        help=(
            "Also ask the provider for direct CAD source, extract it if possible, "
            "compile it, and write source parameter coverage artifacts."
        ),
    )
    parser.add_argument(
        "--source-language",
        choices=("openscad", "cadquery"),
        default="openscad",
        help="Source language for --source-probe. CadQuery is experimental.",
    )
    parser.add_argument(
        "--source-brief",
        action="store_true",
        help=(
            "Before --source-probe generation, ask the provider for a compact structured "
            "source brief and feed it into the OpenSCAD prompt."
        ),
    )
    parser.add_argument(
        "--source-probe-repair",
        action="store_true",
        help=(
            "Run one repair prompt after source-probe compile failure or "
            "source-brief connected-body validation failure, then compile the repaired "
            "source as a separate repair metric."
        ),
    )
    args = parser.parse_args(argv)

    result = LiveBenchmarkRunner().run(
        LiveBenchmarkConfig(
            suite_path=args.suite,
            output_root=args.output_dir,
            run_label=args.run_label,
            benchmark_ids=tuple(args.benchmark_id),
            runs_per_case=args.runs_per_case,
            max_cases=args.max_cases,
            max_runs=args.max_runs,
            max_estimated_tokens=args.max_estimated_tokens,
            cost_per_1k_tokens_usd=args.cost_per_1k_tokens_usd,
            max_estimated_cost_usd=args.max_estimated_cost_usd,
            provider=args.provider,
            allow_live=args.allow_live,
            baseline_manifest_path=args.baseline_manifest,
            phase_validation=args.phase_validation,
            source_probe=args.source_probe,
            source_probe_repair=args.source_probe_repair,
            source_brief=args.source_brief,
            source_language=args.source_language,
        )
    )
    metrics = json.loads(result.metrics_path.read_text(encoding="utf-8"))
    print(f"Run ID: {result.run_id}")
    print(f"Run directory: {result.run_dir}")
    print(f"Manifest: {result.manifest_path}")
    print(f"Metrics: {result.metrics_path}")
    print(f"Prompt comparison: {result.prompt_comparison_path}")
    print(f"Case runs: {metrics['total_case_runs']}")
    print(f"Statuses: {metrics['status_counts']}")
    if metrics.get("source_probe_enabled"):
        print(f"Source probe statuses: {metrics.get('source_probe_status_counts')}")
        print(f"Source probe compile statuses: {metrics.get('source_probe_compile_status_counts')}")
        print(
            "Source probe expected-parameter coverage average: "
            f"{metrics.get('source_probe_expected_parameter_coverage_average')}"
        )
        print(f"Source probe compile warning count: {metrics.get('source_probe_compile_warning_count')}")
        print(
            "Source probe disconnected mesh count: "
            f"{metrics.get('source_probe_disconnected_mesh_count')}"
        )
        if metrics.get("source_brief_enabled"):
            print(f"Source brief statuses: {metrics.get('source_brief_status_counts')}")
        if metrics.get("source_probe_repair_enabled"):
            print(f"Source probe repair statuses: {metrics.get('source_probe_repair_status_counts')}")
            print(
                "Source probe repair compile statuses: "
                f"{metrics.get('source_probe_repair_compile_status_counts')}"
            )
            print(
                "Source probe repair compile successes: "
                f"{metrics.get('source_probe_repair_compile_success_count')}"
            )
    print("Prompt promotion: disabled; manual review required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
