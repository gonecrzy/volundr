#!/usr/bin/env python3
"""Run the frozen contract-complexity/model-capability diagnostic matrix.

The command writes all raw responses, rendered prompts, worker jobs, and the
redacted experiment record below a local ignored evidence root.  It never
creates or mutates a normal Volundr project.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.services.ai.gemini_api import GeminiApiProvider
from app.services.ai.gemini_cli import (
    CADQUERY_GEOMETRY_BODY_PROMPT_VERSION,
    CADQUERY_GEOMETRY_BODY_REPAIR_PROMPT_VERSION,
)
from app.services.ai.model_policy import GeminiModelPolicy, PromptMode
from app.services.cad.worker_client import FilesystemCadWorkerRunner
from app.services.diagnostics.contract_complexity import (
    CURRENT_CONTRACT,
    SIMPLIFIED_EXECUTION_BRIEF,
    build_attempt_matrix,
    build_simplified_prompt,
    load_diagnostic_packages,
    run_diagnostic_attempt,
)
from app.services.workflow.redaction import RedactionService


class RecordingProvider:
    """Capture rendered prompts/responses without exposing provider credentials."""

    def __init__(self, provider: GeminiApiProvider, *, evidence_root: Path, redactor: RedactionService) -> None:
        self.provider = provider
        self.evidence_root = evidence_root
        self.redactor = redactor
        self.artifacts: list[dict[str, Any]] = []
        self.call_number = 0

    @property
    def provider_id(self) -> str:
        return self.provider.provider_id

    async def generate_cadquery_model(self, request: Any) -> Any:
        phase = "repair" if request.geometry_body_diagnostics else "initial"
        prompt = self.provider.build_cadquery_prompt(request)
        self.call_number += 1
        artifact_prefix = f"call-{self.call_number:02d}-{phase}"
        prompt_path = self._write_text("prompts", f"{artifact_prefix}.txt", prompt)
        response = await self.provider.generate_cadquery_model(request)
        response_path = self._write_text("responses", f"{artifact_prefix}.txt", response.raw_output)
        self.artifacts.extend(
            [
                {"kind": "rendered_prompt", "path": str(prompt_path.relative_to(self.evidence_root))},
                {"kind": "provider_response", "path": str(response_path.relative_to(self.evidence_root))},
            ]
        )
        return response

    async def _run_routed_prompt(self, prompt: str, request: Any) -> Any:
        self.call_number += 1
        artifact_prefix = f"call-{self.call_number:02d}-{'repair' if 'Repair one CadQuery' in prompt else 'initial'}"
        prompt_path = self._write_text("prompts", f"{artifact_prefix}.txt", prompt)
        routed = await self.provider._run_routed_prompt(prompt, request)
        response_path = self._write_text("responses", f"{artifact_prefix}.txt", routed[0])
        self.artifacts.extend(
            [
                {"kind": "rendered_prompt", "path": str(prompt_path.relative_to(self.evidence_root))},
                {"kind": "provider_response", "path": str(response_path.relative_to(self.evidence_root))},
            ]
        )
        return routed

    def _write_text(self, directory: str, filename: str, value: str) -> Path:
        path = self.evidence_root / directory / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        normalized, _ = self.redactor.normalize_evidence_text(
            value,
            data_root=self.evidence_root / "runtime-data",
            evidence_root=self.evidence_root,
        )
        self.redactor.assert_text_redacted(normalized)
        path.write_text(normalized, encoding="utf-8")
        return path


def _write_redacted_json(
    path: Path,
    payload: Any,
    *,
    redactor: RedactionService,
    evidence_root: Path,
) -> None:
    data_root = evidence_root / "runtime-data"
    redacted, _ = redactor.redact_evidence_value(
        payload,
        data_root=data_root,
        evidence_root=evidence_root,
    )
    redactor.assert_json_redacted(redacted)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(redacted, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _write_redacted_text(
    path: Path,
    value: str,
    *,
    redactor: RedactionService,
    evidence_root: Path,
) -> list[dict[str, Any]]:
    normalized, findings = redactor.normalize_evidence_text(
        value,
        data_root=evidence_root / "runtime-data",
        evidence_root=evidence_root,
    )
    redactor.assert_text_redacted(normalized)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalized, encoding="utf-8")
    return findings


def _redact_runtime_data(
    runtime_data: Path,
    *,
    redactor: RedactionService,
    evidence_root: Path,
) -> dict[str, int]:
    """Redact textual worker inputs/results while leaving binary artifacts intact."""

    files = 0
    findings = 0
    for path in sorted(runtime_data.rglob("*")):
        if not path.is_file():
            continue
        try:
            value = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        normalized, path_findings = redactor.normalize_evidence_text(
            value,
            data_root=runtime_data,
            evidence_root=evidence_root,
        )
        redactor.assert_text_redacted(normalized)
        if normalized != value:
            path.write_text(normalized, encoding="utf-8")
        files += 1
        findings += len(path_findings)
    return {"files_scanned": files, "normalization_findings": findings}


def _git_value(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=Path(__file__).resolve().parents[2],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def _migration_head() -> str:
    versions = sorted((Path(__file__).resolve().parents[1] / "alembic" / "versions").glob("*.py"))
    return versions[-1].stem if versions else "unknown"


def _policy_payload(policy: GeminiModelPolicy, *, model: str) -> dict[str, Any]:
    return {
        "policy_version": policy.policy_version,
        "provider": policy.provider,
        "general_model": model,
        "requirements_model": model,
        "design_plan_model": model,
        "geometry_model": model,
        "geometry_repair_model": model,
        "revision_planning_model": model,
        "component_revision_model": model,
        "temperature": policy.temperature,
        "max_output_tokens": policy.max_output_tokens,
        "thinking_level": policy.thinking_level,
        "max_retries": policy.max_retries,
        "max_retry_sleep_seconds": policy.max_retry_sleep_seconds,
    }


def _experiment_identity(base_policy: GeminiModelPolicy, models: list[str]) -> dict[str, Any]:
    safe_base = {
        "provider": settings.ai_provider,
        "configured_default_model": base_policy.general_model,
        "configured_geometry_model": base_policy.resolve(PromptMode.CADQUERY_GEOMETRY_BODIES).selected_model,
        "temperature": base_policy.temperature,
        "max_output_tokens": base_policy.max_output_tokens,
        "thinking_level": base_policy.thinking_level,
        "max_retries": base_policy.max_retries,
        "cad_timeout_seconds": settings.cad_timeout_seconds,
        "gemini_timeout_seconds": settings.gemini_timeout_seconds,
        "migration_head": _migration_head(),
        "prompt_versions": {
            "current_geometry": CADQUERY_GEOMETRY_BODY_PROMPT_VERSION,
            "current_repair": CADQUERY_GEOMETRY_BODY_REPAIR_PROMPT_VERSION,
            "simplified_brief": "simplified-execution-brief-v1",
        },
    }
    return {
        "git_head": _git_value("rev-parse", "HEAD"),
        "branch": _git_value("branch", "--show-current"),
        "migration_head": _migration_head(),
        "provider": settings.ai_provider,
        "configured_default_model": base_policy.general_model,
        "configured_geometry_model": safe_base["configured_geometry_model"],
        "models_compared": models,
        "base_configuration": safe_base,
        "base_configuration_hash": hashlib.sha256(
            json.dumps(safe_base, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "prompt_versions": safe_base["prompt_versions"],
        "frontend_evidence": "not_applicable_to_diagnostic_harness",
        "screenshot_metadata": "not_applicable_to_diagnostic_harness",
    }


def _policy_for_model(base_policy: GeminiModelPolicy, model: str) -> GeminiModelPolicy:
    return GeminiModelPolicy(
        general_model=model,
        requirements_model=model,
        design_plan_model=model,
        geometry_model=model,
        geometry_repair_model=model,
        revision_planning_model=model,
        component_revision_model=model,
        temperature=base_policy.temperature,
        max_output_tokens=base_policy.max_output_tokens,
        thinking_level=base_policy.thinking_level,
        max_retries=base_policy.max_retries,
        max_retry_sleep_seconds=base_policy.max_retry_sleep_seconds,
        provider=base_policy.provider,
        policy_version=base_policy.policy_version,
    )


def _terminate_worker(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)


def _wait_for_worker(path: Path, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if path.exists():
            return
        if process.poll() is not None:
            raise RuntimeError("CAD worker exited before becoming ready")
        time.sleep(0.25)
    raise RuntimeError("CAD worker did not become ready")


async def _run_matrix(
    *,
    packages: list[dict[str, Any]],
    models: list[str],
    base_policy: GeminiModelPolicy,
    worker: FilesystemCadWorkerRunner,
    evidence_root: Path,
    redactor: RedactionService,
) -> list[dict[str, Any]]:
    matrix = build_attempt_matrix(packages, models)
    records: list[dict[str, Any]] = []
    for index, cell in enumerate(matrix, start=1):
        package = next(item for item in packages if item["family"] == cell["family"])
        provider = GeminiApiProvider(
            api_key=settings.gemini_api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("VOLUNDR_GEMINI_API_KEY"),
            model=cell["model"],
            model_policy=_policy_for_model(base_policy, cell["model"]),
        )
        cell_root = evidence_root / "attempts" / f"{index:02d}-{cell['family']}-{cell['strategy']}-{cell['model']}-a{cell['attempt_number']}"
        recorder = RecordingProvider(provider, evidence_root=cell_root, redactor=redactor)
        record = await run_diagnostic_attempt(
            package,
            strategy=cell["strategy"],
            model=cell["model"],
            attempt_number=cell["attempt_number"],
            provider=recorder,
            worker=worker,
            job_id=f"contract-complexity-{index:02d}-{uuid4().hex}",
        )
        record["matrix_index"] = index
        record["evidence_root"] = str(cell_root.relative_to(evidence_root))
        record["evidence_artifacts"] = recorder.artifacts
        record["model_policy"] = _policy_payload(base_policy, model=cell["model"])
        records.append(record)
        _write_redacted_json(
            evidence_root / "experiment-progress.json",
            {"status": "running", "completed_attempts": len(records), "attempts": records},
            redactor=redactor,
            evidence_root=evidence_root,
        )
        print(
            json.dumps(
                {
                    "completed": len(records),
                    "total": len(matrix),
                    "family": cell["family"],
                    "strategy": cell["strategy"],
                    "model": cell["model"],
                    "worker_reached": record["worker_reached"],
                    "candidate_quality": record["candidate_quality"],
                },
                sort_keys=True,
            ),
            flush=True,
        )
    return records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "diagnostic_inputs",
    )
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--stronger-model", default="gemini-3.5-flash")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if settings.ai_provider != "gemini_api":
        print("The diagnostic requires the configured gemini_api provider.", file=sys.stderr)
        return 2
    api_key = settings.gemini_api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("VOLUNDR_GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY or VOLUNDR_GEMINI_API_KEY is required; it is never written to evidence.", file=sys.stderr)
        return 2
    base_policy = GeminiModelPolicy.from_settings(settings)
    current_model = base_policy.resolve(PromptMode.CADQUERY_GEOMETRY_BODIES).selected_model
    stronger_model = str(args.stronger_model)
    if not current_model or current_model == stronger_model:
        print("The configured and stronger model must be distinct.", file=sys.stderr)
        return 2
    packages = load_diagnostic_packages(args.input_root)
    models = [current_model, stronger_model]
    evidence_root = args.evidence_root.resolve()
    evidence_root.mkdir(parents=True, exist_ok=True)
    redactor = RedactionService()
    identity = _experiment_identity(base_policy, models)
    _write_redacted_json(
        evidence_root / "session.json",
        {
            "schema_version": "contract-complexity-session-v1",
            "status": "running",
            "identity": identity,
            "input_root": str(args.input_root.resolve()),
            "package_hashes": {str(item["family"]): item["package_hash"] for item in packages},
            "raw_evidence_policy": "local-only-outside-Git",
        },
        redactor=redactor,
        evidence_root=evidence_root,
    )
    runtime_data = evidence_root / "runtime-data"
    jobs_root = runtime_data / "jobs"
    runtime_data.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
            "VOLUNDR_DATA_DIR": str(runtime_data),
            "VOLUNDR_CAD_WORKSPACE_DIR": str(jobs_root),
            "VOLUNDR_WORKER_HEALTH_PATH": str(evidence_root / "worker-health.json"),
        }
    )
    env.pop("GEMINI_API_KEY", None)
    env.pop("VOLUNDR_GEMINI_API_KEY", None)
    worker_log_path = evidence_root / "cad-worker.log"
    worker_log = worker_log_path.open("wb")
    worker_process: subprocess.Popen[bytes] | None = None
    try:
        worker_process = subprocess.Popen(
            [sys.executable, "-m", "app.workers.cad_worker"],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            stdout=worker_log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        _wait_for_worker(evidence_root / "worker-health.json", worker_process)
        settings.data_dir = runtime_data
        settings.cad_workspace_dir = jobs_root
        records = asyncio.run(
            _run_matrix(
                packages=packages,
                models=models,
                base_policy=base_policy,
                worker=FilesystemCadWorkerRunner(jobs_root),
                evidence_root=evidence_root,
                redactor=redactor,
            )
        )
        worker_log.flush()
        worker_runtime_scan = _redact_runtime_data(
            runtime_data,
            redactor=redactor,
            evidence_root=evidence_root,
        )
        worker_redaction_findings = _write_redacted_text(
            evidence_root / "cad-worker-redacted.log",
            worker_log_path.read_text(encoding="utf-8", errors="replace"),
            redactor=redactor,
            evidence_root=evidence_root,
        )
        experiment = {
            "schema_version": "contract-complexity-experiment-v1",
            "status": "complete",
            "identity": identity,
            "packages": [
                {
                    "family": item["family"],
                    "source_project_id": item["source_project_id"],
                    "source_batch_id": item["source_batch_id"],
                    "package_hash": item["package_hash"],
                }
                for item in packages
            ],
            "strategies": [CURRENT_CONTRACT, SIMPLIFIED_EXECUTION_BRIEF],
            "models": models,
            "matrix_expected_attempts": 24,
            "matrix_completed_attempts": len(records),
            "attempts": records,
            "repair_policy": {
                "initial_attempts_per_cell": 2,
                "max_worker_informed_repairs_per_attempt": 1,
                "normal_project_mutation": False,
            },
            "redaction_scan": {
                "rendered_prompts": "scanned",
                "provider_responses": "scanned",
                "assembled_source": "worker/source-contract scanned",
                "worker_output": {
                    "status": "scanned",
                    "redacted_log": "cad-worker-redacted.log",
                    "files_scanned": worker_runtime_scan["files_scanned"],
                    "normalization_findings": worker_runtime_scan["normalization_findings"] + len(worker_redaction_findings),
                },
                "screenshots_metadata": "not_applicable",
                "frontend_network_evidence": "not_applicable",
            },
            "worker_log": "cad-worker-redacted.log",
        }
        _write_redacted_json(evidence_root / "experiment.json", experiment, redactor=redactor, evidence_root=evidence_root)
        _write_redacted_json(
            evidence_root / "session.json",
            {"schema_version": "contract-complexity-session-v1", "status": "complete", "identity": identity, "experiment": "experiment.json"},
            redactor=redactor,
            evidence_root=evidence_root,
        )
        print(json.dumps({"evidence_root": str(evidence_root), "attempts": len(records)}, sort_keys=True))
        return 0 if len(records) == 24 else 1
    finally:
        _terminate_worker(worker_process)
        worker_log.close()


if __name__ == "__main__":
    raise SystemExit(main())
