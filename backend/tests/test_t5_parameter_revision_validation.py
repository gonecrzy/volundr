from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.gemini_integration.profile import GeminiFlashLiteContractV1
from app.services.gemini_integration.prompts import (
    GEOMETRY_T5_PARAMETER_ACCESS_PROMPT_VERSION,
    render_geometry_prompt_parameter_access_v1,
)
from app.services.research.provider_ir_validation import build_frozen_task_corpus
from app.services.research.t5_parameter_revision_validation import (
    STUDY_ID,
    build_candidate_tasks,
    evaluate_revision_preservation,
    load_revision_authority,
    validate_parameter_access,
)
from scripts.run_t5_parameter_revision_validation import (
    MAX_LOGICAL_OPERATIONS,
    REPORT_NAMES,
    build_execution_order,
    run_study,
)


def _profile() -> GeminiFlashLiteContractV1:
    return GeminiFlashLiteContractV1(
        profile_id="gemini_flash_lite_contract_v1",
        model="gemini-3.5-flash-lite",
        settings={"temperature": 0.2, "topP": 0.95, "topK": 40, "candidateCount": 1},
        thinking_configuration=None,
        stage_prompt_versions={"requirements": "T2-requirements-missing-fit-v1", "plan": "T0-current", "geometry": "T5-geometry-exact-slot-contract-v1"},
        stage_output_tokens={"requirements": 8192, "plan": 8192, "geometry": 8192},
        source_hashes={},
        settings_hash="test",
    )


def test_candidate_prompt_clarifies_mapping_access_without_geometry_strategy_constraints() -> None:
    task = build_candidate_tasks()[0]
    rendered = render_geometry_prompt_parameter_access_v1(_profile(), task.request)

    assert rendered.prompt_version == GEOMETRY_T5_PARAMETER_ACCESS_PROMPT_VERSION
    assert "params is a mapping" in rendered.prompt
    assert 'params["<authorized_parameter_id>"]' in rendered.prompt
    assert "params.fact_0" in rendered.prompt
    assert "invalid" in rendered.prompt
    assert "Do not otherwise constrain geometry strategy" in rendered.prompt
    assert "slot1D" not in rendered.prompt
    assert rendered.prompt_hash


def test_candidate_tasks_are_six_preregisterable_operations_with_complete_revision_authority() -> None:
    tasks = build_candidate_tasks()

    assert STUDY_ID == "t5-parameter-revision-validation-01"
    assert len(tasks) == 6
    assert [task.task_number for task in tasks] == [1, 2, 3, 4, 5, 6]
    assert tasks[1].required_fixed_points == ((-20, -10), (7, 13), (19, -4))
    for task in tasks[2:5]:
        authority = task.revision_authority
        assert task.output_ids == ("mounting_bracket",)
        assert task.request.geometry_slot_manifest["slots"][0]["required_result"] == "body"
        assert authority["prior_output_id"] == "mounting_bracket"
        assert authority["prior_source_reference"]["source_id"]
        assert authority["prior_source_reference"]["source_sha256"]
        assert authority["prior_geometry"]["base_dimensions_mm"] == {"length": 80, "width": 50, "height": 6}
        assert authority["prior_geometry"]["upright_dimensions_mm"] == {"length": 50, "width": 45, "thickness": 6}
        assert len(authority["prior_geometry"]["holes"]) == 4
        assert all(set(hole) >= {"feature_id", "location_mm", "axis", "owning_face", "diameter_mm"} for hole in authority["prior_geometry"]["holes"])
        assert authority["protected_features"]


def test_revision_authority_source_is_connected_and_hash_bound() -> None:
    authority = load_revision_authority()
    namespace: dict[str, object] = {}
    exec("import cadquery as cq\nbody = " + authority["prior_body_expression"], namespace)
    body = namespace["body"]

    assert len(body.solids().vals()) == 1
    assert authority["prior_source_reference"]["source_sha256"]
    assert authority["prior_output_id"] == "mounting_bracket"


def test_original_incomplete_task5_is_not_scored_against_absent_authority() -> None:
    original = build_frozen_task_corpus()[4]

    assert original.revision_authority is None
    result = evaluate_revision_preservation(original, statements=[])

    assert result["status"] == "fixture_incomplete"
    assert result["provider_failure"] is False
    assert "authoritative_prior_geometry_missing" in result["unresolved"]


def test_mapping_parameter_access_accepts_only_authorized_subscripts() -> None:
    authorized = {"base_length_mm", "hole_diameter_mm"}

    valid = validate_parameter_access(
        [
            'length = params["base_length_mm"]',
            'diameter = params["hole_diameter_mm"]',
        ],
        authorized,
    )
    invalid_attribute = validate_parameter_access(["length = params.base_length_mm"], authorized)
    invalid_id = validate_parameter_access(['length = params["not_authorized"]'], authorized)

    assert valid["passed"] is True
    assert invalid_attribute["passed"] is False
    assert "attribute_access_forbidden" in invalid_attribute["failures"]
    assert invalid_id["passed"] is False
    assert "unauthorized_parameter_id" in invalid_id["failures"]


def test_complete_revision_authority_scores_protected_geometry_and_identity() -> None:
    task = build_candidate_tasks()[2]
    statements = [
        "body = body.translate((2, 0, 0))",
    ]

    result = evaluate_revision_preservation(task, statements=statements)

    assert result["status"] == "provider_failure"
    assert result["provider_failure"] is True
    assert result["output_identity_preserved"] is True
    assert result["prior_geometry_authority_complete"] is True
    assert "protected_geometry_transformed" in result["failures"]


def test_candidate_execution_order_is_frozen_to_six_operations() -> None:
    tasks = build_candidate_tasks()
    first = build_execution_order(tasks)
    second = build_execution_order(tasks)

    assert MAX_LOGICAL_OPERATIONS == 6
    assert len(first) == 6
    assert first == second
    assert len({item["operation_id"] for item in first}) == 6


@pytest.mark.asyncio
async def test_candidate_offline_preregistration_makes_zero_provider_and_worker_calls(tmp_path: Path) -> None:
    result = await run_study(root=tmp_path / "reports", live=False)

    assert result["provider_calls"] == 0
    assert result["worker_calls"] == 0
    assert set(REPORT_NAMES).issubset({path.name for path in (tmp_path / "reports").glob("*.json")})
    assert json.loads((tmp_path / "reports" / "preregistration.json").read_text())["live_authorized"] is False
