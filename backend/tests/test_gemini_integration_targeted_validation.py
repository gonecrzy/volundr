import json
from pathlib import Path

from app.services.gemini_integration.adapters import GeminiGeometryContractAdapter, GeminiPlanContractAdapter
from app.services.gemini_integration.profile import GeminiFlashLiteContractV1
from app.services.gemini_integration.targeted_validation import (
    TARGETED_VALIDATION_ID,
    TargetedValidationRunner,
    TargetedOperation,
    protected_value_findings,
    validate_geometry_response,
    validate_plan_response,
)


def _repo() -> Path:
    return Path(__file__).resolve().parents[2]


def _operation(**overrides) -> TargetedOperation:
    value = {
        "operation_id": "targeted-provider-validation-01:test",
        "group": "G1",
        "stage": "geometry",
        "project_id": "project-003",
        "repetition": 1,
        "request": type("Request", (), {"__dict__": {}})(),
        "rendered_prompt": "frozen",
        "prompt_version": "T0-current",
        "prompt_hash": "prompt",
        "request_hash": "request",
        "expected_slot_ids": ("0", "1"),
        "protected_parameter_values": {"phone_width_param": 78},
        "responsibility_expectations": {"0": []},
    }
    value.update(overrides)
    return TargetedOperation(**value)


def test_targeted_operations_are_exactly_six_and_geometry_brief_is_manifest_derived() -> None:
    repo = _repo()
    profile = GeminiFlashLiteContractV1.from_repository(repo)
    study_root = repo / "data/debug-sessions/gemini-provider-contract-integration/gemini-provider-contract-integration-01"
    runner = TargetedValidationRunner(repo, study_root, profile)

    assert len(runner.operations) == 6
    assert [(item.group, item.project_id, item.stage, item.repetition) for item in runner.operations] == [
        ("G1", "project-003", "geometry", 1),
        ("G1", "project-003", "geometry", 2),
        ("G2", "project-005", "geometry", 1),
        ("G2", "project-005", "geometry", 2),
        ("P1", "project-001", "plan", 1),
        ("P1", "project-001", "plan", 2),
    ]
    assert all(item.request.geometry_slot_brief for item in runner.operations[:4])
    assert all('"slots"' in item.rendered_prompt for item in runner.operations[:4])
    assert all(item.operation_id.startswith(f"{TARGETED_VALIDATION_ID}:") for item in runner.operations)


def test_protected_parameter_values_are_not_rewritten() -> None:
    unchanged = protected_value_findings(["body = body.cut(cutter)", "x = params['phone_width_param']"], {"phone_width_param": 78})
    changed = protected_value_findings(["phone_width_param = 79", "body = body.cut(cutter)"], {"phone_width_param": 78})

    assert unchanged == []
    assert changed[0]["failure_class"] == "protected_value_change"
    assert changed[0]["unchanged"] is False


def test_geometry_missing_and_extra_slots_fail_without_invention() -> None:
    operation = _operation()
    adapter = GeminiGeometryContractAdapter()
    missing_raw = {"slots": [{"slot_id": 0, "statements": ["body = body.cut(cutter)"], "result_symbol": "body"}]}
    missing_evidence = adapter.adapt(missing_raw, {"project_id": "project-003", "expected_slot_ids": ["0", "1"], "allowed_names": ["body", "cutter"]})
    missing = validate_geometry_response(missing_raw, operation, missing_evidence)
    extra_raw = {"slots": [
        {"slot_id": 0, "statements": ["body = body.cut(cutter)"], "result_symbol": "body"},
        {"slot_id": 1, "statements": ["body = body.union(body)"], "result_symbol": "body"},
        {"slot_id": 2, "statements": ["body = body.cut(cutter)"], "result_symbol": "body"},
    ]}
    extra_evidence = adapter.adapt(extra_raw, {"project_id": "project-003", "expected_slot_ids": ["0", "1"], "allowed_names": ["body", "cutter"]})
    extra = validate_geometry_response(extra_raw, operation, extra_evidence)

    assert missing["passed"] is False
    assert missing["missing_slot_ids"] == ["1"]
    assert extra["passed"] is False
    assert extra["extra_slot_ids"] == ["2"]
    assert extra["adapter_did_not_invent_slots"] is True


def test_malformed_plan_remains_rejected_and_is_not_reconstructed() -> None:
    raw = '{"components":[{"id":"base","name":"base"}],"printable_outputs":['
    operation = _operation(stage="plan", group="P1", project_id="project-001", expected_slot_ids=(), expected_output_count=1, required_requirement_ids=("plate_width",))
    evidence = GeminiPlanContractAdapter().adapt(raw, {"project_id": "project-001", "expected_output_count": 1, "required_requirement_ids": ["plate_width"]})
    result = validate_plan_response(raw, operation, evidence)

    assert result["parseable"] is False
    assert result["adapter_accepted"] is False
    assert result["adapter_reconstructed_content"] is False
    assert result["malformed_json_repair_allowed"] is False
    assert result["passed"] is False


def test_fenced_plan_is_a_format_normalization_only() -> None:
    payload = {
        "requirements": [{"id": "plate_width", "description": "width"}],
        "components": [{"id": "base", "name": "base"}],
        "features": [],
        "printable_outputs": [{"id": "out", "component_id": "base"}],
    }
    raw = "```json\n" + json.dumps(payload) + "\n```"
    operation = _operation(stage="plan", group="P1", project_id="project-001", expected_slot_ids=(), expected_output_count=1, required_requirement_ids=("plate_width",))
    evidence = GeminiPlanContractAdapter().adapt(raw, {"project_id": "project-001", "expected_output_count": 1, "required_requirement_ids": ["plate_width"]})
    result = validate_plan_response(raw, operation, evidence)

    assert evidence.accepted is True
    assert result["parse_fence_normalizations"] == 1
    assert result["adapter_reconstructed_content"] is False
    assert result["passed"] is True
