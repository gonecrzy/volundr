import json
from pathlib import Path

from app.services.ai.provider import DesignPlanResult, ModelGenerationResult, SourceBriefResult
from app.services.generation.benchmarks import (
    phase_validation_benchmark_ids,
    load_benchmark_suite,
    run_deterministic_contract_check,
    staged_product_gate_benchmark_ids,
)
from app.services.generation.live_benchmarks import (
    LiveBenchmarkConfig,
    LiveBenchmarkRunner,
    _compile_source_probe_for_language,
    _disconnected_mesh_diagnostics,
    _requirement_request_for,
    _source_explicit_requirement_analysis,
    _source_parameter_analysis,
    _source_repair_request_for,
    _source_request_for,
)
from app.services.generation.live_benchmarks import _source_compile_repair_diagnostics


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "generation_benchmarks"


class BriefTimeoutSourceProvider:
    ruleset_version = "test-ruleset"

    def cadquery_prompt_template_version(self) -> str:
        return "cadquery-generation-v1"

    def source_brief_prompt_template_version(self) -> str:
        return "source-brief-v1"

    def build_cadquery_prompt(self, request) -> str:
        return request.user_instruction

    async def create_source_brief(self, request):
        raise TimeoutError("brief timed out")

    async def generate_cadquery_model(self, request):
        return ModelGenerationResult(
            raw_output="""
```python
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product

PARAMETERS = [
    ParameterSpec(id="plate_width", label="Plate Width", type="float", default=80.0, unit="mm"),
    ParameterSpec(id="plate_depth", label="Plate Depth", type="float", default=35.0, unit="mm"),
    ParameterSpec(id="plate_thickness", label="Plate Thickness", type="float", default=6.0, unit="mm"),
    ParameterSpec(id="hole_diameter", label="Hole Diameter", type="float", default=4.5, unit="mm"),
    ParameterSpec(id="hole_spacing", label="Hole Spacing", type="float", default=55.0, unit="mm"),
]

def build(params):
    body = cq.Workplane("XY").box(params["plate_width"], params["plate_depth"], params["plate_thickness"])
    return Product(
        parameters=PARAMETERS,
        outputs=[
            PrintableOutput(
                output_id="body",
                label="Body",
                model=body,
                component_id="body",
                expected_solid_count=1,
                allow_disconnected_solids=False,
            )
        ],
    )
```
""",
            provider="fake",
            provider_model="fake-source",
        )


class BriefGuidedSourceTimeoutProvider(BriefTimeoutSourceProvider):
    def __init__(self) -> None:
        self.source_calls = 0

    async def create_source_brief(self, request):
        return SourceBriefResult(
            raw_output='{"planned_outputs": [{"output_id": "body", "must_be_connected": true}]}',
            provider="fake",
            provider_model="fake-brief",
        )

    async def generate_cadquery_model(self, request):
        self.source_calls += 1
        if "Structured source brief:" in request.user_instruction:
            raise TimeoutError("brief-guided source timed out")
        return await super().generate_cadquery_model(request)


class DesignPlanProbeProvider:
    ruleset_version = "test-ruleset"

    def design_plan_prompt_template_version(self) -> str:
        return "design-plan-v1"

    def build_design_plan_prompt(self, request) -> str:
        return request.user_instruction

    async def create_design_plan(self, request):
        return DesignPlanResult(
            raw_output="""
{
  "schema_version": "design-plan-v1",
  "outcome": "plan_ready",
  "design_level": "product",
  "components": [
    {"id": "tray_body"},
    {"id": "divider_grid"},
    {"id": "label_tabs"}
  ],
  "features": [
    {"id": "repeated_cells"},
    {"id": "label_tabs"},
    {"id": "rounded_edges"}
  ],
  "dependency_edges": [
    {"from": "row_count", "to": "overall_depth"},
    {"from": "column_count", "to": "overall_width"},
    {"from": "cell_width", "to": "divider_positions"}
  ],
  "presets": [
    {"id": "3x4"},
    {"id": "4x5"}
  ],
  "printable_outputs": [
    {"output_id": "organizer_body"}
  ]
}
""",
            provider="fake",
            provider_model="fake-design-plan",
        )


