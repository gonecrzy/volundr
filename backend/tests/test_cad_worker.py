import asyncio
import json
import os
import stat
import sys
import tomllib
from pathlib import Path

import pytest
import trimesh

from app.api.dependencies import get_cad_runner
from app.services.cad.cadquery_runner import (
    CadQueryCliRunner,
    CadQueryCompileResult,
    CadQueryOutputResult,
    _CADQUERY_RUNNER_SOURCE,
)
from app.services.cad.worker_client import FilesystemCadWorkerClient, FilesystemCadWorkerRunner
from app.services.cad.worker_execution import execute_job_directory, process_next_job
from app.workers.cad_worker import worker_health_path
from app.services.cad.jobs import (
    CAD_EXECUTION_JOB_SCHEMA_VERSION,
    DuplicateJobCompletionError,
    FilesystemCadJobQueue,
    JobManifestError,
    complete_job_atomic,
    load_job_manifest,
    load_job_result,
)


VALID_CADQUERY_SOURCE = """
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product

PARAMETERS = [
    ParameterSpec(
        id="width_mm",
        label="Width",
        type="float",
        default=1.0,
        unit="mm",
        min_value=0.1,
        max_value=10.0,
    )
]

def build(params):
    width = params["width_mm"]
    body = cq.Workplane("XY").box(width, 1, 1)
    return Product(
        parameters=PARAMETERS,
        outputs=[
            PrintableOutput(
                output_id="body",
                component_id="body",
                label="Body",
                model=body,
                expected_solid_count=1,
                allow_disconnected_solids=False,
            )
        ],
    )
"""

UNSAFE_IMPORT_CADQUERY_SOURCE = VALID_CADQUERY_SOURCE.replace(
    "import cadquery as cq\n",
    "import cadquery as cq\nimport os\n",
)

OBSOLETE_PROBE_CADQUERY_SOURCE = (
    "import cadquery as cq\n\n"
    "def build_model():\n"
    "    return cq.Workplane('XY').box(1, 1, 1)\n"
)


def test_worker_health_file_defaults_to_writable_tmpfs_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("VOLUNDR_WORKER_HEALTH_PATH", raising=False)

    assert worker_health_path(tmp_path) == Path("/tmp/.worker-health.json")


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
    assert manifest.source_contract_version == "cadquery-v1"
    assert manifest.source_path == Path("input/model.py")
    assert manifest.parameter_values == {"width": 20}
    assert manifest.requested_outputs == [{"output_id": "body", "required": True}]
    assert manifest.execution_limits.timeout_seconds == 7
    assert manifest.source_file(job_dir).read_text(encoding="utf-8") == VALID_CADQUERY_SOURCE


