import asyncio
import hashlib
import json
import os
import re
import shutil
import signal
from dataclasses import asdict, dataclass
from pathlib import Path

from app.core.config import settings
from app.services.mesh.inspect import MeshMetadata, inspect_stl

FORBIDDEN_SOURCE_PATTERNS = (
    re.compile(r"\bimport\s*\(", re.IGNORECASE),
    re.compile(r"\bsurface\s*\(", re.IGNORECASE),
    re.compile(r"(^|[\"'(/\\])\.\.([/\\]|[\"')])"),
    re.compile(r"(^|[\"'])/[^\"']*"),
)


@dataclass(frozen=True)
class CadCompileResult:
    job_id: str
    success: bool
    timed_out: bool
    exit_code: int | None
    source_path: Path | None
    stl_path: Path | None
    stdout_path: Path | None
    stderr_path: Path | None
    metadata_path: Path | None
    source_hash: str
    output_size_bytes: int
    metadata: MeshMetadata | None
    error_message: str | None


class OpenScadCliRunner:
    def __init__(
        self,
        *,
        openscad_binary: str | None = None,
        workspace_root: Path | None = None,
        timeout_seconds: int | None = None,
        max_source_bytes: int | None = None,
        max_stl_bytes: int | None = None,
    ) -> None:
        self.openscad_binary = openscad_binary or settings.openscad_binary
        self.workspace_root = workspace_root or settings.cad_workspace_dir
        self.timeout_seconds = timeout_seconds or settings.cad_timeout_seconds
        self.max_source_bytes = max_source_bytes or settings.max_source_bytes
        self.max_stl_bytes = max_stl_bytes or settings.max_stl_bytes

    async def compile(self, source: str, job_id: str) -> CadCompileResult:
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
        source_path = job_dir / "model.scad"
        stl_path = job_dir / "model.stl"
        stdout_path = job_dir / "stdout.log"
        stderr_path = job_dir / "stderr.log"
        metadata_path = job_dir / "metadata.json"
        source_path.write_text(source, encoding="utf-8")

        process = await asyncio.create_subprocess_exec(
            self.openscad_binary,
            "-o",
            str(stl_path),
            str(source_path),
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
            return CadCompileResult(
                job_id=job_id,
                success=False,
                timed_out=True,
                exit_code=exit_code,
                source_path=source_path,
                stl_path=stl_path if stl_path.exists() else None,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                metadata_path=None,
                source_hash=source_hash,
                output_size_bytes=self._file_size(stl_path),
                metadata=None,
                error_message=f"OpenSCAD timed out after {self.timeout_seconds} seconds",
            )

        if exit_code != 0:
            return CadCompileResult(
                job_id=job_id,
                success=False,
                timed_out=False,
                exit_code=exit_code,
                source_path=source_path,
                stl_path=stl_path if stl_path.exists() else None,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                metadata_path=None,
                source_hash=source_hash,
                output_size_bytes=self._file_size(stl_path),
                metadata=None,
                error_message=self._diagnostic(stderr, "OpenSCAD failed"),
            )

        output_size = self._file_size(stl_path)
        if output_size == 0:
            return CadCompileResult(
                job_id=job_id,
                success=False,
                timed_out=False,
                exit_code=exit_code,
                source_path=source_path,
                stl_path=None,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                metadata_path=None,
                source_hash=source_hash,
                output_size_bytes=0,
                metadata=None,
                error_message="OpenSCAD did not produce an STL",
            )
        if output_size > self.max_stl_bytes:
            stl_path.unlink(missing_ok=True)
            return CadCompileResult(
                job_id=job_id,
                success=False,
                timed_out=False,
                exit_code=exit_code,
                source_path=source_path,
                stl_path=None,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                metadata_path=None,
                source_hash=source_hash,
                output_size_bytes=output_size,
                metadata=None,
                error_message="generated STL exceeds size limit",
            )

        try:
            metadata = inspect_stl(stl_path)
        except ValueError as exc:
            return CadCompileResult(
                job_id=job_id,
                success=False,
                timed_out=False,
                exit_code=exit_code,
                source_path=source_path,
                stl_path=stl_path,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                metadata_path=None,
                source_hash=source_hash,
                output_size_bytes=output_size,
                metadata=None,
                error_message=str(exc),
            )

        metadata_path.write_text(json.dumps(asdict(metadata), indent=2), encoding="utf-8")

        return CadCompileResult(
            job_id=job_id,
            success=True,
            timed_out=False,
            exit_code=exit_code,
            source_path=source_path,
            stl_path=stl_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            metadata_path=metadata_path,
            source_hash=source_hash,
            output_size_bytes=output_size,
            metadata=metadata,
            error_message=None,
        )

    def _screen_source(self, source: str) -> str | None:
        if not source.strip():
            return "source is empty"
        if len(source.encode("utf-8")) > self.max_source_bytes:
            return "source exceeds size limit"
        for pattern in FORBIDDEN_SOURCE_PATTERNS:
            if pattern.search(source):
                return "source contains forbidden file access"
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
    ) -> CadCompileResult:
        return CadCompileResult(
            job_id=job_id,
            success=False,
            timed_out=False,
            exit_code=None,
            source_path=None,
            stl_path=None,
            stdout_path=None,
            stderr_path=None,
            metadata_path=None,
            source_hash=source_hash,
            output_size_bytes=0,
            metadata=None,
            error_message=error_message,
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
