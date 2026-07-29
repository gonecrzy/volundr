import json
from pathlib import Path

import pytest

from app.services.generation.live_benchmarks import (
    LiveBenchmarkConfig,
    LiveBenchmarkRunner,
    _openscad_warning_lines,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "generation_benchmarks"


def test_openscad_warning_parser_ignores_warning_substring_in_paths(tmp_path: Path) -> None:
    stderr_path = tmp_path / "stderr.log"
    stderr_path.write_text(
        "Can't parse file '/tmp/live-benchmark-compile-warning-source-probe/model.scad'!\n"
        "WARNING: real OpenSCAD warning\n"
        "DEPRECATED: real OpenSCAD deprecation\n",
        encoding="utf-8",
    )

    assert _openscad_warning_lines(stderr_path) == [
        "WARNING: real OpenSCAD warning",
        "DEPRECATED: real OpenSCAD deprecation",
    ]


def test_live_benchmark_dry_run_writes_manifest_metrics_reports_and_scoring_forms(
    tmp_path: Path,
) -> None:
    result = LiveBenchmarkRunner().run(
        LiveBenchmarkConfig(
            suite_path=FIXTURE_DIR / "core.json",
            output_root=tmp_path,
            run_label="smoke",
            benchmark_ids=("simple_mounting_plate", "vague_clarification"),
            provider="dry-run",
        )
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    metrics = json.loads(result.metrics_path.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == "live-benchmark-run-v1"
    assert manifest["no_automatic_prompt_promotion"] is True
    assert manifest["provider"]["mode"] == "dry-run"
    assert manifest["prompt_versions"]["requirements"] == "requirements-v1"
    assert [case["benchmark_id"] for case in manifest["case_runs"]] == [
        "simple_mounting_plate",
        "vague_clarification",
    ]

    assert metrics["schema_version"] == "live-benchmark-metrics-v1"
    assert metrics["total_case_runs"] == 2
    assert metrics["status_counts"] == {"not_run": 2}
    assert metrics["needs_human_scoring"] is True
    assert metrics["next_work_buckets"] == {
        "prompt_quality": 0,
        "design_plan_quality": 0,
        "component_decomposition": 0,
        "parameter_modeling": 0,
        "geometry_generation": 0,
        "printability": 0,
        "revision_preservation": 0,
        "ux": 0,
    }

    for case_run in manifest["case_runs"]:
        report_path = result.run_dir / case_run["report_path"]
        scoring_path = result.run_dir / case_run["scoring_form_path"]
        artifact_path = result.run_dir / case_run["artifact_dir"] / "benchmark-input.json"
        prompt_path = result.run_dir / case_run["artifact_dir"] / "requirements-prompt.txt"

        assert report_path.exists()
        assert artifact_path.exists()
        assert prompt_path.exists()

        scoring = json.loads(scoring_path.read_text(encoding="utf-8"))
        assert scoring["schema_version"] == "human-scoring-form-v1"
        assert scoring["status"] == "unscored"
        assert set(scoring["scores"]) == set(metrics["next_work_buckets"])


def test_live_benchmark_phase_validation_selects_three_progression_scenarios(
    tmp_path: Path,
) -> None:
    result = LiveBenchmarkRunner().run(
        LiveBenchmarkConfig(
            suite_path=FIXTURE_DIR / "core.json",
            output_root=tmp_path,
            run_label="phase-check",
            phase_validation=True,
            provider="dry-run",
        )
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    metrics = json.loads(result.metrics_path.read_text(encoding="utf-8"))

    assert manifest["config"]["phase_validation"] is True
    assert manifest["validation_scenario_set"] == {
        "schema_version": "phase-validation-scenarios-v1",
        "purpose": "quick before/after signal for generation pipeline changes",
        "benchmark_ids": [
            "creative_fish_shelf_bracket",
            "honeycomb_angle_bracket",
            "threaded_control_knob",
        ],
    }
    assert [case["benchmark_id"] for case in manifest["case_runs"]] == [
        "creative_fish_shelf_bracket",
        "honeycomb_angle_bracket",
        "threaded_control_knob",
    ]
    assert metrics["phase_validation"] is True
    assert metrics["total_case_runs"] == 3


def test_live_benchmark_source_probe_dry_run_writes_source_prompt(
    tmp_path: Path,
) -> None:
    result = LiveBenchmarkRunner().run(
        LiveBenchmarkConfig(
            suite_path=FIXTURE_DIR / "core.json",
            output_root=tmp_path,
            run_label="source-probe",
            benchmark_ids=("simple_mounting_plate",),
            provider="dry-run",
            source_probe=True,
        )
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    metrics = json.loads(result.metrics_path.read_text(encoding="utf-8"))
    case_run = manifest["case_runs"][0]
    source_probe = case_run["source_probe"]

    assert manifest["config"]["source_probe"] is True
    assert source_probe["enabled"] is True
    assert source_probe["status"] == "not_run"
    assert source_probe["prompt_template_version"] == "legacy-initial-v1"
    assert source_probe["raw_output_path"] is None
    assert source_probe["parameter_analysis_path"] is None
    source_prompt = (result.run_dir / case_run["artifact_dir"] / "source-prompt.txt").read_text(
        encoding="utf-8"
    )
    assert "Source-probe parameter targets" in source_prompt
    assert "Use each target identifier exactly as written" in source_prompt
    assert "Do not split a target into indexed parameters" in source_prompt
    assert "plate_width" in source_prompt
    assert "hole_spacing" in source_prompt
    assert metrics["source_probe_enabled"] is True
    assert metrics["source_probe_status_counts"] == {"not_run": 1}


def test_live_benchmark_source_probe_extracts_parameter_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.generation import live_benchmarks

    class FakeOllamaProvider:
        def provider_settings(self) -> dict:
            return {"model": "fake-cad", "auth_mode": "local_ollama"}

        def build_requirement_prompt(self, request) -> str:
            return f"requirements for {request.user_instruction}"

        def build_prompt(self, request) -> str:
            return f"source for {request.user_instruction}"

        def requirement_prompt_template_version(self) -> str:
            return "requirements-v1"

        def design_plan_prompt_template_version(self) -> str:
            return "design-plan-v1"

        def revision_plan_prompt_template_version(self) -> str:
            return "revision-planning-v1"

        def prompt_template_version_for(self, request) -> str:
            return "legacy-initial-v1"

        async def extract_requirements(self, request):
            from app.services.ai.provider import RequirementExtractionResult

            return RequirementExtractionResult(
                raw_output="{}",
                provider="ollama",
                provider_model="fake-cad",
            )

        async def generate_model(self, request):
            from app.services.ai.provider import ModelGenerationResult

            return ModelGenerationResult(
                raw_output="""
```openscad
/* [Dimensions] */
plate_width = 80; // [40:1:160]
plate_depth = 35; // [20:1:80]
plate_thickness = 6; // [2:1:12]
hole_spacing = 55; // [20:1:120]

module main_model() {
  cube([plate_width, plate_depth, plate_thickness]);
}
main_model();
```
""",
                provider="ollama",
                provider_model="fake-cad",
            )

    monkeypatch.setattr(live_benchmarks, "OllamaProvider", FakeOllamaProvider)

    result = LiveBenchmarkRunner().run(
        LiveBenchmarkConfig(
            suite_path=FIXTURE_DIR / "core.json",
            output_root=tmp_path,
            run_label="warning-path",
            benchmark_ids=("simple_mounting_plate",),
            provider="ollama",
            source_probe=True,
        )
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    metrics = json.loads(result.metrics_path.read_text(encoding="utf-8"))
    source_probe = manifest["case_runs"][0]["source_probe"]
    analysis = json.loads(
        (result.run_dir / source_probe["parameter_analysis_path"]).read_text(encoding="utf-8")
    )

    assert source_probe["status"] == "source_parameters_analyzed"
    assert source_probe["extracted_source_path"] is not None
    assert analysis["schema_version"] == "source-parameter-analysis-v1"
    assert analysis["source_extracted"] is True
    assert analysis["parameter_ids"] == [
        "plate_width",
        "plate_depth",
        "plate_thickness",
        "hole_spacing",
    ]
    assert analysis["matched_expected_parameters"] == [
        "plate_width",
        "plate_depth",
        "plate_thickness",
        "hole_spacing",
    ]
    assert analysis["expected_parameter_coverage"] == pytest.approx(4 / 5)
    assert metrics["source_probe_status_counts"] == {"source_parameters_analyzed": 1}
    assert metrics["source_probe_expected_parameter_coverage_average"] == pytest.approx(4 / 5)


def test_live_benchmark_source_probe_compiles_extracted_source_and_records_mesh_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.generation import live_benchmarks

    class FakeOllamaProvider:
        def provider_settings(self) -> dict:
            return {"model": "fake-cad", "auth_mode": "local_ollama"}

        def build_requirement_prompt(self, request) -> str:
            return f"requirements for {request.user_instruction}"

        def build_prompt(self, request) -> str:
            return f"source for {request.user_instruction}"

        def requirement_prompt_template_version(self) -> str:
            return "requirements-v1"

        def design_plan_prompt_template_version(self) -> str:
            return "design-plan-v1"

        def revision_plan_prompt_template_version(self) -> str:
            return "revision-planning-v1"

        def prompt_template_version_for(self, request) -> str:
            return "legacy-initial-v1"

        async def extract_requirements(self, request):
            from app.services.ai.provider import RequirementExtractionResult

            return RequirementExtractionResult(
                raw_output="{}",
                provider="ollama",
                provider_model="fake-cad",
            )

        async def generate_model(self, request):
            from app.services.ai.provider import ModelGenerationResult

            return ModelGenerationResult(
                raw_output="""
```openscad
angle = pi / 6;
plate_width = 80;
plate_depth = 35;
plate_thickness = 6;
hole_spacing = 55;

module main_model() {
  cube([plate_width, plate_depth, plate_thickness]);
}
main_model();
```
""",
                provider="ollama",
                provider_model="fake-cad",
            )

    monkeypatch.setattr(live_benchmarks, "OllamaProvider", FakeOllamaProvider)

    result = LiveBenchmarkRunner().run(
        LiveBenchmarkConfig(
            suite_path=FIXTURE_DIR / "core.json",
            output_root=tmp_path,
            benchmark_ids=("simple_mounting_plate",),
            provider="ollama",
            source_probe=True,
        )
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    metrics = json.loads(result.metrics_path.read_text(encoding="utf-8"))
    source_probe = manifest["case_runs"][0]["source_probe"]

    assert source_probe["status"] == "source_parameters_analyzed"
    assert source_probe["compile_status"] == "compile_succeeded"
    assert source_probe["compile_warning_count"] == 2
    assert any("unknown variable 'pi'" in warning for warning in source_probe["compile_warnings"])
    assert source_probe["compiled_stl_path"] is not None
    assert source_probe["mesh_metadata_path"] is not None
    assert (result.run_dir / source_probe["compiled_stl_path"]).stat().st_size > 0
    metadata = json.loads(
        (result.run_dir / source_probe["mesh_metadata_path"]).read_text(encoding="utf-8")
    )
    assert metadata["size_x_mm"] == pytest.approx(80)
    assert metadata["size_y_mm"] == pytest.approx(35)
    assert metadata["size_z_mm"] == pytest.approx(6)
    assert metadata["volume_mm3"] > 0
    assert metadata["triangle_count"] > 0
    assert metadata["is_watertight"] is True
    assert metrics["source_probe_compile_status_counts"] == {"compile_succeeded": 1}
    assert metrics["source_probe_compile_warning_count"] == 2
    assert metrics["source_probe_compiled_watertight_count"] == 1
    assert metrics["source_probe_compiled_nonzero_volume_count"] == 1


def test_live_benchmark_source_probe_compile_supports_relative_output_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.generation import live_benchmarks

    monkeypatch.chdir(tmp_path)

    class FakeOllamaProvider:
        def provider_settings(self) -> dict:
            return {"model": "fake-cad", "auth_mode": "local_ollama"}

        def build_requirement_prompt(self, request) -> str:
            return f"requirements for {request.user_instruction}"

        def build_prompt(self, request) -> str:
            return f"source for {request.user_instruction}"

        def requirement_prompt_template_version(self) -> str:
            return "requirements-v1"

        def design_plan_prompt_template_version(self) -> str:
            return "design-plan-v1"

        def revision_plan_prompt_template_version(self) -> str:
            return "revision-planning-v1"

        def prompt_template_version_for(self, request) -> str:
            return "legacy-initial-v1"

        async def extract_requirements(self, request):
            from app.services.ai.provider import RequirementExtractionResult

            return RequirementExtractionResult(
                raw_output="{}",
                provider="ollama",
                provider_model="fake-cad",
            )

        async def generate_model(self, request):
            from app.services.ai.provider import ModelGenerationResult

            return ModelGenerationResult(
                raw_output="""
```openscad
plate_width = 10;
plate_depth = 10;
plate_thickness = 10;

module main_model() {
  cube([plate_width, plate_depth, plate_thickness]);
}
main_model();
```
""",
                provider="ollama",
                provider_model="fake-cad",
            )

    monkeypatch.setattr(live_benchmarks, "OllamaProvider", FakeOllamaProvider)

    result = LiveBenchmarkRunner().run(
        LiveBenchmarkConfig(
            suite_path=FIXTURE_DIR / "core.json",
            output_root=Path("relative-output"),
            benchmark_ids=("simple_mounting_plate",),
            provider="ollama",
            source_probe=True,
        )
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    source_probe = manifest["case_runs"][0]["source_probe"]

    assert source_probe["compile_status"] == "compile_succeeded"
    assert (result.run_dir / source_probe["compiled_stl_path"]).exists()


def test_live_benchmark_source_probe_records_compile_failure_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.generation import live_benchmarks

    class FakeOllamaProvider:
        def provider_settings(self) -> dict:
            return {"model": "fake-cad", "auth_mode": "local_ollama"}

        def build_requirement_prompt(self, request) -> str:
            return f"requirements for {request.user_instruction}"

        def build_prompt(self, request) -> str:
            return f"source for {request.user_instruction}"

        def requirement_prompt_template_version(self) -> str:
            return "requirements-v1"

        def design_plan_prompt_template_version(self) -> str:
            return "design-plan-v1"

        def revision_plan_prompt_template_version(self) -> str:
            return "revision-planning-v1"

        def prompt_template_version_for(self, request) -> str:
            return "legacy-initial-v1"

        async def extract_requirements(self, request):
            from app.services.ai.provider import RequirementExtractionResult

            return RequirementExtractionResult(
                raw_output="{}",
                provider="ollama",
                provider_model="fake-cad",
            )

        async def generate_model(self, request):
            from app.services.ai.provider import ModelGenerationResult

            return ModelGenerationResult(
                raw_output="""
```openscad
plate_width = 80;

module main_model() {
  cube([plate_width, 10, 10];
}
main_model();
```
""",
                provider="ollama",
                provider_model="fake-cad",
            )

    monkeypatch.setattr(live_benchmarks, "OllamaProvider", FakeOllamaProvider)

    result = LiveBenchmarkRunner().run(
        LiveBenchmarkConfig(
            suite_path=FIXTURE_DIR / "core.json",
            output_root=tmp_path,
            benchmark_ids=("simple_mounting_plate",),
            provider="ollama",
            source_probe=True,
        )
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    metrics = json.loads(result.metrics_path.read_text(encoding="utf-8"))
    source_probe = manifest["case_runs"][0]["source_probe"]

    assert source_probe["status"] == "source_compile_failed"
    assert source_probe["compile_status"] == "compile_failed"
    assert source_probe["compile_error_message"]
    assert source_probe["compile_warning_count"] == 0
    assert source_probe["compile_warnings"] == []
    assert source_probe["compile_stderr_path"] is not None
    assert "parser error" in (
        result.run_dir / source_probe["compile_stderr_path"]
    ).read_text(encoding="utf-8").lower()
    assert source_probe["compiled_stl_path"] is None
    assert source_probe["mesh_metadata_path"] is None
    assert metrics["source_probe_status_counts"] == {"source_compile_failed": 1}
    assert metrics["source_probe_compile_status_counts"] == {"compile_failed": 1}
    assert metrics["source_probe_compile_warning_count"] == 0
    assert metrics["source_probe_compiled_watertight_count"] == 0


def test_live_benchmark_phase_validation_rejects_truncating_case_limit(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="phase_validation cannot be combined with max_cases"):
        LiveBenchmarkRunner().run(
            LiveBenchmarkConfig(
                suite_path=FIXTURE_DIR / "core.json",
                output_root=tmp_path,
                phase_validation=True,
                max_cases=1,
                provider="dry-run",
            )
        )


def test_live_benchmark_repeated_runs_are_explicit_and_bounded(tmp_path: Path) -> None:
    result = LiveBenchmarkRunner().run(
        LiveBenchmarkConfig(
            suite_path=FIXTURE_DIR / "core.json",
            output_root=tmp_path,
            benchmark_ids=("spacer_bushing",),
            runs_per_case=3,
            max_runs=3,
        )
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert [case["run_index"] for case in manifest["case_runs"]] == [1, 2, 3]
    assert len({case["case_run_id"] for case in manifest["case_runs"]}) == 3


def test_live_benchmark_quota_controls_reject_unapproved_live_provider(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="requires --allow-live"):
        LiveBenchmarkRunner().run(
            LiveBenchmarkConfig(
                suite_path=FIXTURE_DIR / "core.json",
                output_root=tmp_path,
                benchmark_ids=("simple_mounting_plate",),
                provider="gemini",
                allow_live=False,
            )
        )


def test_live_benchmark_quota_controls_allow_unapproved_local_ollama(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.generation import live_benchmarks

    class FakeOllamaProvider:
        def provider_settings(self) -> dict:
            return {"model": "qwen3.5:9b", "auth_mode": "local_ollama"}

        def build_requirement_prompt(self, request) -> str:
            return f"requirements for {request.user_instruction}"

        def requirement_prompt_template_version(self) -> str:
            return "requirements-v1"

        def design_plan_prompt_template_version(self) -> str:
            return "design-plan-v1"

        def revision_plan_prompt_template_version(self) -> str:
            return "revision-planning-v1"

        async def extract_requirements(self, request):
            from app.services.ai.provider import RequirementExtractionResult

            return RequirementExtractionResult(
                raw_output="{}",
                provider="ollama",
                provider_model="qwen3.5:9b",
            )

    monkeypatch.setattr(live_benchmarks, "OllamaProvider", FakeOllamaProvider)

    result = LiveBenchmarkRunner().run(
        LiveBenchmarkConfig(
            suite_path=FIXTURE_DIR / "core.json",
            output_root=tmp_path,
            benchmark_ids=("simple_mounting_plate",),
            provider="ollama",
            allow_live=False,
        )
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert manifest["provider"]["mode"] == "ollama"
    assert manifest["provider"]["live_provider_calls_enabled"] is True
    assert manifest["case_runs"][0]["status"] == "provider_output_collected"


def test_live_benchmark_quota_controls_reject_excessive_run_count(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="exceeds max_runs"):
        LiveBenchmarkRunner().run(
            LiveBenchmarkConfig(
                suite_path=FIXTURE_DIR / "core.json",
                output_root=tmp_path,
                benchmark_ids=("simple_mounting_plate", "spacer_bushing"),
                runs_per_case=2,
                max_runs=3,
            )
        )


def test_live_benchmark_cost_controls_use_user_supplied_rate(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="estimated cost"):
        LiveBenchmarkRunner().run(
            LiveBenchmarkConfig(
                suite_path=FIXTURE_DIR / "core.json",
                output_root=tmp_path,
                benchmark_ids=("simple_mounting_plate",),
                cost_per_1k_tokens_usd=1.0,
                max_estimated_cost_usd=0.01,
            )
        )


def test_live_benchmark_prompt_version_comparison_is_report_only(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline-manifest.json"
    baseline_path.write_text(
        json.dumps(
            {
                "schema_version": "live-benchmark-run-v1",
                "prompt_versions": {
                    "requirements": "requirements-v0",
                    "design_plan": "design-plan-v1",
                },
            }
        ),
        encoding="utf-8",
    )

    result = LiveBenchmarkRunner().run(
        LiveBenchmarkConfig(
            suite_path=FIXTURE_DIR / "core.json",
            output_root=tmp_path,
            benchmark_ids=("simple_mounting_plate",),
            baseline_manifest_path=baseline_path,
        )
    )

    comparison = json.loads(result.prompt_comparison_path.read_text(encoding="utf-8"))

    assert comparison["schema_version"] == "prompt-version-comparison-v1"
    assert comparison["automatic_promotion"] is False
    assert comparison["changed_versions"]["requirements"] == {
        "baseline": "requirements-v0",
        "current": "requirements-v1",
    }
    assert "design_plan" in comparison["unchanged_versions"]
