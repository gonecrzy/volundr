from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.gemini_integration.profile import GeminiFlashLiteContractV1
from app.services.gemini_integration.geometry_prompt_narrow_fix import T5GeometryValidator
from app.services.gemini_integration.transport import SecondaryGeminiClient, SharedIntegrationRateLimiter
from scripts.run_provider_ir_targeted_validation import run_study
from scripts.run_t5_corrected_review import REVIEW_REPORT_NAMES, run_review
from app.services.research.geometry_ir_experimental import IR_SCHEMA_ID, GeometryIRValidationError
from app.services.research.provider_ir_validation import (
    MAX_ATTEMPTS,
    MAX_LOGICAL_OPERATIONS,
    IR_PROMPT_VERSION,
    STUDY_ID,
    T5_PROMPT_VERSION,
    build_execution_order,
    build_frozen_task_corpus,
    build_known_good_ir,
    build_paired_operations,
    assemble_t5_source,
    classify_candidate_eligibility,
    classify_ir_response,
    classify_t5_response,
    render_ir_prompt,
    render_t5_prompt,
    report_names,
    redacted_attempt,
    require_secondary_credential,
    summarize_provider_metrics,
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


def test_frozen_corpus_has_six_tasks_and_shared_semantics_across_arms() -> None:
    tasks = build_frozen_task_corpus()

    assert [task.task_id for task in tasks] == [
        "provider-ir-validation-task-01",
        "provider-ir-validation-task-02",
        "provider-ir-validation-task-03",
        "provider-ir-validation-task-04",
        "provider-ir-validation-task-05",
        "provider-ir-validation-task-06",
    ]
    for task in tasks:
        assert task.semantic_facts_hash
        assert task.t5_semantic_facts_hash == task.semantic_facts_hash
        assert task.ir_semantic_facts_hash == task.semantic_facts_hash


def test_execution_order_is_preregistered_and_contains_one_operation_per_arm() -> None:
    tasks = build_frozen_task_corpus()
    order = build_execution_order(tasks, seed="provider-ir-targeted-validation-01-order-v1")

    assert len(order) == 12
    assert len({item["operation_id"] for item in order}) == 12
    assert {item["arm"] for item in order} == {"t5_raw_cadquery", "typed_geometry_ir"}
    assert [item["operation_id"] for item in order] == [
        item["operation_id"] for item in build_execution_order(tasks, seed="provider-ir-targeted-validation-01-order-v1")
    ]


def test_paired_operations_use_frozen_prompts_and_identical_task_hashes(tmp_path: Path) -> None:
    profile = _profile()
    operations = build_paired_operations(build_frozen_task_corpus(), profile, tmp_path)

    assert len(operations) == 12
    for pair in zip(operations[::2], operations[1::2]):
        assert {item.arm for item in pair} == {"t5_raw_cadquery", "typed_geometry_ir"}
        assert pair[0].semantic_facts_hash == pair[1].semantic_facts_hash
    assert all(item.prompt_version == T5_PROMPT_VERSION for item in operations if item.arm == "t5_raw_cadquery")
    assert all(item.prompt_version == IR_PROMPT_VERSION for item in operations if item.arm == "typed_geometry_ir")


def test_ir_prompt_is_frozen_schema_text_and_does_not_encode_cadquery_methods() -> None:
    prompt = render_ir_prompt(build_frozen_task_corpus()[2])

    assert IR_PROMPT_VERSION in prompt
    assert IR_SCHEMA_ID in prompt
    assert "slot1D" not in prompt
    assert "cutBlind" not in prompt
    assert "pushPoints" not in prompt
    assert "workplane" not in prompt.lower()


def test_t5_renderer_remains_the_frozen_contract() -> None:
    rendered = render_t5_prompt(build_frozen_task_corpus()[0], _profile())

    assert rendered.prompt_version == T5_PROMPT_VERSION
    assert "T5-geometry-exact-slot-contract-v1" in rendered.prompt
    assert rendered.prompt_hash


def test_t5_semantics_accept_authorized_parameter_references_as_exact_values() -> None:
    task = build_frozen_task_corpus()[0]
    raw = json.dumps({
        "schema_version": "volundr-geometry-slots-v1",
        "slots": [{
            "slot_id": 0,
            "result_symbol": "body",
            "statements": [
                'base_len = params["fact_0"]',
                'base_wid = params["fact_1"]',
                'base_ht = params["fact_2"]',
                "boss_len = 20",
                "boss_wid = 20",
                "boss_ht = 10",
                "tx = 20",
                "ty = 10",
                "tz = 6",
                'base = cq.Workplane("XY").box(base_len, base_wid, base_ht)',
                'boss = cq.Workplane("XY").box(boss_len, boss_wid, boss_ht).translate((tx, ty, tz))',
                "body = base.union(boss)",
            ],
        }],
    })

    evidence = classify_t5_response(raw, task)

    assert evidence["contract_parse"] is True
    assert evidence["semantic_obligations"] is True
    source = assemble_t5_source(task, json.loads(raw))
    assert "ParameterSpec" in source
    assert "id='fact_0'" in source


def test_t5_recognizes_slot2d_cutblind_as_a_semantic_slot() -> None:
    task = build_frozen_task_corpus()[2]
    raw = json.dumps({
        "schema_version": "volundr-geometry-slots-v1",
        "slots": [{
            "slot_id": 0,
            "result_symbol": "body",
            "statements": [
                "length = params['fact_0']",
                "width = params['fact_1']",
                "height = params['fact_2']",
                "body = cq.Workplane('XY').box(length, width, height)",
                "body = body.faces('>Z').workplane().center(0, 8).slot2D(20, 6, 0).cutBlind(-10)",
            ],
        }],
    })

    evidence = classify_t5_response(raw, task)

    assert evidence["contract_valid"] is True
    assert evidence["semantic_obligations"] is True
    assert evidence["t5_validation"]["passed"] is True
    assert "missing_required_operation" not in evidence["failure_classes"]


def test_t5_recognizes_cbore_hole_as_a_semantic_counterbore() -> None:
    task = build_frozen_task_corpus()[3]
    raw = json.dumps({
        "schema_version": "volundr-geometry-slots-v1",
        "slots": [{
            "slot_id": 0,
            "result_symbol": "body",
            "statements": [
                "length = params['fact_0']",
                "width = params['fact_1']",
                "height = params['fact_2']",
                "hole_dia = 5",
                "cbore_dia = 10",
                "cbore_depth = 3",
                "body = cq.Workplane('XY').box(length, width, height).faces('>Z').workplane().cboreHole(hole_dia, cbore_dia, cbore_depth)",
            ],
        }],
    })

    evidence = classify_t5_response(raw, task)

    assert evidence["contract_valid"] is True
    assert evidence["semantic_obligations"] is True
    assert evidence["t5_validation"]["passed"] is True
    assert "missing_required_operation" not in evidence["failure_classes"]


def test_t5_rejects_attribute_parameter_access_that_worker_runtime_cannot_resolve() -> None:
    task = build_frozen_task_corpus()[3]
    raw = json.dumps({
        "schema_version": "volundr-geometry-slots-v1",
        "slots": [{
            "slot_id": 0,
            "result_symbol": "body",
            "statements": [
                "length = params.fact_0",
                "width = params.fact_1",
                "height = params.fact_2",
                "body = cq.Workplane('XY').box(length, width, height).faces('>Z').workplane().cboreHole(5, 10, 3)",
            ],
        }],
    })

    evidence = classify_t5_response(raw, task)

    assert evidence["contract_valid"] is False
    assert "invalid_parameter_access" in evidence["failure_classes"]
    assert evidence["semantic_operation_recognition"] == ["counterbore"]


def test_t5_recognizes_csk_hole_as_a_semantic_countersink() -> None:
    task = build_frozen_task_corpus()[3]
    task.request.design_plan["features"][0]["operation"] = "countersink"
    raw = json.dumps({
        "schema_version": "volundr-geometry-slots-v1",
        "slots": [{
            "slot_id": 0,
            "result_symbol": "body",
            "statements": [
                "body = cq.Workplane('XY').box(70, 50, 8).faces('>Z').workplane().cskHole(5, 10, 82, 3)",
            ],
        }],
    })

    evidence = T5GeometryValidator().validate(raw, task.request)

    assert evidence["passed"] is True
    assert evidence["slots"][0]["semantic_operation_recognition"][0]["implementation"] == "cskHole"


def test_t5_does_not_accept_slot2d_without_a_subtractive_cut() -> None:
    task = build_frozen_task_corpus()[2]
    raw = json.dumps({
        "schema_version": "volundr-geometry-slots-v1",
        "slots": [{
            "slot_id": 0,
            "result_symbol": "body",
            "statements": [
                "body = cq.Workplane('XY').box(60, 40, 20)",
                "body = body.faces('>Z').workplane().slot2D(20, 6, 0)",
            ],
        }],
    })

    evidence = classify_t5_response(raw, task)

    assert evidence["contract_valid"] is False
    assert "missing_required_operation" in evidence["failure_classes"]


def test_t5_revision_keeps_semantic_failures_after_slot_alias_recognition() -> None:
    task = build_frozen_task_corpus()[4]
    raw = json.dumps({
        "schema_version": "volundr-geometry-slots-v1",
        "slots": [{
            "slot_id": 0,
            "result_symbol": "body",
            "statements": [
                "body = body.faces('>Z').workplane().pushPoints([(-25, 0), (25, 0)]).hole(6.0)",
                "body = body.faces('>Z').workplane().center(0, 0).slot2D(18.0, 5.0, 0).cutBlind(-10.0)",
            ],
        }],
    })

    evidence = classify_t5_response(raw, task)

    assert evidence["contract_valid"] is True
    assert evidence["t5_validation"]["passed"] is True
    assert evidence["semantic_obligations"] is False
    assert evidence["assembled_source"]
    assert "protected_revision_value_missing" in evidence["failure_classes"]
    assert "authoritative_value_not_preserved" in evidence["failure_classes"]
    assert "missing_required_operation" not in evidence["failure_classes"]


def test_t5_does_not_require_raw_cadquery_literal_inside_raw_statements() -> None:
    task = build_frozen_task_corpus()[5]
    raw = json.dumps({
        "schema_version": "volundr-geometry-slots-v1",
        "slots": [{
            "slot_id": 0,
            "result_symbol": "body",
            "statements": [
                "l = params['fact_0']",
                "w = params['fact_1']",
                "h = params['fact_2']",
                "base_box = cq.Workplane('XY').box(l, w, h)",
                "loft_box = cq.Workplane('XY').workplane(offset=h - 0.5).rect(l, w).workplane(offset=10.0).circle(w / 3.0).loft(combine=True)",
                "body = base_box.union(loft_box)",
            ],
        }],
    })

    evidence = classify_t5_response(raw, task)

    assert evidence["contract_valid"] is True
    assert evidence["semantic_obligations"] is True
    assert evidence["t5_validation"]["passed"] is True
    assert "missing_required_operation" not in evidence["failure_classes"]
    assert "required_semantic_operation_missing" not in evidence["failure_classes"]


def test_unknown_ir_operation_and_cadquery_method_names_are_rejected() -> None:
    task = build_frozen_task_corpus()[0]
    unknown = json.loads(json.dumps(build_known_good_ir(task)))
    unknown["operations"][0]["operation"] = "magicCadQueryThing"

    evidence = classify_ir_response(json.dumps(unknown), task)

    assert evidence["contract_parse"] is False
    assert "unknown_ir_operation" in evidence["failure_classes"]


def test_ir_missing_dependency_and_ambiguous_frame_fail_closed() -> None:
    task = build_frozen_task_corpus()[0]
    missing = json.loads(json.dumps(build_known_good_ir(task)))
    missing["operations"][0]["depends_on"] = ["not-present"]
    ambiguous = json.loads(json.dumps(build_known_good_ir(task)))
    ambiguous["frames"]["world"]["origin"][0] = "XY"

    missing_evidence = classify_ir_response(json.dumps(missing), task)
    ambiguous_evidence = classify_ir_response(json.dumps(ambiguous), task)

    assert missing_evidence["contract_parse"] is False
    assert "missing_dependency" in missing_evidence["failure_classes"]
    assert ambiguous_evidence["contract_parse"] is False
    assert "ambiguous_coordinate_frame" in ambiguous_evidence["failure_classes"]


def test_protected_revision_values_must_be_explicit_and_preserved() -> None:
    task = build_frozen_task_corpus()[4]
    document = build_known_good_ir(task)
    document["parameters"]["base_length"]["default"] = 81

    evidence = classify_ir_response(json.dumps(document), task)

    assert evidence["contract_parse"] is True
    assert evidence["semantic_obligations"] is False
    assert "invented_or_unprotected_revision_value" in evidence["failure_classes"]


def test_raw_escape_cannot_mutate_an_unrelated_output() -> None:
    task = build_frozen_task_corpus()[5]
    document = build_known_good_ir(task)
    document["operations"][-1]["statements"][-1] = "other_output = body.union(advanced)"

    evidence = classify_ir_response(json.dumps(document), task)

    assert evidence["contract_parse"] is False
    assert "raw_escape_contract_failure" in evidence["failure_classes"]


def test_strict_response_parsing_rejects_fences_and_prose() -> None:
    task = build_frozen_task_corpus()[0]
    valid = json.dumps(build_known_good_ir(task))

    evidence = classify_ir_response(f"```json\n{valid}\n```", task)
    prose = classify_ir_response(f"Here is the JSON:\n{valid}", task)

    assert evidence["contract_parse"] is False
    assert prose["contract_parse"] is False
    assert "normalization" not in evidence["failure_classes"]


def test_worker_success_cannot_override_provider_contract_failure() -> None:
    result = classify_candidate_eligibility(
        provider_evidence={"contract_parse": False, "failure_classes": ["unknown_ir_operation"]},
        downstream={"worker_execution": True, "requirement_verification": True},
    )

    assert result["candidate_eligible"] is False
    assert result["first_incorrect_boundary"] == "contract_parse"


def test_synthetic_counterfactuals_are_excluded_from_provider_metrics() -> None:
    metrics = summarize_provider_metrics([
        {"provider_attempt": True, "synthetic": False, "arm": "typed_geometry_ir", "candidate_eligible": False},
        {"provider_attempt": False, "synthetic": True, "arm": "typed_geometry_ir", "candidate_eligible": True},
    ])

    assert metrics["typed_geometry_ir"]["provider_operations"] == 1
    assert metrics["typed_geometry_ir"]["candidate_eligibility_rate"] == 0.0


def test_secondary_credential_is_required_without_primary_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_credential():
        raise RuntimeError("GEMINI_API_KEY_2 is absent; no provider call was attempted")

    monkeypatch.setattr("app.services.research.provider_ir_validation.load_secondary_credential", missing_credential)

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY_2"):
        require_secondary_credential()


def test_attempt_redaction_removes_credential_values() -> None:
    value = redacted_attempt({"auth_metadata": {"value": "secret", "environment_variable": "GEMINI_API_KEY_2"}, "error_message": "safe"})

    assert "secret" not in json.dumps(value)
    assert value["auth_metadata"]["environment_variable"] == "GEMINI_API_KEY_2"


def test_production_routing_does_not_import_provider_ir_study() -> None:
    import app.services.gemini_integration as integration

    assert "provider_ir_validation" not in integration.__dict__


@pytest.mark.asyncio
async def test_offline_replay_compiles_synthetic_fixtures_without_provider_or_worker_calls(tmp_path: Path) -> None:
    result = await run_study(root=tmp_path / "reports", live=False, worker_root=tmp_path / "workers")

    assert result["records"] == []
    compiler_results = json.loads((tmp_path / "reports" / "compiler-results.json").read_text())
    assert len(compiler_results) == 6
    assert all(item.get("compiled") is True for item in compiler_results)
    assert json.loads((tmp_path / "reports" / "worker-results.json").read_text())["jobs_used"] == 0
    generated_names = {path.name for path in (tmp_path / "reports").glob("*.json")}
    assert set(report_names()).issubset(generated_names)
    assert json.loads((tmp_path / "reports" / "wave-02-gate.json").read_text())["authorized"] is False


def test_t5_corrected_review_replays_all_preserved_responses_without_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    study_root = Path(
        "/root/volundr/data/debug-sessions/representative-workflow-waves/"
        "representative-workflow-wave-01/reports/provider-ir-targeted-validation-01"
    )

    async def fail_provider(*args, **kwargs):
        raise AssertionError("corrected review must not call the provider")

    monkeypatch.setattr(SecondaryGeminiClient, "generate", fail_provider)

    result = run_review(
        report_root=study_root,
        review_root=tmp_path / "t5-corrected-review",
        execute_worker=False,
        worker_root=tmp_path / "workers",
    )

    assert result["provider_calls"] == 0
    assert result["worker_calls"] == 0
    assert len(result["tasks"]) == 6
    assert set(REVIEW_REPORT_NAMES) == {
        path.name for path in (tmp_path / "t5-corrected-review").glob("*.json")
    }
    assert result["decision"]["decision"] in {
        "wave_02_ready_under_t5",
        "targeted_t5_provider_validation_required",
        "t5_requires_narrow_evaluator_fix",
        "t5_provider_contract_requires_revision",
        "insufficient_evidence",
    }


@pytest.mark.asyncio
async def test_resume_reuses_all_operation_captures_without_provider_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = _profile()
    tasks = build_frozen_task_corpus()
    operations = build_paired_operations(tasks, profile, tmp_path)
    capture_root = tmp_path / "reports" / "operation-captures"
    capture_root.mkdir(parents=True)
    for operation in operations:
        safe_id = operation.operation_id.replace(":", "_")
        (capture_root / f"{safe_id}.json").write_text(json.dumps({"operation_id": operation.operation_id, "raw_provider_output": "{}", "provider_attempt": True, "synthetic": False}))
    (tmp_path / "reports" / "provider-attempts.json").write_text(json.dumps([{"attempt_id": f"attempt-{index}"} for index in range(12)]))

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("resume must not call the provider")

    monkeypatch.setattr(SecondaryGeminiClient, "generate", fail_if_called)
    from scripts.run_provider_ir_targeted_validation import run_study

    result = await run_study(root=tmp_path / "reports", live=True, resume=True, worker_root=tmp_path / "workers")

    assert len(result["records"]) == 12
    assert len(json.loads((tmp_path / "reports" / "provider-attempts.json").read_text())) == 12


def test_shared_transport_rejects_attempt_counts_outside_the_preregistered_range() -> None:
    assert MAX_LOGICAL_OPERATIONS == 12
    assert MAX_ATTEMPTS == 18
    assert SharedIntegrationRateLimiter().hard_max_requests_per_window == 15


@pytest.mark.asyncio
async def test_provider_transport_caps_each_operation_at_two_attempts() -> None:
    client = SecondaryGeminiClient(_profile())

    with pytest.raises(ValueError, match="max_attempts"):
        await client.generate(stage="geometry", prompt="{}", operation_id="cap-test", max_attempts=3)