def test_filesystem_queue_creates_non_root_worker_writable_job_directory(
    tmp_path: Path,
) -> None:
    queue = FilesystemCadJobQueue(tmp_path)

    job_dir = queue.submit_cadquery_source(
        source=VALID_CADQUERY_SOURCE,
        job_id="job-1",
        timeout_seconds=5,
    )

    assert stat.S_IMODE(job_dir.stat().st_mode) == 0o1777


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
                "source_contract_version": "cadquery-v1",
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
async def test_worker_ignores_non_queue_workspace_directories(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "obsolete-runner-workspace"
    workspace_dir.mkdir()

    assert await process_next_job(tmp_path) is None
    assert not (workspace_dir / "result.json").exists()


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
async def test_worker_persists_multi_output_cadquery_result(tmp_path: Path) -> None:
    queue = FilesystemCadJobQueue(tmp_path)
    job_dir = queue.submit_cadquery_source(
        source=VALID_CADQUERY_SOURCE,
        job_id="multi-output",
        parameter_values={"width_mm": 42},
        requested_outputs=[
            {"output_id": "body", "required": True},
            {"output_id": "lid", "required": False},
        ],
        timeout_seconds=5,
    )
    runner = MultiOutputCadQueryRunner(job_dir)

    result = await execute_job_directory(job_dir, runner=runner)

    assert runner.parameter_values == {"width_mm": 42}
    assert runner.requested_outputs == [
        {"output_id": "body", "required": True},
        {"output_id": "lid", "required": False},
    ]
    assert result["success"] is True
    assert [output["output_id"] for output in result["outputs"]] == ["body", "lid"]
    assert result["outputs"][0]["step_path"] == "work/body.step"
    assert result["outputs"][0]["brep_path"] == "work/body.brep"
    assert result["outputs"][0]["topology_metadata"] == {"valid": True, "detected_solid_count": 1}
    assert result["outputs"][1]["success"] is False
    assert result["outputs"][1]["compile_error"] == "optional failed"
    persisted = load_job_result(job_dir)
    assert persisted["outputs"] == result["outputs"]


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
async def test_cadquery_runner_rejects_probe_build_model_sources(tmp_path: Path) -> None:
    result = await CadQueryCliRunner(
        workspace_root=tmp_path / "jobs",
        timeout_seconds=10,
    ).compile(OBSOLETE_PROBE_CADQUERY_SOURCE, job_id="obsolete-probe-source")

    assert result.success is False
    assert result.exit_code is None
    assert result.error_message is not None
    assert "CadQuery contract violation" in result.error_message
    assert "build(params)" in result.error_message


@pytest.mark.asyncio
async def test_cadquery_runner_preserves_topology_metadata_for_solid_count_failure(
    tmp_path: Path,
) -> None:
    source = """
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product

PARAMETERS = [
    ParameterSpec(id="cube_size", label="Cube Size", type="float", default=10.0, unit="mm"),
]

def build(params):
    first = cq.Workplane("XY").box(params["cube_size"], params["cube_size"], params["cube_size"])
    second = cq.Workplane("XY").box(params["cube_size"], params["cube_size"], params["cube_size"]).translate((30, 0, 0))
    model = first.union(second)
    return Product(
        outputs=[
            PrintableOutput(
                output_id="body",
                label="Body",
                model=model,
                component_id="body",
                expected_solid_count=1,
                allow_disconnected_solids=False,
            )
        ],
        parameters=PARAMETERS,
    )
"""

    result = await CadQueryCliRunner(
        workspace_root=tmp_path / "jobs",
        timeout_seconds=10,
    ).compile(source, job_id="solid-count-failure")

    assert result.success is False
    assert result.outputs[0].success is False
    assert result.outputs[0].compile_error == "output shape is invalid"
    assert result.outputs[0].topology_metadata is not None
    assert result.outputs[0].topology_metadata["valid"] is False
    assert result.outputs[0].topology_metadata["outcome"] == "solid_count_mismatch"
    assert result.outputs[0].topology_metadata["detected_solid_count"] == 2
    assert result.outputs[0].topology_metadata["expected_solid_count"] == 1
    assert result.outputs[0].topology_metadata_path is not None


@pytest.mark.asyncio
async def test_cadquery_runner_reports_empty_topology_outcome_for_missing_model(
    tmp_path: Path,
) -> None:
    source = """
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product

PARAMETERS = [
    ParameterSpec(id="cube_size", label="Cube Size", type="float", default=10.0, unit="mm"),
]

def build(params):
    return Product(
        outputs=[
            PrintableOutput(
                output_id="body",
                label="Body",
                model=None,
                component_id="body",
                expected_solid_count=1,
                allow_disconnected_solids=False,
            )
        ],
        parameters=PARAMETERS,
    )
"""

    result = await CadQueryCliRunner(
        workspace_root=tmp_path / "jobs",
        timeout_seconds=10,
    ).compile(source, job_id="empty-output")

    assert result.success is False
    assert result.outputs[0].success is False
    assert result.outputs[0].topology_metadata is not None
    assert result.outputs[0].topology_metadata["valid"] is False
    assert result.outputs[0].topology_metadata["outcome"] == "empty"
    assert result.outputs[0].topology_metadata_path is not None


@pytest.mark.asyncio
async def test_cadquery_runner_reports_unsupported_shape_topology_outcome(
    tmp_path: Path,
) -> None:
    source = """
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product

PARAMETERS = [
    ParameterSpec(id="cube_size", label="Cube Size", type="float", default=10.0, unit="mm"),
]

def build(params):
    return Product(
        outputs=[
            PrintableOutput(
                output_id="body",
                label="Body",
                model="not-a-shape",
                component_id="body",
                expected_solid_count=1,
                allow_disconnected_solids=False,
            )
        ],
        parameters=PARAMETERS,
    )
"""

    result = await CadQueryCliRunner(
        workspace_root=tmp_path / "jobs",
        timeout_seconds=10,
    ).compile(source, job_id="unsupported-shape")

    assert result.success is False
    assert result.outputs[0].success is False
    assert result.outputs[0].topology_metadata is not None
    assert result.outputs[0].topology_metadata["valid"] is False
    assert result.outputs[0].topology_metadata["outcome"] == "unsupported_shape"
    assert result.outputs[0].topology_metadata_path is not None


@pytest.mark.asyncio
async def test_cadquery_runner_reports_execution_failed_topology_for_missing_output(
    tmp_path: Path,
) -> None:
    result = await CadQueryCliRunner(
        workspace_root=tmp_path / "jobs",
        timeout_seconds=10,
    ).compile(
        VALID_CADQUERY_SOURCE,
        job_id="missing-requested-output",
        requested_outputs=[{"output_id": "lid", "required": True}],
    )

    assert result.success is False
    assert result.outputs[0].success is False
    assert result.outputs[0].compile_error == "requested output not found: lid"
    assert result.outputs[0].topology_metadata is not None
    assert result.outputs[0].topology_metadata["valid"] is False
    assert result.outputs[0].topology_metadata["outcome"] == "execution_failed"
    assert result.outputs[0].topology_metadata_path is not None


@pytest.mark.asyncio
async def test_cadquery_runner_places_centered_output_on_build_plate(
    tmp_path: Path,
) -> None:
    result = await CadQueryCliRunner(
        workspace_root=tmp_path / "jobs",
        timeout_seconds=10,
    ).compile(VALID_CADQUERY_SOURCE, job_id="centered-output-placement")

    assert result.success is True
    output = result.outputs[0]
    assert output.stl_path is not None
    assert output.step_path is not None
    mesh = trimesh.load(output.stl_path, force="mesh")
    import cadquery as cq

    step_model = cq.importers.importStep(str(output.step_path))
    step_bounds = step_model.val().BoundingBox()
    assert float(mesh.bounds[0][2]) == pytest.approx(0.0, abs=0.001)
    assert float(step_bounds.zmin) == pytest.approx(0.0, abs=0.001)
    assert output.topology_metadata is not None
    assert output.topology_metadata["placement_policy"] == "cadquery-output-placement-v1"
    assert output.topology_metadata["model_space_bounds"]["z_min"] == pytest.approx(-0.5)
    assert output.topology_metadata["print_transform"]["translation"] == [0.0, 0.0, 0.5]
    assert output.topology_metadata["print_space_bounds"]["z_min"] == pytest.approx(0.0)
    assert output.topology_metadata["detected_solid_count"] == 1


@pytest.mark.asyncio
async def test_cadquery_runner_uses_identity_transform_for_output_already_on_plate(
    tmp_path: Path,
) -> None:
    source = VALID_CADQUERY_SOURCE.replace(
        "body = cq.Workplane(\"XY\").box(width, 1, 1)",
        "body = cq.Workplane(\"XY\").box(width, 1, 1).translate((0, 0, 0.5))",
    )
    result = await CadQueryCliRunner(
        workspace_root=tmp_path / "jobs",
        timeout_seconds=10,
    ).compile(source, job_id="on-plate-output-placement")

    assert result.success is True
    output = result.outputs[0]
    assert output.stl_path is not None
    mesh = trimesh.load(output.stl_path, force="mesh")
    assert float(mesh.bounds[0][2]) == pytest.approx(0.0, abs=0.001)
    assert output.topology_metadata is not None
    assert output.topology_metadata["print_transform"]["translation"] == [0.0, 0.0, 0.0]
    assert output.topology_metadata["model_space_bounds"]["z_min"] == pytest.approx(0.0)
    assert output.topology_metadata["print_space_bounds"]["z_min"] == pytest.approx(0.0)


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


@pytest.mark.asyncio
async def test_cadquery_runner_timeout_preserves_durable_diagnostics(tmp_path: Path) -> None:
    source = VALID_CADQUERY_SOURCE.replace(
        "body = cq.Workplane(\"XY\").box(width, 1, 1)",
        "body = cq.Workplane(\"XY\").box(width, 1, 1)\n    while True:\n        pass",
    )

    result = await CadQueryCliRunner(
        workspace_root=tmp_path / "jobs",
        timeout_seconds=3,
    ).compile(
        source,
        job_id="durable-timeout",
        requested_outputs=[{"output_id": "body", "required": True}],
    )

    assert result.success is False
    assert result.timed_out is True
    assert result.execution_timing is not None
    diagnostics = result.execution_diagnostics or {}
    assert diagnostics["timed_out"] is True
    assert diagnostics["timeout_seconds"] == 3
    assert diagnostics["subprocess_pid"]
    assert diagnostics["timeout_deadline_monotonic"] > diagnostics["started_at_monotonic"]
    assert diagnostics["partial_stdout_path"] == "stdout.log"
    assert diagnostics["partial_stderr_path"] == "stderr.log"
    assert diagnostics["partial_diagnostic_state_path"] == "diagnostic-state.json"
    assert diagnostics["active_phase"] in {"module_import", "build_function", "process_shutdown"}
    assert diagnostics["completed_output_ids"] == []
    assert diagnostics["incomplete_output_ids"] == ["body"]
    if diagnostics["active_phase"] == "build_function":
        assert diagnostics["active_function"] == "build"
        assert "last_completed_operation" in diagnostics
        assert "last_started_incomplete_operation" in diagnostics


@pytest.mark.asyncio
async def test_worker_timeout_result_contract_includes_partial_evidence(tmp_path: Path) -> None:
    source = VALID_CADQUERY_SOURCE.replace(
        "body = cq.Workplane(\"XY\").box(width, 1, 1)",
        "body = cq.Workplane(\"XY\").box(width, 1, 1)\n    while True:\n        pass",
    )
    queue = FilesystemCadJobQueue(tmp_path)
    job_dir = queue.submit_cadquery_source(
        source=source,
        job_id="worker-timeout-contract",
        requested_outputs=[{"output_id": "body", "required": True}],
        timeout_seconds=3,
    )

    result = await execute_job_directory(job_dir)

    assert result["success"] is False
    assert result["failure_class"] == "timeout"
    diagnostics = result["diagnostics"]
    assert diagnostics["timed_out"] is True
    assert diagnostics["timeout_seconds"] == 3
    assert diagnostics["active_phase"] in {"module_import", "build_function", "process_shutdown"}
    assert diagnostics["completed_output_ids"] == []
    assert diagnostics["incomplete_output_ids"] == ["body"]
    assert diagnostics["partial_stdout_path"] == "work/worker-timeout-contract/stdout.log"
    assert diagnostics["partial_stderr_path"] == "work/worker-timeout-contract/stderr.log"
    assert diagnostics["partial_diagnostic_state_path"] == "work/worker-timeout-contract/diagnostic-state.json"


@pytest.mark.asyncio
async def test_required_output_failure_preserves_prior_output_results(tmp_path: Path) -> None:
    source = """
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product

PARAMETERS = []

def build(params):
    body = cq.Workplane("XY").box(1, 1, 1)
    invalid = cq.Workplane("XY").box(1, 1, 1).union(cq.Workplane("XY").box(1, 1, 1).translate((5, 0, 0)))
    return Product(
        parameters=PARAMETERS,
        outputs=[
            PrintableOutput(output_id="body", label="Body", model=body, component_id="body", expected_solid_count=1, allow_disconnected_solids=False),
            PrintableOutput(output_id="lid", label="Lid", model=invalid, component_id="lid", expected_solid_count=1, allow_disconnected_solids=False),
        ],
    )
"""

    result = await CadQueryCliRunner(
        workspace_root=tmp_path / "jobs",
        timeout_seconds=10,
    ).compile(source, job_id="partial-output-failure")

    assert result.success is False
    assert [output.output_id for output in result.outputs] == ["body", "lid"]
    assert result.outputs[0].success is True
    assert result.outputs[1].success is False
    assert result.outputs[1].compile_error == "output shape is invalid"
    assert result.execution_diagnostics is not None
    per_output = result.execution_diagnostics["per_output_results"]
    assert per_output["body"]["status"] == "completed"
    assert per_output["lid"]["status"] == "invalid_shape"
    assert result.execution_diagnostics["completed_output_ids"] == ["body"]


@pytest.mark.asyncio
async def test_operation_shape_counts_are_bounded_to_expensive_operations(tmp_path: Path) -> None:
    source = """
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product

PARAMETERS = []

def build(params):
    body = cq.Workplane("XY").box(1, 1, 1)
    body = body.union(cq.Workplane("XY").box(1, 1, 1).translate((0.25, 0, 0)))
    return Product(
        parameters=PARAMETERS,
        outputs=[
            PrintableOutput(output_id="body", label="Body", model=body, component_id="body", expected_solid_count=1, allow_disconnected_solids=True),
        ],
    )
"""

    result = await CadQueryCliRunner(
        workspace_root=tmp_path / "jobs",
        timeout_seconds=10,
    ).compile(source, job_id="bounded-operation-counts")

    assert result.success is True
    payload = json.loads(result.execution_manifest_path.read_text(encoding="utf-8"))
    operations = payload["execution_timing"]["operations"]
    box_operation = next(operation for operation in operations if operation["name"] == "box")
    union_operation = next(operation for operation in operations if operation["name"] == "union")
    assert box_operation["before"] is None
    assert box_operation["after"] is None
    assert isinstance(union_operation["before"]["solid_count"], int)
    assert isinstance(union_operation["after"]["solid_count"], int)


def test_production_worker_timeout_default_remains_unchanged() -> None:
    from app.core.config import settings

    assert settings.cad_timeout_seconds == 60


def test_cad_worker_container_policy_removes_provider_access() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    compose = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = (repo_root / "cad-worker/Dockerfile").read_text(encoding="utf-8")

    worker_block = compose.split("\n  volundr-cad-worker:", 1)[1]
    assert "network_mode: none" in worker_block
    assert "read_only: true" in worker_block
    assert "GEMINI_API_KEY" not in worker_block
    assert "VOLUNDR_AI_PROVIDER" not in worker_block
    assert "VOLUNDR_OLLAMA" not in worker_block
    assert ".gemini" not in worker_block
    assert "USER volundr-cad" in dockerfile
    assert "libgl1" in dockerfile
    assert "XDG_CACHE_HOME=/tmp/xdg-cache" in dockerfile
    assert "COPY backend/volundr_cad ./volundr_cad" in dockerfile


def test_codex_configuration_is_api_container_only() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    compose = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")
    api_block = compose.split("\n  volundr-api:", 1)[1].split("\n  volundr-cad-worker:", 1)[0]
    web_block = compose.split("\n  volundr-web:", 1)[1].split("\n  volundr-api:", 1)[0]
    worker_block = compose.split("\n  volundr-cad-worker:", 1)[1]
    frontend_dockerfile = (repo_root / "frontend/Dockerfile").read_text(encoding="utf-8")

    assert "VOLUNDR_CODEX_API_BASE_URL" in api_block
    assert "VOLUNDR_CODEX_API_KEY" in api_block
    assert "VOLUNDR_CODEX_MODEL" in api_block
    assert "VOLUNDR_CODEX_API_MODE" in api_block
    assert "VOLUNDR_CODEX" not in web_block
    assert "VOLUNDR_CODEX" not in worker_block
    assert "VOLUNDR_CODEX" not in frontend_dockerfile


def test_backend_package_declares_cadquery_runtime_dependency() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    pyproject = tomllib.loads((repo_root / "backend/pyproject.toml").read_text(encoding="utf-8"))

    dependencies = pyproject["project"]["dependencies"]
    packages = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]

    assert "cadquery==2.8.0" in dependencies
    assert "volundr_cad" in packages