def test_core_generation_benchmark_fixture_loads_required_cases() -> None:
    suite = load_benchmark_suite(FIXTURE_DIR / "core.json")

    assert suite.name == "core"
    assert len(suite.benchmarks) == 9
    assert {benchmark.id for benchmark in suite.benchmarks} == {
        "simple_mounting_plate",
        "cylindrical_holder",
        "spacer_bushing",
        "critical_dimension_revision",
        "vague_clarification",
        "conflicting_dimensions",
        "creative_fish_shelf_bracket",
        "honeycomb_angle_bracket",
        "threaded_control_knob",
    }


def test_full_generation_benchmark_fixture_covers_all_categories() -> None:
    suite = load_benchmark_suite(FIXTURE_DIR / "full.json")

    assert suite.name == "full"
    assert len(suite.benchmarks) >= 15
    assert all(benchmark.protected_design_invariants for benchmark in suite.benchmarks)
    by_id = {benchmark.id: benchmark for benchmark in suite.benchmarks}
    assert "accidental_multiple_solids" in by_id
    assert "configuration_exceeds_build_volume" in by_id
    assert by_id["accidental_multiple_solids"].compile_expectation == (
        "source_may_compile_but_candidate_blocks"
    )
    assert by_id["configuration_exceeds_build_volume"].expected_configuration[
        "expected_validation_state"
    ] == "configuration_blocked_build_volume"
    organizer = by_id["parametric_configurable_organizer"]
    assert organizer.expected_explicit_requirements["row_count"]["value"] == 3
    assert organizer.expected_explicit_requirements["column_count"]["value"] == 4
    assert organizer.expected_explicit_requirements["cell_width"] == {"value": 35.0, "unit": "mm"}
    assert organizer.expected_explicit_requirements["cell_depth"] == {"value": 25.0, "unit": "mm"}
    assert organizer.expected_explicit_requirements["wall_thickness"] == {
        "value": 2.0,
        "unit": "mm",
    }


def test_requirement_request_includes_benchmark_explicit_requirements() -> None:
    suite = load_benchmark_suite(FIXTURE_DIR / "full.json")
    benchmark = {
        entry.id: entry for entry in suite.benchmarks
    }["parametric_configurable_organizer"]

    request = _requirement_request_for(benchmark)

    assert request.defaults["explicit_requirements"]["row_count"]["value"] == 3
    assert request.defaults["explicit_requirements"]["column_count"]["value"] == 4
    assert request.defaults["explicit_requirements"]["cell_width"]["value"] == 35.0
    assert "rows=3" in request.user_instruction
    assert "cell=35x25 mm" in request.user_instruction


def test_staged_product_gate_selects_required_transition_cases() -> None:
    suite = load_benchmark_suite(FIXTURE_DIR / "full.json")
    by_id = {benchmark.id: benchmark for benchmark in suite.benchmarks}

    assert staged_product_gate_benchmark_ids() == (
        "simple_mounting_plate",
        "parametric_adapter",
        "parametric_electronics_enclosure",
        "parametric_repeated_slot_rack",
        "parametric_multi_part_hinged_box",
        "parametric_case_carrier",
        "parametric_configurable_organizer",
        "component_revision_lid_only",
        "vague_clarification",
        "box_with_lid",
        "accidental_multiple_solids",
        "configuration_exceeds_build_volume",
    )
    assert set(staged_product_gate_benchmark_ids()) <= set(by_id)
    assert by_id["component_revision_lid_only"].expected_component_revision["protected_outputs"]
    assert by_id["accidental_multiple_solids"].compile_expectation == (
        "source_may_compile_but_candidate_blocks"
    )
    assert by_id["configuration_exceeds_build_volume"].expected_configuration[
        "expected_blocking_rule"
    ] == "profile.build_volume"


def test_deterministic_benchmark_contract_check_passes_fixtures() -> None:
    suite = load_benchmark_suite(FIXTURE_DIR / "core.json")
    results = run_deterministic_contract_check(suite)

    assert len(results) == len(suite.benchmarks)
    assert all(result.passed for result in results)
    assert {result.failure_class for result in results} == {"none"}


