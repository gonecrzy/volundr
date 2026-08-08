from __future__ import annotations

import json
from pathlib import Path

import pytest
import trimesh

from app.services.external_benchmarks.comparison import compare_reference_geometry
from app.services.external_benchmarks.ingestion import (
    BenchmarkImportError,
    import_reference,
    sha256_file,
)
from app.services.external_benchmarks.models import (
    BenchmarkManifest,
    BenchmarkRunRecord,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PILOT_MANIFEST = REPO_ROOT / "benchmarks/external/mounting-brackets-v1/manifest.json"


def _source_metadata() -> dict:
    return {
        "source_site": "example-cad-site",
        "source_url": "https://example.invalid/reference",
        "creator": "Example creator",
        "source_title": "Example mounting bracket",
        "license": "CC BY 4.0",
        "acquired_at": "2026-08-08",
        "original_filename": "example-bracket.stl",
        "premise": "Design a useful mounting bracket for a small device.",
        "reference_spec": {
            "units": "mm",
            "facts": [
                {
                    "id": "overall_width",
                    "value": 42.0,
                    "unit": "mm",
                    "provenance": "reference_geometry_measured",
                }
            ],
        },
    }


def _write_cube_stl(path: Path) -> None:
    mesh = trimesh.creation.box(extents=(12.0, 8.0, 4.0))
    mesh.export(path, file_type="stl")


def test_pilot_manifest_has_five_neutral_placeholder_slots() -> None:
    manifest = BenchmarkManifest.from_path(PILOT_MANIFEST)

    assert manifest.benchmark_id == "mounting-brackets-v1"
    assert len(manifest.projects) == 5
    assert [project.benchmark_id for project in manifest.projects] == [
        "mounting-bracket-001",
        "mounting-bracket-002",
        "mounting-bracket-003",
        "mounting-bracket-004",
        "mounting-bracket-005",
    ]
    assert all(project.status == "placeholder" for project in manifest.projects)
    assert all(project.split_assignment == "pilot" for project in manifest.projects)


def test_manifest_rejects_duplicate_project_ids() -> None:
    payload = {
        "schema_version": "external-cad-benchmark-manifest-v1",
        "benchmark_id": "test-v1",
        "benchmark_version": "1.0.0",
        "target_project_count": 50,
        "target_category_count": 10,
        "projects": [
            {"benchmark_id": "mounting-bracket-001", "category": "mounting_brackets", "status": "placeholder", "split_assignment": "pilot"},
            {"benchmark_id": "mounting-bracket-001", "category": "mounting_brackets", "status": "placeholder", "split_assignment": "pilot"},
        ],
    }

    with pytest.raises(ValueError, match="unique"):
        BenchmarkManifest.from_dict(payload)


def test_sha256_file_is_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "reference.stl"
    path.write_bytes(b"reference-bytes")

    assert sha256_file(path) == sha256_file(path)
    assert len(sha256_file(path)) == 64


def test_import_stl_preserves_bytes_and_persists_derived_facts(tmp_path: Path) -> None:
    repo_root = tmp_path
    manifest_path = repo_root / "benchmarks/external/mounting-brackets-v1/manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "external-cad-benchmark-manifest-v1",
                "benchmark_id": "mounting-brackets-v1",
                "benchmark_version": "1.0.0",
                "target_project_count": 50,
                "target_category_count": 10,
                "pilot_category": "mounting_brackets",
                "split_policy": {"allowed_assignments": ["pilot", "holdout"]},
                "projects": [
                    {
                        "benchmark_id": "mounting-bracket-001",
                        "category": "mounting_brackets",
                        "status": "placeholder",
                        "split_assignment": "pilot",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    source_path = tmp_path / "source.json"
    source_path.write_text(json.dumps(_source_metadata()), encoding="utf-8")
    original = tmp_path / "downloaded-bracket.stl"
    _write_cube_stl(original)
    original_bytes = original.read_bytes()

    result = import_reference(
        benchmark="mounting-brackets-v1",
        project="mounting-bracket-001",
        source_metadata_path=source_path,
        reference_file=original,
        manifest_path=manifest_path,
        output_root=repo_root / "data/external-benchmarks",
        repository_root=repo_root,
    )

    stored_path = Path(result["reference_path"])
    assert original.read_bytes() == original_bytes
    assert stored_path.read_bytes() == original_bytes
    assert result["reference_sha256"] == sha256_file(original)
    assert result["derived_reference"]["file_type"] == "stl"
    assert result["derived_reference"]["mesh"]["face_count"] == 12
    assert result["derived_reference"]["geometry"]["solid_count"] == 1
    assert result["derived_reference"]["geometry"]["bounding_box_mm"]["size_x"] == pytest.approx(12.0)
    assert (stored_path.parent.parent / "source.json").exists()
    assert (stored_path.parent.parent / "premise.txt").read_text(encoding="utf-8") == _source_metadata()["premise"]
    assert (stored_path.parent.parent / "reference-spec.json").exists()

    updated = BenchmarkManifest.from_path(manifest_path)
    project = updated.projects[0]
    assert project.status == "imported"
    assert project.reference_files[0].sha256 == result["reference_sha256"]
    assert project.source_url == _source_metadata()["source_url"]
    persisted_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert persisted_manifest["pilot_category"] == "mounting_brackets"
    assert persisted_manifest["split_policy"]["allowed_assignments"] == ["pilot", "holdout"]


def test_import_rejects_missing_reference_file(tmp_path: Path) -> None:
    with pytest.raises(BenchmarkImportError, match="does not exist"):
        import_reference(
            benchmark="mounting-brackets-v1",
            project="mounting-bracket-001",
            source_metadata_path=tmp_path / "source.json",
            reference_file=tmp_path / "missing.stl",
            manifest_path=tmp_path / "manifest.json",
            output_root=tmp_path / "data",
            repository_root=tmp_path,
        )


def test_import_rejects_malformed_stl_without_creating_reference_artifacts(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "external-cad-benchmark-manifest-v1",
                "benchmark_id": "mounting-brackets-v1",
                "benchmark_version": "1.0.0",
                "target_project_count": 50,
                "target_category_count": 10,
                "projects": [{"benchmark_id": "mounting-bracket-001", "category": "mounting_brackets", "status": "placeholder", "split_assignment": "pilot"}],
            }
        ),
        encoding="utf-8",
    )
    source_path = tmp_path / "source.json"
    source_path.write_text(json.dumps(_source_metadata()), encoding="utf-8")
    bad_reference = tmp_path / "not-a-model.stl"
    bad_reference.write_text("not a valid STL", encoding="utf-8")

    with pytest.raises(BenchmarkImportError, match="geometry"):
        import_reference(
            benchmark="mounting-brackets-v1",
            project="mounting-bracket-001",
            source_metadata_path=source_path,
            reference_file=bad_reference,
            manifest_path=manifest_path,
            output_root=tmp_path / "data",
            repository_root=tmp_path,
        )
    assert not (tmp_path / "data/external-benchmarks").exists()


def test_premise_and_reference_spec_are_separate_from_provenance(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "external-cad-benchmark-manifest-v1",
                "benchmark_id": "mounting-brackets-v1",
                "benchmark_version": "1.0.0",
                "target_project_count": 50,
                "target_category_count": 10,
                "projects": [{"benchmark_id": "mounting-bracket-001", "category": "mounting_brackets", "status": "placeholder", "split_assignment": "pilot"}],
            }
        ),
        encoding="utf-8",
    )
    source_path = tmp_path / "source.json"
    metadata = _source_metadata()
    source_path.write_text(json.dumps(metadata), encoding="utf-8")
    reference = tmp_path / "reference.stl"
    _write_cube_stl(reference)

    result = import_reference(
        benchmark="mounting-brackets-v1",
        project="mounting-bracket-001",
        source_metadata_path=source_path,
        reference_file=reference,
        manifest_path=manifest_path,
        output_root=tmp_path / "data",
        repository_root=tmp_path,
    )
    project_dir = Path(result["reference_path"]).parent.parent

    assert result["project"]["premise"] == metadata["premise"]
    assert result["project"]["reference_spec"] == metadata["reference_spec"]
    assert json.loads((project_dir / "source.json").read_text(encoding="utf-8"))["source_url"] == metadata["source_url"]
    assert "source_url" not in (project_dir / "reference-spec.json").read_text(encoding="utf-8")


