from enum import StrEnum


class FailureClass(StrEnum):
    NONE = "none"
    PROVIDER_FAILURE = "provider_failure"
    PROVIDER_TIMEOUT = "provider_timeout"
    SOURCE_EXTRACTION_FAILURE = "source_extraction_failure"
    SOURCE_CONTRACT_HARD_REJECTION = "source_contract_hard_rejection"
    OPENSCAD_COMPILE_FAILURE = "openscad_compile_failure"
    OPENSCAD_TIMEOUT = "openscad_timeout"
    MESH_INVALID = "mesh_invalid"
    MESH_EMPTY_OR_ZERO_VOLUME = "mesh_empty_or_zero_volume"
    MESH_NON_WATERTIGHT = "mesh_non_watertight"
    VALIDATION_BLOCKER = "validation_blocker"
    PRINTABILITY_BLOCKER = "printability_blocker"
    CLARIFICATION_MISSED = "clarification_missed"
    CLARIFICATION_OVERASKED = "clarification_overasked"
    REQUIREMENTS_MISREAD = "requirements_misread"
    UNSAFE_ASSUMPTION = "unsafe_assumption"
    DESIGN_SPEC_MISSING = "design_spec_missing"
    DESIGN_SPEC_INVALID = "design_spec_invalid"
    REVISION_REGRESSION = "revision_regression"
    REPAIR_OVERREACH = "repair_overreach"
    BENCHMARK_FIXTURE_INVALID = "benchmark_fixture_invalid"
    OBSERVABILITY_GAP = "observability_gap"
    UNKNOWN_FAILURE = "unknown_failure"


FAILURE_CLASSES = frozenset(item.value for item in FailureClass)


def require_failure_class(value: str) -> str:
    if value not in FAILURE_CLASSES:
        raise ValueError(f"unknown failure class: {value}")
    return value