def test_source_parameter_analysis_reads_cadquery_v1_parameter_specs() -> None:
    suite = load_benchmark_suite(FIXTURE_DIR / "core.json")
    benchmark = {entry.id: entry for entry in suite.benchmarks}["simple_mounting_plate"]
    source = """
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product

PARAMETERS = [
    ParameterSpec(id="plate_width", label="Plate Width", type="float", default=80.0, unit="mm"),
    ParameterSpec(id="plate_depth", label="Plate Depth", type="float", default=35.0, unit="mm"),
    ParameterSpec(id="plate_thickness", label="Plate Thickness", type="float", default=6.0, unit="mm"),
    ParameterSpec(id="hole_diameter", label="Hole Diameter", type="float", default=4.5, unit="mm"),
    ParameterSpec(id="hole_spacing", label="Hole Spacing", type="float", default=55.0, unit="mm"),
]

def build(params):
    body = cq.Workplane("XY").box(params["plate_width"], params["plate_depth"], params["plate_thickness"])
    return Product(
        parameters=PARAMETERS,
        outputs=[
            PrintableOutput(
                output_id="body",
                label="Body",
                model=body,
                component_id="body",
                expected_solid_count=1,
                allow_disconnected_solids=False,
            )
        ],
    )
"""

    analysis = _source_parameter_analysis(
        benchmark=benchmark,
        extracted_source=source,
        extraction_error=None,
        source_language="cadquery",
    )

    assert analysis["parameter_count"] == 5
    assert analysis["matched_expected_parameters"] == benchmark.expected_parameters
    assert analysis["missing_expected_parameters"] == []
    assert analysis["expected_parameter_coverage"] == 1.0
    assert analysis["parameter_types"]["plate_width"] == "float"


def test_source_explicit_requirement_analysis_detects_organizer_default_drift() -> None:
    suite = load_benchmark_suite(FIXTURE_DIR / "full.json")
    benchmark = {
        entry.id: entry for entry in suite.benchmarks
    }["parametric_configurable_organizer"]
    source = """
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product

PARAMETERS = [
    ParameterSpec(id="row_count", label="Rows", type="int", default=2),
    ParameterSpec(id="column_count", label="Columns", type="int", default=3),
    ParameterSpec(id="cell_width", label="Cell Width", type="float", default=50.0, unit="mm"),
    ParameterSpec(id="cell_depth", label="Cell Depth", type="float", default=50.0, unit="mm"),
    ParameterSpec(id="wall_thickness", label="Wall Thickness", type="float", default=2.0, unit="mm"),
]

def build(params):
    body = cq.Workplane("XY").box(10, 10, 10)
    return Product(
        parameters=PARAMETERS,
        outputs=[
            PrintableOutput(
                output_id="organizer_body",
                label="Organizer",
                model=body,
                component_id="organizer",
                expected_solid_count=1,
                allow_disconnected_solids=False,
            )
        ],
    )
"""

    analysis = _source_explicit_requirement_analysis(
        benchmark=benchmark,
        extracted_source=source,
        extraction_error=None,
    )

    assert analysis["source_parameter_trace_status"] == "blocked"
    assert {
        finding["rule_id"] for finding in analysis["findings"]
    } == {"source_parameter.explicit_value_mismatch"}
    assert analysis["matched_explicit_requirements"] == ["wall_thickness"]
    assert set(analysis["mismatched_explicit_requirements"]) == {
        "row_count",
        "column_count",
        "cell_width",
        "cell_depth",
    }


