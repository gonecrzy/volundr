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
from app.services.ai.provider import ModelGenerationRequest, RequirementExtractionRequest
from app.services.ai.source_extraction import SourceExtractionError, extract_scad_source
from app.services.cad.runner import OpenScadCliRunner
from app.services.generation.benchmarks import (
    BenchmarkSuite,
    GenerationBenchmark,
    load_benchmark_suite,
    phase_validation_benchmark_ids,
    phase_validation_scenario_set,
)
from app.services.generation.failure_taxonomy import FailureClass
from app.services.openscad.parameters import extract_editable_parameters


LIVE_BENCHMARK_RUN_SCHEMA_VERSION = "live-benchmark-run-v1"
LIVE_BENCHMARK_METRICS_SCHEMA_VERSION = "live-benchmark-metrics-v1"
PROMPT_COMPARISON_SCHEMA_VERSION = "prompt-version-comparison-v1"
HUMAN_SCORING_FORM_SCHEMA_VERSION = "human-scoring-form-v1"
LIVE_BENCHMARK_HARNESS_VERSION = "live-benchmark-harness-v1"
SOURCE_PARAMETER_ANALYSIS_SCHEMA_VERSION = "source-parameter-analysis-v1"

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
    phase_validation: bool = False
    source_probe: bool = False
    source_probe_repair: bool = False


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
        source_prompts = (
            self._build_source_prompts(provider, selected_benchmarks) if config.source_probe else {}
        )
        estimated_tokens = self._estimate_run_tokens(
            [
                *case_prompts.values(),
                *source_prompts.values(),
                *(source_prompts.values() if config.source_probe_repair else []),
            ],
            config.runs_per_case,
        )
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
                        source_prompt=source_prompts.get(benchmark.id),
                        source_probe_repair=config.source_probe_repair,
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
                "phase_validation": config.phase_validation,
                "source_probe": config.source_probe,
                "source_probe_repair": config.source_probe_repair,
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
            "validation_scenario_set": phase_validation_scenario_set()
            if config.phase_validation
            else None,
            "artifact_collection_root": "artifacts",
            "human_scoring_root": "human-scoring",
            "case_reports_root": "case-reports",
            "no_automatic_prompt_promotion": True,
        }
        manifest_path = run_dir / "run-manifest.json"
        _write_json(manifest_path, manifest)

        metrics_path = run_dir / "aggregate-metrics.json"
        _write_json(metrics_path, self._build_metrics(manifest, run_dir))

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
        source_prompt: str | None = None,
        source_probe_repair: bool = False,
    ) -> dict[str, Any]:
        case_run_id = f"{_safe_slug(benchmark.id)}-run-{run_index:03d}"
        artifact_dir = run_dir / "artifacts" / _safe_slug(benchmark.id) / f"run-{run_index:03d}"
        artifact_dir.mkdir(parents=True)

        _write_json(artifact_dir / "benchmark-input.json", self._benchmark_payload(benchmark))
        (artifact_dir / "requirements-prompt.txt").write_text(prompt, encoding="utf-8")
        if source_prompt is not None:
            (artifact_dir / "source-prompt.txt").write_text(source_prompt, encoding="utf-8")
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

        source_probe = self._run_source_probe(
            benchmark=benchmark,
            provider=provider,
            provider_mode=provider_mode,
            run_dir=run_dir,
            artifact_dir=artifact_dir,
            source_prompt=source_prompt,
            source_probe_repair=source_probe_repair,
        )
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
            "source_probe": source_probe,
            "scoring_form_path": _relative(scoring_form_path, run_dir),
            "report_path": _relative(report_path, run_dir),
        }

    def _run_source_probe(
        self,
        *,
        benchmark: GenerationBenchmark,
        provider: GeminiCliProvider,
        provider_mode: str,
        run_dir: Path,
        artifact_dir: Path,
        source_prompt: str | None,
        source_probe_repair: bool,
    ) -> dict[str, Any]:
        if source_prompt is None:
            return {
                "enabled": False,
                "status": "disabled",
                "prompt_sha256": None,
                "prompt_template_version": None,
                "raw_output_path": None,
                "extracted_source_path": None,
                "parameter_analysis_path": None,
                "compile_status": "disabled",
                "compiled_stl_path": None,
                "compile_stdout_path": None,
                "compile_stderr_path": None,
                "mesh_metadata_path": None,
                "compile_error_message": None,
                "compile_timed_out": None,
                "compile_exit_code": None,
                "compile_warning_count": 0,
                "compile_warnings": [],
                "stl_size_bytes": 0,
                "error_path": None,
                "repair": _empty_source_probe_repair(enabled=False),
            }

        request = _source_request_for(benchmark)
        probe = {
            "enabled": True,
            "status": "not_run",
            "prompt_sha256": _sha256_text(source_prompt),
            "prompt_template_version": provider.prompt_template_version_for(request),
            "raw_output_path": None,
            "extracted_source_path": None,
            "parameter_analysis_path": None,
            "compile_status": "not_run",
            "compiled_stl_path": None,
            "compile_stdout_path": None,
            "compile_stderr_path": None,
            "mesh_metadata_path": None,
            "compile_error_message": None,
            "compile_timed_out": None,
            "compile_exit_code": None,
            "compile_warning_count": 0,
            "compile_warnings": [],
            "stl_size_bytes": 0,
            "error_path": None,
            "repair": _empty_source_probe_repair(enabled=source_probe_repair),
        }
        if provider_mode == "dry-run":
            return probe

        try:
            result = asyncio.run(provider.generate_model(request))
        except TimeoutError as exc:
            probe["status"] = "provider_failed"
            probe["error_path"] = self._write_error(artifact_dir, run_dir, exc)
            return probe
        except Exception as exc:
            probe["status"] = "provider_failed"
            probe["error_path"] = self._write_error(artifact_dir, run_dir, exc)
            return probe

        output_file = artifact_dir / "source-raw-output.txt"
        output_file.write_text(result.raw_output, encoding="utf-8")
        probe["raw_output_path"] = _relative(output_file, run_dir)

        try:
            source = extract_scad_source(result.raw_output)
        except SourceExtractionError as exc:
            analysis_path = artifact_dir / "source-parameter-analysis.json"
            _write_json(
                analysis_path,
                _source_parameter_analysis(
                    benchmark=benchmark,
                    extracted_source=None,
                    extraction_error=str(exc),
                ),
            )
            probe["status"] = "source_extraction_failed"
            probe["parameter_analysis_path"] = _relative(analysis_path, run_dir)
            return probe

        source_path = artifact_dir / "source-extracted.scad"
        source_path.write_text(source, encoding="utf-8")
        analysis_path = artifact_dir / "source-parameter-analysis.json"
        _write_json(
            analysis_path,
            _source_parameter_analysis(
                benchmark=benchmark,
                extracted_source=source,
                extraction_error=None,
            ),
        )
        probe["status"] = "source_parameters_analyzed"
        probe["extracted_source_path"] = _relative(source_path, run_dir)
        probe["parameter_analysis_path"] = _relative(analysis_path, run_dir)
        probe.update(_compile_source_probe(source=source, run_dir=run_dir, artifact_dir=artifact_dir))
        if probe["compile_status"] != "compile_succeeded":
            probe["status"] = "source_compile_failed"
            if source_probe_repair:
                repair = self._run_source_probe_repair(
                    benchmark=benchmark,
                    provider=provider,
                    run_dir=run_dir,
                    artifact_dir=artifact_dir,
                    failed_source=source,
                    compiler_diagnostics=probe["compile_error_message"]
                    or _read_text_if_present(run_dir, probe["compile_stderr_path"])
                    or "OpenSCAD compile failed",
                )
                probe["repair"] = repair
                if repair["status"] == "source_repair_succeeded":
                    probe["status"] = "source_repair_succeeded"
        return probe

    def _run_source_probe_repair(
        self,
        *,
        benchmark: GenerationBenchmark,
        provider: GeminiCliProvider,
        run_dir: Path,
        artifact_dir: Path,
        failed_source: str,
        compiler_diagnostics: str,
    ) -> dict[str, Any]:
        request = _source_repair_request_for(
            benchmark=benchmark,
            current_source=failed_source,
            compiler_diagnostics=compiler_diagnostics,
        )
        repair_prompt = provider.build_prompt(request)
        repair = _empty_source_probe_repair(enabled=True)
        repair["prompt_sha256"] = _sha256_text(repair_prompt)
        repair["prompt_template_version"] = provider.prompt_template_version_for(request)
        prompt_path = artifact_dir / "source-repair-prompt.txt"
        prompt_path.write_text(repair_prompt, encoding="utf-8")
        repair["prompt_path"] = _relative(prompt_path, run_dir)

        try:
            result = asyncio.run(provider.generate_model(request))
        except TimeoutError as exc:
            repair["status"] = "repair_provider_failed"
            repair["error_path"] = self._write_error(artifact_dir, run_dir, exc)
            return repair
        except Exception as exc:
            repair["status"] = "repair_provider_failed"
            repair["error_path"] = self._write_error(artifact_dir, run_dir, exc)
            return repair

        output_file = artifact_dir / "source-repair-raw-output.txt"
        output_file.write_text(result.raw_output, encoding="utf-8")
        repair["raw_output_path"] = _relative(output_file, run_dir)

        try:
            repaired_source = extract_scad_source(result.raw_output)
        except SourceExtractionError as exc:
            analysis_path = artifact_dir / "source-repair-parameter-analysis.json"
            _write_json(
                analysis_path,
                _source_parameter_analysis(
                    benchmark=benchmark,
                    extracted_source=None,
                    extraction_error=str(exc),
                ),
            )
            repair["status"] = "source_repair_extraction_failed"
            repair["parameter_analysis_path"] = _relative(analysis_path, run_dir)
            return repair

        source_path = artifact_dir / "source-repair-extracted.scad"
        source_path.write_text(repaired_source, encoding="utf-8")
        analysis_path = artifact_dir / "source-repair-parameter-analysis.json"
        _write_json(
            analysis_path,
            _source_parameter_analysis(
                benchmark=benchmark,
                extracted_source=repaired_source,
                extraction_error=None,
            ),
        )
        repair["status"] = "source_repair_parameters_analyzed"
        repair["extracted_source_path"] = _relative(source_path, run_dir)
        repair["parameter_analysis_path"] = _relative(analysis_path, run_dir)
        repair.update(
            _compile_source_probe(
                source=repaired_source,
                run_dir=run_dir,
                artifact_dir=artifact_dir,
                workspace_dir_name="source-repair-compile-workspace",
                job_id="source-repair",
            )
        )
        if repair["compile_status"] == "compile_succeeded":
            repair["status"] = "source_repair_succeeded"
        else:
            repair["status"] = "source_repair_compile_failed"
        return repair

    def _select_benchmarks(
        self,
        suite: BenchmarkSuite,
        config: LiveBenchmarkConfig,
    ) -> list[GenerationBenchmark]:
        benchmarks = suite.benchmarks
        if config.phase_validation:
            if config.benchmark_ids:
                raise ValueError("phase_validation cannot be combined with explicit benchmark_ids")
            if config.max_cases is not None:
                raise ValueError("phase_validation cannot be combined with max_cases")
            config = LiveBenchmarkConfig(
                suite_path=config.suite_path,
                output_root=config.output_root,
                run_label=config.run_label,
                benchmark_ids=phase_validation_benchmark_ids(),
                runs_per_case=config.runs_per_case,
                max_cases=config.max_cases,
                max_runs=config.max_runs,
                max_estimated_tokens=config.max_estimated_tokens,
                cost_per_1k_tokens_usd=config.cost_per_1k_tokens_usd,
                max_estimated_cost_usd=config.max_estimated_cost_usd,
                provider=config.provider,
                allow_live=config.allow_live,
                baseline_manifest_path=config.baseline_manifest_path,
                phase_validation=config.phase_validation,
                source_probe=config.source_probe,
                source_probe_repair=config.source_probe_repair,
            )
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
        if config.source_probe_repair and not config.source_probe:
            raise ValueError("source_probe_repair requires source_probe")
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

    def _build_source_prompts(
        self,
        provider: GeminiCliProvider,
        benchmarks: list[GenerationBenchmark],
    ) -> dict[str, str]:
        return {
            benchmark.id: provider.build_prompt(_source_request_for(benchmark))
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

    def _estimate_run_tokens(self, prompts: list[str], runs_per_case: int) -> int:
        return sum(max(1, len(prompt) // 4) for prompt in prompts) * runs_per_case

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

    def _build_metrics(self, manifest: dict[str, Any], run_dir: Path) -> dict[str, Any]:
        status_counts: dict[str, int] = {}
        failure_class_counts: dict[str, int] = {}
        for case_run in manifest["case_runs"]:
            status_counts[case_run["status"]] = status_counts.get(case_run["status"], 0) + 1
            failure_class = case_run["failure_class"]
            failure_class_counts[failure_class] = failure_class_counts.get(failure_class, 0) + 1
        source_probe_status_counts: dict[str, int] = {}
        source_probe_compile_status_counts: dict[str, int] = {}
        source_probe_coverages: list[float] = []
        source_probe_compiled_watertight_count = 0
        source_probe_compiled_nonzero_volume_count = 0
        source_probe_disconnected_mesh_count = 0
        source_probe_max_connected_components = 0
        source_probe_compile_warning_count = 0
        source_probe_repair_status_counts: dict[str, int] = {}
        source_probe_repair_compile_status_counts: dict[str, int] = {}
        source_probe_repair_attempt_count = 0
        source_probe_repair_compile_success_count = 0
        source_probe_repair_compile_warning_count = 0
        for case_run in manifest["case_runs"]:
            source_probe = case_run.get("source_probe", {})
            status = source_probe.get("status", "disabled")
            source_probe_status_counts[status] = source_probe_status_counts.get(status, 0) + 1
            compile_status = source_probe.get("compile_status", "disabled")
            source_probe_compile_status_counts[compile_status] = (
                source_probe_compile_status_counts.get(compile_status, 0) + 1
            )
            warning_count = source_probe.get("compile_warning_count", 0)
            if isinstance(warning_count, int):
                source_probe_compile_warning_count += warning_count
            analysis_path = source_probe.get("parameter_analysis_path")
            if isinstance(analysis_path, str):
                analysis_file = run_dir / analysis_path
                if analysis_file.exists():
                    analysis = json.loads(analysis_file.read_text(encoding="utf-8"))
                    coverage = analysis.get("expected_parameter_coverage")
                    if isinstance(coverage, int | float):
                        source_probe_coverages.append(float(coverage))
            metadata_path = source_probe.get("mesh_metadata_path")
            if isinstance(metadata_path, str):
                metadata_file = run_dir / metadata_path
                if metadata_file.exists():
                    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
                    if metadata.get("is_watertight") is True:
                        source_probe_compiled_watertight_count += 1
                    volume = metadata.get("volume_mm3")
                    if isinstance(volume, int | float) and volume > 0:
                        source_probe_compiled_nonzero_volume_count += 1
                    connected_components = metadata.get("connected_components")
                    if isinstance(connected_components, int):
                        source_probe_max_connected_components = max(
                            source_probe_max_connected_components,
                            connected_components,
                        )
                        if connected_components > 1:
                            source_probe_disconnected_mesh_count += 1
            repair = source_probe.get("repair", {})
            if isinstance(repair, dict):
                repair_status = repair.get("status", "disabled")
                source_probe_repair_status_counts[repair_status] = (
                    source_probe_repair_status_counts.get(repair_status, 0) + 1
                )
                if repair_status not in {"disabled", "not_attempted"}:
                    source_probe_repair_attempt_count += 1
                repair_compile_status = repair.get("compile_status", "disabled")
                source_probe_repair_compile_status_counts[repair_compile_status] = (
                    source_probe_repair_compile_status_counts.get(repair_compile_status, 0) + 1
                )
                if repair_compile_status == "compile_succeeded":
                    source_probe_repair_compile_success_count += 1
                repair_warning_count = repair.get("compile_warning_count", 0)
                if isinstance(repair_warning_count, int):
                    source_probe_repair_compile_warning_count += repair_warning_count
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
            "phase_validation": bool(manifest.get("config", {}).get("phase_validation")),
            "source_probe_enabled": bool(manifest.get("config", {}).get("source_probe")),
            "source_probe_status_counts": source_probe_status_counts,
            "source_probe_compile_status_counts": source_probe_compile_status_counts,
            "source_probe_expected_parameter_coverage_average": (
                round(sum(source_probe_coverages) / len(source_probe_coverages), 4)
                if source_probe_coverages
                else None
            ),
            "source_probe_compiled_watertight_count": source_probe_compiled_watertight_count,
            "source_probe_compiled_nonzero_volume_count": (
                source_probe_compiled_nonzero_volume_count
            ),
            "source_probe_disconnected_mesh_count": source_probe_disconnected_mesh_count,
            "source_probe_max_connected_components": source_probe_max_connected_components,
            "source_probe_compile_warning_count": source_probe_compile_warning_count,
            "source_probe_repair_enabled": bool(
                manifest.get("config", {}).get("source_probe_repair")
            ),
            "source_probe_repair_status_counts": source_probe_repair_status_counts,
            "source_probe_repair_compile_status_counts": (
                source_probe_repair_compile_status_counts
            ),
            "source_probe_repair_attempt_count": source_probe_repair_attempt_count,
            "source_probe_repair_compile_success_count": (
                source_probe_repair_compile_success_count
            ),
            "source_probe_repair_compile_warning_count": (
                source_probe_repair_compile_warning_count
            ),
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


def _source_request_for(benchmark: GenerationBenchmark) -> ModelGenerationRequest:
    user_instruction = benchmark.input_prompt
    if benchmark.expected_parameters:
        user_instruction = "\n".join(
            [
                benchmark.input_prompt,
                "",
                "Source-probe parameter targets:",
                "Expose these as simple top-level OpenSCAD parameters when applicable.",
                "Use each target identifier exactly as written.",
                "Do not split a target into indexed parameters, arrays, renamed aliases, or derived-only values.",
                "Do not force the silhouette or styling into a fixed template; keep the requested creative form.",
                *[f"- {parameter}" for parameter in benchmark.expected_parameters],
            ]
        )
    return ModelGenerationRequest(
        project_name=f"Benchmark: {benchmark.id}",
        original_intent=benchmark.input_prompt,
        user_instruction=user_instruction,
    )


def _source_repair_request_for(
    *,
    benchmark: GenerationBenchmark,
    current_source: str,
    compiler_diagnostics: str,
) -> ModelGenerationRequest:
    return ModelGenerationRequest(
        project_name=f"Benchmark: {benchmark.id}",
        original_intent=benchmark.input_prompt,
        user_instruction=(
            "Repair the OpenSCAD source so it compiles cleanly while preserving the benchmark "
            "intent and expected source-probe parameters."
        ),
        current_source=current_source,
        compiler_diagnostics=compiler_diagnostics,
    )


def _empty_source_probe_repair(*, enabled: bool) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "status": "not_attempted" if enabled else "disabled",
        "prompt_sha256": None,
        "prompt_template_version": None,
        "prompt_path": None,
        "raw_output_path": None,
        "extracted_source_path": None,
        "parameter_analysis_path": None,
        "compile_status": "not_run" if enabled else "disabled",
        "compiled_stl_path": None,
        "compile_stdout_path": None,
        "compile_stderr_path": None,
        "mesh_metadata_path": None,
        "compile_error_message": None,
        "compile_timed_out": None,
        "compile_exit_code": None,
        "compile_warning_count": 0,
        "compile_warnings": [],
        "stl_size_bytes": 0,
        "error_path": None,
    }


def _source_parameter_analysis(
    *,
    benchmark: GenerationBenchmark,
    extracted_source: str | None,
    extraction_error: str | None,
) -> dict[str, Any]:
    if extracted_source is None:
        return {
            "schema_version": SOURCE_PARAMETER_ANALYSIS_SCHEMA_VERSION,
            "benchmark_id": benchmark.id,
            "source_extracted": False,
            "extraction_error": extraction_error,
            "expected_parameters": benchmark.expected_parameters,
            "parameter_count": 0,
            "parameter_ids": [],
            "matched_expected_parameters": [],
            "missing_expected_parameters": benchmark.expected_parameters,
            "expected_parameter_coverage": 0.0 if benchmark.expected_parameters else None,
            "parameter_types": {},
            "parameter_groups": [],
        }

    parameters = extract_editable_parameters(extracted_source)
    parameter_ids = [parameter.id for parameter in parameters]
    parameter_id_set = set(parameter_ids)
    matched = [
        parameter_id
        for parameter_id in benchmark.expected_parameters
        if parameter_id in parameter_id_set
    ]
    missing = [
        parameter_id
        for parameter_id in benchmark.expected_parameters
        if parameter_id not in parameter_id_set
    ]
    coverage = (
        round(len(matched) / len(benchmark.expected_parameters), 4)
        if benchmark.expected_parameters
        else None
    )
    return {
        "schema_version": SOURCE_PARAMETER_ANALYSIS_SCHEMA_VERSION,
        "benchmark_id": benchmark.id,
        "source_extracted": True,
        "extraction_error": None,
        "expected_parameters": benchmark.expected_parameters,
        "parameter_count": len(parameters),
        "parameter_ids": parameter_ids,
        "matched_expected_parameters": matched,
        "missing_expected_parameters": missing,
        "expected_parameter_coverage": coverage,
        "parameter_types": {parameter.id: parameter.type for parameter in parameters},
        "parameter_groups": sorted(
            {parameter.group for parameter in parameters if parameter.group is not None}
        ),
    }


def _compile_source_probe(
    *,
    source: str,
    run_dir: Path,
    artifact_dir: Path,
    workspace_dir_name: str = "source-compile-workspace",
    job_id: str = "source-probe",
) -> dict[str, Any]:
    workspace_root = (artifact_dir / workspace_dir_name).resolve()
    result = asyncio.run(
        OpenScadCliRunner(
            workspace_root=workspace_root,
            timeout_seconds=60,
        ).compile(source, job_id=job_id)
    )
    warnings = _openscad_warning_lines(result.stderr_path)
    return {
        "compile_status": "compile_succeeded" if result.success else "compile_failed",
        "compiled_stl_path": _relative(result.stl_path, run_dir)
        if result.success and result.stl_path is not None
        else None,
        "compile_stdout_path": _relative(result.stdout_path, run_dir)
        if result.stdout_path is not None
        else None,
        "compile_stderr_path": _relative(result.stderr_path, run_dir)
        if result.stderr_path is not None
        else None,
        "mesh_metadata_path": _relative(result.metadata_path, run_dir)
        if result.success and result.metadata_path is not None
        else None,
        "compile_error_message": result.error_message,
        "compile_timed_out": result.timed_out,
        "compile_exit_code": result.exit_code,
        "compile_warning_count": len(warnings),
        "compile_warnings": warnings[:20],
        "stl_size_bytes": result.output_size_bytes,
    }


def _openscad_warning_lines(stderr_path: Path | None) -> list[str]:
    if stderr_path is None or not stderr_path.exists():
        return []
    warnings: list[str] = []
    for line in stderr_path.read_text(encoding="utf-8", errors="replace").splitlines():
        normalized = line.strip()
        if not normalized:
            continue
        upper = normalized.upper()
        if upper.startswith("WARNING:") or upper.startswith("DEPRECATED:"):
            warnings.append(normalized)
    return warnings


def _read_text_if_present(run_dir: Path, relative_path: Any) -> str | None:
    if not isinstance(relative_path, str):
        return None
    path = run_dir / relative_path
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8", errors="replace").strip() or None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _relative(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


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
