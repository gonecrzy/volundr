import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.ai.gemini_cli import (
    COMPONENT_REVISION_PROMPT_VERSION,
    CONTRACT_REPAIR_PROMPT_VERSION,
    GEMINI_RULESET_VERSION,
    LEGACY_COMPILE_REPAIR_PROMPT_VERSION,
    LEGACY_INITIAL_PROMPT_VERSION,
    LEGACY_REVISION_PROMPT_VERSION,
    OPENSCAD_GENERATION_PROMPT_VERSION,
    PLANNED_OPENSCAD_GENERATION_PROMPT_VERSION,
    REQUIREMENTS_PROMPT_VERSION,
    SCOPE_CORRECTION_PROMPT_VERSION,
    STRUCTURED_REVISION_PROMPT_VERSION,
    GeminiCliProvider,
)
from app.services.ai.ollama import OllamaProvider
from app.services.ai.provider import RequirementExtractionRequest
from app.services.generation.benchmarks import BenchmarkSuite, GenerationBenchmark, load_benchmark_suite
from app.services.generation.failure_taxonomy import FailureClass


LIVE_BENCHMARK_RUN_SCHEMA_VERSION = "live-benchmark-run-v1"
LIVE_BENCHMARK_METRICS_SCHEMA_VERSION = "live-benchmark-metrics-v1"
PROMPT_COMPARISON_SCHEMA_VERSION = "prompt-version-comparison-v1"
HUMAN_SCORING_FORM_SCHEMA_VERSION = "human-scoring-form-v1"
LIVE_BENCHMARK_HARNESS_VERSION = "live-benchmark-harness-v1"

SCORING_CATEGORIES = (
    "prompt_quality",
    "design_plan_quality",
    "component_decomposition",
    "parameter_modeling",
    "geometry_generation",
    "printability",
    "revision_preservation",
    "ux",
)


@dataclass(frozen=True)
class LiveBenchmarkConfig:
    suite_path: Path
    output_root: Path
    run_label: str | None = None
    benchmark_ids: tuple[str, ...] = ()
    runs_per_case: int = 1
    max_cases: int | None = None
    max_runs: int = 10
    max_estimated_tokens: int = 250_000
    cost_per_1k_tokens_usd: float | None = None
    max_estimated_cost_usd: float | None = None
    provider: str = "dry-run"
    allow_live: bool = False
    baseline_manifest_path: Path | None = None


@dataclass(frozen=True)
class LiveBenchmarkRunResult:
    run_id: str
    run_dir: Path
    manifest_path: Path
    metrics_path: Path
    prompt_comparison_path: Path


