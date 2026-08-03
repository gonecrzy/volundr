import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.debug_batch import DebugBatch
from app.schemas.debug_batch import DebugBatchStart
from app.services.debug_batches.comparison import DebugBatchComparisonService
from app.services.debug_batches.identity import capture_batch_identity
from app.services.debug_batches.service import DebugBatchService
from app.services.debug_batches.reports import DebugBatchReportService
from app.services.workflow.redaction import RedactionService


def test_evidence_paths_are_normalized_without_persisting_removed_values(tmp_path: Path) -> None:
    redactor = RedactionService()

    normalized, findings = redactor.normalize_evidence_text(
        'worker traceback: "/tmp/volundr/jobs/abc/model.py" and "/home/alice/project/data.json"',
        data_root=tmp_path / "data",
        evidence_root=tmp_path / "data" / "debug-sessions" / "batch-1",
    )

    assert "/tmp/volundr" not in normalized
    assert "/home/alice" not in normalized
    assert "evidence.temporary_path_normalized" in {item["kind"] for item in findings}
    assert "evidence.unregistered_path_redacted" in {item["kind"] for item in findings}
    assert all("original" not in item for item in findings)


def test_registered_artifact_path_becomes_safe_artifact_reference(tmp_path: Path) -> None:
    redactor = RedactionService()
    artifact_path = tmp_path / "data" / "jobs" / "job-1" / "source.py"

    normalized, findings = redactor.normalize_evidence_text(
        f"source path: {artifact_path}",
        data_root=tmp_path / "data",
        evidence_root=tmp_path / "data" / "debug-sessions" / "batch-1",
        registered_paths={str(artifact_path): {"artifact_id": "artifact-1", "relative_path": "source.py"}},
    )

    assert "artifact:artifact-1/source.py" in normalized
    assert findings[0]["kind"] == "evidence.absolute_path_removed"
    assert findings[0]["replacement"] == "artifact:artifact-1/source.py"


def test_identity_requires_complete_build_metadata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.services.debug_batches.identity._git_value", lambda *_args: "unknown")
    monkeypatch.setattr("app.services.debug_batches.identity._git_dirty", lambda *_args: None)
    monkeypatch.setattr("app.services.debug_batches.identity._git_timestamp", lambda *_args: None)

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        identity = capture_batch_identity(db=session, data_dir=tmp_path / "data", frontend_build_identity="frontend-dev")

    assert identity.identity_complete is False
    assert identity.build_identities["backend"]["git_sha"] == "unknown"


def test_incomplete_identity_cannot_be_controlled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.services.debug_batches.identity._git_value", lambda *_args: "unknown")
    monkeypatch.setattr("app.services.debug_batches.identity._git_dirty", lambda *_args: None)
    monkeypatch.setattr("app.services.debug_batches.identity._git_timestamp", lambda *_args: None)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        service = DebugBatchService(db=session, data_dir=tmp_path / "data")
        baseline = service.start(DebugBatchStart(label="baseline"))
        service.finish(baseline.id)
        candidate = service.start(DebugBatchStart(label="candidate", baseline_batch_id=baseline.id))
        service.finish(candidate.id)
        comparison = DebugBatchComparisonService(db=session, data_dir=tmp_path / "data").compare(candidate.id)

    assert comparison["status"] == "identity_incomplete"
    assert comparison["identity_match"] is False
    assert comparison["mismatches"]["identity_completeness"]["candidate"] is False


def test_materialized_report_removes_absolute_runtime_paths(tmp_path: Path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    data_dir = tmp_path / "data"
    with Session(engine) as session:
        service = DebugBatchService(db=session, data_dir=data_dir)
        batch = service.start(DebugBatchStart(label="path-report"))
        batch_id = batch.id
        batch.report_path = "/tmp/worker-scratch/report.md"
        session.commit()
        DebugBatchReportService(db=session, data_dir=data_dir).generate(batch_id)

    root = data_dir / "debug-sessions" / batch_id
    contents = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in root.rglob("*") if path.is_file())
    assert "/tmp/worker-scratch" not in contents
    integrity = json.loads((root / "integrity-report.json").read_text(encoding="utf-8"))
    assert any(item["kind"] == "evidence.temporary_path_normalized" for item in integrity["findings"])
