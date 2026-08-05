from __future__ import annotations

from app.services.gemini_consistency.geometry_slot_canonicalizer import GeometrySlotContractCanonicalizer
from app.services.gemini_consistency.provider_contract_correction import evaluate_executable_repair
from scripts.run_gemini_provider_contract_correction import repair_packets_v2


def _canonicalizer() -> GeometrySlotContractCanonicalizer:
    return GeometrySlotContractCanonicalizer()


def _slot(statements: list[str], *, inputs: list[str] | None = None) -> dict:
    return {
        "slot_id": "2",
        "statements": statements,
        "authoritative_input_symbols": inputs or ["body"],
        "required_result_symbol": "body",
        "allowed_names": ["body", "cq", "feature", "prior_shape"],
    }


def test_sole_authoritative_prior_shape_alias_normalizes_deterministically() -> None:
    result = _canonicalizer().canonicalize(_slot([
        'feature = cq.Workplane("XY").circle(4).extrude(6)',
        "prior_shape = prior_shape.union(feature)",
    ]))

    assert result["accepted"] is True
    assert result["normalized_statements"][-1] == "body = body.union(feature)"
    action = result["actions"][-1]
    assert action["rule_id"] == "sole-authoritative-prior-shape-alias"
    assert action["slot_id"] == "2"
    assert action["authoritative_input"] == "body"
    assert action["required_result_symbol"] == "body"
    assert action["semantic_operation_changed"] is False
    assert action["numeric_literals_changed"] is False
    assert action["operation_order_changed"] is False
    assert action["ambiguity"] is False


def test_ambiguous_alias_fails_closed_when_two_shape_inputs_exist() -> None:
    result = _canonicalizer().canonicalize(_slot(["prior_shape = prior_shape.union(feature)"], inputs=["body", "secondary_body"]))

    assert result["accepted"] is False
    assert result["ambiguity"] is True
    assert result["normalized_statements"] == ["prior_shape = prior_shape.union(feature)"]


def test_alias_normalization_preserves_numeric_literals() -> None:
    result = _canonicalizer().canonicalize(_slot(["prior_shape = prior_shape.fillet(2.5)" ]))

    assert result["accepted"] is True
    assert "2.5" in result["normalized_statements"][0]
    assert result["actions"][0]["numeric_literals_changed"] is False


def test_alias_normalization_preserves_operation_order_and_method() -> None:
    result = _canonicalizer().canonicalize(_slot(["prior_shape = prior_shape.workplane(\"XY\").union(feature).fillet(2)" ]))

    assert result["accepted"] is True
    assert result["normalized_statements"][0] in {
        'body = body.workplane("XY").union(feature).fillet(2)',
        "body = body.workplane('XY').union(feature).fillet(2)",
    }
    assert result["actions"][0]["operation_order_changed"] is False


def test_vacuous_self_union_is_not_accepted_as_meaningful_geometry() -> None:
    result = _canonicalizer().canonicalize(_slot(["prior_shape = prior_shape.union(body)" ]))

    assert result["accepted"] is False
    assert result["reason"] == "semantic_invalid_self_union"


def test_undefined_alias_without_authoritative_input_fails_closed() -> None:
    result = _canonicalizer().canonicalize({**_slot(["prior_shape = prior_shape.union(feature)"]), "authoritative_input_symbols": []})

    assert result["accepted"] is False
    assert result["ambiguity"] is True


def test_non_alias_semantic_defect_is_not_repaired_by_canonicalizer() -> None:
    result = _canonicalizer().canonicalize(_slot(["body = body.union(body)" ]))

    assert result["accepted"] is False
    assert result["reason"] == "semantic_invalid_self_union"


def test_final_assignment_target_must_match_required_symbol() -> None:
    result = GeometrySlotContractCanonicalizer().canonicalize({
        **_slot(["shape = body.workplane(\"XY\").box(20, 20, 4)" ]),
        "required_result_symbol": "body",
    })

    assert result["accepted"] is False
    assert "required result symbol" in result["reason"]


def test_model_repair_m1_requires_executable_body_replacement() -> None:
    packet = next(item for item in repair_packets_v2() if item["packet_id"] == "repair-m1-result-assignment")
    response = {"repaired_items": [{"slot_id": "2", "result_symbol": "body", "statements": ['body = body.workplane("XY").box(20, 20, 4)']}], "preserved_item_ids": ["1"], "rejected_changes": []}

    assert evaluate_executable_repair(packet, response)["result"] == "pass"


def test_model_repair_m2_rejects_declared_invalid_keyword() -> None:
    packet = next(item for item in repair_packets_v2() if item["packet_id"] == "repair-m2-invalid-cadquery-api")
    response = {"repaired_items": [{"slot_id": "2", "result_symbol": "body", "statements": ["body = body.edges().fillet(radius_value=2)"]}], "preserved_item_ids": ["1"], "rejected_changes": []}

    assert evaluate_executable_repair(packet, response)["result"] == "fail_conflicting"


def test_model_repair_m3_requires_the_missing_subtractive_operation() -> None:
    packet = next(item for item in repair_packets_v2() if item["packet_id"] == "repair-m3-missing-subtractive-operation")
    response = {"repaired_items": [{"slot_id": "2", "result_symbol": "body", "statements": ['cutter = cq.Workplane("XY").circle(5).extrude(10)', "body = body.cut(cutter)"]}], "preserved_item_ids": ["1"], "rejected_changes": []}

    assert evaluate_executable_repair(packet, response)["result"] == "pass"


def test_model_repair_cannot_return_completed_item_or_change_protected_dimension() -> None:
    packet = next(item for item in repair_packets_v2() if item["packet_id"] == "repair-m1-result-assignment")
    response = {"repaired_items": [{"slot_id": "1", "result_symbol": "body", "statements": ["body = body"]}], "preserved_item_ids": [], "rejected_changes": []}

    assert evaluate_executable_repair(packet, response)["result"] == "fail_incomplete"
