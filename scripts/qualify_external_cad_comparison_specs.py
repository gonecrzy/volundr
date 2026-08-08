#!/usr/bin/env python3
"""Audit v1 design specifications and build comparison-qualified v1.1 metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.external_benchmarks.comparison_specs import (
    COMPARISON_SPEC_METHODOLOGY_VERSION,
    COMPARISON_SPEC_SCHEMA_VERSION,
    build_comparison_specification,
    build_sealed_holdout_record,
    comparison_specification_hash,
)
from app.services.external_benchmarks.models import BenchmarkManifest


REPO_ROOT = Path(__file__).resolve().parents[1]
INPUT_MANIFEST = REPO_ROOT / "benchmarks/external/cad-50-v1/manifest.json"
OUTPUT_ROOT = REPO_ROOT / "benchmarks/external/cad-50-v1.1"


def _sha256_json(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _derived_path(project: dict[str, Any]) -> Path:
    reference_path = REPO_ROOT / project["reference_files"][0]["relative_path"]
    return reference_path.parent.parent / "derived-reference.json"


def _read_derived(project: dict[str, Any]) -> dict[str, Any]:
    return json.loads(_derived_path(project).read_text(encoding="utf-8"))


def _reference_authority(project: dict[str, Any]) -> str:
    authorities = sorted({str(item.get("authority")) for item in project["reference_files"]})
    return ", ".join(authorities)


def _existing_ready(project: dict[str, Any]) -> bool:
    facts = project.get("reference_spec", {}).get("facts", [])
    ids = {str(fact.get("id")) for fact in facts}
    has_envelope = "overall_envelope" in ids
    has_interface = any(
        any(token in str(fact.get("id", "")).lower() for token in ("diameter", "interface", "spacing", "clearance"))
        and isinstance(fact.get("value"), (int, float, dict, list))
        for fact in facts
    )
    return has_envelope and has_interface


def _audit_row(project: dict[str, Any], specification: dict[str, Any]) -> dict[str, Any]:
    flags = set(project.get("ambiguity_flags", []))
    if specification["status"] == "replacement_required":
        intent_match = "not_defensible_as_current_comparison_target"
        membership = "explicit_but_scope_too_broad_or_ambiguous"
    elif flags:
        intent_match = "provisionally_consistent_with_canonical_geometry; ambiguity_flag_requires_review"
        membership = "explicit_with_ambiguity_flag"
    else:
        intent_match = "provisionally_consistent_with_selected_canonical_parts"
        membership = "explicit"
    supplied = sorted(
        {str(fact.get("id")) for fact in specification["facts"]}
        | {"per_part_envelope"}
    )
    action = {
        "comparison_ready": "comparison_ready",
        "needs_spec_enrichment": "enrich_comparison_specification",
        "replacement_required": "replace_before_comparison_scoring",
    }[specification["status"]]
    return {
        "benchmark_id": project["benchmark_id"],
        "canonical_part_count": len(project["reference_files"]),
        "reference_authority": _reference_authority(project),
        "existing_sufficiency": project.get("reference_spec_sufficiency"),
        "source_description_summary": project.get("source_description_summary"),
        "canonical_selection_basis": project.get("canonical_selection_basis"),
        "source_intent_match": intent_match,
        "canonical_membership": membership,
        "selected_variants": [output["selected_variant"] for output in specification["outputs"]],
        "actual_geometry_evidence": [
            {
                "part_id": output["part_id"],
                "overall_envelope_mm": output["overall_envelope_mm"],
                "authority": output["authority"],
                "quality_classification": output["quality_classification"],
                "solid_count": output["solid_count"],
            }
            for output in specification["outputs"]
        ],
        "existing_specification_fact_ids": sorted(
            str(fact.get("id")) for fact in project.get("reference_spec", {}).get("facts", [])
        ),
        "design_driving_facts_already_supplied": supplied,
        "missing_design_driving_facts": specification["missing_design_driving_facts"],
        "geometric_similarity_fair": specification["comparison_ready"],
        "comparison_readiness": specification["status"],
        "action": action,
    }


def qualify(*, input_manifest: Path, output_root: Path) -> dict[str, Any]:
    source = BenchmarkManifest.from_path(input_manifest)
    if source.benchmark_id != "external-cad-50-v1":
        raise ValueError("comparison qualification requires external-cad-50-v1")
    if output_root.exists():
        raise ValueError(f"refusing to overwrite existing qualification directory: {output_root}")
    output_root.mkdir(parents=True)

    full_specs: dict[str, list[dict[str, Any]]] = {"development": [], "validation": []}
    sealed_holdouts: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    project_records: list[dict[str, Any]] = []

    for source_project in source.projects:
        project = source_project.to_dict()
        split = project["split_assignment"]
        specification = build_comparison_specification(project, _read_derived(project))
        spec_hash = comparison_specification_hash(specification)
        if split == "holdout":
            # Generic extraction is applied, but no holdout specification or
            # result is written into development-visible evidence.
            sealed = build_sealed_holdout_record(specification)
            sealed_holdouts.append(sealed)
            project_records.append(sealed)
            continue

        if split not in full_specs:
            raise ValueError(f"unexpected split assignment: {split}")
        full_specs[split].append(specification)
        if split != "development":
            project_records.append(
                {
                    "benchmark_id": project["benchmark_id"],
                    "category": project["category"],
                    "split_assignment": split,
                    "comparison_specification_hash": spec_hash,
                    "comparison_specification_status": specification["status"],
                    "comparison_ready": specification["comparison_ready"],
                    "source_reference_set_sha256": project.get("reference_set_sha256"),
                }
            )
            continue
        row = _audit_row(project, specification)
        row["specification_hash"] = spec_hash
        audit_rows.append(row)
        project_records.append(
            {
                "benchmark_id": project["benchmark_id"],
                "category": project["category"],
                "split_assignment": split,
                "comparison_specification_hash": spec_hash,
                "comparison_specification_status": specification["status"],
                "comparison_ready": specification["comparison_ready"],
                "source_reference_set_sha256": project.get("reference_set_sha256"),
            }
        )

    for split, specifications in full_specs.items():
        specifications.sort(key=lambda item: item["benchmark_id"])
        _write_json(output_root / f"comparison-specifications-{split}.json", {
            "schema_version": COMPARISON_SPEC_SCHEMA_VERSION,
            "methodology_version": COMPARISON_SPEC_METHODOLOGY_VERSION,
            "source_benchmark_id": source.benchmark_id,
            "split": split,
            "projects": specifications,
        })
    sealed_holdouts.sort(key=lambda item: item["benchmark_id"])
    _write_json(output_root / "holdout-comparison-specifications-sealed.json", {
        "schema_version": "external-cad-holdout-comparison-specifications-sealed-v1",
        "methodology_version": COMPARISON_SPEC_METHODOLOGY_VERSION,
        "source_benchmark_id": source.benchmark_id,
        "projects": sealed_holdouts,
    })

    audit_rows.sort(key=lambda item: item["benchmark_id"])
    summary = Counter(row["comparison_readiness"] for row in audit_rows)
    existing_ready = sum(1 for row in audit_rows if row["comparison_readiness"] == "comparison_ready" and _existing_ready(source.project(row["benchmark_id"]).to_dict()))
    enriched_ready = summary["comparison_ready"] - existing_ready
    audit = {
        "schema_version": "external-cad-development-comparison-audit-v1",
        "source_benchmark_id": source.benchmark_id,
        "methodology_version": COMPARISON_SPEC_METHODOLOGY_VERSION,
        "development_project_count": len(audit_rows),
        "projects": audit_rows,
        "summary": {
            "comparison_ready_without_changes": existing_ready,
            "enriched_to_comparison_ready": enriched_ready,
            "still_underconstrained": summary["needs_spec_enrichment"],
            "replacement_required": summary["replacement_required"],
        },
    }
    _write_json(output_root / "development-audit-30.json", audit)

    methodology = {
        "schema_version": "external-cad-comparison-specification-methodology-v1",
        "methodology_version": COMPARISON_SPEC_METHODOLOGY_VERSION,
        "input": "frozen manifest metadata plus persisted derived-reference.json",
        "allowed_geometry_facts": [
            "per-part overall envelope",
            "solid/component count when already reliable",
            "existing explicit dimensional or interface facts",
        ],
        "prohibited_data": ["vertices", "faces", "point_clouds", "raw_mesh", "source_cad", "reference_render"],
        "fact_provenance": [
            "creator_documented",
            "reference_geometry_measured",
            "manual_benchmark_annotation",
        ],
        "measurement_method_version": "external-cad-reference-derived-v1.geometry.bounding_box_mm",
        "qualification_gate": {
            "output_identity": "explicit canonical part membership and count",
            "selected_variant": "explicit canonical filename and selection reason",
            "major_envelope": "coarse envelope for every canonical output",
            "principal_mating_geometry": "at least one explicit dimensional/interface fact",
            "critical_interface_geometry": "at least one explicit dimensional constraint beyond output count",
            "multi_part_relationships": "explicit output mapping or relationship facts for multi-part designs",
            "ambiguity": "fail closed; replacement or enrichment remains required",
        },
        "similarity_rule": "only comparison_ready projects receive interpreted reference-similarity metrics",
        "validation_policy": "apply unchanged; do not tune per project after development results",
        "holdout_policy": "apply unchanged and persist only allowed metadata plus sealed hashes",
    }
    _write_json(output_root / "comparison-methodology.json", methodology)

    manifest = {
        "schema_version": "external-cad-benchmark-manifest-v1.1",
        "benchmark_id": "external-cad-50-v1.1",
        "source_benchmark_id": source.benchmark_id,
        "methodology_version": COMPARISON_SPEC_METHODOLOGY_VERSION,
        "qualification_status": "comparison_specification_qualified",
        "projects": sorted(project_records, key=lambda item: item["benchmark_id"]),
        "holdout_policy": "benchmarks/external/cad-50-v1/holdout-policy.json",
        "historical_v1_manifest": "benchmarks/external/cad-50-v1/manifest.json",
        "comparison_specs": {
            "development": "benchmarks/external/cad-50-v1.1/comparison-specifications-development.json",
            "validation": "benchmarks/external/cad-50-v1.1/comparison-specifications-validation.json",
            "holdout_sealed": "benchmarks/external/cad-50-v1.1/holdout-comparison-specifications-sealed.json",
        },
    }
    _write_json(output_root / "manifest.json", manifest)

    report = {
        "schema_version": "external-cad-comparison-qualification-report-v1",
        "benchmark_id": "external-cad-50-v1.1",
        "source_benchmark_id": source.benchmark_id,
        "status": "qualified_for_review_before_live_development_survey",
        "development_audit": "benchmarks/external/cad-50-v1.1/development-audit-30.json",
        "methodology": "benchmarks/external/cad-50-v1.1/comparison-methodology.json",
        "development_summary": audit["summary"],
        "validation_structurally_processed": len(full_specs["validation"]),
        "holdout_sealed_count": len(sealed_holdouts),
        "holdout_values_exposed": False,
        "v1_preserved": True,
        "reference_similarity_requires_ready": True,
        "provider_calls": 0,
        "worker_generation_calls": 0,
        "benchmark_runs": 0,
        "production_cad_changes": False,
    }
    _write_json(output_root / "qualification-report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-manifest", type=Path, default=INPUT_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    report = qualify(input_manifest=args.input_manifest, output_root=args.output_root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
