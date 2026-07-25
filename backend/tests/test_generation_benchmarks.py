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
