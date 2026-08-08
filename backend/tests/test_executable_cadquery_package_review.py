from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from app.services.executable_cadquery.package_review import build_neutral_measurement_report
from app.services.executable_cadquery.review import (
    build_blind_review_packet,
    build_blind_review_record,
)


FROZEN_P1_PACKAGE = (
    Path(__file__).resolve().parents[2]
    / "data/debug-sessions/executable-cadquery/recovery-wave-01/frozen-corpus/project-01/package.zip"
)


def _manifest(package_path: Path) -> dict:
    with ZipFile(package_path) as archive:
        return json.loads(archive.read("manifest.json"))


def test_neutral_measurement_report_contains_standardized_geometry_and_hash_facts() -> None:
    manifest = _manifest(FROZEN_P1_PACKAGE)

    report = build_neutral_measurement_report(FROZEN_P1_PACKAGE, manifest)

    assert report["schema_version"] == "executable-cadquery-neutral-measurement-v1"
    assert report["units"] == "mm"
    assert report["output_identities"] == ["mounting_bracket_regression"]
    output = report["outputs"][0]
    assert output["solid_count"] == 1
    assert output["bounding_box_mm"]["size"] == [90.0, 55.0, 10.0]
    assert output["volume_mm3"] > 0
    assert output["artifact_hashes"]["stl"]["declared_sha256"]
    assert output["artifact_hashes"]["stl"]["observed_sha256"] == output["artifact_hashes"]["stl"]["declared_sha256"]
    assert output["hole_or_cylinder_measurements"]
    assert all(
        measurement["evidence_type"] == "stl_circular_profile_candidate"
        and measurement["physical_feature_verified"] is False
        for measurement in output["hole_or_cylinder_measurements"]
    )
    assert output["planar_face_measurements"]
    assert report["relationships"] == []


def test_neutral_report_does_not_copy_contract_expectations() -> None:
    manifest = _manifest(FROZEN_P1_PACKAGE)

    report = build_neutral_measurement_report(FROZEN_P1_PACKAGE, manifest)
    serialized = json.dumps(report, sort_keys=True)

    assert "expected_solid_count" not in serialized
    assert "body_dimensions" not in serialized
    assert "verification_policy" not in serialized


def test_neutral_report_records_revision_deltas() -> None:
    manifest = _manifest(FROZEN_P1_PACKAGE)
    previous = build_neutral_measurement_report(FROZEN_P1_PACKAGE, manifest)

    report = build_neutral_measurement_report(
        FROZEN_P1_PACKAGE,
        manifest,
        previous_report=previous,
    )

    assert report["revision_deltas"] == [
        {
            "output_id": "mounting_bracket_regression",
            "artifact_hash_changed": False,
            "solid_count_delta": 0,
            "volume_delta_mm3": 0.0,
            "bounding_box_size_delta_mm": [0.0, 0.0, 0.0],
        }
    ]


def test_blind_review_packet_excludes_producer_history_and_source_quality() -> None:
    manifest = _manifest(FROZEN_P1_PACKAGE)
    report = build_neutral_measurement_report(FROZEN_P1_PACKAGE, manifest)

    packet = build_blind_review_packet(
        original_prompt="Create a mounting bracket.",
        clarifications=[{"question": "Units?", "answer": "mm"}],
        revisions=[{"instruction": "Keep the output identity."}],
        final_output_identities=report["output_identities"],
        neutral_measurement_report=report,
        fixed_views=["front.png", "isometric.png"],
        units="mm",
        package_manifest={
            "schema_version": "package-v1",
            "canonical_output_ids": ["mounting_bracket_regression"],
            "artifacts": [{"output_id": "mounting_bracket_regression", "sha256": "hash"}],
            "provider_and_contract_provenance": {"repair_history": ["must not be shared"]},
            "semantic_verification": {"status": "must not be shared"},
            "source": "must not be shared",
        },
        producer_history={"repair_history": ["must not be shared"], "source": "must not be shared"},
    )

    assert packet["schema_version"] == "executable-cadquery-blind-review-packet-v1"
    assert packet["final_output_identities"] == ["mounting_bracket_regression"]
    serialized = json.dumps(packet, sort_keys=True)
    assert "repair_history" not in serialized
    assert "must not be shared" not in serialized


def test_blind_review_record_normalizes_requirement_verdicts() -> None:
    record = build_blind_review_record(
        review_cycle=1,
        reviewer_result={
            "reviewer": "blind_codex_cad_qa_v1",
            "requirements": [
                {"requirement_id": "body_dimensions", "verdict": "satisfied"},
                {"requirement_id": "hole", "verdict": "violated"},
            ],
            "final_verdict": "FAIL",
        },
        candidate_policy={"state": "candidate_ready_for_review", "blockers": []},
    )

    assert [item["verdict"] for item in record["requirements"]] == ["satisfied", "violated"]
    assert record["final_verdict"] == "FAIL"


def test_blind_review_pass_is_vetoed_by_deterministic_volundr_failure() -> None:
    record = build_blind_review_record(
        review_cycle=1,
        reviewer_result={
            "requirements": [
                {
                    "requirement_id": "body_dimensions",
                    "evidence_type": "neutral_measurement",
                    "observed": {"size_mm": [90.0, 55.0, 10.0]},
                    "verdict": "PASS",
                    "discrepancies": [],
                }
            ],
            "revision_preservation": {"output_identity_preserved": True},
            "final_verdict": "PASS",
        },
        candidate_policy={"state": "candidate_blocked", "blockers": ["topology"]},
    )

    assert record["final_verdict"] == "PASS"
    assert record["disposition"] == "vetoed_by_deterministic_failure"
    assert record["accepted_for_candidate"] is False