def test_api_default_cad_dependency_uses_worker_queue() -> None:
    runner = get_cad_runner()

    assert type(runner).__name__ == "FilesystemCadWorkerRunner"
    assert not isinstance(runner, CadQueryCliRunner)


@pytest.mark.asyncio
async def test_worker_runner_submits_job_and_reads_structured_result(tmp_path: Path) -> None:
    job_id = "worker-backed-api"
    fake_runner: MultiOutputCadQueryRunner | None = None

    async def worker_once() -> None:
        nonlocal fake_runner
        job_dir = tmp_path / job_id
        while not job_dir.exists():
            await asyncio.sleep(0.01)
        fake_runner = MultiOutputCadQueryRunner(job_dir)
        await execute_job_directory(job_dir, runner=fake_runner)

    worker_task = asyncio.create_task(worker_once())
    result = await FilesystemCadWorkerRunner(
        tmp_path,
        poll_interval_seconds=0.01,
        result_timeout_seconds=2,
    ).compile(
        VALID_CADQUERY_SOURCE,
        job_id=job_id,
        parameter_values={"width_mm": 2.0},
        requested_outputs=[{"output_id": "body", "required": True}],
    )
    await worker_task

    assert result.success is True
    assert result.command_args == ["python", "_runner.py"]
    assert result.execution_manifest_path == tmp_path / job_id / "result.json"
    assert result.outputs[0].output_id == "body"
    assert result.outputs[0].stl_path is not None
    assert result.outputs[0].stl_path.exists()
    assert fake_runner is not None
    assert fake_runner.parameter_values == {"width_mm": 2.0}
    payload = load_job_result(tmp_path / job_id)
    assert payload["requested_output_ids"] == ["body"]
    assert payload["output_ids"] == ["body"]


