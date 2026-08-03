from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.generation_attempt import GenerationAttempt
from app.models.project import Project
from app.services.projects.service import ProjectService
from app.services.workflow.provider_response import (
    ProviderResponseOutcome,
    RepairOutcome,
    analyze_provider_response,
    build_focused_repair_context,
    complete_authoritative_provenance,
    compare_focused_repair,
)


def test_invalid_json_is_distinct_from_schema_invalidity() -> None:
    invalid_json = analyze_provider_response('{"object_type": }', stage="requirements")
    assert invalid_json.classification is ProviderResponseOutcome.INVALID_JSON
    assert invalid_json.parsed is None

    schema_invalid = analyze_provider_response(
        '{"purpose": "holder"}',
        stage="requirements",
        findings=["schema.object_type_missing"],
    )
    assert schema_invalid.classification is ProviderResponseOutcome.SCHEMA_INVALID
    assert schema_invalid.parsed == {"purpose": "holder"}


def test_syntax_normalization_preserves_original_and_cannot_invent_values() -> None:
    fenced = '```json\n{"object_type": "holder",}\n```'
    result = analyze_provider_response(fenced, stage="requirements")

    assert result.classification is ProviderResponseOutcome.VALID_AFTER_NORMALIZATION
    assert result.raw_text == fenced
    assert result.normalized == {"object_type": "holder"}
    assert result.raw_hash != result.normalized_hash

    impossible = analyze_provider_response('{"object_type": }', stage="requirements")
    assert impossible.classification is ProviderResponseOutcome.INVALID_JSON
    assert impossible.normalized is None


def test_authoritative_provenance_can_be_completed_only_when_unambiguous() -> None:
    response = {
        "value": 90,
        "unit": "mm",
        "provenance": {},
    }
    completed = complete_authoritative_provenance(
        response,
        {"requirement-1": {"value": 90, "unit": "mm", "source": "initial_user"}},
        requirement_id="requirement-1",
    )
    assert completed.value["provenance"]["source"] == "initial_user"
    assert completed.findings == ("provenance.source_completed",)

    ambiguous = complete_authoritative_provenance(
        response,
        {
            "requirement-1": {"value": 90, "unit": "mm", "source": "initial_user"},
            "requirement-2": {"value": 90, "unit": "mm", "source": "clarification_user"},
        },
    )
    assert ambiguous.value == response
    assert ambiguous.findings == ("provenance.source_conflict",)


def test_provenance_source_misclassification_remains_blocking() -> None:
    result = complete_authoritative_provenance(
        {
            "value": 5,
            "unit": "kg",
            "provenance": {"source": "volundr_proposal"},
        },
        {"requirement-1": {"value": 5, "unit": "kg", "source": "initial_user"}},
        requirement_id="requirement-1",
    )
    assert result.value["provenance"]["source"] == "volundr_proposal"
    assert result.findings == ("provenance.proposal_misclassified",)


def test_focused_repair_context_contains_only_the_affected_record() -> None:
    context = build_focused_repair_context(
        record={"id": "feature-2", "owner": "component-1", "width": 10},
        findings=["feature.owner_missing"],
        protected_ids=["feature-1", "component-1"],
        allowed_alternatives=["component-1"],
    )
    assert context == {
        "record": {"id": "feature-2", "owner": "component-1", "width": 10},
        "findings": ["feature.owner_missing"],
        "protected_ids": ["feature-1", "component-1"],
        "allowed_alternatives": ["component-1"],
        "prohibited_changes": ["protected_ids", "unrelated_records"],
    }


def test_focused_repair_rejects_unchanged_and_preserves_hashes() -> None:
    original = {"id": "feature-1", "width": 10}
    comparison = compare_focused_repair(
        original,
        {"id": "feature-1", "width": 10},
        findings_before=["feature.width_invalid"],
        findings_after=["feature.width_invalid"],
        affected_paths=["width"],
    )
    assert comparison.outcome is RepairOutcome.UNCHANGED_REPAIR
    assert comparison.original_hash == comparison.repaired_hash
    assert comparison.changed_paths == ()


def test_focused_repair_rejects_protected_identity_mutation() -> None:
    comparison = compare_focused_repair(
        {"id": "feature-1", "width": 10},
        {"id": "feature-2", "width": 12},
        findings_before=["feature.width_invalid"],
        findings_after=[],
        affected_paths=["width"],
        protected_paths=["id"],
    )
    assert comparison.outcome is RepairOutcome.REGRESSIVE_REPAIR
    assert "id" in comparison.changed_paths
    assert comparison.identities_changed is True


def test_focused_repair_rejects_unrelated_record_changes() -> None:
    comparison = compare_focused_repair(
        {
            "features": [
                {"id": "feature-1", "width": 10},
                {"id": "feature-2", "width": 20},
            ]
        },
        {
            "features": [
                {"id": "feature-1", "width": 12},
                {"id": "feature-2", "width": 21},
            ]
        },
        findings_before=["feature.width_invalid"],
        findings_after=[],
        affected_paths=["features[0].width"],
    )
    assert comparison.outcome is RepairOutcome.REGRESSIVE_REPAIR
    assert "features[1].width" in comparison.changed_paths


def test_focused_repair_can_be_partial_but_must_remain_blocked() -> None:
    comparison = compare_focused_repair(
        {"id": "feature-1", "width": 10},
        {"id": "feature-1", "width": 12},
        findings_before=["feature.width_invalid", "feature.owner_missing"],
        findings_after=["feature.owner_missing"],
        affected_paths=["width"],
    )
    assert comparison.outcome is RepairOutcome.PARTIAL_REPAIR
    assert comparison.blocked is True
    assert comparison.resolved_findings == ("feature.width_invalid",)


def test_generation_attempt_persists_immutable_response_lifecycle_metadata() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        project = Project(name="Lifecycle", slug="lifecycle", original_intent="test")
        session.add(project)
        session.flush()
        attempt = GenerationAttempt(
            project_id=project.id,
            attempt_number=1,
            provider_id="fixture",
            prompt_version="fixture-v1",
            ruleset_version="fixture-v1",
            request_payload_path="projects/lifecycle/request.json",
            prompt_path="projects/lifecycle/prompt.txt",
            provider_response_stage="design_plan",
            provider_response_classification="valid_after_repair",
            provider_response_original_path="projects/lifecycle/raw-output.txt",
            provider_response_normalized_path="projects/lifecycle/normalized.json",
            provider_response_repaired_path="projects/lifecycle/repaired.json",
            provider_response_final_path="projects/lifecycle/final.json",
            provider_response_original_hash="a" * 64,
            provider_response_normalized_hash="b" * 64,
            provider_response_repaired_hash="c" * 64,
            provider_response_final_hash="c" * 64,
            provider_response_manifest_json='{"changed_fields":["patterns[0].count"]}',
        )
        session.add(attempt)
        session.commit()
        stored = session.get(GenerationAttempt, attempt.id)

        assert stored is not None
        assert stored.provider_response_classification == "valid_after_repair"
        assert stored.provider_response_original_hash == "a" * 64
        assert stored.provider_response_manifest_json == '{"changed_fields":["patterns[0].count"]}'


def test_assumption_label_is_an_unambiguous_display_alias_not_invented_text() -> None:
    service = ProjectService.__new__(ProjectService)
    normalized = service._normalize_design_assumption(
        {"id": "assumption-1", "label": "Wall mount orientation"},
        0,
    )
    assert normalized["description"] == "Wall mount orientation"

    missing = service._normalize_design_assumption({"id": "assumption-2"}, 1)
    assert "description" not in missing
