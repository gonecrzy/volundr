import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.project import Project
from app.models.workflow import WorkflowArtifact, WorkflowRun
from app.schemas.debug_batch import DebugBatchStart
from app.services.debug_batches.reports import DebugBatchReportService
from app.services.debug_batches.service import DebugBatchService


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_report_materializes_authoritative_evidence_and_review_instruction(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with _session() as session:
        batch = DebugBatchService(db=session, data_dir=data_dir).start(
            DebugBatchStart(label="live-01", target_project_count=1)
        )
        project = Project(name="Fixture", slug="fixture", original_intent="Build a fixture")
        session.add(project)
        session.flush()
        DebugBatchService(db=session, data_dir=data_dir).attach_new_project(project)
        session.commit()

        run = WorkflowRun(
            project_id=project.id,
            workflow_type="initial_generation",
            correlation_id="corr-1",
            status="blocked",
            logging_mode="debug_batch",
            provider="gemini_api",
            model="gemini-3.5-flash-lite",
        )
        session.add(run)
        session.flush()
        artifact_paths = {
            "raw_provider_response": "AIza1234567890-secret",
            "rendered_prompt": "authorization: bearer-secret /root/private/prompt",
            "cadquery_source": "GEMINI_API_KEY=AIza1234567890-secret",
            "worker_diagnostics": "cookie=secret-worker-value",
        }
        for artifact_type, contents in artifact_paths.items():
            artifact_path = data_dir / f"{artifact_type}.txt"
            artifact_path.write_text(contents, encoding="utf-8")
            session.add(
                WorkflowArtifact(
                    workflow_run_id=run.id,
                    root_workflow_run_id=run.id,
                    correlation_id=run.correlation_id,
                    project_id=project.id,
                    stage="generation",
                    artifact_type=artifact_type,
                    role=artifact_type,
                    path=str(artifact_path),
                    redacted=False,
                )
            )
        session.add(
            WorkflowArtifact(
                workflow_run_id=run.id,
                root_workflow_run_id=run.id,
                correlation_id=run.correlation_id,
                project_id=project.id,
                stage="worker",
                artifact_type="worker_result_manifest",
                role="missing",
                path=str(data_dir / "does-not-exist.json"),
                redacted=True,
            )
        )
        session.commit()

        result = DebugBatchReportService(db=session, data_dir=data_dir).generate(batch.id)

        root = Path(result["root_path"])
        assert (root / "session.json").exists()
        assert (root / "report.md").exists()
        assert (root / "report.json").exists()
        assert (root / "codex-review.md").exists()
        assert (root / "redaction-report.json").exists()
        assert (root / "integrity-report.json").exists()
        assert (root / "projects" / project.id / "summary.json").exists()
        assert (root / "projects" / project.id / "conversation.json").exists()
        assert "monitor mount" in (root / "codex-review.md").read_text(encoding="utf-8").lower()

        for path in root.rglob("*"):
            if path.is_file() and path.suffix in {".json", ".txt", ".md", ".py", ".log"}:
                contents = path.read_text(encoding="utf-8")
                assert "AIza1234567890" not in contents
                assert "authorization: bearer-secret" not in contents
                assert "/root/private" not in contents
                assert "secret-worker-value" not in contents

        integrity = json.loads((root / "integrity-report.json").read_text(encoding="utf-8"))
        assert any(item["kind"] == "missing_artifact" for item in integrity["findings"])


def test_report_generation_has_no_provider_or_worker_inputs(tmp_path: Path) -> None:
    with _session() as session:
        batch = DebugBatchService(db=session, data_dir=tmp_path).start(
            DebugBatchStart(label="live-01", target_project_count=1)
        )
        DebugBatchService(db=session, data_dir=tmp_path).finish(batch.id)
        service = DebugBatchReportService(db=session, data_dir=tmp_path)

        assert set(service.__dict__) == {"db", "data_dir", "redactor"}