@pytest.mark.asyncio
async def test_cadquery_execution_manifest_records_source_parameter_and_contract_metadata(
    tmp_path: Path,
) -> None:
    parameter_values = {"width_mm": 2.0}

    result = await CadQueryCliRunner(
        workspace_root=tmp_path / "jobs",
        timeout_seconds=10,
    ).compile(
        VALID_CADQUERY_SOURCE,
        job_id="manifest-metadata",
        parameter_values=parameter_values,
        requested_outputs=[{"output_id": "body", "required": True}],
    )

    assert result.success is True
    assert result.execution_manifest_path is not None
    assert result.execution_manifest_path.name == "execution-manifest.json"
    payload = json.loads(result.execution_manifest_path.read_text(encoding="utf-8"))
    assert payload["cad_backend"] == "cadquery"
    assert payload["cadquery_version"] == "2.8.0"
    assert payload["source_language"] == "python"
    assert payload["source_contract_version"] == "cadquery-v1"
    assert payload["source_hash"] == result.source_hash
    assert payload["parameter_hash"]
    assert payload["requested_output_ids"] == ["body"]
    assert payload["output_ids"] == ["body"]
    assert payload["execution_timing"]["total_ms"] >= 0
    assert payload["outputs"][0]["stl_hash"] == result.outputs[0].stl_hash
    assert payload["outputs"][0]["step_hash"] == result.outputs[0].step_hash
    assert payload["outputs"][0]["brep_hash"] == result.outputs[0].brep_hash
    assert payload["outputs"][0]["topology_metadata"]["shell_count"] == 1
    assert payload["outputs"][0]["topology_metadata"]["bounding_box_mm"]["size_x"] == 2.0
    assert result.outputs[0].topology_metadata is not None
    assert result.outputs[0].topology_metadata["shell_count"] == 1
    assert result.outputs[0].topology_metadata["bounding_box_mm"]["size_x"] == 2.0
    assert payload["worker_version"] == "cadquery-cli-runner-v1"