def test_source_probe_blocks_compile_on_explicit_requirement_drift(tmp_path: Path) -> None:
    suite = load_benchmark_suite(FIXTURE_DIR / "full.json")
    benchmark = {
        entry.id: entry for entry in suite.benchmarks
    }["parametric_configurable_organizer"]
    run_dir = tmp_path / "run"
    artifact_dir = run_dir / "artifacts" / benchmark.id / "run-001"
    artifact_dir.mkdir(parents=True)

    class DriftProvider(BriefTimeoutSourceProvider):
        async def generate_cadquery_model(self, request):
            return ModelGenerationResult(
                raw_output="""
```python
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product

PARAMETERS = [
    ParameterSpec(id="row_count", label="Rows", type="int", default=2),
    ParameterSpec(id="column_count", label="Columns", type="int", default=3),
    ParameterSpec(id="cell_width", label="Cell Width", type="float", default=50.0, unit="mm"),
    ParameterSpec(id="cell_depth", label="Cell Depth", type="float", default=50.0, unit="mm"),
    ParameterSpec(id="wall_thickness", label="Wall Thickness", type="float", default=2.0, unit="mm"),
]

def build(params):
    body = cq.Workplane("XY").box(10, 10, 10)
    return Product(
        parameters=PARAMETERS,
        outputs=[
            PrintableOutput(
                output_id="organizer_body",
                label="Organizer",
                model=body,
                component_id="organizer",
                expected_solid_count=1,
                allow_disconnected_solids=False,
            )
        ],
    )
```
""",
                provider="fake",
                provider_model="fake-source",
            )

    probe = LiveBenchmarkRunner()._run_source_probe(
        benchmark=benchmark,
        provider=DriftProvider(),
        provider_mode="gemini_api",
        run_dir=run_dir,
        artifact_dir=artifact_dir,
        source_prompt="source prompt",
        source_probe_repair=False,
        source_brief_prompt=None,
        source_language="cadquery",
    )

    assert probe["status"] == "source_explicit_requirement_blocked"
    assert probe["compile_status"] == "not_run"
    analysis = json.loads((run_dir / probe["parameter_analysis_path"]).read_text(encoding="utf-8"))
    assert analysis["source_parameter_trace_status"] == "blocked"


def test_source_probe_continues_without_source_brief_after_brief_timeout(tmp_path: Path) -> None:
    suite = load_benchmark_suite(FIXTURE_DIR / "core.json")
    benchmark = {entry.id: entry for entry in suite.benchmarks}["simple_mounting_plate"]
    run_dir = tmp_path / "run"
    artifact_dir = run_dir / "artifacts" / benchmark.id / "run-001"
    artifact_dir.mkdir(parents=True)

    probe = LiveBenchmarkRunner()._run_source_probe(
        benchmark=benchmark,
        provider=BriefTimeoutSourceProvider(),
        provider_mode="gemini_api",
        run_dir=run_dir,
        artifact_dir=artifact_dir,
        source_prompt="source prompt",
        source_probe_repair=False,
        source_brief_prompt="brief prompt",
        source_language="cadquery",
    )

    assert probe["brief"]["status"] == "source_brief_provider_failed"
    assert probe["status"] == "source_parameters_analyzed"
    assert probe["compile_status"] == "compile_succeeded"
    assert probe["extracted_source_path"] is not None


def test_source_probe_retries_without_source_brief_after_brief_guided_timeout(
    tmp_path: Path,
) -> None:
    suite = load_benchmark_suite(FIXTURE_DIR / "core.json")
    benchmark = {entry.id: entry for entry in suite.benchmarks}["simple_mounting_plate"]
    run_dir = tmp_path / "run"
    artifact_dir = run_dir / "artifacts" / benchmark.id / "run-001"
    artifact_dir.mkdir(parents=True)
    provider = BriefGuidedSourceTimeoutProvider()

    probe = LiveBenchmarkRunner()._run_source_probe(
        benchmark=benchmark,
        provider=provider,
        provider_mode="gemini_api",
        run_dir=run_dir,
        artifact_dir=artifact_dir,
        source_prompt="source prompt",
        source_probe_repair=False,
        source_brief_prompt="brief prompt",
        source_language="cadquery",
    )

    assert provider.source_calls == 2
    assert probe["brief"]["status"] == "source_brief_parsed"
    assert probe["brief_guided_source_error_path"] is not None
    assert probe["status"] == "source_parameters_analyzed"
    assert probe["compile_status"] == "compile_succeeded"


