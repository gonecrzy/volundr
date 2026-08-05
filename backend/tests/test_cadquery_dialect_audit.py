import json

from app.services.gemini_integration.cadquery_dialect import (
    API_REFERENCE_CLASSIFICATIONS,
    analyze_geometry_statements,
)
from app.services.gemini_integration.cadquery_dialect_audit import discover_raw_corpus


def _call(result, method, statement=None):
    return next(
        item for item in result["references"]
        if item.get("method") == method and (statement is None or item.get("statement") == statement)
    )


def test_analyzer_infers_receiver_and_argument_types_for_workplane_calls() -> None:
    result = analyze_geometry_statements(
        [
            "body = body.workplane('XY')",
            "valid = cq.Workplane('XY')",
            "offset = body.workplane(offset=5)",
        ],
        initial_types={"body": "Workplane"},
    )

    invalid = _call(result, "workplane", "body = body.workplane('XY')")
    assert invalid["receiver_type_before"] == "Workplane"
    assert invalid["argument_types"] == ["str"]
    assert invalid["classification"] == "current_argument_type_mismatch"
    assert invalid["expected_parameter_types"]["offset"] == "number"
    assert _call(result, "Workplane", "valid = cq.Workplane('XY')")["classification"] == "current_supported"
    assert _call(result, "workplane", "offset = body.workplane(offset=5)")["classification"] == "current_supported"


def test_analyzer_distinguishes_receiver_return_chain_signature_and_unknown_failures() -> None:
    result = analyze_geometry_statements(
        [
            "solid = cq.Solid.makeBox(1, 1, 1)",
            "wrong_receiver = solid.workplane(offset=5)",
            "bad_keyword = cq.Workplane('XY').box(1, 2, 3, no_such_keyword=True)",
            "bad_argument = cq.Workplane('XY').box('1', 2, 3)",
            "shape = cq.Workplane('XY').box(1, 2, 3).val()",
            "return_chain = shape.box(1, 2, 3)",
            "unknown = cq.Workplane('XY').not_a_cadquery_method()",
        ]
    )

    assert _call(result, "workplane", "wrong_receiver = solid.workplane(offset=5)")["classification"] == "current_receiver_type_mismatch"
    assert _call(result, "box", "bad_keyword = cq.Workplane('XY').box(1, 2, 3, no_such_keyword=True)")["classification"] == "current_signature_mismatch"
    assert _call(result, "box", "bad_argument = cq.Workplane('XY').box('1', 2, 3)")["classification"] == "current_argument_type_mismatch"
    assert _call(result, "box", "return_chain = shape.box(1, 2, 3)")["classification"] == "current_return_chain_mismatch"
    assert _call(result, "not_a_cadquery_method")["classification"] == "unknown_or_hallucinated"
    assert set(result["classifications"]) <= API_REFERENCE_CLASSIFICATIONS


def test_analyzer_records_namespace_provenance_and_chained_return_types() -> None:
    result = analyze_geometry_statements(
        [
            "from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut",
            "cut = BRepAlgoAPI_Cut()",
            "wire = cq.Workplane('XY').rect(10, 10).wire()",
        ]
    )

    ocp = next(item for item in result["references"] if item.get("method") == "BRepAlgoAPI_Cut")
    assert ocp["namespace_provenance"] == "direct_ocp_import"
    assert ocp["classification"] == "direct_ocp_version_sensitive"
    wire = _call(result, "wire")
    assert wire["return_type"] == "Workplane"
    assert wire["next_receiver_type"] == "Workplane"


def test_raw_corpus_deduplicates_for_analysis_but_preserves_every_occurrence(tmp_path) -> None:
    response = {
        "response": {
            "candidates": [{
                "content": {"parts": [{"text": '{"schema_version":"volundr-geometry-slots-v1","slots":[{"slot_id":0,"result_symbol":"body","statements":["body = cq.Workplane(\\"XY\\")"]}]}'}]}
            }]
        },
        "project_id": "project-a",
        "stage": "geometry",
    }
    first = tmp_path / "provider-attempts" / "one.json"
    second = tmp_path / "provider-attempts" / "two.json"
    first.parent.mkdir()
    first.write_text(json.dumps(response), encoding="utf-8")
    second.write_text(json.dumps(response), encoding="utf-8")

    corpus = discover_raw_corpus(tmp_path)

    assert corpus["occurrence_count"] == 2
    assert corpus["unique_content_count"] == 1
    assert corpus["geometry_occurrence_count"] == 2
    assert corpus["corpus_policy"]["statement_rewriting"] is False
    assert all(item["exact_statements"] == ['body = cq.Workplane("XY")'] for item in corpus["occurrences"])
