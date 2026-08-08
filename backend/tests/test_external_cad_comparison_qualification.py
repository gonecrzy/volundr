from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
QUALIFICATION_ROOT = REPO_ROOT / "benchmarks/external/cad-50-v1.1"


def _json(name: str) -> dict:
    return json.loads((QUALIFICATION_ROOT / name).read_text(encoding="utf-8"))


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for child in value.values() for key in _keys(child)}
    if isinstance(value, list):
        return {key for child in value for key in _keys(child)}
    return set()


def test_development_audit_has_exactly_thirty_projects_and_summary() -> None:
    audit = _json("development-audit-30.json")

    assert audit["development_project_count"] == 30
    assert len(audit["projects"]) == 30
    assert audit["summary"] == {
        "comparison_ready_without_changes": 0,
        "enriched_to_comparison_ready": 2,
        "still_underconstrained": 25,
        "replacement_required": 3,
    }


def test_v11_manifest_seals_holdout_without_detail_fields() -> None:
    manifest = _json("manifest.json")
    holdouts = [project for project in manifest["projects"] if project["split_assignment"] == "holdout"]

    assert len(holdouts) == 10
    assert all(
        set(project) == {
            "benchmark_id",
            "category",
            "comparison_specification_hash",
            "split_assignment",
            "status",
        }
        for project in holdouts
    )
    assert all(project["status"] == "sealed" for project in holdouts)
    assert all("premise" not in project and "reference_spec" not in project for project in holdouts)


def test_development_and_validation_specs_have_provenance_and_no_mesh_payloads() -> None:
    for filename, expected_count in (
        ("comparison-specifications-development.json", 30),
        ("comparison-specifications-validation.json", 10),
    ):
        payload = _json(filename)
        assert len(payload["projects"]) == expected_count
        for project in payload["projects"]:
            assert all(
                fact["provenance"] in {
                    "creator_documented",
                    "reference_geometry_measured",
                    "manual_benchmark_annotation",
                }
                for fact in project["facts"]
            )
            assert not _keys(project) & {"vertices", "faces", "point_cloud", "raw_mesh"}


def test_methodology_freezes_same_rules_for_validation_and_holdout() -> None:
    methodology = _json("comparison-methodology.json")

    assert methodology["methodology_version"] == "external-cad-comparison-extraction-v1"
    assert methodology["validation_policy"] == "apply unchanged; do not tune per project after development results"
    assert methodology["holdout_policy"] == "apply unchanged and persist only allowed metadata plus sealed hashes"
