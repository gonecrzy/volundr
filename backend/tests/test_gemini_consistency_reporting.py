import json

from app.services.gemini_consistency.reporting import build_experiment_reports


def test_report_generation_is_local_and_writes_required_artifacts(tmp_path) -> None:
    experiment = {
        "id": "experiment-1",
        "mode": "pilot",
        "git_head": "abc",
        "migration_head": "0035",
        "provider": "gemini_api",
        "prompt_versions": {"requirements": "v1"},
        "configuration_hash": "config-a",
        "build_identities": {"backend": {"git_sha": "abc"}},
        "model_policy": {"temperature": 0.2},
    }
    records = [
        {"case_id": "case-001", "model": "flash", "run_index": 1, "evidence": {"requirements": {"a": 1}}},
        {"case_id": "case-001", "model": "flash", "run_index": 2, "evidence": {"requirements": {"a": 1}}},
        {"case_id": "case-001", "model": "pro", "run_index": 1, "evidence": {"requirements": {"a": 2}}},
        {"case_id": "case-001", "model": "pro", "run_index": 2, "evidence": None},
    ]

    result = build_experiment_reports(experiment, records, tmp_path)

    assert result["controlled_comparisons"]["flash"]["controlled"] is True
    assert result["controlled_comparisons"]["pro"]["controlled"] is True
    assert result["integrity_findings"]
    for name in (
        "pilot-summary.md",
        "model-comparison.md",
        "run-consistency.md",
        "failure-signatures.md",
        "codex-review.md",
        "integrity-report.json",
    ):
        assert (tmp_path / name).is_file(), name


def test_report_materializes_missing_artifacts_as_findings_without_crashing(tmp_path) -> None:
    result = build_experiment_reports(
        {"id": "experiment-2", "mode": "full", "git_head": "abc"},
        [{"case_id": "case-001", "model": "flash", "run_index": 1, "evidence": None}],
        tmp_path,
    )

    assert result["integrity_findings"][0]["kind"] == "missing_evidence"
    report = json.loads((tmp_path / "integrity-report.json").read_text())
    assert report["findings"]


def test_report_promotes_nested_metrics_integrity_findings(tmp_path) -> None:
    result = build_experiment_reports(
        {"id": "experiment-3", "mode": "pilot"},
        [{
            "case_id": "case-001",
            "model": "flash",
            "run_index": 1,
            "evidence": {"metrics": {"integrity_findings": [{"kind": "endpoint_unavailable"}]}},
        }],
        tmp_path,
    )

    assert any(item["kind"] == "endpoint_unavailable" for item in result["integrity_findings"])


def test_report_preserves_safe_gemini_model_identity_in_controlled_comparison(tmp_path) -> None:
    identity = {
        "git_head": "abc",
        "migration_head": "0035",
        "provider": "gemini_api",
        "model_policy": {"temperature": 0.2},
        "prompt_versions": {"requirements": "v1"},
        "configuration_hash": "config-a",
        "build_identities": {"backend": {"git_sha": "abc"}},
    }

    build_experiment_reports(
        {"id": "experiment-4", "mode": "pilot", **identity},
        [
            {"case_id": "case-001", "model": "gemini-3.5-flash", "run_index": 1, "identity": identity, "evidence": {}},
            {"case_id": "case-001", "model": "gemini-3.5-flash", "run_index": 2, "identity": identity, "evidence": {}},
        ],
        tmp_path,
    )

    report = json.loads((tmp_path / "comparison.json").read_text())
    assert report["controlled_comparisons"]["gemini-3.5-flash"]["controlled"] is True


def test_report_separates_provider_model_pairs_and_writes_resource_comparison(tmp_path) -> None:
    identity = {
        "git_head": "abc",
        "migration_head": "0036",
        "provider": "ollama",
        "model_policy": {"context_length": 8192, "temperature": 0.2},
        "prompt_versions": {"requirements": "v1"},
        "configuration_hash": "config-a",
        "build_identities": {"backend": {"git_sha": "abc"}},
    }
    build_experiment_reports(
        {"id": "experiment-5", "mode": "five_case", **identity},
        [
            {"case_id": "ollama-case-001", "provider": "gemini_api", "model": "gemini-3.5-flash-lite", "run_index": 1, "identity": {**identity, "provider": "gemini_api"}, "evidence": {"outcome_state": "working_version"}},
            {"case_id": "ollama-case-001", "provider": "gemini_api", "model": "gemini-3.5-flash-lite", "run_index": 2, "identity": {**identity, "provider": "gemini_api"}, "evidence": {"outcome_state": "working_version"}},
            {"case_id": "ollama-case-001", "provider": "ollama", "model": "procad:Q4_K_M", "run_index": 1, "identity": identity, "evidence": {"outcome_state": "failed", "metrics": {"provider_latency_ms": 20}}},
            {"case_id": "ollama-case-001", "provider": "ollama", "model": "procad:Q4_K_M", "run_index": 2, "identity": identity, "evidence": {"outcome_state": "failed", "metrics": {"provider_latency_ms": 30}}},
        ],
        tmp_path,
    )

    report = json.loads((tmp_path / "comparison.json").read_text())
    assert "gemini_api/gemini-3.5-flash-lite" in report["controlled_comparisons"]
    assert "ollama/procad:Q4_K_M" in report["controlled_comparisons"]
    assert (tmp_path / "cross-model-comparison.json").is_file()
    assert (tmp_path / "resource-profile.json").is_file()


def test_incomplete_pairs_are_excluded_from_consistency_means(tmp_path) -> None:
    identity = {
        "git_head": "abc",
        "migration_head": "0036",
        "provider": "ollama",
        "model_policy": {"context_length": 8192},
        "prompt_versions": {"requirements": "v1"},
        "configuration_hash": "config-a",
        "build_identities": {"backend": {"git_sha": "abc"}},
    }

    result = build_experiment_reports(
        {"id": "experiment-incomplete", "mode": "five_case", **identity},
        [
            {
                "case_id": "ollama-case-001",
                "provider": "ollama",
                "model": "specialist",
                "run_index": 1,
                "identity": identity,
                "evidence": {"outcome_state": "working_version"},
            },
            {
                "case_id": "ollama-case-001",
                "provider": "ollama",
                "model": "specialist",
                "run_index": 2,
                "identity": identity,
                "evidence": None,
            },
        ],
        tmp_path,
    )

    summary = result["model_summaries"]["ollama/specialist"]
    assert summary["pair_status"] == "incomplete"
    assert summary["eligible_case_count"] == 0
    assert summary["mean_consistency_score"] is None
    assert summary["incomplete_case_count"] == 1
