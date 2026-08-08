#!/usr/bin/env python3
"""Import and freeze the evaluator-only 50-project external CAD corpus."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import sys
import zipfile
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.external_benchmarks.corpus import (  # noqa: E402
    assign_balanced_split,
    build_holdout_policy,
    validate_corpus_shape,
)
from app.services.external_benchmarks.ingestion import (  # noqa: E402
    BenchmarkImportError,
    import_reference,
)
from app.services.external_benchmarks.models import BenchmarkManifest  # noqa: E402
from app.services.external_benchmarks.reference_analysis import sha256_file  # noqa: E402


EXPECTED_OUTER_SHA256 = "978caed8307f415b30b12f5c71a815a6bb073c012063c3307396797f2a5a5e03"
EXPECTED_ADDITIONAL_PROJECTS = 45
BENCHMARK_ID = "external-cad-50-v1"
PILOT_MANIFEST = REPO_ROOT / "benchmarks/external/mounting-brackets-v1/manifest.json"
INTAKE_MANIFEST = REPO_ROOT / "benchmarks/external/cad-50-v1/intake-manifest.json"
FINAL_MANIFEST = REPO_ROOT / "benchmarks/external/cad-50-v1/manifest.json"
REPORT_PATH = REPO_ROOT / "data/debug-sessions/external-benchmarks/cad-50-v1/corpus-freeze-report.json"
HOLDOUT_POLICY_PATH = REPO_ROOT / "benchmarks/external/cad-50-v1/holdout-policy.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acquisition-zip", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=REPO_ROOT / "data/external-benchmarks")
    parser.add_argument("--intake-manifest", type=Path, default=INTAKE_MANIFEST)
    parser.add_argument("--manifest", type=Path, default=FINAL_MANIFEST)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    return parser


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _zip_file_members(archive: zipfile.ZipFile) -> list[str]:
    return [name for name in archive.namelist() if not name.endswith("/")]


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    for name in archive.namelist():
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise BenchmarkImportError(f"unsafe archive member path: {name}")
        target = destination.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        if name.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.write_bytes(archive.read(name))


def _find_basename(files: list[str], filename: str, *, project: str) -> str:
    matches = [name for name in files if PurePosixPath(name).name == filename]
    if len(matches) != 1:
        raise BenchmarkImportError(
            f"{project}: expected one intake member named {filename!r}, found {matches}"
        )
    return matches[0]


def _source_metadata(
    annotation: dict[str, Any],
    *,
    extracted_files: list[str],
    extracted_root: Path,
    project: str,
) -> tuple[dict[str, Any], list[Path], list[Path]]:
    canonical_specs = annotation["canonical_reference_parts"]
    canonical_names = {item["source_filename"] for item in canonical_specs}
    canonical_paths: list[Path] = []
    for item in canonical_specs:
        member = _find_basename(extracted_files, item["source_filename"], project=project)
        canonical_paths.append(extracted_root.joinpath(*PurePosixPath(member).parts))

    provenance_paths: list[Path] = []
    provenance_specs: list[dict[str, str]] = []
    for member in extracted_files:
        filename = PurePosixPath(member).name
        if filename in canonical_names:
            continue
        path = extracted_root.joinpath(*PurePosixPath(member).parts)
        provenance_paths.append(path)
        suffix = path.suffix.lower()
        role = "source_provenance_pdf" if suffix == ".pdf" else "noncanonical_intake_source"
        provenance_specs.append({"source_filename": filename, "role": role})

    if not provenance_paths:
        raise BenchmarkImportError(f"{project}: intake package has no retained provenance members")
    pdf_paths = [path for path in provenance_paths if path.suffix.lower() == ".pdf"]
    if len(pdf_paths) != 1:
        raise BenchmarkImportError(f"{project}: expected exactly one bundled provenance PDF")

    metadata = {
        "source_site": "Printables",
        "source_url": f"https://www.printables.com/model/{annotation['source_model_id']}",
        "creator": annotation.get("creator"),
        "source_title": annotation["source_title"],
        "license": annotation["license"],
        "acquired_at": annotation.get("acquired_at", "2026-08-08"),
        "original_filename": canonical_specs[0]["source_filename"],
        "premise": annotation["premise"],
        "reference_spec": annotation["reference_spec"],
        "canonical_reference_parts": canonical_specs,
        "reference_output_mapping": annotation.get("reference_output_mapping", {}),
        "provenance_files": provenance_specs,
        "source_model_id": annotation["source_model_id"],
        "source_description_summary": annotation["source_description_summary"],
        "canonical_selection_basis": annotation["canonical_selection_basis"],
        "ambiguity_flags": annotation.get("ambiguity_flags", []),
        "replacement_recommended": bool(annotation.get("replacement_recommended", False)),
        "source_pdf_sha256": sha256_file(pdf_paths[0]),
        "reference_spec_sufficiency": annotation["reference_spec"]["sufficiency"],
    }
    for spec in canonical_specs:
        if spec["source_filename"] not in canonical_names:
            raise BenchmarkImportError(f"{project}: invalid canonical membership")
    return metadata, canonical_paths, provenance_paths


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _manifest_project_dict(project: Any) -> dict[str, Any]:
    return project.to_dict()


def _enrich_locked_pilot_project(project: Any) -> Any:
    """Backfill quality metadata in the new corpus manifest only.

    The five pilot manifests predate the quality-classification fields.  Read
    their already-persisted derived records rather than reimporting or
    rewriting the locked pilot corpus.
    """

    derived_path = REPO_ROOT / project.reference_files[0].relative_path
    derived_path = derived_path.parent.parent / "derived-reference.json"
    payload = json.loads(derived_path.read_text(encoding="utf-8"))
    derived_by_part = {
        item["part_id"]: item["derived"]
        for item in payload.get("canonical_parts", [])
    }
    enriched_files = []
    for reference in project.reference_files:
        derived = derived_by_part.get(reference.part_id, {})
        file_type = reference.file_type
        authority = "analytic_brep" if file_type in {"step", "brep"} else "mesh_derived"
        topology = derived.get("topology", {})
        if file_type in {"step", "brep"}:
            quality = (
                "analytic_brep_authoritative"
                if topology.get("valid")
                else "invalid_or_unsupported_reference"
            )
        else:
            quality = (
                "watertight_mesh_reference"
                if derived.get("mesh", {}).get("watertight")
                else "nonwatertight_mesh_reference"
            )
        enriched_files.append(
            replace(
                reference,
                authority=reference.authority or authority,
                quality_classification=reference.quality_classification or quality,
                selection_reason=reference.selection_reason
                or project.canonical_selection_basis
                or "locked pilot canonical membership",
            )
        )
    facts = project.reference_spec.get("facts", [])
    sufficiency = project.reference_spec_sufficiency or project.reference_spec.get("sufficiency")
    if sufficiency is None:
        sufficiency = "minimal" if len(facts) <= 3 else "moderate"
    source_model_id = project.source_model_id
    if source_model_id is None and project.source_url:
        match = re.search(r"/model/(\d+)", project.source_url)
        source_model_id = match.group(1) if match else None
    source_pdf_sha256 = project.source_pdf_sha256
    if source_pdf_sha256 is None:
        source_pdf_sha256 = next(
            (
                item.sha256
                for item in project.provenance_files
                if item.file_type == "pdf" or item.role == "source_provenance_pdf"
            ),
            None,
        )
    return replace(
        project,
        reference_files=tuple(enriched_files),
        reference_spec_sufficiency=sufficiency,
        source_model_id=source_model_id,
        source_pdf_sha256=source_pdf_sha256,
        canonical_selection_basis=project.canonical_selection_basis
        or "locked pilot canonical membership preserved from the existing pilot manifest",
    )


def _project_quality(project: Any, output_root: Path) -> list[dict[str, Any]]:
    result = []
    for reference in project.reference_files:
        result.append(
            {
                "part_id": reference.part_id,
                "file_type": reference.file_type,
                "sha256": reference.sha256,
                "authority": reference.authority,
                "quality_classification": reference.quality_classification,
                "relative_path": reference.relative_path,
            }
        )
    return result


def freeze_corpus(
    *,
    acquisition_zip: Path,
    output_root: Path,
    intake_manifest_path: Path,
    manifest_path: Path,
    report_path: Path,
) -> dict[str, Any]:
    acquisition_zip = acquisition_zip.resolve()
    output_root = output_root.resolve()
    intake_manifest_path = intake_manifest_path.resolve()
    manifest_path = manifest_path.resolve()
    report_path = report_path.resolve()
    if not acquisition_zip.exists():
        raise BenchmarkImportError(f"acquisition ZIP does not exist: {acquisition_zip}")
    outer_sha256 = sha256_file(acquisition_zip)
    if outer_sha256 != EXPECTED_OUTER_SHA256:
        raise BenchmarkImportError(
            f"outer acquisition SHA-256 mismatch: expected {EXPECTED_OUTER_SHA256}, found {outer_sha256}"
        )
    intake = json.loads(intake_manifest_path.read_text(encoding="utf-8"))
    annotations = intake.get("projects")
    if not isinstance(annotations, list) or len(annotations) != EXPECTED_ADDITIONAL_PROJECTS:
        raise BenchmarkImportError("intake manifest must contain exactly 45 projects")
    annotation_by_id = {item["benchmark_id"]: item for item in annotations}
    if len(annotation_by_id) != len(annotations):
        raise BenchmarkImportError("intake project IDs must be unique")
    if set(annotation_by_id) & {
        project.benchmark_id for project in BenchmarkManifest.from_path(PILOT_MANIFEST).projects
    }:
        raise BenchmarkImportError("additional intake overlaps locked pilot IDs")

    by_category: dict[str, int] = {}
    for item in annotations:
        by_category[item["category"]] = by_category.get(item["category"], 0) + 1
    if len(by_category) != 9 or set(by_category.values()) != {5}:
        raise BenchmarkImportError(f"additional intake categories are not nine groups of five: {by_category}")

    run_root = output_root.parent / "incoming" / f"external-cad-50-freeze-{outer_sha256}"
    if run_root.exists():
        raise BenchmarkImportError(f"refusing to reuse existing intake run directory: {run_root}")
    run_root.mkdir(parents=True)
    extracted_root = run_root / "extracted"
    metadata_root = run_root / "metadata"
    raw_root = output_root / BENCHMARK_ID / "source-zips"
    extracted_root.mkdir()
    metadata_root.mkdir()
    raw_root.mkdir(parents=True, exist_ok=False)

    imported_manifest_path = run_root / "import-manifest.json"
    imported_manifest_payload = {
        "schema_version": "external-cad-benchmark-manifest-v1",
        "benchmark_id": BENCHMARK_ID,
        "benchmark_version": "1.0.0",
        "target_project_count": 50,
        "target_category_count": 10,
        "projects": [
            {
                "benchmark_id": item["benchmark_id"],
                "category": item["category"],
                "status": "placeholder",
                "split_assignment": "pilot",
            }
            for item in annotations
        ],
    }
    _write_json(imported_manifest_path, imported_manifest_payload)
    inner_hashes: dict[str, str] = {}
    source_zip_paths: dict[str, str] = {}

    try:
        with zipfile.ZipFile(acquisition_zip) as outer:
            bad_outer_member = outer.testzip()
            if bad_outer_member is not None:
                raise BenchmarkImportError(f"outer ZIP CRC failure at {bad_outer_member}")
            inner_members = [name for name in outer.namelist() if name.endswith(".zip")]
            expected_members = {item["package_member"] for item in annotations}
            if set(inner_members) != expected_members:
                raise BenchmarkImportError("outer ZIP members do not exactly match intake metadata")

            for item in annotations:
                project = item["benchmark_id"]
                inner_member = item["package_member"]
                inner_bytes = outer.read(inner_member)
                inner_hashes[project] = _sha256_bytes(inner_bytes)
                raw_path = raw_root / f"{project}.zip"
                raw_path.write_bytes(inner_bytes)
                if raw_path.read_bytes() != inner_bytes:
                    raise BenchmarkImportError(f"{project}: source ZIP was not preserved byte-for-byte")
                source_zip_paths[project] = raw_path.relative_to(REPO_ROOT).as_posix()
                project_root = extracted_root / project
                project_root.mkdir()
                with zipfile.ZipFile(io.BytesIO(inner_bytes)) as inner:
                    bad_inner_member = inner.testzip()
                    if bad_inner_member is not None:
                        raise BenchmarkImportError(f"{project}: inner ZIP CRC failure at {bad_inner_member}")
                    _safe_extract(inner, project_root)
                    files = _zip_file_members(inner)
                metadata, canonical_paths, provenance_paths = _source_metadata(
                    item,
                    extracted_files=files,
                    extracted_root=project_root,
                    project=project,
                )
                metadata_path = metadata_root / f"{project}.json"
                _write_json(metadata_path, metadata)
                try:
                    import_reference(
                        benchmark=BENCHMARK_ID,
                        project=project,
                        source_metadata_path=metadata_path,
                        reference_files=canonical_paths,
                        provenance_files=provenance_paths,
                        manifest_path=imported_manifest_path,
                        output_root=output_root,
                        repository_root=REPO_ROOT,
                    )
                except BenchmarkImportError as exc:
                    raise BenchmarkImportError(f"{project}: {exc}") from exc

        imported = BenchmarkManifest.from_path(imported_manifest_path)
        pilot = BenchmarkManifest.from_path(PILOT_MANIFEST)
        combined = [_enrich_locked_pilot_project(project) for project in pilot.projects]
        combined.extend(imported.projects)
        assignments = assign_balanced_split(combined)
        frozen_projects = tuple(
            replace(
                project,
                benchmark_version="1.0.0",
                split_assignment=assignments[project.benchmark_id],
            )
            for project in sorted(combined, key=lambda item: item.benchmark_id)
        )
        validate_corpus_shape(frozen_projects)

        holdout_policy = build_holdout_policy()
        holdout_policy["protected_projects"] = [
            {"benchmark_id": project.benchmark_id, "category": project.category, "split_assignment": project.split_assignment}
            for project in frozen_projects
            if project.split_assignment == "holdout"
        ]
        final_manifest = BenchmarkManifest(
            schema_version="external-cad-benchmark-manifest-v1",
            benchmark_id=BENCHMARK_ID,
            benchmark_version="1.0.0",
            target_project_count=50,
            target_category_count=10,
            projects=frozen_projects,
            metadata={
                "corpus_status": "frozen",
                "freeze_timestamp": "2026-08-08",
                "source_site": "Printables",
                "outer_acquisition_package": {
                    "filename": acquisition_zip.name,
                    "relative_path": acquisition_zip.relative_to(REPO_ROOT).as_posix(),
                    "sha256": outer_sha256,
                    "inner_archive_count": len(inner_hashes),
                },
                "source_zip_sha256": inner_hashes,
                "source_zip_relative_paths": source_zip_paths,
                "pilot_manifest_preserved": PILOT_MANIFEST.relative_to(REPO_ROOT).as_posix(),
                "split_policy": {
                    "algorithm": "lexicographic benchmark_id within each category",
                    "assignments_by_category": {"development": 3, "validation": 1, "holdout": 1},
                    "pilot_projects_excluded_from_pilot_split": True,
                },
                "holdout_policy": holdout_policy,
                "provider_calls": 0,
                "worker_executions": 0,
                "benchmark_runs": 0,
            },
        )
        _write_json(manifest_path, final_manifest.to_dict())
        _write_json(HOLDOUT_POLICY_PATH, holdout_policy)

        project_dicts = []
        for project in frozen_projects:
            project_payload = {
                "benchmark_id": project.benchmark_id,
                "category": project.category,
                "source_model_id": project.source_model_id,
                "source_url": project.source_url,
                "source_title": project.source_title,
                "creator": project.creator,
                "license": project.license,
                "acquired_at": project.acquired_at,
                "source_pdf_sha256": project.source_pdf_sha256,
                "split_assignment": project.split_assignment,
                "canonical_parts": _project_quality(project, output_root),
                "canonical_part_count": project.canonical_part_count,
                "reference_set_sha256": project.reference_set_sha256,
                "provenance_file_count": len(project.provenance_files),
                "canonical_selection_basis": project.canonical_selection_basis,
                "source_description_summary": project.source_description_summary,
                "premise_sha256": hashlib.sha256(project.premise.encode()).hexdigest(),
                "reference_spec_sha256": hashlib.sha256(
                    json.dumps(project.reference_spec, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                "reference_spec_sufficiency": project.reference_spec_sufficiency
                or project.reference_spec.get("sufficiency"),
                "ambiguity_flags": list(project.ambiguity_flags),
                "replacement_recommended": project.replacement_recommended,
            }
            project_dicts.append(project_payload)

        report = {
            "schema_version": "external-cad-benchmark-corpus-freeze-report-v1",
            "benchmark_id": BENCHMARK_ID,
            "status": "frozen",
            "outer_acquisition_sha256": outer_sha256,
            "inner_archive_integrity": {
                "count": len(inner_hashes),
                "all_crc_valid": True,
                "all_source_bytes_preserved": True,
                "sha256": inner_hashes,
            },
            "project_count": len(frozen_projects),
            "category_count": len({project.category for project in frozen_projects}),
            "projects": project_dicts,
            "category_counts": {
                category: sum(project.category == category for project in frozen_projects)
                for category in sorted({project.category for project in frozen_projects})
            },
            "split_counts": {
                assignment: sum(project.split_assignment == assignment for project in frozen_projects)
                for assignment in ("development", "validation", "holdout")
            },
            "ambiguous_projects": [project.benchmark_id for project in frozen_projects if project.ambiguity_flags],
            "projects_requiring_replacement_consideration": [
                project.benchmark_id for project in frozen_projects if project.replacement_recommended
            ],
            "non_watertight_reference_parts": [
                {
                    "benchmark_id": project.benchmark_id,
                    "part_id": reference.part_id,
                }
                for project in frozen_projects
                for reference in project.reference_files
                if reference.quality_classification == "nonwatertight_mesh_reference"
            ],
            "reference_authority_policy": {
                "step_brep": "analytic_brep_authoritative when topology is valid",
                "stl_3mf": "mesh-derived; closed-volume metrics unavailable when non-watertight",
                "native_source": "provenance_only",
            },
            "holdout_protection": holdout_policy,
            "requirement_vs_similarity_separate": True,
            "provider_calls": 0,
            "worker_executions": 0,
            "benchmark_runs": 0,
            "process_contamination_audit": {
                "holdout_details_used_before_split": False,
                "holdout_runs_started": False,
                "third_party_bytes_committed": False,
                "benchmark_specific_cad_generation": False,
            },
            "manifest_relative_path": manifest_path.relative_to(REPO_ROOT).as_posix(),
        }
        _write_json(report_path, report)
        return {
            "manifest": str(manifest_path),
            "report": str(report_path),
            "project_count": len(frozen_projects),
            "category_count": len({project.category for project in frozen_projects}),
            "outer_sha256": outer_sha256,
            "provider_calls": 0,
            "worker_executions": 0,
        }
    except Exception:
        shutil.rmtree(output_root / BENCHMARK_ID, ignore_errors=True)
        manifest_path.unlink(missing_ok=True)
        report_path.unlink(missing_ok=True)
        HOLDOUT_POLICY_PATH.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = freeze_corpus(
            acquisition_zip=args.acquisition_zip,
            output_root=args.output_root,
            intake_manifest_path=args.intake_manifest,
            manifest_path=args.manifest,
            report_path=args.report,
        )
    except (BenchmarkImportError, OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"corpus freeze failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
