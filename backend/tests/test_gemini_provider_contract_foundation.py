from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

import scripts.run_gemini_provider_contract_foundation as foundation
from scripts.run_gemini_provider_contract_foundation import (
    HOLDOUT_PACKET_IDS,
    MODEL,
    SECONDARY_ENV,
    SELECTION_PACKET_IDS,
    holdout_packets,
    offline_rescore,
    prepare_study,
    selection_packets,
)
from app.services.gemini_consistency.provider_contract import (
    QUALITY_RESULTS,
    GeminiProviderContractAdapter,
    canonicalization_distance,
    contract_entropy,
    evaluate_intrinsic,
    extract_requirement_operators,
    geometry_strategy_signature,
    identity_signature,
    semantic_signature,
    structural_signature,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_selection_and_holdout_packets_are_disjoint_and_frozen() -> None:
    selection = selection_packets()
    holdout = holdout_packets()

    assert [item["packet_id"] for item in selection] == list(SELECTION_PACKET_IDS)
    assert [item["packet_id"] for item in holdout] == list(HOLDOUT_PACKET_IDS)
    assert not {item["packet_id"] for item in selection} & {item["packet_id"] for item in holdout}
    assert [item["stage"] for item in holdout].count("requirements") == 3
    assert [item["stage"] for item in holdout].count("plan") == 3
    assert [item["stage"] for item in holdout].count("geometry") == 3
    assert [item["stage"] for item in holdout].count("repair") == 1


def test_prepare_creates_preregistration_before_any_calls(tmp_path: Path) -> None:
    result = prepare_study(tmp_path / "study", REPO_ROOT)
    prereg = json.loads((tmp_path / "study/reports/study-preregistration.json").read_text(encoding="utf-8"))

    assert result["provider_calls"] == 0
    assert result["worker_calls"] == 0
    assert prereg["model"] == MODEL
    assert prereg["credential_policy"] == {
        "automatic_rotation": False,
        "credential_slot": "secondary",
        "credential_source": SECONDARY_ENV,
        "primary_fallback": False,
    }
    assert prereg["rate_policy"]["concurrency"] == 1
    assert prereg["rate_policy"]["default_requests_per_minute"] == 12
    assert prereg["rate_policy"]["hard_max_requests_per_rolling_60_seconds"] == 15


def test_offline_rescore_accounts_for_historical_corpus_without_calls(tmp_path: Path) -> None:
    prepare_study(tmp_path / "study", REPO_ROOT)
    result = offline_rescore(tmp_path / "study", REPO_ROOT)
    report = json.loads((tmp_path / "study/reports/intrinsic-quality-offline-rescore.json").read_text(encoding="utf-8"))

    assert result["provider_calls"] == 0
    assert result["worker_calls"] == 0
    assert report["record_count"] == 109
    assert any(item["source"] == "system-boundary-preserved-quota-stop" for item in report["records"])
    assert all("diagnostic_current_build" in item for item in report["records"])


def _packet(packet_id: str) -> dict:
    return next(item for item in selection_packets() if item["packet_id"] == packet_id)


def test_intrinsic_quality_does_not_inspect_current_build_outcomes() -> None:
    packet = _packet("selection-requirements-specified")
    response = {
        "requirements": [
            {"id": "r1", "description": "phone width", "value": 78, "unit": "mm", "source": "user"},
            {"id": "r2", "description": "phone thickness with case", "value": 12, "unit": "mm", "source": "user"},
            {"id": "r3", "description": "view angle", "value": 65, "unit": "deg", "source": "user"},
            {"id": "r4", "description": "one printed part", "value": 1, "source": "user"},
        ],
        "clarification_required": False,
        "generation_ready": True,
        "charging_opening": "centered",
        "output_count": 1,
        "summary": "78 mm 12 mm 65 degrees centered charging opening one printed part",
    }

    without_build = evaluate_intrinsic(packet, response)
    with_build = evaluate_intrinsic(packet, response, diagnostic_context={"parser_acceptance": False, "worker_reached": False, "topology_valid": False})

    assert without_build == with_build
    assert without_build["result"] in QUALITY_RESULTS


def test_requirement_operators_are_preserved_and_critical_invention_fails() -> None:
    packet = _packet("selection-requirements-specified")
    response = {
        "requirements": [
            {"id": "r1", "subject": "width", "operator": "exact", "value": 78, "unit": "mm", "source": "user"},
            {"id": "r2", "subject": "thickness", "operator": "maximum", "value": 12, "unit": "mm", "source": "user"},
            {"id": "r3", "subject": "angle", "operator": "approximately", "value": 65, "unit": "deg", "source": "user"},
        ],
        "clarification_required": False,
        "generation_ready": True,
        "charging_opening": "centered",
        "output_count": 1,
        "summary": "78 mm 12 mm 65 degrees centered charging opening one printed part",
    }

    assert extract_requirement_operators(response) == ["approximately", "exact", "maximum"]
    assert evaluate_intrinsic(packet, response)["result"] == "pass"
    invented = dict(response)
    invented["requirements"] = [*response["requirements"], {"id": "r4", "subject": "fit clearance", "operator": "exact", "value": 2, "unit": "mm", "source": "user"}]
    assert evaluate_intrinsic(packet, invented)["result"] == "fail_invented_critical_meaning"


def test_empty_nested_records_and_empty_ready_plan_fail() -> None:
    packet = _packet("selection-plan-ordinary")
    assert evaluate_intrinsic(packet, {"components": [{}], "plan_ready": True})["result"] == "fail_structurally_empty"
    assert evaluate_intrinsic(packet, {"components": [], "features": [], "printable_outputs": [], "plan_ready": True})["result"] == "fail_structurally_empty"


def test_plan_missing_feature_family_and_wrong_output_count_fail() -> None:
    packet = _packet("selection-plan-feature-rich")
    base = {
        "plan_ready": True,
        "components": [{"id": "c1", "name": "carrier"}],
        "features": [{"id": "f1", "description": "carrying handle"}],
        "printable_outputs": [{"id": "o1", "component_id": "c1", "description": "carrier", "quantity": 1}],
    }
    missing = evaluate_intrinsic(packet, base)
    assert missing["result"] == "fail_incomplete"
    wrong_count = dict(base)
    wrong_count["printable_outputs"] = [*base["printable_outputs"], {"id": "o2", "component_id": "c1", "description": "extra"}]
    assert evaluate_intrinsic(packet, wrong_count)["result"] == "fail_wrong_output_obligation"


def test_geometry_api_symbols_and_result_assignment_are_intrinsic_failures() -> None:
    packet = _packet("selection-geometry-simple")
    invalid = [
        {"slots": [{"slot_id": "1", "statements": ["body = body.rotate(rotation=90)"], "result_symbol": "body"}]},
        {"slots": [{"slot_id": "1", "statements": ["body = body.union(missing_shape)"], "result_symbol": "body"}]},
        {"slots": [{"slot_id": "1", "statements": ["body = body.cut(cutter)"]}]},
    ]
    assert evaluate_intrinsic(packet, invalid[0])["result"] == "fail_invalid_api"
    assert evaluate_intrinsic(packet, invalid[1])["result"] == "fail_undefined_symbols"
    assert evaluate_intrinsic(packet, invalid[2])["result"] == "fail_structurally_empty"


def test_geometry_source_contract_is_scored_without_current_parser_acceptance() -> None:
    packet = _packet("selection-geometry-simple")
    source = """```python\nimport cadquery as cq\ndef build(params):\n    body = cq.Workplane('XY').box(100, 80, 10).faces('>Z').workplane().hole(20)\n    return Product(outputs=[PrintableOutput(output_id='body', model=body)])\n```"""

    result = evaluate_intrinsic(packet, source, diagnostic_context={"parser_acceptance": False, "worker_reached": False})

    assert result["result"] == "pass"


def test_semantic_and_byte_consistency_are_separate_and_entropy_is_reproducible() -> None:
    packet = _packet("selection-geometry-simple")
    first = {"slots": [{"slot_id": "1", "statements": ["body = body.cut(cq.Workplane('XY').circle(4).extrude(5))"], "result_symbol": "body"}]}
    second = {"slots": [{"slot_id": "1", "statements": ["body = body.cut(cq.Workplane('XY').circle(4).extrude(5))"], "result_symbol": "body", "notes": "same meaning"}]}
    assert semantic_signature(first, packet) == semantic_signature(second, packet)
    assert structural_signature(first) != structural_signature(second)
    assert contract_entropy([first, second], packet) == contract_entropy([first, second], packet)
    assert geometry_strategy_signature(first) == geometry_strategy_signature(second)
    assert identity_signature(first) == identity_signature(second)


def test_canonicalization_distance_only_counts_benign_formatting() -> None:
    raw = "```json\n{\"status\":\"ready_for_generation\",\"result\":\"body\"}\n```"
    normalized = {"result_symbol": "body", "status": "generation_ready"}
    assert canonicalization_distance(raw, normalized) > 0
    semantic_change = {"result_symbol": "body", "status": "generation_ready", "value": 999}
    assert canonicalization_distance(raw, semantic_change) > canonicalization_distance(raw, normalized)


def test_generic_adapter_attaches_volundr_ownership_without_inventing_provider_meaning() -> None:
    packet = _packet("selection-geometry-simple")
    raw = {"slots": [{"slot_id": "1", "statements": ["modified_shape = body.cut(cq.Workplane('XY').circle(4).extrude(5))"], "result": "modified_shape"}]}
    adapter = GeminiProviderContractAdapter(stage="geometry", contract={"required_slot_ids": ["1"], "required_result_symbol": "body"})

    result = adapter.adapt(raw, packet, provenance={"logical_operation_id": "op-1"}, owned_ids={"slot_id": "1"})

    assert result["accepted"] is True
    assert result["canonical_provider_record"]["slots"][0]["result_symbol"] == "body"
    assert result["volundr_mapping"]["provenance"] == {"logical_operation_id": "op-1"}
    assert {action["action_class"] for action in result["actions"]} >= {"result_symbol_normalization", "prior_shape_alias_normalization", "slot_attachment"}


def test_generic_adapter_accepts_provider_owned_geometry_source_without_current_parser() -> None:
    packet = _packet("selection-geometry-simple")
    source = """```python
import cadquery as cq
def build(params):
    body = cq.Workplane('XY').box(100, 80, 10).faces('>Z').workplane().hole(20)
    return Product(outputs=[PrintableOutput(output_id='body', model=body)])
```"""
    adapter = GeminiProviderContractAdapter(stage="geometry", contract={"response_kind": "cadquery_source"})

    result = adapter.adapt(source, packet, provenance={"logical_operation_id": "source-1"})

    assert result["accepted"] is True
    assert result["canonical_provider_record"]["response_kind"] == "cadquery_source"
    assert result["canonical_provider_record"]["source"] == source
    assert result["volundr_mapping"]["provenance"] == {"logical_operation_id": "source-1"}


def test_adapter_rejects_protected_dimension_change_and_arbitrary_api_repair() -> None:
    packet = _packet("selection-geometry-simple")
    adapter = GeminiProviderContractAdapter(stage="geometry", contract={"required_slot_ids": ["1"], "required_result_symbol": "body"})
    changed = {"slots": [{"slot_id": "1", "statements": ["body = body.cut(cq.Workplane('XY').circle(9).extrude(5))"], "result_symbol": "body"}]}
    invalid = {"slots": [{"slot_id": "1", "statements": ["body = body.rotate(rotation=90)"], "result_symbol": "body"}]}

    protected = adapter.adapt(changed, packet, protected_values={"hole_diameter": 4}, owned_ids={"slot_id": "1"})
    rejected = adapter.adapt(invalid, packet, owned_ids={"slot_id": "1"})

    assert protected["accepted"] is False
    assert rejected["accepted"] is False
    assert all(action["action_class"] != "rejected_ambiguity" for action in rejected["actions"])


def test_settings_thinking_and_prompt_profiles_change_only_declared_contract_inputs() -> None:
    s0 = foundation._generation_config("S0-current-explicit", "H0-current-stage-specific", "requirements", "T0-current")
    s1 = foundation._generation_config("S1-profile-b", "H0-current-stage-specific", "requirements", "T0-current")
    assert set(s0) - {"temperature", "topP", "topK"} == {"maxOutputTokens", "thinkingConfig"}
    assert set(s1) - {"seed", "candidateCount"} == {"maxOutputTokens", "thinkingConfig"}
    assert foundation._thinking_config("H0-current-stage-specific", "requirements") != foundation._thinking_config("H1-provider-default", "requirements")
    packet = _packet("selection-requirements-fit")
    assert foundation._prompt_for_packet(packet, "T0-current") != foundation._prompt_for_packet(packet, "T1-canonical-contract")


def test_only_secondary_credential_is_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY_2", "secondary-test-value")
    assert foundation._require_secondary_key() == "secondary-test-value"
    monkeypatch.delenv("GEMINI_API_KEY_2", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY_2"):
        foundation._require_secondary_key()


class _FakeLimiter:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def acquire(self) -> dict:
        return {"call_start_monotonic": float(len(self.events) + 1), "prior_rolling_window_count": len(self.events), "sleep_seconds": None, "limiter_decision": "allow", "effective_requests_per_minute": 12}


def _provider_response(text: str, *, model: str = MODEL) -> httpx.Response:
    return httpx.Response(200, json={"modelVersion": model, "candidates": [{"content": {"parts": [{"text": text}]}}]})


def test_retry_429_is_identical_and_has_one_new_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    packet = _packet("selection-requirements-fit")
    valid = json.dumps({"clarification_required": True, "clarification_questions": [{"question": "What are the phone dimensions?"}], "generation_ready": False, "requirements": [{"id": "r1", "description": "phone stand", "source": "user"}]})
    responses = [httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED"}}), _provider_response(valid)]

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(foundation.asyncio, "sleep", no_sleep)

    async def run() -> dict:
        async def handler(_: httpx.Request) -> httpx.Response:
            return responses.pop(0)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://example.test") as client:
            return await foundation._call_provider(client=client, limiter=_FakeLimiter(), logical_operation_id="op-429", packet=packet, settings_profile="S0-current-explicit", thinking_profile="H0-current-stage-specific", prompt_profile="T0-current", prompt="frozen", generation_config={"temperature": 0.2}, key="secondary-test-value")

    result = asyncio.run(run())
    assert result["complete"] is True
    assert len(result["attempts"]) == 2
    assert result["attempts"][0]["status_code"] == 429
    assert result["attempts"][0]["retry_wait_seconds"] >= 30
    assert result["attempts"][1]["retry_number"] == 1
    assert result["attempts"][0]["provider_attempt_id"] != result["attempts"][1]["provider_attempt_id"]
    assert result["attempts"][0]["logical_operation_id"] == result["attempts"][1]["logical_operation_id"] == "op-429"
    assert result["attempts"][0]["payload_hash"] == result["attempts"][1]["payload_hash"]
    assert result["attempts"][0]["configuration_hash"] == result["attempts"][1]["configuration_hash"]


def test_second_429_receives_no_third_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    packet = _packet("selection-requirements-fit")
    responses = [httpx.Response(429), httpx.Response(429), _provider_response("never-used")]

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(foundation.asyncio, "sleep", no_sleep)

    async def run() -> dict:
        async def handler(_: httpx.Request) -> httpx.Response:
            return responses.pop(0)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://example.test") as client:
            return await foundation._call_provider(client=client, limiter=_FakeLimiter(), logical_operation_id="op-twice-429", packet=packet, settings_profile="S0-current-explicit", thinking_profile="H0-current-stage-specific", prompt_profile="T0-current", prompt="frozen", generation_config={}, key="secondary-test-value")

    result = asyncio.run(run())
    assert result["complete"] is False
    assert [item["status_code"] for item in result["attempts"]] == [429, 429]
    assert len(responses) == 1


def test_resume_does_not_repeat_completed_or_twice_failed_operations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "study"
    reports = output / "reports"
    reports.mkdir(parents=True)
    records = []
    common = {"settings_profile": "S0-current-explicit", "thinking_profile": "H0-current-stage-specific", "prompt_profile": "T0-current"}
    records.append({**common, "logical_operation_id": "settings-study-results:S0-current-explicit:H0-current-stage-specific:T0-current:selection-requirements-fit:rep-1", "complete": True, "success": True, "status_code": 200, "parsed_response": {"clarification_required": True, "clarification_questions": [{"question": "What are the phone dimensions?"}], "generation_ready": False, "requirements": [{"id": "r1", "description": "phone stand"}]}, "attempts": [{"status_code": 200}]})
    records.append({**common, "logical_operation_id": "settings-study-results:S0-current-explicit:H0-current-stage-specific:T0-current:selection-requirements-specified:rep-1", "complete": False, "success": False, "status_code": 429, "attempts": [{"status_code": 429}, {"status_code": 429}]})
    (reports / "settings-study-results.json").write_text(json.dumps({"run": True, "records": records, "rate_limit": {"events": [{"old": True}]}}), encoding="utf-8")
    monkeypatch.setenv("GEMINI_API_KEY_2", "secondary-test-value")

    async def fail_if_called(**_: object) -> dict:
        raise AssertionError("resume repeated an existing logical operation")

    monkeypatch.setattr(foundation, "_call_provider", fail_if_called)
    packets = [_packet("selection-requirements-fit"), _packet("selection-requirements-specified")]
    result = asyncio.run(foundation.run_live_matrix(output, phase="settings-study-results", settings_profiles=["S0-current-explicit"], thinking_profile="H0-current-stage-specific", prompt_profiles=["T0-current"], packets=packets, repetitions=1, limiter=_FakeLimiter()))
    assert len(result["records"]) == 2
    assert result["rate_limit"]["events"] == [{"old": True}]
