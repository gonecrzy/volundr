from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.gemini_integration.transport import SecondaryGeminiClient
from app.services.research.t5_final_revision_microstudy import (
    FINAL_STUDY_ID,
    OUTPUT_ID,
    RESULT_SYMBOL,
    build_final_tasks,
    known_good_body_initializer,
    known_good_statements,
    revision_delta_report,
)
from scripts.run_t5_final_revision_microstudy import (
    MAX_LOGICAL_OPERATIONS,
    _authority_product_source_without_parameters,
    _hash_bundle,
    _profile,
    run_live,
    run_study,
)


def test_final_tasks_have_explicit_order_and_no_stale_body_output_identity() -> None:
    tasks = build_final_tasks()

    assert FINAL_STUDY_ID == "t5-final-revision-microstudy-01"
    assert MAX_LOGICAL_OPERATIONS == 3
    assert [task.task_id for task in tasks] == [
        "t5-final-revision-microstudy-01-task-01",
        "t5-final-revision-microstudy-01-task-02",
        "t5-final-revision-microstudy-01-task-03",
    ]
    for task in tasks:
        assert task.output_ids == (OUTPUT_ID,)
        assert task.request.output_manifest["outputs"][0]["output_id"] == OUTPUT_ID
        assert task.request.geometry_slot_manifest["output_obligations"][0]["output_id"] == OUTPUT_ID
        assert task.request.geometry_slot_manifest["slots"][0]["required_result"] == RESULT_SYMBOL
        assert task.semantic_facts["output_id"] == OUTPUT_ID


def test_revision_deltas_are_complete_and_capsule_slot_is_explicit() -> None:
    tasks = build_final_tasks()

    for task in tasks:
        report = revision_delta_report(task)
        assert report["complete"] is True
        assert report["output_id"] == OUTPUT_ID
        assert report["prior_output_id"] == OUTPUT_ID
        for change in report["changed_features"]:
            assert {
                "prior_feature_dimensions",
                "requested_feature_dimensions",
                "owning_face",
                "local_coordinate_frame",
                "feature_center_local_mm",
                "feature_axis",
                "depth_direction",
                "depth_mode",
            }.issubset(change)

    slot = tasks[1].semantic_facts["revision_delta"]["changed_features"][0]["requested_feature_dimensions"]
    assert slot["profile_type"] == "rounded_end_capsule"
    assert slot["overall_length_mm"] == 18
    assert slot["width_mm"] == 5
    assert slot["end_radius_mm"] == slot["width_mm"] / 2
    assert slot["depth_mode"] == "blind"
    assert slot["depth_mm"] == 3


def test_known_good_controls_are_synthetic_and_do_not_change_provider_fixture() -> None:
    assert "hole(6)" in known_good_body_initializer("left_hole")
    assert known_good_statements("left_hole") == []
    assert known_good_statements("slot")
    assert known_good_statements("right_hole_and_slot") == known_good_statements("slot")

    task = build_final_tasks()[0]
    assert "pushPoints([(12, 13), (34, 31)]).hole(5)" in task.body_initializer
    assert "pushPoints([(12, 13)]).hole(6)" not in task.body_initializer


@pytest.mark.asyncio
async def test_offline_certification_makes_zero_provider_calls_and_excludes_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail_provider(*args, **kwargs):
        raise AssertionError("offline certification must not call Gemini")

    monkeypatch.setattr(SecondaryGeminiClient, "generate", fail_provider)
    result = await run_study(root=tmp_path / "reports", worker_root=tmp_path / "workers", live=False)

    assert result["certification"]["status"] == "passed"
    assert result["certification"]["provider_calls"] == 0
    controls = json.loads((tmp_path / "reports" / "known-good-counterfactuals.json").read_text())["controls"]
    assert len(controls) == 3
    assert all(item["synthetic"] is True and item["provider_success_eligible"] is False for item in controls)


@pytest.mark.asyncio
async def test_live_refuses_frozen_hash_mismatch_before_secondary_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks = build_final_tasks()
    root = tmp_path / "reports"
    root.mkdir()
    current = _hash_bundle(tasks, _profile(), authority_source=_authority_product_source_without_parameters())
    frozen = dict(current)
    frozen["fixture_hash"] = "mismatch"
    (root / "fixture-certification.json").write_text(json.dumps({"status": "passed"}))
    (root / "frozen-hashes.json").write_text(json.dumps(frozen))
    (root / "preregistration.json").write_text(json.dumps({
        "live_authorized": True,
        "execution_order": [task.task_id for task in tasks],
    }))

    def credential_must_not_be_requested():
        raise AssertionError("credential lookup must occur after frozen-hash validation")

    monkeypatch.setattr("scripts.run_t5_final_revision_microstudy.require_secondary_credential", credential_must_not_be_requested)

    with pytest.raises(RuntimeError, match="frozen hashes disagree"):
        await run_live(root=root, worker_root=tmp_path / "workers")


def test_worker_success_does_not_mask_provider_owned_semantic_geometry_failure() -> None:
    task = build_final_tasks()[1]
    from scripts.run_t5_final_revision_microstudy import _task_row

    row = _task_row(
        task,
        {
            "operation_id": task.task_id,
            "raw_provider_output": "{}",
            "classification": {
                "contract_valid": True,
                "parameter_access_valid": True,
                "semantic_obligations": True,
                "first_incorrect_boundary": None,
                "failure_classes": [],
                "semantic": {"parameter_access": {}},
                "validation": {},
                "payload": {
                    "schema_version": "volundr-geometry-slots-v1",
                    "slots": [{
                        "slot_id": 0,
                        "result_symbol": "body",
                        "statements": ['body = body.hole(params["slot_width_mm"])'],
                    }],
                },
            },
            "worker_execution": True,
            "worker": {"success": True},
            "feature_verification": {
                "passed": False,
                "protected_features_preserved": False,
                "output_identity": OUTPUT_ID,
            },
        },
        expected="slot",
        worker_calls=1,
    )

    assert row["worker_execution"] is True
    assert row["candidate_eligible"] is False
    assert row["first_incorrect_boundary"] == "topology_or_feature_verification"
    assert row["provider_owned_failure"] is True
    assert row["runtime_api_failure"] is False
    assert "semantic_geometry_failure" in row["failure_classes"]
