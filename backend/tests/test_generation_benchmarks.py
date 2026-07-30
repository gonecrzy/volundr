from pathlib import Path

from app.services.generation.benchmarks import (
    phase_validation_benchmark_ids,
    load_benchmark_suite,
    run_deterministic_contract_check,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "generation_benchmarks"


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


def test_deterministic_benchmark_contract_check_passes_fixtures() -> None:
    suite = load_benchmark_suite(FIXTURE_DIR / "core.json")
    results = run_deterministic_contract_check(suite)

    assert len(results) == len(suite.benchmarks)
    assert all(result.passed for result in results)
    assert {result.failure_class for result in results} == {"none"}


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
