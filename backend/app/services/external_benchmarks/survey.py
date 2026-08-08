"""Frozen external-CAD development-survey inputs and gate logic.

This module owns only benchmark orchestration metadata.  It does not create
requirements or executable contracts; live cells are sent to the ordinary
executable-CadQuery workflow with the selected prompt as user intent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


SURVEY_SCHEMA_VERSION = "external-cad-development-first-pass-v1"
SURVEY_MODES = ("premise_only", "comparison_specification")
REPLACEMENT_STATUS = "replacement_required"


@dataclass(frozen=True)
class FrozenSurveyProject:
    benchmark_id: str
    category: str
    split_assignment: str
    premise: str
    comparison_prompt: str
    comparison_ready: bool
    comparison_specification_status: str
    comparison_specification_hash: str
    reference_set_sha256: str
    canonical_part_count: int | None
    reference_output_mapping: dict[str, str]
    reference_files: tuple[dict[str, Any], ...]

    @property
    def excluded(self) -> bool:
        return self.comparison_specification_status == REPLACEMENT_STATUS

    @property
    def reference_similarity_status(self) -> str:
        return reference_similarity_status(self.comparison_specification_status, generated=True)


@dataclass(frozen=True)
class SurveyCell:
    order: int
    benchmark_id: str
    category: str
    mode: str
    prompt: str
    excluded: bool
    exclusion_reason: str | None
    comparison_ready: bool
    reference_similarity_status: str
    comparison_specification_hash: str
    reference_set_sha256: str


def load_frozen_development_projects(
    v11_manifest_path: Path,
    v1_manifest_path: Path,
    development_specs_path: Path,
) -> tuple[FrozenSurveyProject, ...]:
    """Load only development inputs from the frozen v1.1 qualification.

    The v1 manifest is consulted only for the selected development IDs so the
    survey can recover the locked premise and canonical reference metadata.
    Holdout records are never returned or used as survey inputs.
    """

    v11_manifest = _read_object(v11_manifest_path)
    v11_projects = _list(v11_manifest, "projects")
    split_counts = _split_counts(v11_projects)
    if split_counts.get("development") != 30:
        raise ValueError("frozen v1.1 manifest must contain exactly 30 development projects")
    if split_counts != {"development": 30, "validation": 10, "holdout": 10}:
        raise ValueError(f"frozen v1.1 split counts are invalid: {split_counts}")

    development_entries = [
        item for item in v11_projects if item.get("split_assignment") == "development"
    ]
    if len(development_entries) != 30:
        raise ValueError("frozen v1.1 manifest must contain exactly 30 development projects")
    development_entries.sort(key=lambda item: (str(item.get("category")), str(item.get("benchmark_id"))))
    development_ids = [str(item.get("benchmark_id")) for item in development_entries]
    if any(not item for item in development_ids) or len(set(development_ids)) != 30:
        raise ValueError("development benchmark IDs must be present and unique")

    v1_manifest = _read_object(v1_manifest_path)
    v1_by_id: dict[str, Mapping[str, Any]] = {}
    for item in _list(v1_manifest, "projects"):
        if item.get("split_assignment") != "development":
            continue
        benchmark_id = item.get("benchmark_id")
        if benchmark_id in development_ids:
            v1_by_id[str(benchmark_id)] = item

    specs_payload = _read_object(development_specs_path)
    specs = _list(specs_payload, "projects")
    specs_by_id = {str(item.get("benchmark_id")): item for item in specs}
    if set(specs_by_id) != set(development_ids):
        raise ValueError("development comparison specifications do not match the frozen development IDs")

    projects: list[FrozenSurveyProject] = []
    for entry in development_entries:
        benchmark_id = str(entry["benchmark_id"])
        source = v1_by_id.get(benchmark_id)
        specification = specs_by_id[benchmark_id]
        if source is None:
            raise ValueError(f"v1 premise metadata is missing for development project {benchmark_id}")
        premise = _required_string(source, "premise")
        comparison_prompt = _required_string(specification, "prompt")
        status = _required_string(entry, "comparison_specification_status")
        if status not in {"comparison_ready", "needs_spec_enrichment", REPLACEMENT_STATUS}:
            raise ValueError(f"unsupported comparison status for {benchmark_id}: {status}")
        reference_files = source.get("reference_files")
        if not isinstance(reference_files, list):
            raise ValueError(f"reference_files missing for {benchmark_id}")
        projects.append(
            FrozenSurveyProject(
                benchmark_id=benchmark_id,
                category=_required_string(entry, "category"),
                split_assignment="development",
                premise=premise,
                comparison_prompt=comparison_prompt,
                comparison_ready=bool(entry.get("comparison_ready")),
                comparison_specification_status=status,
                comparison_specification_hash=_required_string(entry, "comparison_specification_hash"),
                reference_set_sha256=_required_string(entry, "source_reference_set_sha256"),
                canonical_part_count=(
                    int(source["canonical_part_count"])
                    if source.get("canonical_part_count") is not None
                    else None
                ),
                reference_output_mapping={
                    str(key): str(value)
                    for key, value in (source.get("reference_output_mapping") or {}).items()
                },
                reference_files=tuple(dict(item) for item in reference_files if isinstance(item, Mapping)),
            )
        )
    return tuple(projects)


def build_survey_order(projects: tuple[FrozenSurveyProject, ...]) -> tuple[SurveyCell, ...]:
    """Build the preregistered PASS-A/PASS-B order."""

    if len(projects) != 30:
        raise ValueError("survey order requires exactly 30 development projects")
    sorted_projects = tuple(sorted(projects, key=lambda item: (item.category, item.benchmark_id)))
    cells: list[SurveyCell] = []
    order = 1
    for mode in SURVEY_MODES:
        for project in sorted_projects:
            excluded = project.excluded
            cells.append(
                SurveyCell(
                    order=order,
                    benchmark_id=project.benchmark_id,
                    category=project.category,
                    mode=mode,
                    prompt=project.premise if mode == "premise_only" else project.comparison_prompt,
                    excluded=excluded,
                    exclusion_reason=REPLACEMENT_STATUS if excluded else None,
                    comparison_ready=project.comparison_ready,
                    reference_similarity_status=(
                        "replacement_required"
                        if excluded
                        else reference_similarity_status(project.comparison_specification_status, generated=True)
                    ),
                    comparison_specification_hash=project.comparison_specification_hash,
                    reference_set_sha256=project.reference_set_sha256,
                )
            )
            order += 1
    return tuple(cells)


def reference_similarity_status(status: str, *, generated: bool) -> str:
    if status == REPLACEMENT_STATUS:
        return "replacement_required"
    if not generated:
        return "unavailable"
    if status == "comparison_ready":
        return "eligible"
    return "specification_underconstrained"


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _list(payload: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{key} must be a list of objects")
    return value


def _split_counts(projects: list[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for project in projects:
        split = str(project.get("split_assignment") or "")
        counts[split] = counts.get(split, 0) + 1
    return counts


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()
