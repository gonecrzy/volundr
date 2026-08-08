"""Deterministic validation and split policy for the external CAD corpus."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any


def _value(project: Any, key: str) -> Any:
    if isinstance(project, Mapping):
        return project.get(key)
    return getattr(project, key)


def assign_balanced_split(projects: Sequence[Any]) -> dict[str, str]:
    """Assign 3 development, 1 validation, and 1 holdout per category."""

    by_category: dict[str, list[str]] = defaultdict(list)
    for project in projects:
        by_category[str(_value(project, "category"))].append(str(_value(project, "benchmark_id")))
    assignments: dict[str, str] = {}
    for category, project_ids in sorted(by_category.items()):
        ordered = sorted(project_ids)
        if len(ordered) != 5:
            raise ValueError(f"category {category!r} must contain exactly five projects")
        for index, project_id in enumerate(ordered):
            assignments[project_id] = ("development", "development", "development", "validation", "holdout")[index]
    return assignments


def validate_corpus_shape(
    projects: Sequence[Any],
    *,
    expected_projects: int = 50,
    expected_categories: int = 10,
) -> None:
    ids = [str(_value(project, "benchmark_id")) for project in projects]
    if len(projects) != expected_projects:
        raise ValueError(f"expected {expected_projects} projects, found {len(projects)}")
    if len(ids) != len(set(ids)):
        raise ValueError("benchmark project IDs must be unique")
    categories = Counter(str(_value(project, "category")) for project in projects)
    if len(categories) != expected_categories:
        raise ValueError(f"expected {expected_categories} categories, found {len(categories)}")
    if set(categories.values()) != {5}:
        raise ValueError("every category must contain exactly five projects")
    split_counts = Counter(str(_value(project, "split_assignment")) for project in projects)
    if split_counts != Counter({"development": 30, "validation": 10, "holdout": 10}):
        raise ValueError(f"unexpected corpus split counts: {dict(split_counts)}")
    for category in categories:
        category_projects = [project for project in projects if str(_value(project, "category")) == category]
        counts = Counter(str(_value(project, "split_assignment")) for project in category_projects)
        if counts != Counter({"development": 3, "validation": 1, "holdout": 1}):
            raise ValueError(f"category {category!r} does not have a 3/1/1 split")


def build_holdout_policy() -> dict[str, Any]:
    return {
        "schema_version": "external-cad-benchmark-holdout-policy-v1",
        "protected_after_freeze": True,
        "allowed_metadata": ["benchmark_id", "category", "split_assignment"],
        "disallowed_metadata": [
            "source_title",
            "creator",
            "source_url",
            "premise",
            "reference_spec",
            "reference_geometry",
            "derived_geometry",
            "run_results",
        ],
        "qualification_gate": "phase_2_holdout_opened_explicitly",
        "public_model_caveat": "repository/process holdout; not proof of model non-exposure during training",
    }
