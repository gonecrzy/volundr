"""Offline counterfactual replay for category-A envelope recovery."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from collections import Counter
from pathlib import Path
from typing import Any

from app.services.requirements.trace import canonicalize_dimension_envelopes


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SURVEY_ROOT = ROOT / "data/debug-sessions/external-benchmarks/cad-50-v1.1/development-first-pass"
DEFAULT_RECONSTRUCTION = ROOT / "data/debug-sessions/executable-cadquery/recovery-development-16/phase-1b-external-cad-semantic-unverifiable-reconstruction.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_paths(root: Path) -> list[Path]:
    return sorted([*root.glob("premise-only/*/run.json"), *root.glob("comparison-specification/*/run.json")])


def _is_bounds(item: dict[str, Any]) -> bool:
    value = item.get("value")
    return isinstance(value, dict) and {"width", "depth", "height"}.issubset(value)


def replay(
    survey_root: Path = DEFAULT_SURVEY_ROOT,
    reconstruction_path: Path = DEFAULT_RECONSTRUCTION,
) -> dict[str, Any]:
    reconstruction = _load(reconstruction_path)
    categories = {
        (item["benchmark_project_id"], item["mode"], item["requirement_id"]): item["primary_category"]
        for item in reconstruction["requirements"]
    }
    cells: list[dict[str, Any]] = []
    all_recovered_a: list[dict[str, Any]] = []
    total_canonical_bounds = 0
    total_reduced_requirements = 0
    for path in _run_paths(survey_root):
        run = _load(path)
        if run.get("failure_class") != "semantic_requirement_unverifiable":
            continue
        contract = run["executable_contract"]["contract"]
        before = contract.get("requirements", [])
        normalization_inputs = []
        for item in before:
            normalized_item = deepcopy(item)
            expected = normalized_item.pop("expected", None)
            if isinstance(expected, dict) and set(expected) == {"value"}:
                normalized_item["value"] = expected["value"]
            normalization_inputs.append(normalized_item)
        after = canonicalize_dimension_envelopes(normalization_inputs)
        groups = [item for item in after if isinstance(item, dict) and _is_bounds(item)]
        total_canonical_bounds += len(groups)
        total_reduced_requirements += len(before) - len(after)
        recovered_a: list[dict[str, Any]] = []
        for group in groups:
            source_ids = group.get("provenance", {}).get("source_requirement_ids", [])
            source_categories = [
                categories.get((run["benchmark_project_id"], run["mode"], source_id))
                for source_id in source_ids
            ]
            if source_categories and all(category == "A" for category in source_categories):
                recovered_a.append(
                    {
                        "canonical_requirement_id": group.get("requirement_id"),
                        "source_requirement_ids": source_ids,
                        "expected": group.get("value"),
                        "verification_policy_after_materialization": "final_mesh_bounds",
                    }
                )
                all_recovered_a.extend(
                    {
                        "benchmark_project_id": run["benchmark_project_id"],
                        "mode": run["mode"],
                        "requirement_id": source_id,
                    }
                    for source_id in source_ids
                )
        before_counts = Counter(
            categories[(run["benchmark_project_id"], run["mode"], item["requirement_id"])]
            for item in before
            if (run["benchmark_project_id"], run["mode"], item["requirement_id"]) in categories
        )
        recovered_a_count = sum(len(item["source_requirement_ids"]) for item in recovered_a)
        after_counts = dict(before_counts)
        after_counts["A"] = after_counts.get("A", 0) - recovered_a_count
        cells.append(
            {
                "benchmark_project_id": run["benchmark_project_id"],
                "mode": run["mode"],
                "original_requirement_count": len(before),
                "counterfactual_requirement_count": len(after),
                "canonical_bounds_requirements": groups,
                "recovered_category_a": recovered_a,
                "original_category_counts": dict(before_counts),
                "category_counts_after_a_only": after_counts,
                "historical_evidence_mutated": False,
            }
        )

    original = Counter()
    for cell in cells:
        original.update(cell["original_category_counts"])
    recovered_a_count = len(all_recovered_a)
    after = dict(original)
    after["A"] = after.get("A", 0) - recovered_a_count
    a_only_states = {"candidate_blocked": len(cells), "candidate_ready_for_review": 0, "candidate_fully_verified": 0}
    prior_counterfactual = reconstruction["completion_gate_counterfactual"]["states"]
    return {
        "schema_version": "phase-1b-external-cad-envelope-canonicalization-replay-v1",
        "replay_type": "offline_counterfactual_only",
        "provider_calls": 0,
        "worker_executions": 0,
        "validation_details_loaded": False,
        "holdout_details_loaded": False,
        "input_failure_class": "semantic_requirement_unverifiable",
        "cells": cells,
        "summary": {
            "cell_count": len(cells),
            "canonical_bounds_requirements_produced": total_canonical_bounds,
            "scalar_requirements_removed_by_canonicalization": total_reduced_requirements,
            "category_a_requirements_recovered": recovered_a_count,
            "category_a_requirements_remaining": after.get("A", 0),
            "category_counts_before": dict(original),
            "category_counts_after_a_only": after,
            "category_b_after": after.get("B", 0),
            "category_c_after": after.get("C", 0),
            "category_e_after": after.get("E", 0),
            "a_only_candidate_state_counterfactual": a_only_states,
            "prior_a_and_b_fixed_counterfactual": prior_counterfactual,
        },
        "interpretation": {
            "recovered_a_scope": "single-output or already defensibly scoped envelope facts only",
            "multi_output_scope_recovery": "not implemented; part-scoped tuples remain blocked by category C where output identity is collapsed",
            "mixed_operator_behavior": "incompatible exact/approximately members remain ungrouped and fail closed",
            "flexible_behavior": "flexible/model-selected envelopes may be tuple-normalized but remain flexible and unprotected; category B is unchanged",
            "semantic_status_claim": "no live recovery or candidate PASS is claimed",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--survey-root", type=Path, default=DEFAULT_SURVEY_ROOT)
    parser.add_argument("--reconstruction", type=Path, default=DEFAULT_RECONSTRUCTION)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = replay(args.survey_root, args.reconstruction)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
