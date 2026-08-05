import json
from pathlib import Path

from app.services.gemini_integration.cadquery_dialect import (
    CADQUERY_ISSUE_CLASSES,
    API_REFERENCE_CLASSIFICATIONS,
    characterize_geometry_statements,
    diagnose_wave_geometry_compatibility,
)
from app.services.gemini_integration.representative_waves import WaveEvidenceStore


def test_characterization_preserves_exact_statements_and_records_signatures() -> None:
    statements = (
        "body = cq.Workplane('XY').box(10, 20, 3, centered=(False, False, False))",
        "body = body.fictional_method(rotation=90)",
    )

    result = characterize_geometry_statements(statements, project_id="project-01")

    assert result["statements"] == list(statements)
    assert set(result["classifications"]) <= API_REFERENCE_CLASSIFICATIONS
    box = next(item for item in result["references"] if item["method"] == "box")
    assert box["statement"] == statements[0]
    assert "centered" in box["keywords"]
    assert box["runtime_signature"]
    hallucinated = next(item for item in result["references"] if item["method"] == "fictional_method")
    assert hallucinated["classification"] == "unknown_or_hallucinated"
    assert hallucinated["issue_class"] == "hallucinated_cadquery_api"


def test_signature_mismatch_and_direct_ocp_are_distinguished() -> None:
    result = characterize_geometry_statements(
        (
            "body = cq.Workplane('XY').box(10, 20, 3, not_a_box_keyword=True)",
            "from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut",
            "result = BRepAlgoAPI_Cut(foo=True)",
        ),
        project_id="project-02",
    )

    box = next(item for item in result["references"] if item["method"] == "box")
    assert box["classification"] == "current_signature_mismatch"
    assert box["issue_class"] == "obsolete_cadquery_signature"
    ocp = [item for item in result["references"] if item["root"] == "OCP"]
    assert ocp
    assert all(item["classification"] == "direct_ocp_version_sensitive" for item in ocp)
    assert set(result["issue_classes"]) <= CADQUERY_ISSUE_CLASSES


def test_wave_diagnosis_keeps_provider_response_unmodified_and_classifies_worker_failures(tmp_path: Path) -> None:
    store = WaveEvidenceStore(tmp_path / "wave", wave_id="wave-test")
    raw_response = json.dumps({
        "schema_version": "volundr-geometry-slots-v1",
        "slots": [{"slot_id": 0, "result_symbol": "body", "statements": [
            "body = cq.Workplane('XY').slot1D(10, 2)",
        ]}],
    })
    store.record_boundary({
        "boundary_id": "project-01:provider_geometry",
        "boundary": "provider_geometry",
        "project_id": "project-01",
        "output": {"text": raw_response, "attempt_ids": ["attempt-01"]},
    })
    store.record_boundary({
        "boundary_id": "project-01:worker",
        "boundary": "worker",
        "project_id": "project-01",
        "output": {"success": False, "failure_class": "timeout", "error_message": "timed out"},
    })

    report = diagnose_wave_geometry_compatibility(store)

    project = report["projects"][0]
    assert project["raw_provider_responses"][0]["text"] == raw_response
    assert project["raw_provider_responses"][0]["statements"] == ["body = cq.Workplane('XY').slot1D(10, 2)"]
    assert project["statements_modified"] is False
    assert "hallucinated_cadquery_api" in project["issue_classes"]
    assert project["worker_execution"]["failure_class"] == "timeout"