@pytest.mark.asyncio
async def test_isolated_cadquery_worker_reruns_source_contract_validation(
    tmp_path: Path,
) -> None:
    job_dir = tmp_path / "isolated-validation"
    output_dir = job_dir / "outputs"
    job_dir.mkdir()
    output_dir.mkdir()
    (job_dir / "model.py").write_text(UNSAFE_IMPORT_CADQUERY_SOURCE, encoding="utf-8")
    (job_dir / "_volundr_cadquery_runner.py").write_text(
        _CADQUERY_RUNNER_SOURCE,
        encoding="utf-8",
    )
    result_path = job_dir / "execution-manifest.json"
    (job_dir / "parameter-values.json").write_text(
        json.dumps({"width_mm": 2.0}),
        encoding="utf-8",
    )
    (job_dir / "requested-outputs.json").write_text(
        json.dumps([{"output_id": "body", "required": True}]),
        encoding="utf-8",
    )
    env = CadQueryCliRunner(workspace_root=tmp_path / "jobs")._subprocess_env()

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "_volundr_cadquery_runner.py",
        "outputs",
        result_path.name,
        "parameter-values.json",
        "requested-outputs.json",
        cwd=job_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    _stdout, stderr = await process.communicate()

    assert process.returncode != 0
    assert "CadQuery contract violation" in stderr.decode("utf-8")
    assert not result_path.exists()