class LiveBenchmarkRunner:
    """Creates reproducible benchmark artifacts without promoting prompt changes."""

    def run(self, config: LiveBenchmarkConfig) -> LiveBenchmarkRunResult:
        suite = load_benchmark_suite(config.suite_path)
        selected_benchmarks = self._select_benchmarks(suite, config)
        provider = self._provider_for(config)
        case_prompts = self._build_requirement_prompts(provider, selected_benchmarks)
        estimated_tokens = self._estimate_run_tokens(case_prompts, config.runs_per_case)
        estimated_cost_usd = self._estimate_cost(config, estimated_tokens)
        self._validate_quota(config, selected_benchmarks, estimated_tokens, estimated_cost_usd)

        run_id = self._build_run_id(config.run_label)
        run_dir = config.output_root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)

        prompt_versions = self._prompt_versions(provider)
        case_runs: list[dict[str, Any]] = []
        for benchmark in selected_benchmarks:
            for run_index in range(1, config.runs_per_case + 1):
                case_runs.append(
                    self._run_case(
                        benchmark=benchmark,
                        provider=provider,
                        provider_mode=config.provider,
                        run_dir=run_dir,
                        run_index=run_index,
                        prompt=case_prompts[benchmark.id],
                    )
                )

        manifest = {
            "schema_version": LIVE_BENCHMARK_RUN_SCHEMA_VERSION,
            "harness_version": LIVE_BENCHMARK_HARNESS_VERSION,
            "run_id": run_id,
            "created_at": _utc_now_iso(),
            "suite": {"name": suite.name, "path": str(config.suite_path)},
            "config": {
                "run_label": config.run_label,
                "benchmark_ids": list(config.benchmark_ids),
                "runs_per_case": config.runs_per_case,
                "max_cases": config.max_cases,
                "max_runs": config.max_runs,
                "max_estimated_tokens": config.max_estimated_tokens,
                "cost_per_1k_tokens_usd": config.cost_per_1k_tokens_usd,
                "max_estimated_cost_usd": config.max_estimated_cost_usd,
                "allow_live": config.allow_live,
                "baseline_manifest_path": str(config.baseline_manifest_path)
                if config.baseline_manifest_path
                else None,
            },
            "provider": {
                "mode": config.provider,
                "settings": provider.provider_settings(),
                "live_provider_calls_enabled": config.provider == "ollama"
                or (config.provider == "gemini" and config.allow_live),
            },
            "prompt_versions": prompt_versions,
            "ruleset_version": GEMINI_RULESET_VERSION,
            "quota_controls": {
                "estimated_tokens": estimated_tokens,
                "max_estimated_tokens": config.max_estimated_tokens,
                "estimated_cost_usd": estimated_cost_usd,
                "max_estimated_cost_usd": config.max_estimated_cost_usd,
                "selected_case_count": len(selected_benchmarks),
                "total_case_runs": len(case_runs),
            },
            "selected_benchmark_ids": [benchmark.id for benchmark in selected_benchmarks],
            "case_runs": case_runs,
            "artifact_collection_root": "artifacts",
            "human_scoring_root": "human-scoring",
            "case_reports_root": "case-reports",
            "no_automatic_prompt_promotion": True,
        }
        manifest_path = run_dir / "run-manifest.json"
        _write_json(manifest_path, manifest)

        metrics_path = run_dir / "aggregate-metrics.json"
        _write_json(metrics_path, self._build_metrics(manifest))

        prompt_comparison_path = run_dir / "prompt-version-comparison.json"
        _write_json(
            prompt_comparison_path,
            self._build_prompt_comparison(prompt_versions, config.baseline_manifest_path),
        )

        return LiveBenchmarkRunResult(
            run_id=run_id,
            run_dir=run_dir,
            manifest_path=manifest_path,
            metrics_path=metrics_path,
            prompt_comparison_path=prompt_comparison_path,
        )

    def _run_case(
        self,
        *,
        benchmark: GenerationBenchmark,
        provider: GeminiCliProvider,
        provider_mode: str,
        run_dir: Path,
        run_index: int,
        prompt: str,
    ) -> dict[str, Any]:
        case_run_id = f"{_safe_slug(benchmark.id)}-run-{run_index:03d}"
        artifact_dir = run_dir / "artifacts" / _safe_slug(benchmark.id) / f"run-{run_index:03d}"
        artifact_dir.mkdir(parents=True)

        _write_json(artifact_dir / "benchmark-input.json", self._benchmark_payload(benchmark))
        (artifact_dir / "requirements-prompt.txt").write_text(prompt, encoding="utf-8")
        provider_output_path: str | None = None
        error_path: str | None = None
        failure_class = FailureClass.NONE.value

        if provider_mode == "dry-run":
            status = "not_run"
        else:
            try:
                result = asyncio.run(provider.extract_requirements(_requirement_request_for(benchmark)))
                output_file = artifact_dir / "requirements-raw-output.txt"
                output_file.write_text(result.raw_output, encoding="utf-8")
                provider_output_path = _relative(output_file, run_dir)
                status = "provider_output_collected"
            except TimeoutError as exc:
                status = "provider_failed"
                failure_class = FailureClass.PROVIDER_TIMEOUT.value
                error_path = self._write_error(artifact_dir, run_dir, exc)
            except Exception as exc:
                status = "provider_failed"
                failure_class = _provider_failure_class(exc)
                error_path = self._write_error(artifact_dir, run_dir, exc)

        scoring_form_path = self._write_scoring_form(
            run_dir=run_dir,
            benchmark=benchmark,
            case_run_id=case_run_id,
            run_index=run_index,
        )
        report_path = self._write_case_report(
            run_dir=run_dir,
            benchmark=benchmark,
            case_run_id=case_run_id,
            run_index=run_index,
        )

        return {
            "case_run_id": case_run_id,
            "benchmark_id": benchmark.id,
            "run_index": run_index,
            "status": status,
            "failure_class": failure_class,
            "prompt_sha256": _sha256_text(prompt),
            "prompt_template_version": REQUIREMENTS_PROMPT_VERSION,
            "artifact_dir": _relative(artifact_dir, run_dir),
            "provider_output_path": provider_output_path,
            "error_path": error_path,
            "scoring_form_path": _relative(scoring_form_path, run_dir),
            "report_path": _relative(report_path, run_dir),
        }

    def _select_benchmarks(
        self,
        suite: BenchmarkSuite,
        config: LiveBenchmarkConfig,
    ) -> list[GenerationBenchmark]:
        benchmarks = suite.benchmarks
        if config.benchmark_ids:
            by_id = {benchmark.id: benchmark for benchmark in benchmarks}
            missing = sorted(set(config.benchmark_ids) - set(by_id))
            if missing:
                raise ValueError(f"unknown benchmark ids: {', '.join(missing)}")
            benchmarks = [by_id[benchmark_id] for benchmark_id in config.benchmark_ids]
        if config.max_cases is not None:
            if config.max_cases < 1:
                raise ValueError("max_cases must be at least 1")
            benchmarks = benchmarks[: config.max_cases]
        if not benchmarks:
            raise ValueError("no benchmarks selected")
        return benchmarks

    def _provider_for(self, config: LiveBenchmarkConfig) -> GeminiCliProvider:
        if config.provider not in {"dry-run", "gemini", "ollama"}:
            raise ValueError("provider must be dry-run, gemini, or ollama")
        if config.provider == "ollama":
            return OllamaProvider()
        return GeminiCliProvider()

    def _validate_quota(
        self,
        config: LiveBenchmarkConfig,
        selected_benchmarks: list[GenerationBenchmark],
        estimated_tokens: int,
        estimated_cost_usd: float | None,
    ) -> None:
        if config.runs_per_case < 1:
            raise ValueError("runs_per_case must be at least 1")
        total_runs = len(selected_benchmarks) * config.runs_per_case
        if total_runs > config.max_runs:
            raise ValueError(f"requested {total_runs} runs exceeds max_runs={config.max_runs}")
        if estimated_tokens > config.max_estimated_tokens:
            raise ValueError(
                f"estimated token usage {estimated_tokens} exceeds max_estimated_tokens="
                f"{config.max_estimated_tokens}"
            )
        if (
            estimated_cost_usd is not None
            and config.max_estimated_cost_usd is not None
            and estimated_cost_usd > config.max_estimated_cost_usd
        ):
            raise ValueError(
                f"estimated cost ${estimated_cost_usd:.4f} exceeds max_estimated_cost_usd="
                f"${config.max_estimated_cost_usd:.4f}"
            )
        if config.provider == "gemini" and not config.allow_live:
            raise ValueError("provider=gemini requires --allow-live")

    def _build_requirement_prompts(
        self,
        provider: GeminiCliProvider,
        benchmarks: list[GenerationBenchmark],
    ) -> dict[str, str]:
        return {
            benchmark.id: provider.build_requirement_prompt(_requirement_request_for(benchmark))
            for benchmark in benchmarks
        }

    def _prompt_versions(self, provider: GeminiCliProvider) -> dict[str, str]:
        return {
            "requirements": provider.requirement_prompt_template_version(),
            "design_plan": provider.design_plan_prompt_template_version(),
            "planned_openscad": PLANNED_OPENSCAD_GENERATION_PROMPT_VERSION,
            "design_spec_openscad": OPENSCAD_GENERATION_PROMPT_VERSION,
            "revision_plan": provider.revision_plan_prompt_template_version(),
            "structured_revision": STRUCTURED_REVISION_PROMPT_VERSION,
            "component_revision": COMPONENT_REVISION_PROMPT_VERSION,
            "contract_repair": CONTRACT_REPAIR_PROMPT_VERSION,
            "scope_correction": SCOPE_CORRECTION_PROMPT_VERSION,
            "compile_repair": LEGACY_COMPILE_REPAIR_PROMPT_VERSION,
            "legacy_initial": LEGACY_INITIAL_PROMPT_VERSION,
            "legacy_revision": LEGACY_REVISION_PROMPT_VERSION,
        }

    def _estimate_run_tokens(self, prompts: dict[str, str], runs_per_case: int) -> int:
        return sum(max(1, len(prompt) // 4) for prompt in prompts.values()) * runs_per_case

    def _estimate_cost(self, config: LiveBenchmarkConfig, estimated_tokens: int) -> float | None:
        if config.cost_per_1k_tokens_usd is None:
            return None
        if config.cost_per_1k_tokens_usd < 0:
            raise ValueError("cost_per_1k_tokens_usd must be non-negative")
        return round((estimated_tokens / 1000) * config.cost_per_1k_tokens_usd, 6)

    def _build_run_id(self, label: str | None) -> str:
        suffix = f"-{_safe_slug(label)}" if label else ""
        return f"live-benchmark-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}{suffix}"

    def _benchmark_payload(self, benchmark: GenerationBenchmark) -> dict[str, Any]:
        return {
            "id": benchmark.id,
            "suite": benchmark.suite,
            "input_prompt": benchmark.input_prompt,
            "required_dimensions": benchmark.required_dimensions,
            "allowed_assumptions": benchmark.allowed_assumptions,
            "expected_clarification": benchmark.expected_clarification,
            "expected_modules": benchmark.expected_modules,
            "expected_parameters": benchmark.expected_parameters,
            "expected_printability_constraints": benchmark.expected_printability_constraints,
            "compile_expectation": benchmark.compile_expectation,
            "mesh_expectation": benchmark.mesh_expectation,
            "expected_geometric_invariants": benchmark.expected_geometric_invariants,
            "expected_design_plan": benchmark.expected_design_plan,
            "expected_revision_plan": benchmark.expected_revision_plan,
            "expected_configuration": benchmark.expected_configuration,
            "expected_component_revision": benchmark.expected_component_revision,
            "revision_expectation": benchmark.revision_expectation,
            "protected_design_invariants": benchmark.protected_design_invariants,
            "unacceptable_outcomes": benchmark.unacceptable_outcomes,
        }

    def _write_scoring_form(
        self,
        *,
        run_dir: Path,
        benchmark: GenerationBenchmark,
        case_run_id: str,
        run_index: int,
    ) -> Path:
        scoring_dir = run_dir / "human-scoring"
        scoring_dir.mkdir(exist_ok=True)
        path = scoring_dir / f"{case_run_id}.json"
        _write_json(
            path,
            {
                "schema_version": HUMAN_SCORING_FORM_SCHEMA_VERSION,
                "case_run_id": case_run_id,
                "benchmark_id": benchmark.id,
                "run_index": run_index,
                "status": "unscored",
                "reviewer": None,
                "reviewed_at": None,
                "scores": {
                    category: {
                        "score": None,
                        "notes": "",
                        "evidence_paths": [],
                    }
                    for category in SCORING_CATEGORIES
                },
                "blocking_failures": [],
                "recommended_next_work": [],
                "overall_notes": "",
                "score_guidance": {
                    "0": "not evaluated",
                    "1": "failed or misleading",
                    "2": "usable only with major correction",
                    "3": "partially successful",
                    "4": "good with minor issues",
                    "5": "ready quality for this benchmark",
                },
            },
        )
        return path

    def _write_case_report(
        self,
        *,
        run_dir: Path,
        benchmark: GenerationBenchmark,
        case_run_id: str,
        run_index: int,
    ) -> Path:
        report_dir = run_dir / "case-reports"
        report_dir.mkdir(exist_ok=True)
        path = report_dir / f"{case_run_id}.md"
        lines = [
            f"# {benchmark.id} Run {run_index}",
            "",
            f"- Case run ID: `{case_run_id}`",
            f"- Expected clarification: `{benchmark.expected_clarification}`",
            f"- Compile expectation: `{benchmark.compile_expectation}`",
            f"- Mesh expectation: {benchmark.mesh_expectation}",
            "",
            "## Input Prompt",
            "",
            benchmark.input_prompt,
            "",
            "## Required Dimensions",
            "",
            *[f"- {dimension}" for dimension in benchmark.required_dimensions],
            "",
            "## Expected Parameters",
            "",
            *[f"- {parameter}" for parameter in benchmark.expected_parameters],
            "",
            "## Unacceptable Outcomes",
            "",
            *[f"- {outcome}" for outcome in benchmark.unacceptable_outcomes],
            "",
            "## Human Review",
            "",
            "Complete the matching JSON scoring form in `human-scoring/` after reviewing artifacts.",
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def _write_error(self, artifact_dir: Path, run_dir: Path, exc: Exception) -> str:
        error_file = artifact_dir / "provider-error.txt"
        error_file.write_text(str(exc), encoding="utf-8")
        return _relative(error_file, run_dir)

    def _build_metrics(self, manifest: dict[str, Any]) -> dict[str, Any]:
        status_counts: dict[str, int] = {}
        failure_class_counts: dict[str, int] = {}
        for case_run in manifest["case_runs"]:
            status_counts[case_run["status"]] = status_counts.get(case_run["status"], 0) + 1
            failure_class = case_run["failure_class"]
            failure_class_counts[failure_class] = failure_class_counts.get(failure_class, 0) + 1
        return {
            "schema_version": LIVE_BENCHMARK_METRICS_SCHEMA_VERSION,
            "run_id": manifest["run_id"],
            "total_case_runs": len(manifest["case_runs"]),
            "status_counts": status_counts,
            "failure_class_counts": failure_class_counts,
            "estimated_tokens": manifest["quota_controls"]["estimated_tokens"],
            "estimated_cost_usd": manifest["quota_controls"]["estimated_cost_usd"],
            "live_provider_calls_enabled": manifest["provider"]["live_provider_calls_enabled"],
            "needs_human_scoring": True,
            "next_work_buckets": {category: 0 for category in SCORING_CATEGORIES},
            "no_automatic_prompt_promotion": True,
        }

    def _build_prompt_comparison(
        self,
        prompt_versions: dict[str, str],
        baseline_manifest_path: Path | None,
    ) -> dict[str, Any]:
        baseline_versions: dict[str, str] = {}
        if baseline_manifest_path:
            payload = json.loads(baseline_manifest_path.read_text(encoding="utf-8"))
            raw_versions = payload.get("prompt_versions", {})
            if isinstance(raw_versions, dict):
                baseline_versions = {
                    key: value for key, value in raw_versions.items() if isinstance(value, str)
                }

        changed = {
            key: {"baseline": baseline_versions[key], "current": current}
            for key, current in prompt_versions.items()
            if key in baseline_versions and baseline_versions[key] != current
        }
        unchanged = {
            key: current
            for key, current in prompt_versions.items()
            if key in baseline_versions and baseline_versions[key] == current
        }
        new_versions = {
            key: current for key, current in prompt_versions.items() if key not in baseline_versions
        }
        removed_versions = {
            key: baseline_versions[key] for key in baseline_versions if key not in prompt_versions
        }
        return {
            "schema_version": PROMPT_COMPARISON_SCHEMA_VERSION,
            "baseline_manifest_path": str(baseline_manifest_path) if baseline_manifest_path else None,
            "changed_versions": changed,
            "unchanged_versions": unchanged,
            "new_versions": new_versions,
            "removed_versions": removed_versions,
            "automatic_promotion": False,
            "promotion_decision": "manual_review_required",
        }


def _requirement_request_for(benchmark: GenerationBenchmark) -> RequirementExtractionRequest:
    return RequirementExtractionRequest(
        project_name=f"Benchmark: {benchmark.id}",
        original_intent=benchmark.input_prompt,
        user_instruction=benchmark.input_prompt,
        defaults={
            "units": "mm",
            "default_nozzle_mm": 0.4,
            "default_layer_height_mm": 0.2,
            "wall_thickness_mm": 3.0,
            "supports_assumed_allowed": False,
        },
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _relative(path: Path, root: Path) -> str:
    return str(path.relative_to(root))


def _safe_slug(value: str | None) -> str:
    raw = value or "run"
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", raw).strip("-._").lower()
    return slug or "run"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _provider_failure_class(exc: Exception) -> str:
    if "timed out" in str(exc).lower():
        return FailureClass.PROVIDER_TIMEOUT.value
    return FailureClass.PROVIDER_FAILURE.value


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
