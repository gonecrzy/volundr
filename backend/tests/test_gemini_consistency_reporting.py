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
