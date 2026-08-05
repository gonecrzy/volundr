import json
import shutil
from pathlib import Path

from app.services.ai.provider import ModelGenerationRequest
from app.services.gemini_integration.geometry_prompt_narrow_fix import (
    FAILURE_CLASSES,
    GEOMETRY_T5_PROMPT_VERSION,
    GeometryPromptNarrowFixRunner,
    GeometryValidationEvidence,
    T5GeometryValidator,
    audit_historical_failures,
    build_generalized_fixtures,
    build_geometry_operations,
    run_fixture_corpus,
)
from app.services.gemini_integration.profile import GeminiFlashLiteContractV1
from app.services.gemini_integration.prompts import render_geometry_prompt_v2, render_integration_prompt
from app.services.gemini_integration.capture import IntegrationEvidenceStore


def _repo() -> Path:
    return Path(__file__).resolve().parents[2]


def _study_root() -> Path:
    return _repo() / "data/debug-sessions/gemini-provider-contract-integration/gemini-provider-contract-integration-01"


def test_t5_is_geometry_only_and_preserves_frozen_production_profile() -> None:
    profile = GeminiFlashLiteContractV1.from_repository(_repo())
    operation = build_geometry_operations(profile, IntegrationEvidenceStore(_study_root(), study_id="gemini-provider-contract-integration-01").boundaries())[0]
    rendered = render_geometry_prompt_v2(profile, operation.request)
    production = render_integration_prompt(profile, "geometry", operation.request)

    assert rendered.prompt_version == GEOMETRY_T5_PROMPT_VERSION
    assert production.prompt_version == "T0-current"
    assert profile.model == "gemini-3.5-flash-lite"
    assert profile.settings == {"temperature": 0.2, "topP": 0.95, "topK": 40, "candidateCount": 1}
    assert profile.thinking_configuration is None
    assert "Do not use Markdown or code fences" in rendered.prompt
    assert "Local variable names, intermediate solids, statement counts" in rendered.prompt
    for slot in operation.expectations:
        assert json.dumps(slot.slot_id) in rendered.prompt
        assert slot.required_result_symbol in rendered.prompt


def test_generalized_contract_corpus_accepts_strategies_and_rejects_invariants() -> None:
    validator = T5GeometryValidator()
    report = run_fixture_corpus(validator)

    assert report["all_expected_results"] is True
    assert report["valid_fixture_count"] >= 11
    assert report["negative_fixture_count"] >= 14
    valid_ids = {item["fixture_id"] for item in report["results"][: report["valid_fixture_count"]]}
    assert {"additive_union", "subtractive_cut", "intersection", "loft", "sweep", "revolve", "shell", "selector_chamfer", "transformed_intermediates", "multislot_arbitrary_identity", "solid_result_form", "compound_result_form", "assembly_result_form"} <= valid_ids
    observed = {failure for item in report["results"] for failure in item.get("observed_failure_classes", [])}
    assert observed <= FAILURE_CLASSES


def test_typed_evidence_preserves_arbitrary_result_identity_without_semantic_repair() -> None:
    fixture = next(item for item in build_generalized_fixtures() if item["fixture_id"] == "multislot_arbitrary_identity")
    request = ModelGenerationRequest(**fixture["request"])
    evidence = T5GeometryValidator().validate_evidence(fixture["raw"], request)

    assert isinstance(evidence, GeometryValidationEvidence)
    assert evidence.passed is True
    assert evidence.adapter_semantic_repair is False
    assert evidence.expected_slot_ids == ("slot-X", "slot-17")
    assert [slot.required_result_symbol for slot in evidence.slots] == ["alpha_result", "beta_result"]
    assert evidence.slots[0].defined_symbols == ("alpha", "alpha_result")


def test_historical_audit_has_parser_counterfactual_and_causal_chain() -> None:
    audit = audit_historical_failures(_study_root(), T5GeometryValidator())

    assert audit["provider_calls"] == 0
    assert audit["worker_calls"] == 0
    assert audit["historical_failure_count"] == 4
    assert set(audit["distinct_failure_classes"]) <= FAILURE_CLASSES
    assert "multiple_independent_defects" in audit["distinct_failure_classes"]
    for record in audit["records"]:
        assert record["authoritative_manifest"]["slots"]
        assert record["raw_provider_response"]["hash"]
        assert record["parsed_response"]["hash"]
        assert record["parser_counterfactual"]["provider_calls"] == 0
        assert record["root_cause_tests"]["parser_altered_semantic_content"] is False
        assert record["causal_chain"]["first_incorrect_boundary"]
        assert record["source_assembly_expectation"]["provider_calls"] == 0


def test_geometry_holdout_is_frozen_project_004_and_exactly_six_operations() -> None:
    profile = GeminiFlashLiteContractV1.from_repository(_repo())
    boundaries = IntegrationEvidenceStore(_study_root(), study_id="gemini-provider-contract-integration-01").boundaries()
    operations = build_geometry_operations(profile, boundaries)

    assert len(operations) == 6
    assert [(item.group, item.project_id, item.repetition) for item in operations] == [
        ("G1", "project-003", 1),
        ("G1", "project-003", 2),
        ("G2", "project-005", 1),
        ("G2", "project-005", 2),
        ("G3", "project-004", 1),
        ("G3", "project-004", 2),
    ]
    assert all(item.prompt_version == GEOMETRY_T5_PROMPT_VERSION for item in operations)
    assert all(item.request.geometry_slot_manifest for item in operations)


def test_runner_offline_mode_writes_no_provider_or_worker_calls(tmp_path: Path) -> None:
    profile = GeminiFlashLiteContractV1.from_repository(_repo())
    isolated = tmp_path / "study"
    isolated.mkdir()
    (isolated / "captures").symlink_to(_study_root() / "captures", target_is_directory=True)
    (isolated / "reports").mkdir()
    shutil.copytree(_study_root() / "reports" / "targeted-provider-validation-01", isolated / "reports" / "targeted-provider-validation-01")
    runner = GeometryPromptNarrowFixRunner(_repo(), isolated, profile)
    result = runner.run(live=False)

    assert result["mode"] == "offline"
    assert result["failure_audit"]["provider_calls"] == 0
    assert result["fixtures"]["worker_calls"] == 0
