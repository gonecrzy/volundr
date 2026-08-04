from __future__ import annotations

import json
from pathlib import Path

from scripts.run_gemini_provider_contract_foundation import (
    HOLDOUT_PACKET_IDS,
    MODEL,
    SECONDARY_ENV,
    SELECTION_PACKET_IDS,
    holdout_packets,
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
