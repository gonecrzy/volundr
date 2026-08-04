from pathlib import Path

import pytest

from app.services.gemini_consistency.corpus import (
    load_flash_lite_study_corpus,
    validate_flash_lite_study_corpus,
)
from app.schemas.gemini_benchmark import GeminiBenchmarkExperimentCreate


CORPUS_PATH = Path(__file__).parents[2] / "benchmarks" / "gemini-flash-lite-study-v1.json"


def test_flash_lite_study_corpus_has_exactly_ten_frozen_cases() -> None:
    corpus = load_flash_lite_study_corpus(CORPUS_PATH)

    assert corpus.version == "gemini-flash-lite-study-v1"
    assert corpus.case_ids == tuple(f"case-{index:03d}" for index in range(1, 11))
    assert len(corpus.cases) == 10
    assert corpus.case("case-001").initial_prompt.startswith("Create a compact desktop phone stand")
    assert corpus.case("case-010").fact_sheet["single_start_thread"] is True


def test_flash_lite_study_corpus_hash_is_stable_and_frozen() -> None:
    first = load_flash_lite_study_corpus(CORPUS_PATH)
    second = load_flash_lite_study_corpus(CORPUS_PATH)

    assert first.content_hash == second.content_hash
    assert first.raw["study_kind"] == "before-and-after product correction study"


def test_flash_lite_study_corpus_rejects_wrong_case_count() -> None:
    corpus = load_flash_lite_study_corpus(CORPUS_PATH)
    document = corpus.to_document()
    document["cases"].pop()

    with pytest.raises(ValueError, match="exactly 10"):
        validate_flash_lite_study_corpus(document)


def test_study_experiment_contract_allows_one_model_and_three_repetitions() -> None:
    payload = GeminiBenchmarkExperimentCreate(
        label="Gemini Flash Lite study",
        corpus_version="gemini-flash-lite-study-v1",
        corpus_hash="a" * 64,
        mode="study",
        models=["gemini-3.5-flash-lite"],
        runs=3,
    )

    assert payload.mode == "study"
    assert payload.models == ["gemini-3.5-flash-lite"]
    assert payload.runs == 3
