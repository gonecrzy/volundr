import json
from pathlib import Path

from app.services.gemini_consistency.study_reporting import build_study_reports


def _write_evidence(root: Path, round_name: str, repetition: int, case_id: str, *, success: bool) -> None:
    path = root / round_name / f"repetition-{repetition:02d}" / "projects" / case_id / f"project-{repetition}" / "evidence.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "round": round_name,
                "repetition": repetition,
                "case_id": case_id,
                "workspace": {"current_working_revision_id": f"revision-{repetition}" if success else None},
                "requirements": {"value": 10},
                "planning": {"route": "compact"},
                "generation_attempts": [{"status": "succeeded" if success else "failed", "failure_class": None if success else "worker_runtime"}],
                "workflow_events": {"run": [{"stage": "worker", "event_type": "worker.submitted"}]} if success else {},
                "outcome_category": "candidate" if success else "worker_runtime",
            }
        ),
        encoding="utf-8",
    )


def test_study_reports_separate_stage_consistency_and_before_after_label(tmp_path: Path) -> None:
    for repetition in (1, 2, 3):
        _write_evidence(tmp_path, "baseline", repetition, "case-001", success=repetition != 3)
        _write_evidence(tmp_path, "validation", repetition, "case-001", success=True)

    report = build_study_reports(tmp_path)

    assert report["study_kind"] == "before-and-after product correction study"
    assert set(report["rounds"]) == {"baseline", "validation"}
    assert "requirement_consistency" in report["rounds"]["baseline"]["consistency_scores"]
    assert "candidate_readiness" in report["rounds"]["validation"]["primary_metrics"]
    assert (tmp_path / "comparisons" / "before-after.json").is_file()
