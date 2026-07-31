import time
from pathlib import Path
from typing import Any

from app.services.cad.cadquery_runner import CadQueryCliRunner
from app.services.cad.jobs import (
    DuplicateJobCompletionError,
    JobManifestError,
    complete_job_atomic,
    load_job_manifest,
    result_payload,
)


async def execute_job_directory(
    job_dir: Path,
    *,
    runner: CadQueryCliRunner | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    job_id = job_dir.name
    try:
        job = load_job_manifest(job_dir)
        job_id = job.job_id
        source = job.source_file(job_dir).read_text(encoding="utf-8")
    except JobManifestError as exc:
        result = result_payload(
            job_id=job_id,
            success=False,
            failure_class="invalid_manifest",
            duration_seconds=_duration(started),
            diagnostics={"message": str(exc)},
        )
        _persist_result(job_dir, result)
        return result

    active_runner = runner or CadQueryCliRunner(
        workspace_root=job_dir / "work",
        timeout_seconds=job.execution_limits.timeout_seconds,
    )
    compile_result = await active_runner.compile(
        source,
        job_id=job.job_id,
        source_contract_version=job.source_contract_version,
        parameter_values=job.parameter_values,
        requested_outputs=job.requested_outputs,
    )
    diagnostics: dict[str, Any] = {
        "message": compile_result.error_message,
        "timed_out": compile_result.timed_out,
        "exit_code": compile_result.exit_code,
        "command_args": compile_result.command_args,
    }
    outputs = _result_outputs(job_dir, compile_result)
    output_failure = any(output["required"] and not output["success"] for output in outputs)
    failure_class = None
    success = bool(compile_result.success and not output_failure)
    if not success:
        failure_class = "timeout" if compile_result.timed_out else "execution_failed"
    result = result_payload(
        job_id=job.job_id,
        success=success,
        failure_class=failure_class,
        duration_seconds=_duration(started),
        outputs=outputs,
        requested_output_ids=[
            str(output.get("output_id"))
            for output in job.requested_outputs
            if isinstance(output, dict) and output.get("output_id")
        ],
        diagnostics=diagnostics,
    )
    _persist_result(job_dir, result)
    return result


async def process_next_job(jobs_root: Path) -> dict[str, Any] | None:
    for job_dir in sorted(path for path in jobs_root.iterdir() if path.is_dir()):
        if (
            job_dir.name.startswith(".")
            or not (job_dir / "job.json").exists()
            or (job_dir / "result.json").exists()
        ):
            continue
        return await execute_job_directory(job_dir)
    return None


def _persist_result(job_dir: Path, result: dict[str, Any]) -> None:
    try:
        complete_job_atomic(job_dir, result)
    except DuplicateJobCompletionError:
        raise


def _duration(started: float) -> float:
    return round(time.monotonic() - started, 6)


def _relative_path(job_dir: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(job_dir.resolve()))
    except ValueError:
        return None


def _result_outputs(job_dir: Path, compile_result: Any) -> list[dict[str, Any]]:
    if getattr(compile_result, "outputs", None):
        results = []
        for output in compile_result.outputs:
            stl_path = _relative_path(job_dir, output.stl_path)
            step_path = _relative_path(job_dir, output.step_path)
            brep_path = _relative_path(job_dir, output.brep_path)
            metadata_path = _relative_path(job_dir, output.metadata_path)
            topology_metadata_path = _relative_path(job_dir, output.topology_metadata_path)
            success = bool(output.success)
            compile_error = output.compile_error
            if success and any(
                original_path is not None and relative_path is None
                for original_path, relative_path in (
                    (output.stl_path, stl_path),
                    (output.step_path, step_path),
                    (output.brep_path, brep_path),
                    (output.metadata_path, metadata_path),
                    (output.topology_metadata_path, topology_metadata_path),
                )
            ):
                success = False
                compile_error = "output artifact path is outside job directory"
            results.append(
                {
                "output_id": output.output_id,
                "entrypoint": output.entrypoint,
                "required": output.required,
                "success": success,
                "stl_path": stl_path,
                "step_path": step_path,
                "brep_path": brep_path,
                "metadata_path": metadata_path,
                "topology_metadata_path": topology_metadata_path,
                "source_hash": compile_result.source_hash,
                "stl_hash": output.stl_hash,
                "step_hash": output.step_hash,
                "brep_hash": output.brep_hash,
                "stl_size_bytes": output.output_size_bytes,
                "topology_metadata": output.topology_metadata,
                "compile_error": compile_error,
            }
            )
        return results
    if not compile_result.success:
        return []
    return [
        {
            "output_id": "model",
            "entrypoint": "build",
            "required": True,
            "success": True,
            "stl_path": _relative_path(job_dir, compile_result.stl_path),
            "step_path": _relative_path(job_dir, compile_result.step_path),
            "brep_path": None,
            "metadata_path": _relative_path(job_dir, compile_result.metadata_path),
            "topology_metadata_path": None,
            "source_hash": compile_result.source_hash,
            "stl_hash": None,
            "step_hash": None,
            "brep_hash": None,
            "stl_size_bytes": compile_result.output_size_bytes,
            "topology_metadata": None,
            "compile_error": None,
        }
    ]