def test_design_plan_probe_scores_expected_fixture_plan(tmp_path: Path) -> None:
    suite = load_benchmark_suite(FIXTURE_DIR / "full.json")
    benchmark = {
        entry.id: entry for entry in suite.benchmarks
    }["parametric_configurable_organizer"]
    run_dir = tmp_path / "run"
    artifact_dir = run_dir / "artifacts" / benchmark.id / "run-001"
    artifact_dir.mkdir(parents=True)

    probe = LiveBenchmarkRunner()._run_design_plan_probe(
        benchmark=benchmark,
        provider=DesignPlanProbeProvider(),
        provider_mode="gemini_api",
        run_dir=run_dir,
        artifact_dir=artifact_dir,
        design_specification={"object_type": "drawer_organizer", "units": "mm"},
        design_plan_prompt="design plan prompt",
    )

    assert probe["status"] == "design_plan_analyzed"
    assert probe["raw_output_path"] == (
        "artifacts/parametric_configurable_organizer/run-001/design-plan-raw-output.txt"
    )
    assert probe["analysis_path"] == (
        "artifacts/parametric_configurable_organizer/run-001/design-plan-analysis.json"
    )
    assert probe["expected_component_coverage"] == 1.0
    assert probe["expected_feature_coverage"] == 1.0
    assert probe["expected_output_coverage"] == 1.0
    assert probe["expected_dependency_coverage"] == 1.0


