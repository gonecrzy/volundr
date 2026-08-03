from pathlib import Path

import pytest

from app.services.gemini_consistency.corpus import (
    load_ollama_consistency_corpus,
    validate_ollama_consistency_corpus,
)
from app.services.gemini_consistency.runner import (
    BenchmarkRunSelection,
    validate_run_selection,
)


CORPUS_PATH = Path(__file__).parents[2] / "benchmarks" / "ollama-consistency-v1.json"


def test_ollama_corpus_is_exactly_the_five_frozen_cases() -> None:
    corpus = load_ollama_consistency_corpus(CORPUS_PATH)

    assert corpus.version == "ollama-consistency-v1"
    assert corpus.case_ids == tuple(f"ollama-case-{index:03d}" for index in range(1, 6))
    assert corpus.case("ollama-case-001").initial_prompt.startswith("Create a compact desktop phone stand")
    assert corpus.case("ollama-case-004").expected_output_count == 2
    assert "physical engineering and load testing are mandatory" in corpus.case("ollama-case-004").fact_sheet["safety"]
    assert corpus.content_hash == load_ollama_consistency_corpus(CORPUS_PATH).content_hash


def test_ollama_selection_rejects_anything_other_than_the_five_cases() -> None:
    corpus = load_ollama_consistency_corpus(CORPUS_PATH)

    selected = validate_run_selection(
        corpus,
        BenchmarkRunSelection(models=("gemini-3.5-flash-lite", "ollama:model"), runs=2, pilot=False, full=True),
        benchmark_kind="ollama-five-case",
    )
    assert [case.case_id for case in selected] == list(corpus.case_ids)

    with pytest.raises(ValueError, match="exactly five"):
        validate_run_selection(
            corpus,
            BenchmarkRunSelection(models=("model-a", "model-b"), runs=2, pilot=False, full=True),
            benchmark_kind="ollama-five-case",
            case_filter=("ollama-case-001",),
        )


def test_ollama_corpus_rejects_wrong_ids() -> None:
    corpus = load_ollama_consistency_corpus(CORPUS_PATH)
    raw = corpus.to_document()
    raw["cases"][0]["case_id"] = "case-001"

    with pytest.raises(ValueError, match="ollama-case-001"):
        validate_ollama_consistency_corpus(raw)
