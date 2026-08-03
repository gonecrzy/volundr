import trimesh

from app.services.geometry.feature_evidence import evaluate_feature_evidence


def _trace(*, feature_id: str, changed: bool = True) -> dict:
    return {
        "feature_id": feature_id,
        "source_function_id": f"_ai_feature_{feature_id}",
        "source_executed": True,
        "shape_changed": changed,
        "input_shape_hash": "before",
        "output_shape_hash": "after" if changed else "before",
        "operation_category": "subtractive" if changed else "no_effect",
    }


def test_source_declaration_alone_does_not_satisfy_requirement() -> None:
    evaluation = evaluate_feature_evidence(
        mesh=trimesh.creation.box(extents=(10, 10, 10)),
        output_id="body",
        requirement_trace={
            "features": [{"feature_id": "handle", "object_type": "handle", "requirement_ids": ["req_handle"]}],
            "validation_targets": [],
        },
        feature_trace=[],
    )

    record = evaluation.records[0]
    assert record.requirement_outcome == "unverifiable"
    assert record.source_executed is None
    assert record.geometry_presence == "unknown"
    assert evaluation.trace_findings[0]["rule_id"] == "feature.trace_missing"


def test_executed_feature_with_no_geometry_change_emits_no_effect() -> None:
    evaluation = evaluate_feature_evidence(
        mesh=trimesh.creation.box(extents=(10, 10, 10)),
        output_id="body",
        requirement_trace={
            "features": [{"feature_id": "slot", "object_type": "slot", "requirement_ids": ["req_slot"]}],
            "validation_targets": [],
        },
        feature_trace=[_trace(feature_id="slot", changed=False)],
    )

    assert evaluation.records[0].requirement_outcome == "feature_absent"
    assert evaluation.trace_findings[0]["rule_id"] == "feature.source_no_effect"


def test_ambiguous_runtime_trace_remains_unverifiable() -> None:
    trace = _trace(feature_id="slot")
    evaluation = evaluate_feature_evidence(
        mesh=trimesh.creation.box(extents=(220, 140, 65)),
        output_id="organizer",
        requirement_trace={
            "features": [{"feature_id": "slot", "object_type": "slot", "requirement_ids": ["req_slot"]}],
            "validation_targets": [],
        },
        feature_trace=[trace, trace],
    )

    assert evaluation.records[0].requirement_outcome == "unverifiable"
    assert evaluation.trace_findings[0]["rule_id"] == "feature.trace_ambiguous"


def test_final_mesh_dimension_is_measured_not_inferred_from_source_name() -> None:
    evaluation = evaluate_feature_evidence(
        mesh=trimesh.creation.box(extents=(220, 140, 65)),
        output_id="organizer",
        requirement_trace={
            "features": [{"feature_id": "main_body", "object_type": "desktop organizer", "requirement_ids": ["req_width"]}],
            "validation_targets": [{"feature_id": "main_body", "measurement": "width", "requirement_ids": ["req_width"], "value": 220}],
        },
        feature_trace=[_trace(feature_id="main_body")],
        topology_metadata={"expected_solid_count": 1},
    )

    record = evaluation.records[0]
    assert record.measurement_status == "measured"
    assert record.requirement_outcome == "satisfied"
    assert record.evidence_method == "final_mesh_bounds"
