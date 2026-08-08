from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import trimesh

from app.services.external_benchmarks.comparison import compare_reference_geometry
from app.services.external_benchmarks.ingestion import BenchmarkImportError, import_reference
from app.services.external_benchmarks.models import BenchmarkManifest


def _manifest(path: Path) -> Path:
    manifest_path = path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "external-cad-benchmark-manifest-v1",
                "benchmark_id": "mounting-brackets-v1",
                "benchmark_version": "1.0.0",
                "target_project_count": 50,
                "target_category_count": 10,
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
    return manifest_path


def _metadata(*parts: dict[str, str], provenance: list[dict[str, str]] | None = None) -> dict:
    payload = {
        "source_site": "example-cad-site",
        "source_url": "https://example.invalid/reference",
        "creator": "Example creator",
        "source_title": "Example mounting bracket",
        "license": "CC BY 4.0",
        "acquired_at": "2026-08-08",
        "original_filename": parts[0]["source_filename"] if parts else "example-bracket.stl",
        "premise": "Design a useful mounting bracket for a small device.",
        "reference_spec": {"units": "mm", "facts": []},
    }
    if parts:
        payload["canonical_reference_parts"] = list(parts)
    if provenance is not None:
        payload["provenance_files"] = provenance
    return payload


def _write_cube(path: Path, *, size: float) -> None:
    trimesh.creation.box(extents=(size, size, size)).export(path, file_type="stl")


def _write_import_inputs(tmp_path: Path, metadata: dict, filenames: list[str]) -> tuple[Path, list[Path]]:
    source = tmp_path / "source.json"
    source.write_text(json.dumps(metadata), encoding="utf-8")
    references: list[Path] = []
    for index, filename in enumerate(filenames, start=1):
        reference = tmp_path / filename
        _write_cube(reference, size=float(index + 2))
        references.append(reference)
    return source, references


def test_two_part_import_requires_explicit_membership_and_persists_each_part(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path)
    metadata = _metadata(
        {"part_id": "lower_part", "source_filename": "lower.stl"},
        {"part_id": "upper_part", "source_filename": "upper.stl"},
    )
    source, references = _write_import_inputs(tmp_path, metadata, ["lower.stl", "upper.stl"])

    result = import_reference(
        benchmark="mounting-brackets-v1",
        project="mounting-bracket-001",
        source_metadata_path=source,
        reference_files=references,
        manifest_path=manifest_path,
        output_root=tmp_path / "data",
        repository_root=tmp_path,
    )

    assert result["canonical_part_count"] == 2
    assert set(result["reference_paths"]) == {"lower_part", "upper_part"}
    assert result["derived_reference"]["canonical_part_count"] == 2
    persisted = BenchmarkManifest.from_path(manifest_path).projects[0]
    assert persisted.status == "imported"
    assert persisted.canonical_part_count == 2
    assert [item.part_id for item in persisted.reference_files] == ["lower_part", "upper_part"]


def test_per_file_sha256_is_recorded(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path)
    metadata = _metadata(
        {"part_id": "left", "source_filename": "left.stl"},
        {"part_id": "right", "source_filename": "right.stl"},
    )
    source, references = _write_import_inputs(tmp_path, metadata, ["left.stl", "right.stl"])

    result = import_reference(
        benchmark="mounting-brackets-v1",
        project="mounting-bracket-001",
        source_metadata_path=source,
        reference_files=references,
        manifest_path=manifest_path,
        output_root=tmp_path / "data",
        repository_root=tmp_path,
    )

    for reference in references:
        expected = hashlib.sha256(reference.read_bytes()).hexdigest()
        part_id = reference.stem
        assert result["project"]["reference_files"]
        record = next(item for item in result["project"]["reference_files"] if item["part_id"] == part_id)
        assert record["sha256"] == expected


