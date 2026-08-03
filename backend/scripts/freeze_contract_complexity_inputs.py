#!/usr/bin/env python3
"""Freeze redacted diagnostic inputs from an existing debug-batch report."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SOURCE_BATCH_ID = "c3179a89-62e2-4d61-b3dc-a36f4b9956b6"

PROJECTS = {
    "five_tray_wall_carrier": {
        "project_id": "f5264c40-b09d-4c23-adaa-6a1a7e11bce2",
        "approved_fact_sheet": {
            "unit": "Millimeters.",
            "capacity": "Up to five trays; fewer may be present.",
            "mount": "Vertical wall mounting.",
            "load": "Load trays from the front.",
            "handle": "Use an integral printed handle.",
            "retain": "Use a removable front retention bar.",
            "screw": "Use #10 wall-mounting screws.",
            "clearance": "Use a reasonable tray-clearance proposal.",
        },
    },
    "desktop_organizer": {
        "project_id": "ef3cc600-7230-4477-921d-fc4d76d80a0d",
        "approved_fact_sheet": {
            "unit": "Millimeters.",
            "open": "One connected printable part with an open top.",
            "dimension": "The overall dimensions are external.",
            "slot": "Center the rear slot.",
            "compartment": "Calculate the remaining front-right width; use a 55 mm center compartment and 3 mm dividers.",
            "notch": "Center the 12 mm cable notch in the rear wall; it passes through the wall, not the base.",
        },
    },
    "screw_lid_container": {
        "project_id": "f2c0c3f1-9647-4321-95c3-2c1627b302a5",
        "approved_fact_sheet": {
            "unit": "Millimeters.",
            "output": "Use two printable outputs: body and lid.",
            "diameter": "The internal diameter is 90 mm.",
            "height": "The usable internal height is 120 mm.",
            "overlap": "The lid overlap is 18 mm.",
            "thread": "Use a coarse single-start thread, 4 mm pitch, about 1.5 mm depth, and 0.4 mm radial clearance.",
            "watertight": "Do not assume a watertight guarantee.",
        },
    },
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _requirement_rows(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            key: requirement.get(key)
            for key in (
                "requirement_id",
                "type",
                "kind",
                "value",
                "unit",
                "source",
                "provenance",
                "status",
                "subject",
                "target",
                "explicit",
                "verification_evidence",
            )
        }
        for requirement in plan.get("requirements", [])
        if isinstance(requirement, dict) and requirement.get("requirement_id")
    ]


def _provenance(plan: dict[str, Any], trace: dict[str, Any]) -> dict[str, Any]:
    return {
        "requirement_sources": sorted(
            {
                str(item.get("source"))
                for item in plan.get("requirements", [])
                if isinstance(item, dict) and item.get("source")
            }
        ),
        "requirement_provenance": [
            {
                "requirement_id": item.get("requirement_id"),
                "source": item.get("source"),
                "provenance": item.get("provenance"),
            }
            for item in plan.get("requirements", [])
            if isinstance(item, dict) and item.get("requirement_id")
        ],
        "plan_proposals": plan.get("proposals", []),
        "plan_preserved_requirements": plan.get("preserved_requirements", []),
        "normalization_decisions": trace.get("normalization_decisions", []),
    }


def _find_artifact(project_root: Path, pattern: str) -> dict[str, Any]:
    matches = sorted(project_root.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"missing preserved evidence artifact: {pattern}")
    return _load(matches[0])


def freeze_project(*, slug: str, config: dict[str, Any], evidence_root: Path) -> dict[str, Any]:
    project_root = evidence_root / "projects" / config["project_id"]
    summary = _load(project_root / "summary.json")
    design_spec = _load(next(project_root.glob("findings/*design-spec*.json")))
    plan = _load(project_root / "planning" / "selected_compact_plan-parsed-design-plan.json")
    trace = _load(project_root / "requirements" / "requirement_trace_normalized-requirement-trace-normalized.json")
    context = _load(project_root / "geometrys" / "normalized_geometry_execution_context-geometry-execution-context.json")
    prompt_context_pack = _find_artifact(project_root, "prompts/generation_prompt_context_pack-*.json")
    provider_contract_manifest = _find_artifact(
        project_root,
        "findings/provider_contract_manifest-provider-contract-manifest.json",
    )

    package: dict[str, Any] = {
        "package_version": "diagnostic-input-v1",
        "source_batch_id": SOURCE_BATCH_ID,
        "source_project_id": config["project_id"],
        "family": slug,
        "project_name": summary["project_name"],
        "user_request": summary["original_intent"],
        "approved_fact_sheet": config["approved_fact_sheet"],
        "clarification_answers": [],
        "clarification_rounds_observed": 0,
        "authoritative_requirements": _requirement_rows(plan),
        "active_requirements": context.get("active_requirements", []),
        "provenance": _provenance(plan, trace),
        "design_specification": design_spec,
        "expected_components": plan.get("components", []),
        "expected_outputs": plan.get("printable_outputs", []),
        "required_functional_features": plan.get("features", []),
        "coordinate_frames": context.get("coordinate_frames", plan.get("coordinate_frames", [])),
        "relationships": context.get("relationships", plan.get("relationships", [])),
        "verification_targets": {
            "plan": plan.get("validation_targets", []),
            "requirement_trace": trace.get("validation_targets", []),
            "obligations": trace.get("obligations", []),
        },
        "exposed_controls": plan.get("exposed_controls", []),
        "prompt_context_pack": prompt_context_pack,
        "provider_contract_manifest": provider_contract_manifest,
        "source_plan": plan,
        "geometry_execution_context": context,
    }
    canonical = json.dumps(package, sort_keys=True, separators=(",", ":")).encode("utf-8")
    package["package_hash"] = hashlib.sha256(canonical).hexdigest()
    return package


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    evidence_root = args.evidence_root
    output_root = args.output_root
    output_root.mkdir(parents=True, exist_ok=True)
    for slug, config in PROJECTS.items():
        package = freeze_project(slug=slug, config=config, evidence_root=evidence_root)
        (output_root / f"{slug}.json").write_text(
            json.dumps(package, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    manifest = {
        "package_version": "diagnostic-input-manifest-v1",
        "source_batch_id": SOURCE_BATCH_ID,
        "families": sorted(PROJECTS),
        "package_hashes": {
            slug: _load(output_root / f"{slug}.json")["package_hash"]
            for slug in sorted(PROJECTS)
        },
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
