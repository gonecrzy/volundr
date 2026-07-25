import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.generation.failure_taxonomy import FailureClass


REQUIRED_BENCHMARK_FIELDS = frozenset(
    {
        "id",
        "suite",
        "input_prompt",
        "required_dimensions",
        "allowed_assumptions",
        "expected_clarification",
        "expected_modules",
        "expected_parameters",
        "expected_printability_constraints",
        "compile_expectation",
        "mesh_expectation",
        "revision_expectation",
        "protected_design_invariants",
        "unacceptable_outcomes",
    }
)


@dataclass(frozen=True)
class GenerationBenchmark:
    id: str
    suite: str
    input_prompt: str
    required_dimensions: list[str]
    allowed_assumptions: list[str]
    expected_clarification: str
    expected_modules: list[str]
    expected_parameters: list[str]
    expected_printability_constraints: list[str]
    compile_expectation: str
    mesh_expectation: str
    revision_expectation: str
    protected_design_invariants: list[str]
    unacceptable_outcomes: list[str]
    expected_geometric_invariants: list[dict[str, Any]]
    expected_design_plan: dict[str, Any]
    expected_revision_plan: dict[str, Any]
    expected_configuration: dict[str, Any]


@dataclass(frozen=True)
class BenchmarkSuite:
    name: str
    benchmarks: list[GenerationBenchmark]


@dataclass(frozen=True)
class DeterministicBenchmarkResult:
    benchmark_id: str
    passed: bool
    failure_class: str
    findings: list[str]


def load_benchmark_suite(path: Path) -> BenchmarkSuite:
    payload = json.loads(path.read_text(encoding="utf-8"))
    name = _required_text(payload, "suite")
    raw_benchmarks = payload.get("benchmarks")
    if not isinstance(raw_benchmarks, list) or not raw_benchmarks:
        raise ValueError("benchmark fixture must contain benchmarks")

    benchmarks = [_parse_benchmark(entry) for entry in raw_benchmarks]
    ids = [benchmark.id for benchmark in benchmarks]
    if len(ids) != len(set(ids)):
        raise ValueError("benchmark fixture contains duplicate ids")
    return BenchmarkSuite(name=name, benchmarks=benchmarks)


def run_deterministic_contract_check(suite: BenchmarkSuite) -> list[DeterministicBenchmarkResult]:
    results: list[DeterministicBenchmarkResult] = []
    for benchmark in suite.benchmarks:
        findings: list[str] = []
        if benchmark.expected_clarification not in {"none", "required", "optional"}:
            findings.append("invalid expected_clarification")
        if not benchmark.protected_design_invariants:
            findings.append("missing protected design invariants")
        results.append(
            DeterministicBenchmarkResult(
                benchmark_id=benchmark.id,
                passed=not findings,
                failure_class=FailureClass.NONE.value
                if not findings
                else FailureClass.BENCHMARK_FIXTURE_INVALID.value,
                findings=findings,
            )
        )
    return results


def _parse_benchmark(payload: object) -> GenerationBenchmark:
    if not isinstance(payload, dict):
        raise ValueError("benchmark entry must be an object")
    missing = sorted(REQUIRED_BENCHMARK_FIELDS - set(payload))
    if missing:
        raise ValueError(f"benchmark entry missing fields: {', '.join(missing)}")

    return GenerationBenchmark(
        id=_required_text(payload, "id"),
        suite=_required_text(payload, "suite"),
        input_prompt=_required_text(payload, "input_prompt"),
        required_dimensions=_required_text_list(payload, "required_dimensions"),
        allowed_assumptions=_required_text_list(payload, "allowed_assumptions"),
        expected_clarification=_required_text(payload, "expected_clarification"),
        expected_modules=_required_text_list(payload, "expected_modules"),
        expected_parameters=_required_text_list(payload, "expected_parameters"),
        expected_printability_constraints=_required_text_list(
            payload,
            "expected_printability_constraints",
        ),
        compile_expectation=_required_text(payload, "compile_expectation"),
        mesh_expectation=_required_text(payload, "mesh_expectation"),
        revision_expectation=_required_text(payload, "revision_expectation"),
        protected_design_invariants=_required_text_list(payload, "protected_design_invariants"),
        unacceptable_outcomes=_required_text_list(payload, "unacceptable_outcomes"),
        expected_geometric_invariants=_optional_object_list(payload, "expected_geometric_invariants"),
        expected_design_plan=_optional_object(payload, "expected_design_plan"),
        expected_revision_plan=_optional_object(payload, "expected_revision_plan"),
        expected_configuration=_optional_object(payload, "expected_configuration"),
    )


def _required_text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be non-empty text")
    return value


def _required_text_list(payload: dict[str, object], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{key} must be a non-empty text list")
    return value


def _optional_object_list(payload: dict[str, object], key: str) -> list[dict[str, Any]]:
    value = payload.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{key} must be an object list")
    return value


def _optional_object(payload: dict[str, object], key: str) -> dict[str, Any]:
    value = payload.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return value
