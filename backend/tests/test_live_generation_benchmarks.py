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


def test_live_benchmark_cadquery_source_probe_dry_run_writes_python_prompt(
    tmp_path: Path,
) -> None:
    result = LiveBenchmarkRunner().run(
        LiveBenchmarkConfig(
            suite_path=FIXTURE_DIR / "core.json",
            output_root=tmp_path,
            run_label="cadquery-source-probe",
            benchmark_ids=("simple_mounting_plate",),
            provider="dry-run",
            source_probe=True,
            source_language="cadquery",
        )
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    metrics = json.loads(result.metrics_path.read_text(encoding="utf-8"))
    case_run = manifest["case_runs"][0]
    source_probe = case_run["source_probe"]

    assert manifest["config"]["source_language"] == "cadquery"
    assert source_probe["source_language"] == "cadquery"
    source_prompt = (result.run_dir / case_run["artifact_dir"] / "source-prompt.txt").read_text(
        encoding="utf-8"
    )
    assert "You generate CadQuery Python for Volundr" in source_prompt
    assert "cadquery-v1 source contract" in source_prompt
    assert "The only import allowed is exactly `import cadquery as cq`" in source_prompt
    assert "Do not run CadQuery operations" in source_prompt
    assert "helper functions may also be defined inside build_model()" in source_prompt
    assert "Known-good CadQuery patterns" in source_prompt
    assert ".pushPoints([(x, y)]).hole(hole_diameter)" in source_prompt
    assert "translate((x, y, z))" in source_prompt
    assert "Do not call hallucinated or unavailable helpers" in source_prompt
    assert ".holes()" in source_prompt
    assert "model = build_model()" in source_prompt
    assert "def build_model()" in source_prompt
    assert "```python" in source_prompt
    assert "Source-probe parameter targets" in source_prompt
    assert metrics["source_probe_language_counts"] == {"cadquery": 1}


def test_live_benchmark_source_brief_dry_run_writes_brief_prompt(
    tmp_path: Path,
) -> None:
    result = LiveBenchmarkRunner().run(
        LiveBenchmarkConfig(
            suite_path=FIXTURE_DIR / "core.json",
            output_root=tmp_path,
            run_label="source-brief",
            benchmark_ids=("creative_fish_shelf_bracket",),
            provider="dry-run",
            source_probe=True,
            source_brief=True,
        )
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    metrics = json.loads(result.metrics_path.read_text(encoding="utf-8"))
    case_run = manifest["case_runs"][0]
    source_probe = case_run["source_probe"]
    brief = source_probe["brief"]

    assert manifest["config"]["source_brief"] is True
    assert brief["enabled"] is True
    assert brief["status"] == "not_run"
    assert brief["prompt_template_version"] == "source-brief-v1"
    assert brief["raw_output_path"] is None
    prompt = (result.run_dir / case_run["artifact_dir"] / "source-brief-prompt.txt").read_text(
        encoding="utf-8"
    )
    assert "Return JSON only" in prompt
    assert "expected_connected_body_count" in prompt
    assert "decorative features must physically attach" in prompt
    assert metrics["source_brief_enabled"] is True
    assert metrics["source_brief_status_counts"] == {"not_run": 1}


def test_live_benchmark_source_brief_requires_source_probe(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="source_brief requires source_probe"):
        LiveBenchmarkRunner().run(
            LiveBenchmarkConfig(
                suite_path=FIXTURE_DIR / "core.json",
                output_root=tmp_path,
                benchmark_ids=("simple_mounting_plate",),
                provider="dry-run",
                source_brief=True,
            )
        )


def test_live_benchmark_source_probe_repair_requires_source_probe(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="source_probe_repair requires source_probe"):
        LiveBenchmarkRunner().run(
            LiveBenchmarkConfig(
                suite_path=FIXTURE_DIR / "core.json",
                output_root=tmp_path,
                benchmark_ids=("simple_mounting_plate",),
                provider="dry-run",
                source_probe_repair=True,
            )
        )


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
angle = PI / 6;
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
    assert source_probe["compile_warning_count"] == 0
    assert source_probe["compile_warnings"] == []
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
    assert metrics["source_probe_compile_warning_count"] == 0
    assert metrics["source_probe_compiled_watertight_count"] == 1
    assert metrics["source_probe_compiled_nonzero_volume_count"] == 1


def test_live_benchmark_cadquery_source_probe_extracts_and_records_compile_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.generation import live_benchmarks

    class FakeOllamaProvider:
        def provider_settings(self) -> dict:
            return {"model": "fake-cad", "auth_mode": "local_ollama"}

        def build_requirement_prompt(self, request) -> str:
            return f"requirements for {request.user_instruction}"

        def build_cadquery_prompt(self, request) -> str:
            return f"cadquery source for {request.user_instruction}"

        def cadquery_prompt_template_version(self) -> str:
            return "cadquery-source-v1"

        def requirement_prompt_template_version(self) -> str:
            return "requirements-v1"

        def design_plan_prompt_template_version(self) -> str:
            return "design-plan-v1"

        def revision_plan_prompt_template_version(self) -> str:
            return "revision-planning-v1"

        def prompt_template_version_for(self, request) -> str:
            return "cadquery-source-v1"

        async def extract_requirements(self, request):
            from app.services.ai.provider import RequirementExtractionResult

            return RequirementExtractionResult(
                raw_output="{}",
                provider="ollama",
                provider_model="fake-cad",
            )

        async def generate_cadquery_model(self, request):
            from app.services.ai.provider import ModelGenerationResult

            assert "Source-probe parameter targets" in request.user_instruction
            return ModelGenerationResult(
                raw_output="""
```python
import cadquery as cq

plate_width = 80
plate_depth = 35
plate_thickness = 6
hole_spacing = 55

def build_model():
    return cq.Workplane("XY").box(plate_width, plate_depth, plate_thickness)
```
""",
                provider="ollama",
                provider_model="fake-cad",
            )

    def fake_compile_cadquery_probe(*, source, run_dir, artifact_dir, workspace_dir_name="source-compile-workspace", job_id="source-probe"):
        workspace = artifact_dir / workspace_dir_name / job_id
        workspace.mkdir(parents=True)
        stl_path = workspace / "model.stl"
        stl_path.write_text("solid fake\nendsolid fake\n", encoding="utf-8")
        metadata_path = workspace / "metadata.json"
        metadata_path.write_text(
            json.dumps(
                {
                    "size_x_mm": 80,
                    "size_y_mm": 35,
                    "size_z_mm": 6,
                    "volume_mm3": 16800,
                    "triangle_count": 12,
                    "connected_components": 1,
                    "is_watertight": True,
                    "is_winding_consistent": True,
                    "center_of_mass": [0, 0, 0],
                }
            ),
            encoding="utf-8",
        )
        return {
            "compile_status": "compile_succeeded",
            "compiled_stl_path": str(stl_path.resolve().relative_to(run_dir.resolve())),
            "compiled_step_path": None,
            "compile_stdout_path": None,
            "compile_stderr_path": None,
            "mesh_metadata_path": str(metadata_path.resolve().relative_to(run_dir.resolve())),
            "compile_error_message": None,
            "compile_timed_out": False,
            "compile_exit_code": 0,
            "compile_warning_count": 0,
            "compile_warnings": [],
            "stl_size_bytes": stl_path.stat().st_size,
        }

    monkeypatch.setattr(live_benchmarks, "OllamaProvider", FakeOllamaProvider)
    monkeypatch.setattr(live_benchmarks, "_compile_cadquery_probe", fake_compile_cadquery_probe)

    result = LiveBenchmarkRunner().run(
        LiveBenchmarkConfig(
            suite_path=FIXTURE_DIR / "core.json",
            output_root=tmp_path,
            benchmark_ids=("simple_mounting_plate",),
            provider="ollama",
            source_probe=True,
            source_language="cadquery",
        )
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    metrics = json.loads(result.metrics_path.read_text(encoding="utf-8"))
    source_probe = manifest["case_runs"][0]["source_probe"]

    assert source_probe["source_language"] == "cadquery"
    assert source_probe["status"] == "source_parameters_analyzed"
    assert source_probe["compile_status"] == "compile_succeeded"
    assert source_probe["extracted_source_path"].endswith("source-extracted.py")
    assert source_probe["compiled_step_path"] is None
    assert metrics["source_probe_language_counts"] == {"cadquery": 1}
    assert metrics["source_probe_compile_status_counts"] == {"compile_succeeded": 1}


def test_live_benchmark_cadquery_source_probe_can_repair_failed_compile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.generation import live_benchmarks

    class FakeOllamaProvider:
        def __init__(self) -> None:
            self.generation_requests = []

        def provider_settings(self) -> dict:
            return {"model": "fake-cadquery", "auth_mode": "local_ollama"}

        def build_requirement_prompt(self, request) -> str:
            return f"requirements for {request.user_instruction}"

        def build_cadquery_prompt(self, request) -> str:
            if request.compiler_diagnostics:
                return f"cadquery repair {request.compiler_diagnostics}"
            return f"cadquery source for {request.user_instruction}"

        def cadquery_prompt_template_version(self) -> str:
            return "cadquery-source-v1"

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
                provider_model="fake-cadquery",
            )

        async def generate_cadquery_model(self, request):
            from app.services.ai.provider import ModelGenerationResult

            self.generation_requests.append(request)
            if request.compiler_diagnostics:
                assert request.current_source is not None
                assert ".holes(" in request.current_source
                assert "no attribute 'holes'" in request.compiler_diagnostics
                return ModelGenerationResult(
                    raw_output="""
```python
import cadquery as cq

plate_width = 80
plate_depth = 35
plate_thickness = 6
hole_diameter = 4

def build_model():
    return (
        cq.Workplane("XY")
        .box(plate_width, plate_depth, plate_thickness)
        .faces(">Z")
        .workplane()
        .pushPoints([(0, 0)])
        .hole(hole_diameter)
    )
```
""",
                    provider="ollama",
                    provider_model="fake-cadquery",
                )
            return ModelGenerationResult(
                raw_output="""
```python
import cadquery as cq

plate_width = 80
plate_depth = 35
plate_thickness = 6
hole_diameter = 4

def build_model():
    return cq.Workplane("XY").box(plate_width, plate_depth, plate_thickness).holes(hole_diameter)
```
""",
                provider="ollama",
                provider_model="fake-cadquery",
            )

    compile_calls = []

    def fake_compile_cadquery_probe(
        *,
        source,
        run_dir,
        artifact_dir,
        workspace_dir_name="source-compile-workspace",
        job_id="source-probe",
    ):
        compile_calls.append((workspace_dir_name, job_id, source))
        workspace = artifact_dir / workspace_dir_name / job_id
        workspace.mkdir(parents=True)
        if job_id == "source-probe":
            stderr_path = workspace / "stderr.log"
            stderr_path.write_text("AttributeError: no attribute 'holes'\n", encoding="utf-8")
            return {
                "compile_status": "compile_failed",
                "compiled_stl_path": None,
                "compiled_step_path": None,
                "compile_stdout_path": None,
                "compile_stderr_path": str(stderr_path.resolve().relative_to(run_dir.resolve())),
                "mesh_metadata_path": None,
                "compile_error_message": "AttributeError: no attribute 'holes'",
                "compile_timed_out": False,
                "compile_exit_code": 1,
                "compile_warning_count": 0,
                "compile_warnings": [],
                "stl_size_bytes": 0,
            }
        stl_path = workspace / "model.stl"
        stl_path.write_text("solid fake\nendsolid fake\n", encoding="utf-8")
        metadata_path = workspace / "metadata.json"
        metadata_path.write_text(
            json.dumps(
                {
                    "size_x_mm": 80,
                    "size_y_mm": 35,
                    "size_z_mm": 6,
                    "volume_mm3": 16800,
                    "triangle_count": 12,
                    "connected_components": 1,
                    "is_watertight": True,
                    "is_winding_consistent": True,
                    "center_of_mass": [0, 0, 0],
                }
            ),
            encoding="utf-8",
        )
        return {
            "compile_status": "compile_succeeded",
            "compiled_stl_path": str(stl_path.resolve().relative_to(run_dir.resolve())),
            "compiled_step_path": None,
            "compile_stdout_path": None,
            "compile_stderr_path": None,
            "mesh_metadata_path": str(metadata_path.resolve().relative_to(run_dir.resolve())),
            "compile_error_message": None,
            "compile_timed_out": False,
            "compile_exit_code": 0,
            "compile_warning_count": 0,
            "compile_warnings": [],
            "stl_size_bytes": stl_path.stat().st_size,
        }

    provider = FakeOllamaProvider()
    monkeypatch.setattr(live_benchmarks, "OllamaProvider", lambda: provider)
    monkeypatch.setattr(live_benchmarks, "_compile_cadquery_probe", fake_compile_cadquery_probe)

    result = LiveBenchmarkRunner().run(
        LiveBenchmarkConfig(
            suite_path=FIXTURE_DIR / "core.json",
            output_root=tmp_path,
            benchmark_ids=("simple_mounting_plate",),
            provider="ollama",
            source_probe=True,
            source_probe_repair=True,
            source_language="cadquery",
        )
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    metrics = json.loads(result.metrics_path.read_text(encoding="utf-8"))
    source_probe = manifest["case_runs"][0]["source_probe"]
    repair = source_probe["repair"]

    assert len(provider.generation_requests) == 2
    assert [call[1] for call in compile_calls] == ["source-probe", "source-repair"]
    assert source_probe["status"] == "source_repair_succeeded"
    assert source_probe["compile_status"] == "compile_failed"
    assert repair["enabled"] is True
    assert repair["status"] == "source_repair_succeeded"
    assert repair["prompt_template_version"] == "cadquery-source-v1"
    assert repair["extracted_source_path"].endswith("source-repair-extracted.py")
    assert repair["parameter_analysis_path"] is not None
    assert repair["compile_status"] == "compile_succeeded"
    assert repair["compiled_stl_path"] is not None
    assert metrics["source_probe_status_counts"] == {"source_repair_succeeded": 1}
    assert metrics["source_probe_compile_status_counts"] == {"compile_failed": 1}
    assert metrics["source_probe_repair_enabled"] is True
    assert metrics["source_probe_repair_status_counts"] == {"source_repair_succeeded": 1}
    assert metrics["source_probe_repair_compile_status_counts"] == {"compile_succeeded": 1}
    assert metrics["source_probe_repair_attempt_count"] == 1
    assert metrics["source_probe_repair_compile_success_count"] == 1


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


def test_live_benchmark_source_probe_counts_disconnected_meshes(
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
plate_width = 10;
plate_depth = 10;
plate_thickness = 10;

module main_model() {
  union() {
    cube([plate_width, plate_depth, plate_thickness]);
    translate([30, 0, 0]) cube([plate_width, plate_depth, plate_thickness]);
  }
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
    metadata = json.loads(
        (result.run_dir / source_probe["mesh_metadata_path"]).read_text(encoding="utf-8")
    )

    assert source_probe["compile_status"] == "compile_succeeded"
    assert metadata["connected_components"] == 2
    assert metrics["source_probe_disconnected_mesh_count"] == 1
    assert metrics["source_probe_max_connected_components"] == 2


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


def test_live_benchmark_source_probe_can_repair_failed_compile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.generation import live_benchmarks

    class FakeOllamaProvider:
        def __init__(self) -> None:
            self.generation_requests = []

        def provider_settings(self) -> dict:
            return {"model": "fake-cad", "auth_mode": "local_ollama"}

        def build_requirement_prompt(self, request) -> str:
            return f"requirements for {request.user_instruction}"

        def build_prompt(self, request) -> str:
            if request.compiler_diagnostics:
                return f"repair {request.compiler_diagnostics}"
            return f"source for {request.user_instruction}"

        def requirement_prompt_template_version(self) -> str:
            return "requirements-v1"

        def design_plan_prompt_template_version(self) -> str:
            return "design-plan-v1"

        def revision_plan_prompt_template_version(self) -> str:
            return "revision-planning-v1"

        def prompt_template_version_for(self, request) -> str:
            if request.compiler_diagnostics:
                return "legacy-compile-repair-v1"
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

            self.generation_requests.append(request)
            if request.compiler_diagnostics:
                assert request.current_source is not None
                assert "missing_offset" in request.current_source
                assert "OpenSCAD emitted hard warnings" in request.compiler_diagnostics
                return ModelGenerationResult(
                    raw_output="""
```openscad
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
            return ModelGenerationResult(
                raw_output="""
```openscad
plate_width = 80;
plate_depth = 35;
plate_thickness = 6;
hole_spacing = 55;

module main_model() {
  union() {
    cube([plate_width, plate_depth, plate_thickness]);
    translate([missing_offset, 0, 0]) cube([1, 1, 1]);
  }
}
main_model();
```
""",
                provider="ollama",
                provider_model="fake-cad",
            )

    provider = FakeOllamaProvider()
    monkeypatch.setattr(live_benchmarks, "OllamaProvider", lambda: provider)

    result = LiveBenchmarkRunner().run(
        LiveBenchmarkConfig(
            suite_path=FIXTURE_DIR / "core.json",
            output_root=tmp_path,
            benchmark_ids=("simple_mounting_plate",),
            provider="ollama",
            source_probe=True,
            source_probe_repair=True,
        )
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    metrics = json.loads(result.metrics_path.read_text(encoding="utf-8"))
    source_probe = manifest["case_runs"][0]["source_probe"]
    repair = source_probe["repair"]

    assert len(provider.generation_requests) == 2
    assert source_probe["status"] == "source_repair_succeeded"
    assert source_probe["compile_status"] == "compile_failed"
    assert repair["enabled"] is True
    assert repair["status"] == "source_repair_succeeded"
    assert repair["prompt_template_version"] == "legacy-compile-repair-v1"
    assert repair["raw_output_path"] is not None
    assert repair["extracted_source_path"] is not None
    assert repair["parameter_analysis_path"] is not None
    assert repair["compile_status"] == "compile_succeeded"
    assert repair["compiled_stl_path"] is not None
    assert repair["mesh_metadata_path"] is not None
    assert metrics["source_probe_status_counts"] == {"source_repair_succeeded": 1}
    assert metrics["source_probe_compile_status_counts"] == {"compile_failed": 1}
    assert metrics["source_probe_repair_enabled"] is True
    assert metrics["source_probe_repair_status_counts"] == {"source_repair_succeeded": 1}
    assert metrics["source_probe_repair_compile_status_counts"] == {"compile_succeeded": 1}
    assert metrics["source_probe_repair_attempt_count"] == 1
    assert metrics["source_probe_repair_compile_success_count"] == 1


def test_live_benchmark_source_probe_can_repair_disconnected_mesh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.generation import live_benchmarks

    class FakeOllamaProvider:
        def __init__(self) -> None:
            self.generation_requests = []

        def provider_settings(self) -> dict:
            return {"model": "fake-cad", "auth_mode": "local_ollama"}

        def build_requirement_prompt(self, request) -> str:
            return f"requirements for {request.user_instruction}"

        def build_source_brief_prompt(self, request) -> str:
            return f"brief for {request.user_instruction}"

        def build_prompt(self, request) -> str:
            if request.compiler_diagnostics:
                return f"repair {request.compiler_diagnostics}"
            return f"source for {request.user_instruction}"

        def requirement_prompt_template_version(self) -> str:
            return "requirements-v1"

        def source_brief_prompt_template_version(self) -> str:
            return "source-brief-v1"

        def design_plan_prompt_template_version(self) -> str:
            return "design-plan-v1"

        def revision_plan_prompt_template_version(self) -> str:
            return "revision-planning-v1"

        def prompt_template_version_for(self, request) -> str:
            if request.compiler_diagnostics:
                return "legacy-compile-repair-v1"
            return "legacy-initial-v1"

        async def extract_requirements(self, request):
            from app.services.ai.provider import RequirementExtractionResult

            return RequirementExtractionResult(
                raw_output="{}",
                provider="ollama",
                provider_model="fake-cad",
            )

        async def create_source_brief(self, request):
            from app.services.ai.provider import SourceBriefResult

            return SourceBriefResult(
                raw_output=json.dumps(
                    {
                        "schema_version": "source-brief-v1",
                        "intent_understanding": {
                            "object_type": "mounting plate",
                            "functional_goal": "mount parts",
                            "style_goal": "none",
                        },
                        "planned_outputs": [
                            {
                                "id": "main_plate",
                                "expected_connected_body_count": 1,
                                "must_be_connected": True,
                                "approx_size_mm": [80, 35, 6],
                            }
                        ],
                        "functional_features": [],
                        "style_features": [],
                        "hard_requirements": ["one connected printable body"],
                        "open_questions": [],
                    }
                ),
                provider="ollama",
                provider_model="fake-cad",
            )

        async def generate_model(self, request):
            from app.services.ai.provider import ModelGenerationResult

            self.generation_requests.append(request)
            if request.compiler_diagnostics:
                assert request.current_source is not None
                assert "translate([100, 0, 0])" in request.current_source
                assert "connected components" in request.compiler_diagnostics
                assert "expected connected body count: 1" in request.compiler_diagnostics
                return ModelGenerationResult(
                    raw_output="""
```openscad
plate_width = 80;
plate_depth = 35;
plate_thickness = 6;
hole_spacing = 55;

module main_model() {
  union() {
    cube([plate_width, plate_depth, plate_thickness]);
    translate([plate_width - 0.5, 0, 0])
      cube([10, plate_depth, plate_thickness]);
  }
}
main_model();
```
""",
                    provider="ollama",
                    provider_model="fake-cad",
                )
            return ModelGenerationResult(
                raw_output="""
```openscad
plate_width = 80;
plate_depth = 35;
plate_thickness = 6;
hole_spacing = 55;

module main_model() {
  union() {
    cube([plate_width, plate_depth, plate_thickness]);
    translate([100, 0, 0]) cube([plate_width, plate_depth, plate_thickness]);
  }
}
main_model();
```
""",
                provider="ollama",
                provider_model="fake-cad",
            )

    provider = FakeOllamaProvider()
    monkeypatch.setattr(live_benchmarks, "OllamaProvider", lambda: provider)

    result = LiveBenchmarkRunner().run(
        LiveBenchmarkConfig(
            suite_path=FIXTURE_DIR / "core.json",
            output_root=tmp_path,
            benchmark_ids=("simple_mounting_plate",),
            provider="ollama",
            source_probe=True,
            source_probe_repair=True,
            source_brief=True,
        )
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    metrics = json.loads(result.metrics_path.read_text(encoding="utf-8"))
    source_probe = manifest["case_runs"][0]["source_probe"]
    repair = source_probe["repair"]

    assert len(provider.generation_requests) == 2
    assert source_probe["status"] == "source_mesh_repair_succeeded"
    assert source_probe["compile_status"] == "compile_succeeded"
    assert repair["enabled"] is True
    assert repair["status"] == "source_repair_succeeded"
    assert repair["compile_status"] == "compile_succeeded"
    assert repair["mesh_metadata_path"] is not None
    assert metrics["source_probe_status_counts"] == {"source_mesh_repair_succeeded": 1}
    assert metrics["source_probe_compile_status_counts"] == {"compile_succeeded": 1}
    assert metrics["source_probe_repair_status_counts"] == {"source_repair_succeeded": 1}
    assert metrics["source_probe_repair_attempt_count"] == 1
    assert metrics["source_probe_repair_compile_success_count"] == 1


def test_live_benchmark_source_brief_feeds_source_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.generation import live_benchmarks

    class FakeOllamaProvider:
        def __init__(self) -> None:
            self.source_prompt = ""

        def provider_settings(self) -> dict:
            return {"model": "fake-cad", "auth_mode": "local_ollama"}

        def build_requirement_prompt(self, request) -> str:
            return f"requirements for {request.user_instruction}"

        def build_source_brief_prompt(self, request) -> str:
            return f"brief for {request.user_instruction}"

        def build_prompt(self, request) -> str:
            self.source_prompt = request.user_instruction
            return f"source for {request.user_instruction}"

        def requirement_prompt_template_version(self) -> str:
            return "requirements-v1"

        def source_brief_prompt_template_version(self) -> str:
            return "source-brief-v1"

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

        async def create_source_brief(self, request):
            from app.services.ai.provider import SourceBriefResult

            return SourceBriefResult(
                raw_output=json.dumps(
                    {
                        "schema_version": "source-brief-v1",
                        "intent_understanding": {
                            "object_type": "shelf bracket",
                            "functional_goal": "support shelf",
                            "style_goal": "fish underside",
                        },
                        "planned_outputs": [
                            {
                                "id": "main_bracket",
                                "expected_connected_body_count": 1,
                                "must_be_connected": True,
                                "approx_size_mm": {"x": 120, "y": 30, "z": 90},
                            }
                        ],
                        "functional_features": [{"id": "mounting_holes", "count": 4}],
                        "style_features": [
                            {
                                "id": "fish_underside",
                                "attachment_rule": "fused into main_bracket",
                            }
                        ],
                        "hard_requirements": ["one connected printable body"],
                        "open_questions": [],
                    }
                ),
                provider="ollama",
                provider_model="fake-cad",
            )

        async def generate_model(self, request):
            from app.services.ai.provider import ModelGenerationResult

            assert "Structured source brief" in request.user_instruction
            assert "expected_connected_body_count" in request.user_instruction
            assert "fish_underside" in request.user_instruction
            return ModelGenerationResult(
                raw_output="""
```openscad
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

    provider = FakeOllamaProvider()
    monkeypatch.setattr(live_benchmarks, "OllamaProvider", lambda: provider)

    result = LiveBenchmarkRunner().run(
        LiveBenchmarkConfig(
            suite_path=FIXTURE_DIR / "core.json",
            output_root=tmp_path,
            benchmark_ids=("creative_fish_shelf_bracket",),
            provider="ollama",
            source_probe=True,
            source_brief=True,
        )
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    metrics = json.loads(result.metrics_path.read_text(encoding="utf-8"))
    source_probe = manifest["case_runs"][0]["source_probe"]
    brief = source_probe["brief"]

    assert brief["status"] == "source_brief_parsed"
    assert brief["raw_output_path"] is not None
    assert brief["parsed_brief_path"] is not None
    assert source_probe["status"] == "source_parameters_analyzed"
    assert source_probe["compile_status"] == "compile_succeeded"
    assert metrics["source_brief_status_counts"] == {"source_brief_parsed": 1}


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
