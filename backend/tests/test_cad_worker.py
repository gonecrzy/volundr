import json
import os
from pathlib import Path

import pytest

from app.services.cad.cadquery_runner import CadQueryCliRunner
from app.services.cad.worker_client import FilesystemCadWorkerClient
from app.services.cad.worker_execution import execute_job_directory
from app.services.cad.jobs import (
    CAD_EXECUTION_JOB_SCHEMA_VERSION,
    DuplicateJobCompletionError,
    FilesystemCadJobQueue,
    JobManifestError,
    complete_job_atomic,
    load_job_manifest,
    load_job_result,
)


VALID_CADQUERY_SOURCE = (
    "import cadquery as cq\n\n"
    "def build_model():\n"
    "    return cq.Workplane('XY').box(1, 1, 1)\n"
)


def test_filesystem_queue_writes_structured_cadquery_job(tmp_path: Path) -> None:
    queue = FilesystemCadJobQueue(tmp_path)

    job_dir = queue.submit_cadquery_source(
        source=VALID_CADQUERY_SOURCE,
        job_id="job-1",
        parameter_values={"width": 20},
        requested_outputs=[{"output_id": "body", "required": True}],
        timeout_seconds=7,
    )

    manifest = load_job_manifest(job_dir)
    assert manifest.schema_version == CAD_EXECUTION_JOB_SCHEMA_VERSION
    assert manifest.job_id == "job-1"
    assert manifest.cad_backend == "cadquery"
    assert manifest.source_language == "python"
    assert manifest.source_path == Path("input/model.py")
    assert manifest.parameter_values == {"width": 20}
    assert manifest.requested_outputs == [{"output_id": "body", "required": True}]
    assert manifest.execution_limits.timeout_seconds == 7
    assert manifest.source_file(job_dir).read_text(encoding="utf-8") == VALID_CADQUERY_SOURCE


def test_job_manifest_rejects_path_traversal(tmp_path: Path) -> None:
    job_dir = tmp_path / "unsafe-job"
    input_dir = job_dir / "input"
    input_dir.mkdir(parents=True)
    (input_dir / "model.py").write_text(VALID_CADQUERY_SOURCE, encoding="utf-8")
    (job_dir / "job.json").write_text(
        json.dumps(
            {
                "schema_version": CAD_EXECUTION_JOB_SCHEMA_VERSION,
                "job_id": "unsafe-job",
                "cad_backend": "cadquery",
                "source_language": "python",
                "source_path": "../outside.py",
                "source_hash": "bad",
                "parameter_values": {},
                "requested_outputs": [],
                "execution_limits": {"timeout_seconds": 5},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(JobManifestError, match="source_path"):
        load_job_manifest(job_dir)


def test_duplicate_job_completion_is_prevented(tmp_path: Path) -> None:
    queue = FilesystemCadJobQueue(tmp_path)
    job_dir = queue.submit_cadquery_source(
        source=VALID_CADQUERY_SOURCE,
        job_id="job-1",
        timeout_seconds=5,
    )
    result = {
        "schema_version": "cad-execution-result-v1",
        "job_id": "job-1",
        "success": False,
        "failure_class": "execution_failed",
        "duration_seconds": 0.01,
        "outputs": [],
        "diagnostics": {"message": "first result"},
        "worker_version": "test",
    }

    complete_job_atomic(job_dir, result)
    with pytest.raises(DuplicateJobCompletionError):
        complete_job_atomic(job_dir, result)


@pytest.mark.asyncio
async def test_worker_records_structured_failure_for_malformed_manifest(
    tmp_path: Path,
) -> None:
    job_dir = tmp_path / "bad-job"
    job_dir.mkdir()
    (job_dir / "job.json").write_text("{}", encoding="utf-8")

    result = await execute_job_directory(job_dir)

    assert result["success"] is False
    assert result["failure_class"] == "invalid_manifest"
    persisted = load_job_result(job_dir)
    assert persisted["failure_class"] == "invalid_manifest"


@pytest.mark.asyncio
async def test_api_client_reads_structured_worker_failure(tmp_path: Path) -> None:
    client = FilesystemCadWorkerClient(tmp_path)
    job_dir = client.submit_cadquery_execution(
        source="import os\n\ndef build_model():\n    return None\n",
        job_id="api-failure",
        timeout_seconds=5,
    )

    await execute_job_directory(job_dir)
    result = client.read_result("api-failure")

    assert result is not None
    assert result["success"] is False
    assert result["failure_class"] == "execution_failed"
    assert "CadQuery contract violation" in result["diagnostics"]["message"]


@pytest.mark.asyncio
async def test_cadquery_runner_scrubs_provider_credentials_from_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_python = tmp_path / "fake-python"
    fake_python.write_text(
        "#!/bin/sh\n"
        "env | grep -E 'GEMINI|OLLAMA|VOLUNDR_AI_PROVIDER' >&2 || true\n"
        "exit 3\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key")
    monkeypatch.setenv("VOLUNDR_GEMINI_API_KEY", "volundr-secret")
    monkeypatch.setenv("VOLUNDR_AI_PROVIDER", "gemini_api")
    monkeypatch.setenv("VOLUNDR_OLLAMA_BASE_URL", "http://ollama.invalid")

    result = await CadQueryCliRunner(
        python_binary=str(fake_python),
        workspace_root=tmp_path / "jobs",
        timeout_seconds=5,
    ).compile(VALID_CADQUERY_SOURCE, job_id="env-job")

    assert result.success is False
    assert result.stderr_path is not None
    assert result.stderr_path.read_text(encoding="utf-8") == ""


@pytest.mark.asyncio
async def test_cadquery_runner_timeout_kills_process_group(tmp_path: Path) -> None:
    marker = tmp_path / "child-finished"
    fake_python = tmp_path / "slow-python"
    fake_python.write_text(
        "#!/bin/sh\n"
        f"(sleep 5; touch {marker}) &\n"
        "wait\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    result = await CadQueryCliRunner(
        python_binary=str(fake_python),
        workspace_root=tmp_path / "jobs",
        timeout_seconds=1,
    ).compile(VALID_CADQUERY_SOURCE, job_id="timeout-job")

    assert result.success is False
    assert result.timed_out is True
    await _wait_briefly()
    assert not marker.exists()


def test_cad_worker_container_policy_removes_provider_access() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    compose = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = (repo_root / "cad-worker/Dockerfile").read_text(encoding="utf-8")

    worker_block = compose.split("volundr-cad-worker:", 1)[1]
    assert "network_mode: none" in worker_block
    assert "read_only: true" in worker_block
    assert "GEMINI_API_KEY" not in worker_block
    assert "VOLUNDR_AI_PROVIDER" not in worker_block
    assert "VOLUNDR_OLLAMA" not in worker_block
    assert ".gemini" not in worker_block
    assert "USER volundr-cad" in dockerfile


async def _wait_briefly() -> None:
    import asyncio

    await asyncio.sleep(0.2)
