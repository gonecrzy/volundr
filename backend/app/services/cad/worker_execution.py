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
    compile_result = await active_runner.compile(source, job_id=job.job_id)
    diagnostics: dict[str, Any] = {
        "message": compile_result.error_message,
        "timed_out": compile_result.timed_out,
        "exit_code": compile_result.exit_code,
        "command_args": compile_result.command_args,
    }
    outputs: list[dict[str, Any]] = []
    if compile_result.success:
        outputs.append(
            {
                "output_id": "model",
                "required": True,
                "stl_path": _relative_path(job_dir, compile_result.stl_path),
                "step_path": _relative_path(job_dir, compile_result.step_path),
                "metadata_path": _relative_path(job_dir, compile_result.metadata_path),
                "source_hash": compile_result.source_hash,
                "stl_size_bytes": compile_result.output_size_bytes,
            }
        )
    failure_class = None
    if not compile_result.success:
        failure_class = "timeout" if compile_result.timed_out else "execution_failed"
    result = result_payload(
        job_id=job.job_id,
        success=compile_result.success,
        failure_class=failure_class,
        duration_seconds=_duration(started),
        outputs=outputs,
        diagnostics=diagnostics,
    )
    _persist_result(job_dir, result)
    return result


async def process_next_job(jobs_root: Path) -> dict[str, Any] | None:
    for job_dir in sorted(path for path in jobs_root.iterdir() if path.is_dir()):
        if job_dir.name.startswith(".") or (job_dir / "result.json").exists():
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
        return path.name
