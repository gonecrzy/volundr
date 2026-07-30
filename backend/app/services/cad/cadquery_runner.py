import asyncio
import hashlib
import json
import os
import re
import shutil
import signal
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from app.core.config import settings
from app.services.cad.cadquery_contract import (
    CadQueryContractError,
    validate_cadquery_source,
)
from app.services.mesh.inspect import MeshMetadata, inspect_stl


@dataclass(frozen=True)
class CadQueryCompileResult:
    job_id: str
    success: bool
    timed_out: bool
    exit_code: int | None
    source_path: Path | None
    stl_path: Path | None
    step_path: Path | None
    stdout_path: Path | None
    stderr_path: Path | None
    metadata_path: Path | None
    source_hash: str
    output_size_bytes: int
    metadata: MeshMetadata | None
    error_message: str | None
    command_args: list[str] | None = None


class CadQueryCliRunner:
    def __init__(
        self,
        *,
        python_binary: str | None = None,
        workspace_root: Path | None = None,
        timeout_seconds: int | None = None,
        max_source_bytes: int | None = None,
        max_stl_bytes: int | None = None,
    ) -> None:
        self.python_binary = python_binary or sys.executable
        self.workspace_root = workspace_root or settings.cad_workspace_dir
        self.timeout_seconds = timeout_seconds or settings.cad_timeout_seconds
        self.max_source_bytes = max_source_bytes or settings.max_source_bytes
        self.max_stl_bytes = max_stl_bytes or settings.max_stl_bytes

    async def compile(self, source: str, job_id: str) -> CadQueryCompileResult:
        source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        rejection = self._screen_source(source)
        if rejection is not None:
            return self._failure(
                job_id=job_id,
                source_hash=source_hash,
                error_message=rejection,
            )

        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        source_path = job_dir / "model.py"
        runner_path = job_dir / "_volundr_cadquery_runner.py"
        stl_path = job_dir / "model.stl"
        step_path = job_dir / "model.step"
        stdout_path = job_dir / "stdout.log"
        stderr_path = job_dir / "stderr.log"
        metadata_path = job_dir / "metadata.json"
        source_path.write_text(source, encoding="utf-8")
        runner_path.write_text(_CADQUERY_RUNNER_SOURCE, encoding="utf-8")

        command_args = [
            self.python_binary,
            str(runner_path.name),
            str(stl_path.name),
            str(step_path.name),
        ]
        process = await asyncio.create_subprocess_exec(
            *command_args,
            cwd=job_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )

        timed_out = False
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout_seconds,
            )
        except TimeoutError:
            timed_out = True
            self._terminate_process_group(process.pid)
            stdout, stderr = await process.communicate()

        stdout_path.write_bytes(stdout)
        stderr_path.write_bytes(stderr)
        exit_code = process.returncode

        if timed_out:
            return self._compile_failure(
                job_id=job_id,
                source_path=source_path,
                stl_path=stl_path,
                step_path=step_path,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                source_hash=source_hash,
                timed_out=True,
                exit_code=exit_code,
                error_message=f"CadQuery timed out after {self.timeout_seconds} seconds",
                command_args=command_args,
            )

        if exit_code != 0:
            return self._compile_failure(
                job_id=job_id,
                source_path=source_path,
                stl_path=stl_path,
                step_path=step_path,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                source_hash=source_hash,
                timed_out=False,
                exit_code=exit_code,
                error_message=self._diagnostic(stderr, "CadQuery failed"),
                command_args=command_args,
            )

        output_size = self._file_size(stl_path)
        if output_size == 0:
            return self._compile_failure(
                job_id=job_id,
                source_path=source_path,
                stl_path=stl_path,
                step_path=step_path,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                source_hash=source_hash,
                timed_out=False,
                exit_code=exit_code,
                error_message="CadQuery did not produce an STL",
                command_args=command_args,
            )
        if output_size > self.max_stl_bytes:
            stl_path.unlink(missing_ok=True)
            return self._compile_failure(
                job_id=job_id,
                source_path=source_path,
                stl_path=stl_path,
                step_path=step_path,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                source_hash=source_hash,
                timed_out=False,
                exit_code=exit_code,
                error_message="generated STL exceeds size limit",
                command_args=command_args,
            )

        try:
            metadata = inspect_stl(stl_path)
        except ValueError as exc:
            return self._compile_failure(
                job_id=job_id,
                source_path=source_path,
                stl_path=stl_path,
                step_path=step_path,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                source_hash=source_hash,
                timed_out=False,
                exit_code=exit_code,
                error_message=str(exc),
                command_args=command_args,
            )

        metadata_path.write_text(json.dumps(asdict(metadata), indent=2), encoding="utf-8")
        return CadQueryCompileResult(
            job_id=job_id,
            success=True,
            timed_out=False,
            exit_code=exit_code,
            source_path=source_path,
            stl_path=stl_path,
            step_path=step_path if step_path.exists() else None,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            metadata_path=metadata_path,
            source_hash=source_hash,
            output_size_bytes=output_size,
            metadata=metadata,
            error_message=None,
            command_args=self._safe_command_args(command_args),
        )

    def _screen_source(self, source: str) -> str | None:
        if not source.strip():
            return "source is empty"
        if len(source.encode("utf-8")) > self.max_source_bytes:
            return "source exceeds size limit"
        try:
            validate_cadquery_source(source)
        except CadQueryContractError as exc:
            return f"CadQuery contract violation: {exc}"
        return None

    def _job_dir(self, job_id: str) -> Path:
        safe_id = re.sub(r"[^A-Za-z0-9_.-]", "-", job_id).strip(".-")
        if not safe_id:
            safe_id = "job"
        path = self.workspace_root / safe_id
        if path.exists():
            shutil.rmtree(path)
        return path

    def _failure(
        self,
        *,
        job_id: str,
        source_hash: str,
        error_message: str,
    ) -> CadQueryCompileResult:
        return CadQueryCompileResult(
            job_id=job_id,
            success=False,
            timed_out=False,
            exit_code=None,
            source_path=None,
            stl_path=None,
            step_path=None,
            stdout_path=None,
            stderr_path=None,
            metadata_path=None,
            source_hash=source_hash,
            output_size_bytes=0,
            metadata=None,
            error_message=error_message,
            command_args=None,
        )

    def _compile_failure(
        self,
        *,
        job_id: str,
        source_path: Path,
        stl_path: Path,
        step_path: Path,
        stdout_path: Path,
        stderr_path: Path,
        source_hash: str,
        timed_out: bool,
        exit_code: int | None,
        error_message: str,
        command_args: list[str],
    ) -> CadQueryCompileResult:
        return CadQueryCompileResult(
            job_id=job_id,
            success=False,
            timed_out=timed_out,
            exit_code=exit_code,
            source_path=source_path,
            stl_path=stl_path if stl_path.exists() else None,
            step_path=step_path if step_path.exists() else None,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            metadata_path=None,
            source_hash=source_hash,
            output_size_bytes=self._file_size(stl_path),
            metadata=None,
            error_message=error_message,
            command_args=self._safe_command_args(command_args),
        )

    def _terminate_process_group(self, pid: int) -> None:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            return

    def _file_size(self, path: Path) -> int:
        return path.stat().st_size if path.exists() else 0

    def _diagnostic(self, stderr: bytes, fallback: str) -> str:
        decoded = stderr.decode("utf-8", errors="replace").strip()
        return decoded or fallback

    def _safe_command_args(self, args: list[str]) -> list[str]:
        return [Path(arg).name if Path(arg).is_absolute() else arg for arg in args]


_CADQUERY_RUNNER_SOURCE = """
import importlib.util
import sys
from pathlib import Path

import cadquery as cq


def main() -> int:
    stl_path = Path(sys.argv[1])
    step_path = Path(sys.argv[2])
    spec = importlib.util.spec_from_file_location("volundr_generated_model", "model.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load generated model.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "build_model"):
        raise RuntimeError("generated source must define build_model()")
    model = module.build_model()
    if model is None:
        raise RuntimeError("build_model() returned None")
    cq.exporters.export(model, str(stl_path))
    try:
        cq.exporters.export(model, str(step_path))
    except Exception:
        step_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""
