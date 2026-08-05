from pathlib import Path

from app.services.gemini_integration.narrow_fix import NARROW_FIX_REPORTS, NarrowFixStudy


def test_narrow_fix_audit_is_zero_call_and_writes_required_reports(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    study_root = tmp_path / "study"
    output_root = tmp_path / "reports" / "narrow-fix-01"

    reports = NarrowFixStudy(repository_root, study_root).write_reports(output_root)

    assert tuple(sorted(reports)) == tuple(sorted(NARROW_FIX_REPORTS))
    assert reports["narrow-fix-decision.json"]["provider_calls"] == 0
    assert reports["narrow-fix-decision.json"]["worker_calls"] == 0
    assert reports["narrow-fix-decision.json"]["production_default_changed"] is False
    assert all((output_root / name).is_file() for name in NARROW_FIX_REPORTS)
