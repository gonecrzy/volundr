from pathlib import Path

from app.services.generation.benchmarks import load_benchmark_suite, run_deterministic_contract_check


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "generation_benchmarks"


def test_core_generation_benchmark_fixture_loads_required_cases() -> None:
    suite = load_benchmark_suite(FIXTURE_DIR / "core.json")

    assert suite.name == "core"
    assert len(suite.benchmarks) == 6
    assert {benchmark.id for benchmark in suite.benchmarks} == {
        "simple_mounting_plate",
        "cylindrical_holder",
        "spacer_bushing",
        "critical_dimension_revision",
        "vague_clarification",
        "conflicting_dimensions",
    }


def test_full_generation_benchmark_fixture_covers_all_categories() -> None:
    suite = load_benchmark_suite(FIXTURE_DIR / "full.json")

    assert suite.name == "full"
    assert len(suite.benchmarks) >= 15
    assert all(benchmark.protected_design_invariants for benchmark in suite.benchmarks)


def test_deterministic_benchmark_contract_check_passes_fixtures() -> None:
    suite = load_benchmark_suite(FIXTURE_DIR / "core.json")
    results = run_deterministic_contract_check(suite)

    assert len(results) == len(suite.benchmarks)
    assert all(result.passed for result in results)
    assert {result.failure_class for result in results} == {"none"}


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
            "no_scad_generated",
            "no_scad_until_fasteners_clarified",
            "no_scad_until_vent_or_split_decision",
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
        == "openscad-component-revision-v1"
    )
    assert (
        by_id["component_revision_unauthorized_output_drift"]
        .expected_component_revision["expected_blocking_rule"]
        == "revision.protected_output_unexpected_change"
    )