def test_live_benchmark_run_writes_design_plan_probe_metrics(tmp_path: Path) -> None:
    result = LiveBenchmarkRunner().run(
        LiveBenchmarkConfig(
            suite_path=FIXTURE_DIR / "full.json",
            output_root=tmp_path,
            run_label="design-plan-dry-run",
            benchmark_ids=("parametric_configurable_organizer",),
            max_runs=1,
            provider="dry-run",
            design_plan_probe=True,
        )
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    metrics = json.loads(result.metrics_path.read_text(encoding="utf-8"))
    case_run = manifest["case_runs"][0]

    assert manifest["config"]["design_plan_probe"] is True
    assert case_run["design_plan_probe"]["enabled"] is True
    assert case_run["design_plan_probe"]["status"] == "not_run"
    assert case_run["design_plan_probe"]["prompt_path"] == (
        "artifacts/parametric_configurable_organizer/run-001/design-plan-prompt.txt"
    )
    assert metrics["design_plan_probe_enabled"] is True
    assert metrics["design_plan_probe_status_counts"] == {"not_run": 1}


def test_live_benchmark_run_writes_configuration_probe_metrics(tmp_path: Path) -> None:
    result = LiveBenchmarkRunner().run(
        LiveBenchmarkConfig(
            suite_path=FIXTURE_DIR / "full.json",
            output_root=tmp_path,
            run_label="configuration-dry-run",
            benchmark_ids=("configuration_exceeds_build_volume",),
            max_runs=1,
            provider="dry-run",
            source_probe=True,
            configuration_probe=True,
        )
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    metrics = json.loads(result.metrics_path.read_text(encoding="utf-8"))
    case_run = manifest["case_runs"][0]

    assert manifest["config"]["configuration_probe"] is True
    assert case_run["configuration_probe"]["enabled"] is True
    assert case_run["configuration_probe"]["status"] == "source_unavailable"
    assert metrics["configuration_probe_enabled"] is True
    assert metrics["configuration_probe_status_counts"] == {"source_unavailable": 1}


def test_configuration_probe_blocks_build_volume_override(tmp_path: Path) -> None:
    suite = load_benchmark_suite(FIXTURE_DIR / "full.json")
    benchmark = {
        entry.id: entry for entry in suite.benchmarks
    }["configuration_exceeds_build_volume"]
    run_dir = tmp_path / "run"
    artifact_dir = run_dir / "artifacts" / benchmark.id / "run-001"
    artifact_dir.mkdir(parents=True)
    source = """
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product

PARAMETERS = [
    ParameterSpec(id="rail_length", label="Rail Length", type="float", default=180.0, unit="mm"),
    ParameterSpec(id="hook_count", label="Hook Count", type="int", default=6),
    ParameterSpec(id="hook_spacing", label="Hook Spacing", type="float", default=28.0, unit="mm"),
    ParameterSpec(id="wall_thickness", label="Wall Thickness", type="float", default=5.0, unit="mm"),
]

def build(params):
    body = cq.Workplane("XY").box(params["rail_length"], 30.0, 12.0, centered=(True, True, False))
    return Product(
        parameters=PARAMETERS,
        outputs=[
            PrintableOutput(
                output_id="wall_rail",
                label="Wall Rail",
                model=body,
                component_id="rail_body",
                expected_solid_count=1,
                allow_disconnected_solids=False,
            )
        ],
    )
"""

    probe = LiveBenchmarkRunner()._run_configuration_probe(
        benchmark=benchmark,
        run_dir=run_dir,
        artifact_dir=artifact_dir,
        source=source,
        source_language="cadquery",
    )

    assert probe["enabled"] is True
    assert probe["status"] == "configuration_blocked_build_volume"
    assert probe["compile_status"] == "compile_succeeded"
    assert probe["expected_blocking_rule_observed"] is True
    assert probe["blocking_rule_ids"] == ["profile.build_volume"]
    assert probe["parameter_values"] == {"rail_length": 360}


def test_source_request_includes_configuration_probe_targets() -> None:
    suite = load_benchmark_suite(FIXTURE_DIR / "full.json")
    benchmark = {
        entry.id: entry for entry in suite.benchmarks
    }["configuration_exceeds_build_volume"]

    request = _source_request_for(benchmark, source_language="cadquery")

    assert "Configuration-probe override targets:" in request.user_instruction
    assert '"rail_length": 360' in request.user_instruction
    assert "profile.build_volume" in request.user_instruction
    assert "ParameterSpec range must allow each override value" in request.user_instruction


def test_source_request_marks_accidental_multiple_solids_as_negative_control() -> None:
    suite = load_benchmark_suite(FIXTURE_DIR / "full.json")
    benchmark = {
        entry.id: entry for entry in suite.benchmarks
    }["accidental_multiple_solids"]

    request = _source_request_for(benchmark, source_language="cadquery")

    assert "Negative-control topology target:" in request.user_instruction
    assert "expected_solid_count=1" in request.user_instruction
    assert "detected_solid_count greater than one" in request.user_instruction


def test_source_probe_reports_solid_count_rejection_metadata(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    artifact_dir = run_dir / "artifacts" / "accidental_multiple_solids" / "run-001"
    artifact_dir.mkdir(parents=True)
    source = """
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product

PARAMETERS = [
    ParameterSpec(id="cube_size", label="Cube Size", type="float", default=10.0, unit="mm"),
]

def build(params):
    first = cq.Workplane("XY").box(params["cube_size"], params["cube_size"], params["cube_size"])
    second = cq.Workplane("XY").box(params["cube_size"], params["cube_size"], params["cube_size"]).translate((30, 0, 0))
    return Product(
        outputs=[
            PrintableOutput(
                output_id="body",
                label="Body",
                model=first.union(second),
                component_id="body",
                expected_solid_count=1,
                allow_disconnected_solids=False,
            )
        ],
        parameters=PARAMETERS,
    )
"""

    result = _compile_source_probe_for_language(
        source=source,
        source_language="cadquery",
        run_dir=run_dir,
        artifact_dir=artifact_dir,
    )

    assert result["compile_status"] == "compile_failed"
    assert result["solid_count_rejection_count"] == 1
    assert result["topology_rejection_count"] == 1
    assert result["output_topology_metadata"][0]["detected_solid_count"] == 2
    assert result["output_topology_metadata"][0]["expected_solid_count"] == 1


def test_source_compile_repair_diagnostics_expand_invalid_topology() -> None:
    diagnostics = _source_compile_repair_diagnostics(
        compile_error_message="output shape is invalid",
        stderr_text=None,
        source_language="cadquery",
    )

    assert "topology validation failed" in diagnostics
    assert "overlap ribs, rails, handles, tabs, hinge barrels" in diagnostics
    assert "simple overlapping boxes" in diagnostics
    assert "two overlapping rectangular flanges" in diagnostics
    assert "two overlapping posts and an overlapping crossbar" in diagnostics
    assert "posts must overlap side walls or the back wall" in diagnostics
    assert "x = +/- (outer_width / 2 - wall_thickness / 2)" in diagnostics
    assert "omit the handle" in diagnostics


def test_source_repair_prompt_uses_cadquery_v1_entrypoint() -> None:
    suite = load_benchmark_suite(FIXTURE_DIR / "core.json")
    benchmark = {entry.id: entry for entry in suite.benchmarks}["simple_mounting_plate"]

    request = _source_repair_request_for(
        benchmark=benchmark,
        current_source="import cadquery as cq\n\ndef build(params):\n    raise RuntimeError()\n",
        compiler_diagnostics="runtime failed",
        source_language="cadquery",
    )

    assert "build(params)" in request.user_instruction
    assert "build_model()" not in request.user_instruction


def test_disconnected_mesh_diagnostics_use_cadquery_v1_entrypoint() -> None:
    diagnostics = _disconnected_mesh_diagnostics(
        expected_connected_body_count=1,
        connected_components=2,
        source_language="cadquery",
    )

    assert "Rewrite build(params)" in diagnostics
    assert "build_model()" not in diagnostics


def test_phase_validation_scenarios_cover_function_style_and_library_progression() -> None:
    core = load_benchmark_suite(FIXTURE_DIR / "core.json")
    full = load_benchmark_suite(FIXTURE_DIR / "full.json")
    core_by_id = {benchmark.id: benchmark for benchmark in core.benchmarks}
    full_by_id = {benchmark.id: benchmark for benchmark in full.benchmarks}

    assert phase_validation_benchmark_ids() == (
        "creative_fish_shelf_bracket",
        "honeycomb_angle_bracket",
        "threaded_control_knob",
    )
    assert set(phase_validation_benchmark_ids()) <= set(core_by_id)
    assert set(phase_validation_benchmark_ids()) <= set(full_by_id)

    fish = core_by_id["creative_fish_shelf_bracket"]
    assert fish.expected_clarification == "none"
    assert {"wall_mounting_holes", "shelf_mounting_holes", "fish_silhouette"} <= set(fish.expected_modules)
    assert "visible underside fish silhouette" in fish.protected_design_invariants
    assert "plain L bracket with no fish-like underside" in fish.unacceptable_outcomes

    honeycomb = core_by_id["honeycomb_angle_bracket"]
    assert "hexagonal lightening pattern" in honeycomb.protected_design_invariants
    assert "honeycomb represented as surface decoration only" in honeycomb.unacceptable_outcomes
    assert any(invariant["type"] == "hole_group" for invariant in honeycomb.expected_geometric_invariants)

    knob = core_by_id["threaded_control_knob"]
    assert "BOSL2/threading allowed when curated library support is enabled" in knob.allowed_assumptions
    assert "hand-rolled fake threads accepted as functional threads" in knob.unacceptable_outcomes
    assert "thread_spec" in knob.expected_parameters


def test_requirement_stage_benchmarks_cover_ready_clarification_and_conflict_cases() -> None:
    core = load_benchmark_suite(FIXTURE_DIR / "core.json")
    full = load_benchmark_suite(FIXTURE_DIR / "full.json")
    core_by_id = {benchmark.id: benchmark for benchmark in core.benchmarks}
    full_by_id = {benchmark.id: benchmark for benchmark in full.benchmarks}

    assert core_by_id["simple_mounting_plate"].expected_clarification == "none"
    assert core_by_id["cylindrical_holder"].expected_clarification == "none"
    assert core_by_id["vague_clarification"].expected_clarification == "required"
    assert core_by_id["conflicting_dimensions"].expected_clarification == "required"

    for benchmark_id in (
        "vague_clarification",
        "conflicting_dimensions",
        "hose_adapter",
        "wall_tool_holder",
        "inaccessible_internal_cavity",
    ):
        benchmark = full_by_id[benchmark_id]
        assert benchmark.expected_clarification in {"required", "optional"}
        assert benchmark.compile_expectation in {
            "no_cadquery_generated",
            "no_cadquery_until_fasteners_clarified",
            "no_cadquery_until_vent_or_split_decision",
            "success_without_repair",
            "success_after_clarification_or_defaults",
        }


def test_geometric_invariant_benchmarks_cover_supported_measurements() -> None:
    core = load_benchmark_suite(FIXTURE_DIR / "core.json")
    full = load_benchmark_suite(FIXTURE_DIR / "full.json")
    by_id = {benchmark.id: benchmark for benchmark in [*core.benchmarks, *full.benchmarks]}

    for benchmark_id in (
        "simple_mounting_plate",
        "cylindrical_holder",
        "spacer_bushing",
        "critical_dimension_revision",
        "countersunk_holes",
    ):
        assert by_id[benchmark_id].expected_geometric_invariants

    invariant_types = {
        invariant["type"]
        for benchmark in by_id.values()
        for invariant in benchmark.expected_geometric_invariants
    }
    assert {"bounds", "build_plate", "hole", "hole_group", "wall_thickness"} <= invariant_types


def test_parametric_product_benchmarks_cover_generic_plan_shapes() -> None:
    suite = load_benchmark_suite(FIXTURE_DIR / "full.json")
    by_id = {benchmark.id: benchmark for benchmark in suite.benchmarks}

    for benchmark_id in (
        "parametric_simple_bracket",
        "parametric_electronics_enclosure",
        "parametric_configurable_organizer",
        "parametric_adapter",
        "parametric_case_carrier",
        "parametric_multi_part_hinged_box",
        "parametric_repeated_slot_rack",
    ):
        plan = by_id[benchmark_id].expected_design_plan
        assert plan["design_level"] in {"single_part", "product", "assembly"}
        assert plan["components"]
        assert plan["features"]
        assert plan["printable_outputs"]
        assert plan["dependency_edges"]


def test_revision_benchmarks_cover_structured_revision_plans() -> None:
    suite = load_benchmark_suite(FIXTURE_DIR / "full.json")
    by_id = {benchmark.id: benchmark for benchmark in suite.benchmarks}

    for benchmark_id in (
        "critical_dimension_revision",
        "new_feature_revision",
        "parametric_electronics_enclosure",
        "parametric_case_carrier",
        "parametric_repeated_slot_rack",
    ):
        plan = by_id[benchmark_id].expected_revision_plan
        assert plan["targeted_components"]
        assert plan["targeted_outputs"]
        assert plan["allowed_parameter_changes"]
        assert plan["protected_parameters"]
        assert plan["success_criteria"]


def test_configuration_benchmarks_cover_direct_parameter_regeneration() -> None:
    core = load_benchmark_suite(FIXTURE_DIR / "core.json")
    full = load_benchmark_suite(FIXTURE_DIR / "full.json")
    by_id = {benchmark.id: benchmark for benchmark in [*core.benchmarks, *full.benchmarks]}

    for benchmark_id in (
        "critical_dimension_revision",
        "parametric_configurable_organizer",
        "parametric_repeated_slot_rack",
    ):
        config = by_id[benchmark_id].expected_configuration
        assert config["editable_parameters"]
        assert config["expected_affected_outputs"]
        assert config["expected_validation_state"] == "configuration_ready"
        assert config["provider_call_forbidden"] is True


def test_component_revision_benchmarks_cover_targeted_full_source_revisions() -> None:
    suite = load_benchmark_suite(FIXTURE_DIR / "full.json")
    by_id = {benchmark.id: benchmark for benchmark in suite.benchmarks}

    for benchmark_id in (
        "component_revision_lid_only",
        "component_revision_handle_only",
        "component_revision_unauthorized_output_drift",
    ):
        component_revision = by_id[benchmark_id].expected_component_revision
        assert component_revision["targeted_components"]
        assert component_revision["targeted_outputs"]
        assert component_revision["protected_outputs"]

    assert (
        by_id["component_revision_lid_only"].expected_component_revision["prompt_template_version"]
        == "cadquery-component-revision-v1"
    )
    assert (
        by_id["component_revision_unauthorized_output_drift"]
        .expected_component_revision["expected_blocking_rule"]
        == "revision.protected_output_unexpected_change"
    )


def test_case_carrier_benchmark_covers_recent_tackle_box_failure_modes() -> None:
    suite = load_benchmark_suite(FIXTURE_DIR / "full.json")
    case = {benchmark.id: benchmark for benchmark in suite.benchmarks}["parametric_case_carrier"]

    assert "handle attachment load path" in case.protected_design_invariants
    assert "tray retention constrains forward tray removal" in case.protected_design_invariants
    assert "attached top bridge or explicit open-top decision" in case.protected_design_invariants
    assert "handle sizing source is user, default, or calculated" in case.protected_design_invariants

    assert "handle visually present but disconnected from load-bearing body" in case.unacceptable_outcomes
    assert "cosmetic hinge blocks without functional hinge or fixed attachment decision" in case.unacceptable_outcomes
    assert "open top created without explicit open-top requirement or retention plan" in case.unacceptable_outcomes
    assert "handle size exposed as arbitrary user parameter without ergonomic/default source" in case.unacceptable_outcomes