def test_run_record_round_trips_and_keeps_requirement_and_similarity_independent() -> None:
    record = BenchmarkRunRecord.from_dict(
        {
            "schema_version": "external-cad-benchmark-run-v1",
            "benchmark_project_id": "mounting-bracket-001",
            "mode": "premise_only",
            "provider_model_profile": {"provider": "gemini_api", "model": "test-model"},
            "prompt_hashes": {"user_request": "a" * 64},
            "workflow_id": "workflow-1",
            "revision_id": "revision-1",
            "provider_attempt_ids": ["attempt-1"],
            "generated_source_hash": "b" * 64,
            "worker_result": {"status": "succeeded"},
            "brep_topology_result": {"solid_count": 1},
            "semantic_verification_result": {"status": "passed"},
            "artifact_hashes": {"step": "c" * 64},
            "reference_metrics": {"reference_similarity": {"status": "not_run"}},
            "failure_stage": None,
            "failure_class": None,
            "first_incorrect_owner": None,
        }
    )

    assert BenchmarkRunRecord.from_dict(record.to_dict()).mode == "premise_only"
    with pytest.raises(ValueError, match="mode"):
        BenchmarkRunRecord.from_dict({**record.to_dict(), "mode": "unknown"})


def test_reference_comparison_keeps_requirement_compliance_separate() -> None:
    result = compare_reference_geometry(
        reference={
            "geometry": {"bounding_box_mm": {"size_x": 10.0, "size_y": 8.0, "size_z": 4.0}, "solid_count": 1, "volume_mm3": 320.0, "surface_area_mm2": 304.0},
        },
        generated={
            "geometry": {"bounding_box_mm": {"size_x": 11.0, "size_y": 8.0, "size_z": 3.5}, "solid_count": 1, "volume_mm3": 300.0, "surface_area_mm2": 290.0},
        },
        requirement_compliance={"machine_verified": 2, "failed": 1, "unverifiable": 0, "review_required": 1},
    )

    assert result["requirement_compliance"]["machine_verified"] == 2
    assert result["reference_similarity"]["metrics"]["bounding_box_error_by_axis_mm"] == {"x": 1.0, "y": 0.0, "z": 0.5}
    assert result["reference_similarity"]["metrics"]["solid_count_agreement"] is True
    assert "chamfer_distance" not in result["reference_similarity"]["metrics"]


def test_reference_bytes_live_under_ignored_data_root() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "data/" in gitignore
    assert "data/external-benchmarks" not in (REPO_ROOT / "benchmarks/external/mounting-brackets-v1/manifest.json").read_text(encoding="utf-8")
