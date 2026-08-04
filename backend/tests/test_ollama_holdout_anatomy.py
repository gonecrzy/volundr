from __future__ import annotations

from copy import deepcopy
import inspect
from pathlib import Path

import app.services.ollama_benchmark.holdout_anatomy as anatomy
import pytest
from app.services.ollama_benchmark.holdout_anatomy import (
    assess_holdout_fairness,
    classify_quality_band,
    earliest_authoritative_blocker,
    normalization_audit,
    reassess_admission,
    recurring_signature_models,
)


def test_earliest_blocker_wins_over_later_findings() -> None:
    findings = [
        {"stage": "broad_geometry_mismatch", "signature": "wrong_overall_dimensions"},
        {"stage": "python_ast", "signature": "invalid_python"},
        {"stage": "worker_runtime", "signature": "worker_exception"},
    ]

    assert earliest_authoritative_blocker(findings) == findings[1]


def test_secondary_findings_remain_preserved() -> None:
    findings = [
        {"stage": "source_safety", "signature": "unsafe_source"},
        {"stage": "worker_runtime", "signature": "worker_exception"},
        {"stage": "broad_geometry_mismatch", "signature": "wrong_overall_dimensions"},
    ]

    blocker = earliest_authoritative_blocker(findings)

    assert blocker == findings[0]
    assert [finding["signature"] for finding in findings if finding is not blocker] == [
        "worker_exception",
        "wrong_overall_dimensions",
    ]


def test_shared_signature_requires_three_distinct_models() -> None:
    attempts = [
        {"model_id": "a", "primary_signature": "worker_timeout"},
        {"model_id": "a", "primary_signature": "worker_timeout"},
        {"model_id": "b", "primary_signature": "worker_timeout"},
        {"model_id": "c", "primary_signature": "wrong_overall_dimensions"},
    ]

    assert recurring_signature_models(attempts, "worker_timeout") == []
    attempts.append({"model_id": "c", "primary_signature": "worker_timeout"})
    assert recurring_signature_models(attempts, "worker_timeout") == ["a", "b", "c"]


def test_infrastructure_findings_cannot_become_cad_quality_conclusions() -> None:
    assert classify_quality_band(
        {"success": False, "worker_reached": False, "topology": None}
    ) == "no_executable_geometry"
    assert classify_quality_band(
        {"success": False, "worker_reached": True, "topology": None}
    ) == "no_executable_geometry"


def test_normalization_differences_are_reported_without_rewriting_source() -> None:
    raw = "```python\nresult = 1\n```\n"
    normalized = "result = 1"

    audit = normalization_audit(raw, normalized, ["representation.markdown_wrapped"])

    assert audit["changed"] is True
    assert audit["safe_wrapper_only"] is True
    assert audit["removed_lines"] == ["```python", "```"]
    assert audit["normalized_source"] == normalized


def test_quality_bands_derive_consistently() -> None:
    assert classify_quality_band({"success": True, "topology": {"valid": True}, "broad_geometry": {"status": "passed"}}) == "holdout_pass"
    assert classify_quality_band({"success": True, "topology": {"valid": True}, "broad_geometry": {"status": "failed", "feature_check": {"status": "failed"}}}) == "partially_satisfies_holdout"
    assert classify_quality_band({"success": True, "topology": {"valid": False}, "broad_geometry": {"status": "failed"}}) == "executable_but_invalid"


def test_holdout_fairness_is_explicit() -> None:
    result = assess_holdout_fairness(
        {
            "prompt": "Create a plate with four through-holes.",
            "expected_broad_geometry": ["one plate", "four through-holes"],
        }
    )

    assert result["classification"] == "fair_with_minor_evaluator_risk"
    assert result["expectations_derivable"] is True
    assert result["risk"]


def test_admission_reassessment_does_not_mutate_existing_records() -> None:
    current = {"cad-coder": {"admission": "operational_low_cad_quality"}}
    snapshot = deepcopy(current)

    proposed = reassess_admission(current, [{"model_id": "cad-coder", "quality_band": "partially_satisfies_holdout"}])

    assert current == snapshot
    assert proposed["cad-coder"]["current_disposition"] == "operational_low_cad_quality"


def test_report_generation_is_read_only_and_has_no_provider_or_worker_calls() -> None:
    source = inspect.getsource(anatomy)

    assert "OllamaProvider" not in source
    assert "CadWorker" not in source
    assert "process_next_job" not in source


def test_frozen_report_generation_reads_all_pairs_without_mutating_admission() -> None:
    evidence_root = Path(__file__).parents[2] / "data/debug-sessions/ollama-calibration/calibration-admission-report"
    if not (evidence_root / "admission.json").is_file():
        pytest.skip("frozen calibration evidence is not available")
    admission_before = (evidence_root / "admission.json").read_bytes()

    report = anatomy.analyze_frozen_evidence(evidence_root)

    assert len(report["attempts"]) == 12
    assert (evidence_root / "admission.json").read_bytes() == admission_before
