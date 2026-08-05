from app.services.gemini_integration.corpus import build_integration_corpus


def test_corpus_contains_exactly_ten_frozen_representative_projects() -> None:
    corpus = build_integration_corpus()

    assert [project.project_id for project in corpus] == [f"project-{index:03d}" for index in range(1, 11)]
    assert len({project.project_id for project in corpus}) == 10
    assert corpus[1].fit_critical_missing == ("cable diameter",)
    assert corpus[1].clarification_answers
    assert corpus[4].expected_output_count == 2
    assert corpus[9].revision_of == "project-009"


def test_corpus_freezes_unsafe_claim_policy_and_revision_protection() -> None:
    corpus = build_integration_corpus()

    assert all("physical certification" in project.unsafe_claims for project in corpus)
    revision = corpus[9]
    assert revision.protected_facts
    assert revision.requirement_delta