@pytest.mark.asyncio
async def test_worker_runner_rejects_non_v1_source_contract_without_queueing(
    tmp_path: Path,
) -> None:
    result = await FilesystemCadWorkerRunner(
        tmp_path,
        poll_interval_seconds=0.001,
        result_timeout_seconds=0.01,
    ).compile(
        VALID_CADQUERY_SOURCE,
        job_id="unsupported-contract",
        source_contract_version="cadquery-probe-v1",
    )

    assert result.success is False
    assert result.exit_code is None
    assert result.error_message == "unsupported CadQuery source_contract_version"
    assert not (tmp_path / "unsupported-contract").exists()


def test_cadquery_runner_rejects_successful_output_with_malformed_step(
    tmp_path: Path,
) -> None:
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    stl_path = job_dir / "body.stl"
    step_path = job_dir / "body.step"
    trimesh.creation.box(extents=(1, 1, 1)).export(stl_path)
    step_path.write_text("not a STEP file", encoding="utf-8")

    outputs = CadQueryCliRunner(workspace_root=tmp_path / "jobs")._collect_output_results(
        job_dir,
        {
            "outputs": [
                {
                    "output_id": "body",
                    "required": True,
                    "success": True,
                    "stl_path": "body.stl",
                    "step_path": "body.step",
                }
            ]
        },
    )

    assert outputs[0].success is False
    assert outputs[0].compile_error is not None
    assert "STEP" in outputs[0].compile_error


