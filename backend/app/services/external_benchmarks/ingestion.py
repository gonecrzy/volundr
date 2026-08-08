"""Hash-safe import of evaluator-only external reference geometry."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

from .models import BenchmarkManifest, BenchmarkProject, ReferenceFileRecord
from .reference_analysis import (
    ReferenceAnalysisError,
    analyze_reference,
    identify_reference_type,
    sha256_file,
)


class BenchmarkImportError(ValueError):
    """Raised when external benchmark metadata or geometry is invalid."""


def import_reference(
    *,
    benchmark: str,
    project: str,
    source_metadata_path: Path,
    reference_file: Path,
    manifest_path: Path,
    output_root: Path,
    repository_root: Path,
) -> dict[str, Any]:
    try:
        manifest = BenchmarkManifest.from_path(manifest_path)
        if manifest.benchmark_id != benchmark:
            raise BenchmarkImportError(
                f"manifest benchmark_id {manifest.benchmark_id!r} does not match {benchmark!r}"
            )
        project_record = manifest.project(project)
        metadata = _load_metadata(source_metadata_path)
        _validate_source_metadata(metadata)
        if not reference_file.exists():
            raise BenchmarkImportError(f"reference file does not exist: {reference_file}")
        file_type = identify_reference_type(reference_file)
        source_hash = sha256_file(reference_file)
        derived = analyze_reference(
            reference_file,
            file_type=file_type,
            units=metadata.get("reference_spec", {}).get("units"),
        )
        derived["file_sha256"] = source_hash
    except (ValueError, OSError, ReferenceAnalysisError) as exc:
        if isinstance(exc, BenchmarkImportError):
            raise
        raise BenchmarkImportError(str(exc)) from exc

    project_dir = output_root / benchmark / project
    reference_dir = project_dir / "reference"
    stored_path = reference_dir / f"reference.{file_type}"
    if project_record.status == "imported" and project_record.reference_files:
        raise BenchmarkImportError(f"benchmark project is already imported: {project}")

    project_dir.mkdir(parents=True, exist_ok=False)
    reference_dir.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(reference_file, stored_path)
        if sha256_file(stored_path) != source_hash:
            raise BenchmarkImportError("stored reference hash differs from source hash")
        source_payload = {
            key: value
            for key, value in metadata.items()
            if key not in {"premise", "reference_spec"}
        }
        (project_dir / "source.json").write_text(
            json.dumps(source_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (project_dir / "premise.txt").write_text(metadata["premise"], encoding="utf-8")
        (project_dir / "reference-spec.json").write_text(
            json.dumps(metadata["reference_spec"], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (project_dir / "derived-reference.json").write_text(
            json.dumps(derived, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except Exception:
        shutil.rmtree(project_dir, ignore_errors=True)
        raise

    relative_path = stored_path.relative_to(repository_root).as_posix()
    updated_project = replace(
        project_record,
        source_site=metadata["source_site"],
        source_url=metadata["source_url"],
        creator=metadata["creator"],
        source_title=metadata["source_title"],
        license=metadata["license"],
        acquired_at=metadata["acquired_at"],
        reference_files=(
            ReferenceFileRecord(
                relative_path=relative_path,
                file_type=file_type,
                sha256=source_hash,
                original_filename=metadata["original_filename"],
            ),
        ),
        premise=metadata["premise"],
        reference_spec=metadata["reference_spec"],
        status="imported",
    )
    updated_manifest = manifest.with_project(updated_project)
    manifest_path.write_text(
        json.dumps(updated_manifest.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "benchmark": benchmark,
        "project": updated_project.to_dict(),
        "reference_path": str(stored_path),
        "reference_sha256": source_hash,
        "derived_reference": derived,
        "manifest_path": str(manifest_path),
    }


def _load_metadata(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise BenchmarkImportError(f"source metadata does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkImportError(f"source metadata is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise BenchmarkImportError("source metadata must be a JSON object")
    return payload


def _validate_source_metadata(metadata: dict[str, Any]) -> None:
    required = (
        "source_site",
        "source_url",
        "creator",
        "source_title",
        "license",
        "acquired_at",
        "original_filename",
        "premise",
        "reference_spec",
    )
    for key in required:
        value = metadata.get(key)
        if key == "reference_spec":
            if not isinstance(value, dict):
                raise BenchmarkImportError("reference_spec must be a JSON object")
        elif not isinstance(value, str) or not value.strip():
            raise BenchmarkImportError(f"source metadata requires non-empty {key}")
    facts = metadata["reference_spec"].get("facts", [])
    if not isinstance(facts, list):
        raise BenchmarkImportError("reference_spec.facts must be a list when supplied")
    for fact in facts:
        if not isinstance(fact, dict) or fact.get("provenance") not in {
            "creator_documented",
            "reference_geometry_measured",
            "manual_benchmark_annotation",
        }:
            raise BenchmarkImportError(
                "each reference-spec fact requires an allowed provenance value"
            )
