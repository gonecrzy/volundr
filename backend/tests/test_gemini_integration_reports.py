import json
from pathlib import Path

import pytest

from app.services.gemini_integration.corpus import build_integration_corpus
from app.services.gemini_integration.profile import GeminiFlashLiteContractV1
from app.services.gemini_integration.reports import (
    REQUIRED_REPORTS,
    IntegrationReportWriter,
)


def test_prepare_creates_isolated_study_tree_and_preregisters_corpus(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    profile = GeminiFlashLiteContractV1.from_repository(repo)
    writer = IntegrationReportWriter(
        tmp_path / "gemini-provider-contract-integration" / "gemini-provider-contract-integration-01",
        repo,
    )

    result = writer.prepare(profile, build_integration_corpus())

    assert result["provider_calls"] == 0
    assert result["worker_calls"] == 0
    for directory in ("captures", "projects", "replays", "issues", "counterfactuals", "reports"):
        assert (writer.root / directory).is_dir()
    prereg = json.loads((writer.root / "reports/study-preregistration.json").read_text())
    assert len(prereg["projects"]) == 10
    assert prereg["provider_call_cap"] == 50
    assert prereg["worker_call_cap"] == 15


def test_final_bundle_writes_required_embedded_reports(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    writer = IntegrationReportWriter(tmp_path / "study", repo)
    profile = GeminiFlashLiteContractV1.from_repository(repo)
    writer.prepare(profile, build_integration_corpus())

    writer.write_final(
        profile=profile,
        projects=build_integration_corpus(),
        project_outcomes=[{"project_id": "project-001", "earliest_blocker": None}],
        provider_attempts=[{"attempt_id": "attempt-001", "credential": {"credential_slot": "secondary"}}],
        issues=[],
    )

    for report in REQUIRED_REPORTS:
        assert (writer.root / "reports" / report).is_file(), report
    bundle = json.loads((writer.root / "reports/all-integration-loop-evidence.json").read_text())
    assert bundle["provider_attempts"][0]["attempt_id"] == "attempt-001"
    assert bundle["redaction"]["credential_values_serialized"] is False