def test_duplicate_part_ids_are_rejected_before_writes(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path)
    metadata = _metadata(
        {"part_id": "same_part", "source_filename": "left.stl"},
        {"part_id": "same_part", "source_filename": "right.stl"},
    )
    source, references = _write_import_inputs(tmp_path, metadata, ["left.stl", "right.stl"])

    with pytest.raises(BenchmarkImportError, match="part IDs"):
        import_reference(
            benchmark="mounting-brackets-v1",
            project="mounting-bracket-001",
            source_metadata_path=source,
            reference_files=references,
            manifest_path=manifest_path,
            output_root=tmp_path / "data",
            repository_root=tmp_path,
        )
    assert not (tmp_path / "data").exists()


def test_duplicate_source_paths_are_rejected_before_writes(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path)
    metadata = _metadata(
        {"part_id": "left", "source_filename": "same.stl"},
        {"part_id": "right", "source_filename": "same.stl"},
    )
    source, references = _write_import_inputs(tmp_path, metadata, ["left.stl", "right.stl"])

    with pytest.raises(BenchmarkImportError, match="source paths"):
        import_reference(
            benchmark="mounting-brackets-v1",
            project="mounting-bracket-001",
            source_metadata_path=source,
            reference_files=references,
            manifest_path=manifest_path,
            output_root=tmp_path / "data",
            repository_root=tmp_path,
        )
    assert not (tmp_path / "data").exists()


def test_malformed_second_part_rolls_back_atomically(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path)
    metadata = _metadata(
        {"part_id": "valid_part", "source_filename": "valid.stl"},
        {"part_id": "invalid_part", "source_filename": "invalid.stl"},
    )
    source = tmp_path / "source.json"
    source.write_text(json.dumps(metadata), encoding="utf-8")
    valid = tmp_path / "valid.stl"
    _write_cube(valid, size=3.0)
    invalid = tmp_path / "invalid.stl"
    invalid.write_text("not geometry", encoding="utf-8")
    before = manifest_path.read_bytes()

    with pytest.raises(BenchmarkImportError, match="geometry"):
        import_reference(
            benchmark="mounting-brackets-v1",
            project="mounting-bracket-001",
            source_metadata_path=source,
            reference_files=[valid, invalid],
            manifest_path=manifest_path,
            output_root=tmp_path / "data",
            repository_root=tmp_path,
        )

    assert not (tmp_path / "data").exists()
    assert manifest_path.read_bytes() == before
    assert BenchmarkManifest.from_path(manifest_path).projects[0].status == "placeholder"


def test_provenance_files_do_not_change_canonical_part_count(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path)
    metadata = _metadata(
        {"part_id": "canonical", "source_filename": "canonical.stl"},
        provenance=[{"source_filename": "alternate.3mf", "role": "alternate_source"}],
    )
    source, references = _write_import_inputs(tmp_path, metadata, ["canonical.stl"])
    provenance = tmp_path / "alternate.3mf"
    provenance.write_bytes(b"provenance bytes")

    result = import_reference(
        benchmark="mounting-brackets-v1",
        project="mounting-bracket-001",
        source_metadata_path=source,
        reference_files=references,
        provenance_files=[provenance],
        manifest_path=manifest_path,
        output_root=tmp_path / "data",
        repository_root=tmp_path,
    )

    assert result["canonical_part_count"] == 1
    assert len(result["project"]["reference_files"]) == 1
    assert len(result["project"]["provenance_files"]) == 1
    assert Path(result["provenance_paths"]["alternate.3mf"]).exists()
    assert BenchmarkManifest.from_path(manifest_path).projects[0].canonical_part_count == 1


def test_multiple_files_without_explicit_membership_are_rejected(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path)
    metadata = _metadata()
    source, references = _write_import_inputs(tmp_path, metadata, ["one.stl", "two.stl"])

    with pytest.raises(BenchmarkImportError, match="canonical part membership"):
        import_reference(
            benchmark="mounting-brackets-v1",
            project="mounting-bracket-001",
            source_metadata_path=source,
            reference_files=references,
            manifest_path=manifest_path,
            output_root=tmp_path / "data",
            repository_root=tmp_path,
        )
    assert not (tmp_path / "data").exists()


