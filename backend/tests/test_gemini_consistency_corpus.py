from pathlib import Path

import pytest

from app.services.gemini_consistency.corpus import (
    PILOT_CASE_IDS,
    load_consistency_corpus,
    validate_consistency_corpus,
)


CORPUS_PATH = Path(__file__).parents[2] / "benchmarks" / "gemini-consistency-v1.json"


def test_frozen_corpus_has_fifty_stable_cases_and_required_distribution() -> None:
    corpus = load_consistency_corpus(CORPUS_PATH)

    assert corpus.version == "gemini-consistency-v1"
    assert len(corpus.cases) == 50
    assert [case.case_id for case in corpus.cases] == [f"case-{index:03d}" for index in range(1, 51)]
    assert len({case.case_id for case in corpus.cases}) == 50
    assert corpus.specificity_counts == {
        "vague": 10,
        "moderate": 15,
        "high": 15,
        "constrained": 10,
    }
    assert len(PILOT_CASE_IDS) == 10
    assert all(case_id in corpus.case_ids for case_id in PILOT_CASE_IDS)
    assert all(case.family for case in corpus.cases)
    assert all(case.fact_sheet for case in corpus.cases)
    assert all(case.safety_notes for case in corpus.cases)
    assert all(case.expected_output_count >= 1 for case in corpus.cases)


def test_frozen_corpus_has_balanced_families_and_stable_hash() -> None:
    corpus = load_consistency_corpus(CORPUS_PATH)

    assert len(corpus.family_counts) >= 10
    assert max(corpus.family_counts.values()) <= 5
    assert corpus.content_hash == load_consistency_corpus(CORPUS_PATH).content_hash
    assert corpus.case("case-001").title == "Vague phone stand"
    assert corpus.case("case-050").title == "Adjustable-width bracket"


def test_corpus_rejects_duplicate_or_missing_case_ids() -> None:
    corpus = load_consistency_corpus(CORPUS_PATH)
    raw = corpus.to_document()
    raw["cases"][-1]["case_id"] = raw["cases"][0]["case_id"]

    with pytest.raises(ValueError, match="stable case IDs"):
        validate_consistency_corpus(raw)

