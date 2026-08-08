from __future__ import annotations

import subprocess
from pathlib import Path

from app.services.external_benchmarks.models import BenchmarkManifest


REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_MANIFEST = REPO_ROOT / "benchmarks/external/cad-50-v1/manifest.json"


def test_frozen_corpus_has_balanced_categories_and_splits() -> None:
    manifest = BenchmarkManifest.from_path(CORPUS_MANIFEST)

    assert manifest.benchmark_id == "external-cad-50-v1"
    assert len(manifest.projects) == 50
    categories = {project.category for project in manifest.projects}
    assert len(categories) == 10
    for category in categories:
        projects = [project for project in manifest.projects if project.category == category]
        assert len(projects) == 5
        assert [project.split_assignment for project in projects].count("development") == 3
        assert [project.split_assignment for project in projects].count("validation") == 1
        assert [project.split_assignment for project in projects].count("holdout") == 1


def test_frozen_corpus_has_explicit_reference_quality_and_specs() -> None:
    manifest = BenchmarkManifest.from_path(CORPUS_MANIFEST)
    quality_values = {
        "analytic_brep_authoritative",
        "watertight_mesh_reference",
        "nonwatertight_mesh_reference",
        "invalid_or_unsupported_reference",
    }
    spec_values = {"minimal", "moderate", "reconstruction_grade"}

    assert all(project.reference_spec_sufficiency in spec_values for project in manifest.projects)
    for project in manifest.projects:
        assert project.premise
        assert project.reference_spec
        for reference in project.reference_files:
            assert reference.authority
            assert reference.quality_classification in quality_values
            assert reference.selection_reason
            assert len(reference.sha256) == 64
        for fact in project.reference_spec.get("facts", []):
            assert fact["provenance"] in {
                "creator_documented",
                "reference_geometry_measured",
                "manual_benchmark_annotation",
            }


def test_holdout_manifest_metadata_is_neutral_only() -> None:
    manifest = BenchmarkManifest.from_path(CORPUS_MANIFEST)
    policy = manifest.metadata["holdout_policy"]

    assert policy["protected_after_freeze"] is True
    assert set(policy["allowed_metadata"]) == {"benchmark_id", "category", "split_assignment"}
    assert "reference_geometry" in policy["disallowed_metadata"]
    assert "reference_spec" in policy["disallowed_metadata"]


def test_no_reference_bytes_are_tracked_under_committed_corpus_paths() -> None:
    result = subprocess.run(
        ["git", "ls-files", "benchmarks/external/cad-50-v1"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    byte_suffixes = {".stl", ".step", ".stp", ".brep", ".3mf", ".zip", ".pdf", ".f3d", ".dwg"}
    tracked_paths = [Path(line) for line in result.stdout.splitlines() if line]
    assert all(path.suffix.lower() not in byte_suffixes for path in tracked_paths)
