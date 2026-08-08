"""Hash-safe import of evaluator-only external reference geometry."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence

from .models import BenchmarkManifest, ProvenanceFileRecord, ReferenceFileRecord
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
    reference_file: Path | None = None,
    reference_files: Sequence[Path] | None = None,
    provenance_files: Sequence[Path] | None = None,
    manifest_path: Path,
    output_root: Path,
    repository_root: Path,
) -> dict[str, Any]:
    """Import one or more explicit canonical reference parts atomically.

    ``reference_file`` remains supported for the original single-file API.
    Multi-part imports must declare ``canonical_reference_parts`` (or the
    compatibility alias ``canonical_parts``) in source metadata.  File names
    are matched explicitly; input order is never used as part identity.
    """

    try:
        manifest = BenchmarkManifest.from_path(manifest_path)
        if manifest.benchmark_id != benchmark:
            raise BenchmarkImportError(
                f"manifest benchmark_id {manifest.benchmark_id!r} does not match {benchmark!r}"
            )
        project_record = manifest.project(project)
        metadata = _load_metadata(source_metadata_path)
        _validate_source_metadata(metadata)
        canonical_paths = _normalize_reference_paths(reference_file, reference_files)
        canonical_specs = _resolve_canonical_specs(metadata, canonical_paths)
        provenance_specs, normalized_provenance_paths = _resolve_provenance_specs(
            metadata,
            provenance_files,
        )
        if project_record.status == "imported" and project_record.reference_files:
            raise BenchmarkImportError(f"benchmark project is already imported: {project}")

        canonical_entries = _analyze_canonical_parts(canonical_specs, metadata)
        provenance_entries = _prepare_provenance_entries(provenance_specs, normalized_provenance_paths)
        _reject_duplicate_source_names(canonical_entries, provenance_entries)
        reference_set_sha256 = _reference_set_sha256(canonical_entries)
    except (BenchmarkImportError, ValueError, OSError, ReferenceAnalysisError) as exc:
        if isinstance(exc, BenchmarkImportError):
            raise
        raise BenchmarkImportError(str(exc)) from exc

    project_dir = output_root / benchmark / project
    reference_dir = project_dir / "reference"
    provenance_dir = project_dir / "provenance"
    stored_paths: dict[str, Path] = {}
    stored_provenance_paths: dict[str, Path] = {}

    try:
        project_dir.mkdir(parents=True, exist_ok=False)
        reference_dir.mkdir()
        if provenance_entries:
            provenance_dir.mkdir()
        for entry in canonical_entries:
            stored_path = reference_dir / f"{entry['part_id']}.{entry['file_type']}"
            shutil.copyfile(entry["source_path"], stored_path)
            if sha256_file(stored_path) != entry["sha256"]:
                raise BenchmarkImportError(
                    f"stored reference hash differs from source hash for {entry['part_id']}"
                )
            stored_paths[entry["part_id"]] = stored_path
        for entry in provenance_entries:
            stored_path = provenance_dir / entry["original_filename"]
            shutil.copyfile(entry["source_path"], stored_path)
            if sha256_file(stored_path) != entry["sha256"]:
                raise BenchmarkImportError(
                    f"stored provenance hash differs from source hash for {entry['original_filename']}"
                )
            stored_provenance_paths[entry["original_filename"]] = stored_path

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
        derived_reference = _derived_reference_set(
            canonical_entries,
            provenance_entries,
            reference_set_sha256,
        )
        (project_dir / "derived-reference.json").write_text(
            json.dumps(derived_reference, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except BenchmarkImportError:
        shutil.rmtree(project_dir, ignore_errors=True)
        raise
    except (OSError, ValueError, TypeError) as exc:
        shutil.rmtree(project_dir, ignore_errors=True)
        raise BenchmarkImportError(str(exc)) from exc

    relative_paths = {
        entry["part_id"]: stored_paths[entry["part_id"]].relative_to(repository_root).as_posix()
        for entry in canonical_entries
    }
    provenance_records = tuple(
        ProvenanceFileRecord(
            relative_path=stored_provenance_paths[entry["original_filename"]]
            .relative_to(repository_root)
            .as_posix(),
            file_type=entry["file_type"],
            sha256=entry["sha256"],
            original_filename=entry["original_filename"],
            role=entry["role"],
        )
        for entry in provenance_entries
    )
    reference_records = tuple(
        ReferenceFileRecord(
            part_id=entry["part_id"],
            relative_path=relative_paths[entry["part_id"]],
            file_type=entry["file_type"],
            sha256=entry["sha256"],
            original_filename=entry["original_filename"],
            authority=entry["derived"].get("authority"),
            quality_classification=entry["derived"].get("quality_classification"),
            selection_reason=entry.get("selection_reason"),
        )
        for entry in canonical_entries
    )
    updated_project = replace(
        project_record,
        source_site=metadata["source_site"],
        source_url=metadata["source_url"],
        creator=metadata["creator"],
        source_title=metadata["source_title"],
        license=metadata["license"],
        acquired_at=metadata["acquired_at"],
        reference_files=reference_records,
        provenance_files=provenance_records,
        canonical_part_count=len(reference_records),
        reference_set_sha256=reference_set_sha256,
        reference_output_mapping=dict(metadata.get("reference_output_mapping", {})),
        premise=metadata["premise"],
        reference_spec=metadata["reference_spec"],
        reference_spec_sufficiency=metadata.get("reference_spec_sufficiency")
        or metadata["reference_spec"].get("sufficiency"),
        source_model_id=metadata.get("source_model_id"),
        source_pdf_sha256=metadata.get("source_pdf_sha256"),
        source_description_summary=metadata.get("source_description_summary"),
        canonical_selection_basis=metadata.get("canonical_selection_basis"),
        ambiguity_flags=tuple(str(item) for item in (metadata.get("ambiguity_flags") or [])),
        replacement_recommended=bool(metadata.get("replacement_recommended", False)),
        status="imported",
    )
    updated_manifest = manifest.with_project(updated_project)
    try:
        _write_manifest_atomically(manifest_path, updated_manifest.to_dict())
    except Exception as exc:
        shutil.rmtree(project_dir, ignore_errors=True)
        if isinstance(exc, BenchmarkImportError):
            raise
        raise BenchmarkImportError(str(exc)) from exc

    first_entry = canonical_entries[0]
    return {
        "benchmark": benchmark,
        "project": updated_project.to_dict(),
        "reference_path": str(stored_paths[first_entry["part_id"]]),
        "reference_paths": {part_id: str(path) for part_id, path in stored_paths.items()},
        "reference_sha256": first_entry["sha256"],
        "reference_sha256s": {
            entry["part_id"]: entry["sha256"] for entry in canonical_entries
        },
        "canonical_part_count": len(canonical_entries),
        "reference_set_sha256": reference_set_sha256,
        "provenance_paths": {
            filename: str(path) for filename, path in stored_provenance_paths.items()
        },
        "derived_reference": derived_reference,
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
    creator = metadata.get("creator")
    if creator is not None and (not isinstance(creator, str) or not creator.strip()):
        raise BenchmarkImportError("creator must be a non-empty string when supplied")
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


def _normalize_reference_paths(
    reference_file: Path | None,
    reference_files: Sequence[Path] | None,
) -> list[Path]:
    if reference_file is not None and reference_files is not None:
        raise BenchmarkImportError("provide reference_file or reference_files, not both")
    paths = [Path(reference_file)] if reference_file is not None else [Path(path) for path in reference_files or []]
    if not paths:
        raise BenchmarkImportError("at least one canonical reference file is required")
    resolved = [path.resolve() for path in paths]
    if len(resolved) != len(set(resolved)):
        raise BenchmarkImportError("canonical source paths must be unique")
    for path in paths:
        if not path.exists():
            raise BenchmarkImportError(f"reference file does not exist: {path}")
        if not path.is_file():
            raise BenchmarkImportError(f"reference path is not a file: {path}")
    return paths


def _resolve_canonical_specs(metadata: dict[str, Any], paths: list[Path]) -> list[dict[str, str]]:
    raw_specs = metadata.get("canonical_reference_parts", metadata.get("canonical_parts"))
    if raw_specs is None:
        if len(paths) != 1:
            raise BenchmarkImportError(
                "canonical part membership must be explicit for multiple reference files"
            )
        return [
            {
                "part_id": "primary_part",
                "source_filename": paths[0].name,
                "selection_reason": "single canonical reference file supplied by intake",
                "source_path": str(paths[0]),
            }
        ]
    if not isinstance(raw_specs, list) or not raw_specs:
        raise BenchmarkImportError("canonical_reference_parts must be a non-empty list")
    if len(raw_specs) != len(paths):
        raise BenchmarkImportError(
            "canonical reference metadata and input files must match exactly once"
        )
    specs: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for item in raw_specs:
        if not isinstance(item, dict):
            raise BenchmarkImportError("each canonical reference part must be an object")
        part_id = item.get("part_id")
        source_filename = item.get("source_filename")
        if not isinstance(part_id, str) or not part_id.strip():
            raise BenchmarkImportError("each canonical reference part requires a part_id")
        if not isinstance(source_filename, str) or not source_filename.strip():
            raise BenchmarkImportError("each canonical reference part requires a source_filename")
        normalized_part_id = part_id.strip()
        if not re.fullmatch(r"[a-z0-9]+(?:[_-][a-z0-9]+)*", normalized_part_id):
            raise BenchmarkImportError("part_id must be a neutral lowercase identifier")
        if normalized_part_id in seen_ids:
            raise BenchmarkImportError("canonical part IDs must be unique")
        source_name = _safe_filename(source_filename, "canonical source_filename")
        selection_reason = item.get(
            "selection_reason",
            "explicit canonical membership from intake metadata",
        )
        if not isinstance(selection_reason, str) or not selection_reason.strip():
            raise BenchmarkImportError("canonical reference selection_reason must be a non-empty string")
        if source_name in seen_names:
            raise BenchmarkImportError("canonical source paths must be unique")
        seen_ids.add(normalized_part_id)
        seen_names.add(source_name)
        specs.append(
            {
                "part_id": normalized_part_id,
                "source_filename": source_name,
                "selection_reason": selection_reason.strip(),
            }
        )
    input_by_name: dict[str, Path] = {}
    for path in paths:
        if path.name in input_by_name:
            raise BenchmarkImportError("canonical source paths must be unique")
        input_by_name[path.name] = path
    if set(input_by_name) != seen_names:
        raise BenchmarkImportError(
            "canonical reference metadata must identify every input file exactly once"
        )
    return [dict(spec, source_path=str(input_by_name[spec["source_filename"]])) for spec in specs]


def _resolve_provenance_specs(
    metadata: dict[str, Any],
    paths: Sequence[Path] | None,
) -> tuple[list[dict[str, str]], list[Path]]:
    normalized_paths = [Path(path) for path in paths or []]
    if len({path.resolve() for path in normalized_paths}) != len(normalized_paths):
        raise BenchmarkImportError("provenance source paths must be unique")
    for path in normalized_paths:
        if not path.exists() or not path.is_file():
            raise BenchmarkImportError(f"provenance file does not exist or is not a file: {path}")
    raw_specs = metadata.get("provenance_files")
    if raw_specs is None:
        return [
            {
                "source_filename": path.name,
                "role": "provenance",
            }
            for path in normalized_paths
        ], normalized_paths
    if not isinstance(raw_specs, list):
        raise BenchmarkImportError("provenance_files must be a list")
    if len(raw_specs) != len(normalized_paths):
        raise BenchmarkImportError(
            "provenance metadata and input files must match exactly once"
        )
    specs: list[dict[str, str]] = []
    seen_names: set[str] = set()
    for item in raw_specs:
        if not isinstance(item, dict):
            raise BenchmarkImportError("each provenance file must be an object")
        source_filename = item.get("source_filename")
        role = item.get("role", "provenance")
        if not isinstance(source_filename, str) or not source_filename.strip():
            raise BenchmarkImportError("each provenance file requires a source_filename")
        if not isinstance(role, str) or not role.strip():
            raise BenchmarkImportError("each provenance file requires a role")
        source_name = _safe_filename(source_filename, "provenance source_filename")
        if source_name in seen_names:
            raise BenchmarkImportError("provenance source paths must be unique")
        seen_names.add(source_name)
        specs.append({"source_filename": source_name, "role": role.strip()})
    path_by_name = {path.name: path for path in normalized_paths}
    if len(path_by_name) != len(normalized_paths) or set(path_by_name) != seen_names:
        raise BenchmarkImportError(
            "provenance metadata must identify every input file exactly once"
        )
    return specs, [path_by_name[spec["source_filename"]] for spec in specs]


def _safe_filename(value: str, field_name: str) -> str:
    candidate = Path(value.strip())
    if candidate.name != value.strip() or candidate.name in {"", ".", ".."}:
        raise BenchmarkImportError(f"{field_name} must be a simple filename")
    return candidate.name


def _analyze_canonical_parts(
    specs: list[dict[str, str]],
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    units = metadata.get("reference_spec", {}).get("units")
    for spec in specs:
        path = Path(spec["source_path"])
        try:
            file_type = identify_reference_type(path)
            source_hash = sha256_file(path)
            derived = analyze_reference(path, file_type=file_type, units=units)
        except (OSError, ReferenceAnalysisError) as exc:
            raise BenchmarkImportError(str(exc)) from exc
        entries.append(
            {
                "part_id": spec["part_id"],
                "source_path": path,
                "file_type": file_type,
                "sha256": source_hash,
                "original_filename": spec["source_filename"],
                "selection_reason": spec["selection_reason"],
                "derived": derived,
            }
        )
    return entries


def _prepare_provenance_entries(
    specs: list[dict[str, str]],
    paths: list[Path],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for spec, path in zip(specs, paths, strict=True):
        try:
            source_hash = sha256_file(path)
        except ReferenceAnalysisError as exc:
            raise BenchmarkImportError(str(exc)) from exc
        entries.append(
            {
                "source_path": path,
                "file_type": _provenance_file_type(path),
                "sha256": source_hash,
                "original_filename": spec["source_filename"],
                "role": spec["role"],
            }
        )
    return entries


def _provenance_file_type(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    return suffix if suffix in {"3mf", "dwg", "f3d", "pdf", "stl", "step", "brep"} else "unknown"


def _reject_duplicate_source_names(
    canonical_entries: list[dict[str, Any]],
    provenance_entries: list[dict[str, Any]],
) -> None:
    names = [entry["original_filename"] for entry in canonical_entries + provenance_entries]
    if len(names) != len(set(names)):
        raise BenchmarkImportError("canonical and provenance source paths must be unique")


def _reference_set_sha256(entries: list[dict[str, Any]]) -> str:
    identity = {
        "canonical_parts": [
            {
                "part_id": entry["part_id"],
                "file_type": entry["file_type"],
                "sha256": entry["sha256"],
            }
            for entry in sorted(entries, key=lambda item: item["part_id"])
        ]
    }
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _derived_reference_set(
    canonical_entries: list[dict[str, Any]],
    provenance_entries: list[dict[str, Any]],
    reference_set_sha256: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "external-cad-reference-set-derived-v1",
        "canonical_part_count": len(canonical_entries),
        "reference_set_sha256": reference_set_sha256,
        "aggregate_geometry": _aggregate_geometry(canonical_entries),
        "canonical_parts": [
            {
                "part_id": entry["part_id"],
                "original_filename": entry["original_filename"],
                "file_type": entry["file_type"],
                "file_sha256": entry["sha256"],
                "derived": entry["derived"],
            }
            for entry in canonical_entries
        ],
        "provenance_files": [
            {
                "original_filename": entry["original_filename"],
                "file_type": entry["file_type"],
                "file_sha256": entry["sha256"],
                "role": entry["role"],
            }
            for entry in provenance_entries
        ],
    }
    if len(canonical_entries) == 1:
        payload.update(canonical_entries[0]["derived"])
        payload["canonical_part_count"] = 1
        payload["reference_set_sha256"] = reference_set_sha256
    return payload


def _aggregate_geometry(canonical_entries: list[dict[str, Any]]) -> dict[str, Any]:
    geometries = [entry["derived"].get("geometry", {}) for entry in canonical_entries]
    aggregate: dict[str, Any] = {
        "aggregation": "constituent_part_facts",
        "solid_count": _sum_numeric(geometries, "solid_count"),
        "volume_mm3": _sum_numeric(geometries, "volume_mm3"),
        "surface_area_mm2": _sum_numeric(geometries, "surface_area_mm2"),
    }
    if len(geometries) == 1 and isinstance(geometries[0].get("bounding_box_mm"), dict):
        aggregate["bounding_box_mm"] = geometries[0]["bounding_box_mm"]
    else:
        aggregate["bounding_box_mm"] = None
        aggregate["bounding_box_note"] = "not unioned across independent reference parts"
    return aggregate


def _sum_numeric(geometries: list[dict[str, Any]], key: str) -> float | int | None:
    values = [geometry.get(key) for geometry in geometries]
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
        return None
    total = sum(float(value) for value in values)
    return int(total) if all(isinstance(value, int) for value in values) else total


def _write_manifest_atomically(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise BenchmarkImportError(f"unable to persist benchmark manifest: {path}") from exc