def test_incomplete_membership_cannot_partially_import_project(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path)
    metadata = _metadata(
        {"part_id": "only_declared", "source_filename": "one.stl"},
        {"part_id": "missing_input", "source_filename": "two.stl"},
    )
    source, references = _write_import_inputs(tmp_path, metadata, ["one.stl"])
    before = manifest_path.read_bytes()

    with pytest.raises(BenchmarkImportError, match="exactly once"):
        import_reference(
            benchmark="mounting-brackets-v1",
            project="mounting-bracket-001",
            source_metadata_path=source,
            reference_files=references,
            manifest_path=manifest_path,
            output_root=tmp_path / "data",
            repository_root=tmp_path,
        )
    assert not (tmp_path / "data").exists()
    assert manifest_path.read_bytes() == before


def test_multi_part_comparison_uses_explicit_neutral_mapping_and_separate_metrics() -> None:
    reference = {
        "canonical_part_count": 2,
        "canonical_parts": [
            {
                "part_id": "alpha_part",
                "derived": {
                    "geometry": {
                        "bounding_box_mm": {"size_x": 10.0, "size_y": 8.0, "size_z": 4.0},
                        "solid_count": 1,
                        "volume_mm3": 320.0,
                        "surface_area_mm2": 304.0,
                    }
                },
            },
            {
                "part_id": "beta_part",
                "derived": {
                    "geometry": {
                        "bounding_box_mm": {"size_x": 6.0, "size_y": 5.0, "size_z": 3.0},
                        "solid_count": 1,
                        "volume_mm3": 90.0,
                        "surface_area_mm2": 126.0,
                    }
                },
            },
        ],
        "aggregate_geometry": {
            "solid_count": 2,
            "volume_mm3": 410.0,
            "surface_area_mm2": 430.0,
        },
    }
    generated = {
        "parts": {
            "output-z": {
                "geometry": {
                    "bounding_box_mm": {"size_x": 6.0, "size_y": 5.0, "size_z": 3.0},
                    "solid_count": 1,
                    "volume_mm3": 90.0,
                    "surface_area_mm2": 126.0,
                }
            },
            "output-a": {
                "geometry": {
                    "bounding_box_mm": {"size_x": 10.0, "size_y": 8.0, "size_z": 4.0},
                    "solid_count": 1,
                    "volume_mm3": 320.0,
                    "surface_area_mm2": 304.0,
                }
            },
        },
        "aggregate_geometry": {
            "solid_count": 2,
            "volume_mm3": 410.0,
            "surface_area_mm2": 430.0,
        },
    }

    result = compare_reference_geometry(
        reference=reference,
        generated=generated,
        reference_output_mapping={"alpha_part": "output-a", "beta_part": "output-z"},
    )

    metrics = result["reference_similarity"]["metrics"]
    assert result["reference_similarity"]["status"] == "measured"
    assert metrics["project_part_count_agreement"] is True
    assert set(metrics["per_part"]) == {"alpha_part", "beta_part"}
    assert metrics["per_part"]["alpha_part"]["volume_difference_mm3"] == 0.0
    assert metrics["aggregate"]["volume_difference_mm3"] == 0.0


def test_multi_part_comparison_without_mapping_remains_unavailable() -> None:
    reference = {
        "canonical_parts": [
            {"part_id": "alpha_part", "derived": {"geometry": {"solid_count": 1}}},
            {"part_id": "beta_part", "derived": {"geometry": {"solid_count": 1}}},
        ]
    }
    generated = {"parts": {"output-a": {"geometry": {"solid_count": 1}}, "output-b": {"geometry": {"solid_count": 1}}}}

    result = compare_reference_geometry(reference=reference, generated=generated)

    assert result["reference_similarity"]["status"] == "unavailable"
    assert result["reference_similarity"]["metrics"]["per_part"] == {}
    assert result["reference_similarity"]["metrics"]["mapping_status"] == "explicit_reference_output_mapping_required"
