import pytest

from app.services.generation.failure_taxonomy import (
    FAILURE_CLASSES,
    FailureClass,
    require_failure_class,
)


def test_failure_taxonomy_contains_priority_zero_classes() -> None:
    assert FailureClass.NONE in FAILURE_CLASSES
    assert FailureClass.PROVIDER_FAILURE in FAILURE_CLASSES
    assert FailureClass.SOURCE_EXTRACTION_FAILURE in FAILURE_CLASSES
    assert FailureClass.CADQUERY_COMPILE_FAILURE in FAILURE_CLASSES
    assert FailureClass.REPAIR_OVERREACH in FAILURE_CLASSES
    assert FailureClass.BENCHMARK_FIXTURE_INVALID in FAILURE_CLASSES


def test_failure_taxonomy_rejects_unknown_values() -> None:
    with pytest.raises(ValueError, match="unknown failure class"):
        require_failure_class("made_up_failure")
