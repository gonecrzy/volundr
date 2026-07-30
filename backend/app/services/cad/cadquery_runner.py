import asyncio
import hashlib
import json
import os
import re
import shutil
import signal
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.core.config import settings
from app.services.cad.cadquery_contract import (
    CadQueryContractError,
    validate_cadquery_source,
)
from app.services.mesh.inspect import MeshMetadata, inspect_stl


@dataclass(frozen=True)
class CadQueryOutputResult:
    output_id: str
    entrypoint: str
    required: bool
    success: bool
    stl_path: Path | None
    step_path: Path | None
    brep_path: Path | None
    metadata_path: Path | None
    topology_metadata_path: Path | None
    stl_hash: str | None
    step_hash: str | None
    brep_hash: str | None
    output_size_bytes: int
    metadata: MeshMetadata | None
    topology_metadata: dict | None
    compile_error: str | None = None


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
    outputs: list[CadQueryOutputResult] = field(default_factory=list)
    execution_manifest_path: Path | None = None


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

    async def compile(
        self,
        source: str,
        job_id: str,
        *,
        source_contract_version: str = "cadquery-v1",
        parameter_values: dict | None = None,
        requested_outputs: list[dict] | None = None,
    ) -> CadQueryCompileResult:
        source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        rejection = self._screen_source(source, source_contract_version=source_contract_version)
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
        output_dir = job_dir / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        execution_result_path = job_dir / "execution-result.json"
        parameter_values_path = job_dir / "parameter-values.json"
        requested_outputs_path = job_dir / "requested-outputs.json"
        stdout_path = job_dir / "stdout.log"
        stderr_path = job_dir / "stderr.log"
        source_path.write_text(source, encoding="utf-8")
        runner_path.write_text(_CADQUERY_RUNNER_SOURCE, encoding="utf-8")
        parameter_values_path.write_text(
            json.dumps(parameter_values or {}, sort_keys=True),
            encoding="utf-8",
        )
        requested_outputs_path.write_text(
            json.dumps(requested_outputs or [], sort_keys=True),
            encoding="utf-8",
        )

        command_args = [
            self.python_binary,
            str(runner_path.name),
            str(output_dir.name),
            str(execution_result_path.name),
            str(parameter_values_path.name),
            str(requested_outputs_path.name),
        ]
        process = await asyncio.create_subprocess_exec(
            *command_args,
            cwd=job_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._subprocess_env(),
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
                stl_path=None,
                step_path=None,
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
                stl_path=None,
                step_path=None,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                source_hash=source_hash,
                timed_out=False,
                exit_code=exit_code,
                error_message=self._diagnostic(stderr, "CadQuery failed"),
                command_args=command_args,
            )

        try:
            execution_payload = json.loads(execution_result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._compile_failure(
                job_id=job_id,
                source_path=source_path,
                stl_path=None,
                step_path=None,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                source_hash=source_hash,
                timed_out=False,
                exit_code=exit_code,
                error_message="CadQuery did not produce an execution result",
                command_args=command_args,
            )

        outputs = self._collect_output_results(job_dir, execution_payload)
        successful_outputs = [output for output in outputs if output.success]
        required_failures = [output for output in outputs if output.required and not output.success]
        if not outputs or not successful_outputs or required_failures:
            error_message = "CadQuery did not produce required outputs"
            if required_failures and required_failures[0].compile_error:
                error_message = required_failures[0].compile_error
            return self._compile_failure(
                job_id=job_id,
                source_path=source_path,
                stl_path=successful_outputs[0].stl_path if successful_outputs else None,
                step_path=successful_outputs[0].step_path if successful_outputs else None,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                source_hash=source_hash,
                timed_out=False,
                exit_code=exit_code,
                error_message=error_message,
                command_args=command_args,
                outputs=outputs,
            )

        oversized_output = next(
            (
                output
                for output in successful_outputs
                if output.output_size_bytes > self.max_stl_bytes
            ),
            None,
        )
        if oversized_output is not None:
            return self._compile_failure(
                job_id=job_id,
                source_path=source_path,
                stl_path=oversized_output.stl_path,
                step_path=oversized_output.step_path,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                source_hash=source_hash,
                timed_out=False,
                exit_code=exit_code,
                error_message="generated STL exceeds size limit",
                command_args=command_args,
                outputs=outputs,
            )

        primary_output = successful_outputs[0]
        return CadQueryCompileResult(
            job_id=job_id,
            success=True,
            timed_out=False,
            exit_code=exit_code,
            source_path=source_path,
            stl_path=primary_output.stl_path,
            step_path=primary_output.step_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            metadata_path=primary_output.metadata_path,
            source_hash=source_hash,
            output_size_bytes=sum(output.output_size_bytes for output in successful_outputs),
            metadata=primary_output.metadata,
            error_message=None,
            command_args=self._safe_command_args(command_args),
            outputs=outputs,
            execution_manifest_path=execution_result_path,
        )

    def _screen_source(self, source: str, *, source_contract_version: str) -> str | None:
        if not source.strip():
            return "source is empty"
        if len(source.encode("utf-8")) > self.max_source_bytes:
            return "source exceeds size limit"
        if source_contract_version != "cadquery-v1":
            return "unsupported CadQuery source_contract_version"
        try:
            validate_cadquery_source(source, contract_version=source_contract_version)
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
        stl_path: Path | None,
        step_path: Path | None,
        stdout_path: Path,
        stderr_path: Path,
        source_hash: str,
        timed_out: bool,
        exit_code: int | None,
        error_message: str,
        command_args: list[str],
        outputs: list[CadQueryOutputResult] | None = None,
    ) -> CadQueryCompileResult:
        return CadQueryCompileResult(
            job_id=job_id,
            success=False,
            timed_out=timed_out,
            exit_code=exit_code,
            source_path=source_path,
            stl_path=stl_path if stl_path is not None and stl_path.exists() else None,
            step_path=step_path if step_path is not None and step_path.exists() else None,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            metadata_path=None,
            source_hash=source_hash,
            output_size_bytes=self._file_size(stl_path),
            metadata=None,
            error_message=error_message,
            command_args=self._safe_command_args(command_args),
            outputs=outputs or [],
        )

    def _collect_output_results(
        self,
        job_dir: Path,
        execution_payload: dict,
    ) -> list[CadQueryOutputResult]:
        raw_outputs = execution_payload.get("outputs", [])
        if not isinstance(raw_outputs, list):
            return []
        outputs: list[CadQueryOutputResult] = []
        for raw_output in raw_outputs:
            if not isinstance(raw_output, dict):
                continue
            output_id = str(raw_output.get("output_id") or "model")
            stl_path = self._job_relative_path(job_dir, raw_output.get("stl_path"))
            step_path = self._job_relative_path(job_dir, raw_output.get("step_path"))
            brep_path = self._job_relative_path(job_dir, raw_output.get("brep_path"))
            topology_metadata = raw_output.get("topology_metadata")
            topology_metadata_path: Path | None = None
            if isinstance(topology_metadata, dict):
                topology_metadata_path = (stl_path.parent if stl_path else job_dir) / "topology.json"
                topology_metadata_path.write_text(
                    json.dumps(topology_metadata, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
            metadata: MeshMetadata | None = None
            metadata_path: Path | None = None
            output_size = self._file_size(stl_path) if stl_path is not None else 0
            success = bool(raw_output.get("success", False))
            compile_error = raw_output.get("compile_error")
            if success and stl_path is not None:
                try:
                    metadata = inspect_stl(stl_path)
                    metadata_path = stl_path.with_suffix(".metadata.json")
                    metadata_path.write_text(
                        json.dumps(asdict(metadata), indent=2, sort_keys=True),
                        encoding="utf-8",
                    )
                except ValueError as exc:
                    success = False
                    compile_error = str(exc)
            if success:
                if step_path is None or not step_path.exists():
                    success = False
                    compile_error = "STEP artifact is missing"
                elif not _step_file_looks_valid(step_path):
                    success = False
                    compile_error = "STEP artifact is malformed"
            outputs.append(
                CadQueryOutputResult(
                    output_id=output_id,
                    entrypoint=str(raw_output.get("entrypoint") or output_id),
                    required=bool(raw_output.get("required", True)),
                    success=success,
                    stl_path=stl_path if stl_path and stl_path.exists() else None,
                    step_path=step_path if step_path and step_path.exists() else None,
                    brep_path=brep_path if brep_path and brep_path.exists() else None,
                    metadata_path=metadata_path,
                    topology_metadata_path=topology_metadata_path,
                    stl_hash=self._sha256_file(stl_path) if stl_path and stl_path.exists() else None,
                    step_hash=self._sha256_file(step_path) if step_path and step_path.exists() else None,
                    brep_hash=self._sha256_file(brep_path) if brep_path and brep_path.exists() else None,
                    output_size_bytes=output_size,
                    metadata=metadata,
                    topology_metadata=topology_metadata if isinstance(topology_metadata, dict) else None,
                    compile_error=str(compile_error) if compile_error else None,
                )
            )
        return outputs

    def _terminate_process_group(self, pid: int) -> None:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            return

    def _file_size(self, path: Path | None) -> int:
        return path.stat().st_size if path is not None and path.exists() else 0

    def _sha256_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _job_relative_path(self, job_dir: Path, raw_path: object) -> Path | None:
        if not isinstance(raw_path, str) or not raw_path:
            return None
        path = Path(raw_path)
        if path.is_absolute() or ".." in path.parts:
            return None
        resolved_job_dir = job_dir.resolve()
        resolved_path = (job_dir / path).resolve()
        try:
            resolved_path.relative_to(resolved_job_dir)
        except ValueError:
            return None
        return resolved_path

    def _diagnostic(self, stderr: bytes, fallback: str) -> str:
        decoded = stderr.decode("utf-8", errors="replace").strip()
        return decoded or fallback

    def _safe_command_args(self, args: list[str]) -> list[str]:
        return [Path(arg).name if Path(arg).is_absolute() else arg for arg in args]

    def _subprocess_env(self) -> dict[str, str]:
        allowed_keys = {
            "LANG",
            "LC_ALL",
            "PATH",
            "PYTHONIOENCODING",
            "TZ",
        }
        env = {
            key: value
            for key, value in os.environ.items()
            if key in allowed_keys and value
        }
        env.setdefault("PATH", os.defpath)
        env["HOME"] = str(self.workspace_root / ".home")
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[3])
        return env


def _step_file_looks_valid(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            prefix = handle.read(512).decode("ascii", errors="ignore").upper()
    except OSError:
        return False
    return "ISO-10303-21" in prefix and "HEADER" in prefix


_CADQUERY_RUNNER_SOURCE = """
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import cadquery as cq
from app.services.cad.cadquery_contract import CadQueryContractError, validate_cadquery_source
from volundr_cad.runtime import ParameterValues, PrintableOutput, Product


def main() -> int:
    output_dir = Path(sys.argv[1])
    result_path = Path(sys.argv[2])
    parameter_values_path = Path(sys.argv[3])
    requested_outputs_path = Path(sys.argv[4])
    output_dir.mkdir(parents=True, exist_ok=True)
    parameter_values = json.loads(parameter_values_path.read_text(encoding="utf-8"))
    requested_outputs = json.loads(requested_outputs_path.read_text(encoding="utf-8"))
    source_path = Path("model.py")
    _validate_source_contract(source_path)
    spec = importlib.util.spec_from_file_location("volundr_generated_model", source_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load generated model.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "build"):
        raise RuntimeError("generated source must define build(params)")
    product = _build_product(module, parameter_values)
    outputs = _execute_product_outputs(product, requested_outputs, output_dir)

    result_path.write_text(
        json.dumps(
            {
                "cad_backend": "cadquery",
                "source_language": "python",
                "source_contract_version": "cadquery-v1",
                "source_hash": _file_sha256(Path("model.py")),
                "parameter_hash": _json_sha256(parameter_values),
                "requested_output_ids": [
                    str(request.get("output_id") or "")
                    for request in requested_outputs
                ] if requested_outputs else [output.output_id for output in product.outputs],
                "output_ids": [
                    output["output_id"]
                    for output in outputs
                    if output.get("success")
                ],
                "outputs": outputs,
                "worker_version": "cadquery-cli-runner-v1",
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return 0


def _validate_source_contract(source_path):
    source = source_path.read_text(encoding="utf-8")
    try:
        validate_cadquery_source(source, contract_version="cadquery-v1")
    except CadQueryContractError as exc:
        raise RuntimeError(f"CadQuery contract violation: {exc}") from exc


def _build_product(module, parameter_values):
    specs = getattr(module, "PARAMETERS", ())
    params = ParameterValues.from_specs(specs, parameter_values)
    product = module.build(params)
    if not isinstance(product, Product):
        raise RuntimeError("build(params) must return Product")
    return product


def _execute_product_outputs(product, requested_outputs, output_dir):
    by_id = {output.output_id: output for output in product.outputs}
    requests = requested_outputs or [{"output_id": output.output_id, "required": output.required} for output in product.outputs]
    results = []
    for request in requests:
        output_id = str(request.get("output_id") or "")
        required = bool(request.get("required", True))
        printable = by_id.get(output_id)
        if printable is None:
            results.append({
                "output_id": output_id,
                "entrypoint": output_id,
                "required": required,
                "success": False,
                "compile_error": f"requested output not found: {output_id}",
                "topology_metadata": _execution_failed_topology_metadata(
                    output_id=output_id,
                    expected_solid_count=int(request.get("expected_solid_count") or 1),
                    allow_disconnected_solids=bool(request.get("allow_disconnected_solids", False)),
                ),
            })
            continue
        results.append(_export_printable_output(output_dir, printable, required=required))
    return results


def _export_printable_output(output_dir, printable, *, required):
    return _export_output(
        output_dir=output_dir,
        output_id=printable.output_id,
        entrypoint=printable.output_id,
        required=required,
        model=printable.model,
        expected_solid_count=printable.expected_solid_count,
        allow_disconnected_solids=printable.allow_disconnected_solids,
    )


def _export_output(
    *,
    output_dir,
    output_id,
    entrypoint,
    required,
    model,
    expected_solid_count,
    allow_disconnected_solids,
):
    if model is None:
        return _failed_output(
            output_id,
            entrypoint,
            required,
            "output model is None",
            topology_metadata=_empty_topology_metadata(
                output_id=output_id,
                expected_solid_count=expected_solid_count,
                allow_disconnected_solids=allow_disconnected_solids,
            ),
        )
    safe_id = _safe_stem(output_id)
    artifact_dir = output_dir / safe_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stl_path = artifact_dir / f"{safe_id}.stl"
    step_path = artifact_dir / f"{safe_id}.step"
    brep_path = artifact_dir / f"{safe_id}.brep"
    try:
        topology_metadata = _topology_metadata(
            output_id=output_id,
            model=model,
            expected_solid_count=expected_solid_count,
            allow_disconnected_solids=allow_disconnected_solids,
        )
        if not topology_metadata["valid"]:
            return _failed_output(
                output_id,
                entrypoint,
                required,
                "output shape is invalid",
                topology_metadata=topology_metadata,
            )
        cq.exporters.export(model, str(stl_path))
        cq.exporters.export(model, str(step_path))
        try:
            cq.exporters.export(model, str(brep_path))
        except Exception:
            brep_path.unlink(missing_ok=True)
        return {
            "output_id": output_id,
            "entrypoint": entrypoint,
            "required": required,
            "success": True,
            "stl_path": str(stl_path),
            "step_path": str(step_path),
            "brep_path": str(brep_path) if brep_path.exists() else None,
            "stl_hash": _file_sha256(stl_path),
            "step_hash": _file_sha256(step_path),
            "brep_hash": _file_sha256(brep_path) if brep_path.exists() else None,
            "topology_metadata": topology_metadata,
        }
    except Exception as exc:
        return _failed_output(
            output_id,
            entrypoint,
            required,
            str(exc),
            topology_metadata=_execution_failed_topology_metadata(
                output_id=output_id,
                expected_solid_count=expected_solid_count,
                allow_disconnected_solids=allow_disconnected_solids,
            ),
        )


def _failed_output(output_id, entrypoint, required, message, topology_metadata=None):
    return {
        "output_id": output_id,
        "entrypoint": entrypoint,
        "required": required,
        "success": False,
        "compile_error": message,
        "topology_metadata": topology_metadata,
    }


def _topology_metadata(
    *,
    output_id,
    model,
    expected_solid_count,
    allow_disconnected_solids,
):
    shape = _shape_for(model)
    if shape is None:
        return _empty_topology_metadata(
            output_id=output_id,
            expected_solid_count=expected_solid_count,
            allow_disconnected_solids=allow_disconnected_solids,
        )
    if not _is_supported_shape_data(model, shape):
        return _unsupported_shape_topology_metadata(
            output_id=output_id,
            expected_solid_count=expected_solid_count,
            allow_disconnected_solids=allow_disconnected_solids,
        )
    valid = bool(shape.isValid()) if hasattr(shape, "isValid") else True
    volume = float(shape.Volume()) if hasattr(shape, "Volume") else None
    detected_solid_count = _solid_count(model, shape)
    outcome = "valid"
    if volume is not None and volume <= 0:
        valid = False
        outcome = "empty"
    if detected_solid_count != expected_solid_count and not allow_disconnected_solids:
        valid = False
        outcome = "solid_count_mismatch"
    if not valid and outcome == "valid":
        outcome = "invalid"
    return {
        "output_id": output_id,
        "valid": valid,
        "outcome": outcome,
        "volume_mm3": volume,
        "detected_solid_count": detected_solid_count,
        "expected_solid_count": expected_solid_count,
        "allow_disconnected_solids": allow_disconnected_solids,
    }


def _unsupported_shape_topology_metadata(*, output_id, expected_solid_count, allow_disconnected_solids):
    return {
        "output_id": output_id,
        "valid": False,
        "outcome": "unsupported_shape",
        "volume_mm3": None,
        "detected_solid_count": 0,
        "expected_solid_count": expected_solid_count,
        "allow_disconnected_solids": allow_disconnected_solids,
    }


def _execution_failed_topology_metadata(*, output_id, expected_solid_count, allow_disconnected_solids):
    return {
        "output_id": output_id,
        "valid": False,
        "outcome": "execution_failed",
        "volume_mm3": None,
        "detected_solid_count": 0,
        "expected_solid_count": expected_solid_count,
        "allow_disconnected_solids": allow_disconnected_solids,
    }


def _empty_topology_metadata(*, output_id, expected_solid_count, allow_disconnected_solids):
    return {
        "output_id": output_id,
        "valid": False,
        "outcome": "empty",
        "volume_mm3": 0,
        "detected_solid_count": 0,
        "expected_solid_count": expected_solid_count,
        "allow_disconnected_solids": allow_disconnected_solids,
    }


def _shape_for(model):
    if hasattr(model, "val"):
        try:
            return model.val()
        except Exception:
            return None
    return model


def _is_supported_shape_data(model, shape):
    supported_attributes = ("isValid", "Volume", "Solids")
    return (
        hasattr(model, "val")
        or hasattr(model, "solids")
        or any(hasattr(shape, attribute) for attribute in supported_attributes)
    )


def _solid_count(model, shape):
    if hasattr(model, "solids"):
        try:
            solids = model.solids()
            if hasattr(solids, "size"):
                return int(solids.size())
        except Exception:
            pass
    if hasattr(shape, "Solids"):
        try:
            return len(shape.Solids())
        except Exception:
            pass
    return 1


def _file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_sha256(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_stem(value):
    return "".join(character if character.isalnum() or character in "._-" else "-" for character in value).strip(".-") or "output"


if __name__ == "__main__":
    raise SystemExit(main())
"""
