import json
from pathlib import Path

import pytest

from app.services.generation.live_benchmarks import (
    LiveBenchmarkConfig,
    LiveBenchmarkRunner,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "generation_benchmarks"


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
