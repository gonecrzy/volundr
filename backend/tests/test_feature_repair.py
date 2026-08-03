import pytest

from app.services.geometry.feature_repair import (
    build_feature_repair_context,
    validate_feature_repair_result,
)


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
        after={"output_ids": ["body"], "hashes": {"slot_2": "unchanged"}, "detected_solid_count": 1, "handle": "connected"},
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