@pytest.mark.asyncio
async def test_worker_rejects_output_artifact_paths_outside_job_directory(
    tmp_path: Path,
) -> None:
    queue = FilesystemCadJobQueue(tmp_path)
    job_dir = queue.submit_cadquery_source(
        source=VALID_CADQUERY_SOURCE,
        job_id="escaped-output",
        requested_outputs=[{"output_id": "body", "required": True}],
        timeout_seconds=5,
    )
    outside_stl = tmp_path / "outside.stl"
    outside_stl.write_text("outside", encoding="utf-8")

    result = await execute_job_directory(job_dir, runner=EscapingArtifactRunner(outside_stl))

    assert result["success"] is False
    assert result["failure_class"] == "execution_failed"
    assert result["outputs"][0]["success"] is False
    assert result["outputs"][0]["stl_path"] is None
    assert "outside job directory" in result["outputs"][0]["compile_error"]


async def _wait_briefly() -> None:
    import asyncio

    await asyncio.sleep(0.2)


class MultiOutputCadQueryRunner:
    def __init__(self, job_dir: Path) -> None:
        self.job_dir = job_dir
        self.parameter_values: dict | None = None
        self.requested_outputs: list[dict] | None = None

    async def compile(
        self,
        source: str,
        job_id: str,
        *,
        source_contract_version: str = "cadquery-v1",
        parameter_values: dict | None = None,
        requested_outputs: list[dict] | None = None,
    ) -> CadQueryCompileResult:
        self.parameter_values = parameter_values
        self.requested_outputs = requested_outputs
        work_dir = self.job_dir / "work"
        work_dir.mkdir()
        body_stl = work_dir / "body.stl"
        body_step = work_dir / "body.step"
        body_brep = work_dir / "body.brep"
        for path in (body_stl, body_step, body_brep):
            path.write_text(path.name, encoding="utf-8")
        return CadQueryCompileResult(
            job_id=job_id,
            success=True,
            timed_out=False,
            exit_code=0,
            source_path=self.job_dir / "input" / "model.py",
            stl_path=body_stl,
            step_path=body_step,
            stdout_path=work_dir / "stdout.log",
            stderr_path=work_dir / "stderr.log",
            metadata_path=None,
            source_hash="0" * 64,
            output_size_bytes=body_stl.stat().st_size,
            metadata=None,
            error_message=None,
            command_args=["python", "_runner.py"],
            outputs=[
                CadQueryOutputResult(
                    output_id="body",
                    entrypoint="body",
                    required=True,
                    success=True,
                    stl_path=body_stl,
                    step_path=body_step,
                    brep_path=body_brep,
                    metadata_path=None,
                    topology_metadata_path=None,
                    stl_hash="1" * 64,
                    step_hash="2" * 64,
                    brep_hash="3" * 64,
                    output_size_bytes=body_stl.stat().st_size,
                    metadata=None,
                    topology_metadata={"valid": True, "detected_solid_count": 1},
                ),
                CadQueryOutputResult(
                    output_id="lid",
                    entrypoint="lid",
                    required=False,
                    success=False,
                    stl_path=None,
                    step_path=None,
                    brep_path=None,
                    metadata_path=None,
                    topology_metadata_path=None,
                    stl_hash=None,
                    step_hash=None,
                    brep_hash=None,
                    output_size_bytes=0,
                    metadata=None,
                    topology_metadata=None,
                    compile_error="optional failed",
                ),
            ],
        )


