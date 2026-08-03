import pytest
from types import SimpleNamespace

from app.services.geometry.feature_repair import (
    build_feature_repair_context,
    is_feature_repair_request,
    validate_feature_repair_result,
)
from app.services.projects.service import ProjectService


def _finding(feature_id: str, *, protected_hashes=None) -> dict:
    return {
        "feature_id": feature_id,
        "metadata": {
            "requirement_ids": [f"req_{feature_id}"],
            "source_function_id": f"_ai_feature_{feature_id}",
            "measurements": {"connected_to_primary_body": False},
            "protected_hashes": protected_hashes or {"slot_2": "unchanged"},
        },
    }


def test_feature_repair_context_targets_one_feature_and_one_provider_call() -> None:
    context = build_feature_repair_context(
        [_finding("handle")],
        worker_succeeded=True,
        topology_valid=True,
    )

    assert context.feature_id == "handle"
    assert context.max_provider_calls == 1
    assert "Do not change unrelated feature slots." in context.prohibited_changes


def test_geometric_finding_with_one_feature_is_a_bounded_repair_request() -> None:
    finding = _finding("handle") | {"category": "geometry_feature", "rule_id": "feature.evidence.handle.req_handle"}

    assert is_feature_repair_request("geometric_finding", [finding]) is True
    assert is_feature_repair_request("geometric_finding", []) is False
    assert is_feature_repair_request("geometric_finding", [_finding("handle"), _finding("drainage")]) is False


def test_feature_repair_rejects_multiple_features_and_unchanged_results() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        build_feature_repair_context(
            [_finding("handle"), _finding("drainage")],
            worker_succeeded=True,
            topology_valid=True,
        )
    context = build_feature_repair_context(
        [_finding("handle")], worker_succeeded=True, topology_valid=True
    )
    before = {"output_ids": ["body"], "hashes": {"slot_2": "unchanged"}}
    assert validate_feature_repair_result(
        context, before=before, after=before, provider_calls=1
    )["reason"] == "repair_unchanged"


def test_feature_repair_preserves_unaffected_hashes_and_rejects_disconnected_output() -> None:
    context = build_feature_repair_context(
        [_finding("handle")], worker_succeeded=True, topology_valid=True
    )
    before = {"output_ids": ["body"], "hashes": {"slot_2": "unchanged"}}
    accepted = validate_feature_repair_result(
        context,
        before=before,
        after={
            "output_ids": ["body"],
            "hashes": {"slot_2": "unchanged"},
            "detected_solid_count": 1,
            "feature_evidence": {
                "feature_id": "handle",
                "requirement_outcome": "satisfied",
                "measurement_status": "measured",
                "measurements": {
                    "connected_to_primary_body": True,
                    "material_overlap_volume_estimate_mm3": 2,
                },
            },
        },
        provider_calls=1,
    )
    rejected = validate_feature_repair_result(
        context,
        before=before,
        after={"output_ids": ["body"], "hashes": {"slot_2": "unchanged"}, "detected_solid_count": 2},
        provider_calls=1,
    )

    assert accepted["accepted"] is True
    assert rejected["reason"] == "repair_disconnected_output"


def test_feature_repair_requires_satisfied_final_evidence() -> None:
    context = build_feature_repair_context(
        [_finding("handle")], worker_succeeded=True, topology_valid=True
    )
    before = {"output_ids": ["body"], "hashes": {"slot_2": "unchanged"}}

    accepted = validate_feature_repair_result(
        context,
        before=before,
        after={
            "output_ids": ["body"],
            "hashes": {"slot_2": "unchanged"},
            "detected_solid_count": 1,
            "feature_evidence": {
                "feature_id": "handle",
                "requirement_outcome": "satisfied",
                "measurement_status": "measured",
                "measurements": {
                    "connected_to_primary_body": True,
                    "material_overlap_volume_estimate_mm3": 4.0,
                },
            },
        },
        provider_calls=1,
    )
    rejected = validate_feature_repair_result(
        context,
        before=before,
        after={
            "output_ids": ["body"],
            "hashes": {"slot_2": "unchanged"},
            "detected_solid_count": 1,
            "feature_evidence": {
                "feature_id": "handle",
                "requirement_outcome": "not_satisfied",
                "measurement_status": "measured",
                "measurements": {"connected_to_primary_body": False},
            },
        },
        provider_calls=1,
    )

    assert accepted["accepted"] is True
    assert rejected["reason"] == "repair_feature_not_satisfied"

    missing = validate_feature_repair_result(
        context,
        before=before,
        after={
            "output_ids": ["body"],
            "hashes": {"slot_2": "unchanged"},
            "detected_solid_count": 1,
        },
        provider_calls=1,
    )
    assert missing["reason"] == "repair_feature_evidence_missing"


def test_project_service_rejects_repair_without_final_feature_evidence(tmp_path) -> None:
    class FakeDb:
        def __init__(self):
            self.added = []
            self.scalar_calls = 0
            self.scalars_calls = 0

        def scalars(self, _statement):
            self.scalars_calls += 1
            if self.scalars_calls == 1:
                return [
                    SimpleNamespace(
                        id="new-output",
                        output_id="body",
                        detected_solid_count=1,
                    )
                ]
            return [SimpleNamespace(output_id="body")]

        def scalar(self, _statement):
            self.scalar_calls += 1
            return SimpleNamespace(result_path="analysis.json")

        def add(self, value):
            self.added.append(value)

        def flush(self):
            return None

    finding = _finding("handle")
    finding["metadata"]["output_id"] = "body"
    context = build_feature_repair_context(
        [finding], worker_succeeded=True, topology_valid=True
    )
    db = FakeDb()
    service = ProjectService(db=db, data_dir=tmp_path)
    events = []
    service._read_json_file = lambda _path: {
        "feature_evidence": [
            {
                "feature_id": "handle",
                "requirement_outcome": "not_satisfied",
                "measurement_status": "measured",
                "measurements": {"connected_to_primary_body": False},
            }
        ]
    }
    service._record_workflow_event = lambda *args, **kwargs: events.append(kwargs)

    result = service._persist_feature_repair_validation(
        revision=SimpleNamespace(id="new-revision", parent_revision_id="base-revision"),
        context=context,
        workflow_run=SimpleNamespace(id="workflow"),
    )

    assert result["accepted"] is False
    assert result["reason"] == "repair_feature_not_satisfied"
    assert db.added[-1].rule_id == "feature.repair_rejected"
    assert events[-1]["event_type"] == "feature_repair.validated"