class EscapingArtifactRunner:
    def __init__(self, artifact_path: Path) -> None:
        self.artifact_path = artifact_path

    async def compile(
        self,
        source: str,
        job_id: str,
        *,
        source_contract_version: str = "cadquery-v1",
        parameter_values: dict | None = None,
        requested_outputs: list[dict] | None = None,
    ) -> CadQueryCompileResult:
        return CadQueryCompileResult(
            job_id=job_id,
            success=True,
            timed_out=False,
            exit_code=0,
            source_path=None,
            stl_path=self.artifact_path,
            step_path=None,
            stdout_path=None,
            stderr_path=None,
            metadata_path=None,
            source_hash="0" * 64,
            output_size_bytes=self.artifact_path.stat().st_size,
            metadata=None,
            error_message=None,
            command_args=["python", "_runner.py"],
            outputs=[
                CadQueryOutputResult(
                    output_id="body",
                    entrypoint="body",
                    required=True,
                    success=True,
                    stl_path=self.artifact_path,
                    step_path=None,
                    brep_path=None,
                    metadata_path=None,
                    topology_metadata_path=None,
                    stl_hash="1" * 64,
                    step_hash=None,
                    brep_hash=None,
                    output_size_bytes=self.artifact_path.stat().st_size,
                    metadata=None,
                    topology_metadata=None,
                )
            ],
        )
