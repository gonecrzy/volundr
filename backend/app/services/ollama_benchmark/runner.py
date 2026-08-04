"""Serialized Ollama calibration runner.

The runner is intentionally separate from the formal benchmark runner.  It
never calls Gemini and it has no five-case execution path.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.ai.ollama import OllamaProvider, OllamaProviderError
from app.services.cad.worker_client import FilesystemCadWorkerRunner
from app.services.cad.worker_execution import process_next_job
from app.services.ollama_benchmark.calibration import (
    EXPECTED_MODEL_IDENTITIES,
    CalibrationIssue,
    CalibrationProfile,
    admission_gate,
    build_resolution_queue,
    classify_calibration_failure,
    classify_native_and_production,
    freeze_profile,
    load_calibration_profile,
    normalize_native_source,
    normalize_structured_response,
    run_models_serially,
    wrap_native_source_for_worker,
    verify_model_identity,
)
from app.services.ollama_benchmark.readiness import (
    classify_production_slot_output,
    classify_structured_output,
)


CALIBRATION_SCHEMA_VERSION = "ollama-calibration-run-v1"
CALIBRATION_SYSTEM_PROMPT = "You are a helpful assistant."
SLOT_IDS = ("base", "features")
SLOT_SCHEMA = {
    "type": "object",
    "properties": {
        "schema_version": {"type": "string"},
        "slots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "slot_id": {"type": "string"},
                    "statements": {"type": "array", "items": {"type": "string"}},
                    "result_symbol": {"type": "string"},
                },
                "required": ["slot_id", "statements", "result_symbol"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["schema_version", "slots"],
    "additionalProperties": False,
}
TRIVIAL_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string"},
        "items": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["status", "items"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class CalibrationRunnerConfig:
    base_url: str = "http://10.1.20.25:11434"
    output_root: Path = Path("data/debug-sessions/ollama-calibration")
    profiles_dir: Path = Path("benchmarks/ollama-prompts/profiles")
    calibration_corpus: Path = Path("benchmarks/ollama-calibration-v1.yaml")
    holdout_corpus: Path = Path("benchmarks/ollama-holdout-v1.yaml")
    context_length: int = 8192
    experiment_id: str | None = None
    model_ids: tuple[str, ...] = ()
    run_holdout: bool = True
    dry_run: bool = False


def _now_id() -> str:
    return datetime.now(timezone.utc).strftime("calibration-%Y%m%dT%H%M%SZ")


def _load_json_compatible_yaml(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _git_value(root: Path, *args: str) -> str | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _normalized_ollama_error_code(error: OllamaProviderError) -> str:
    mapping = {
        "ollama_model_not_installed": "ollama.model_not_installed",
        "ollama_server_unreachable": "ollama.server_unreachable",
        "ollama_proxy_disconnect": "ollama.proxy_disconnect",
        "ollama_stream_parse_error": "adapter.stream_parse_failed",
        "ollama_first_token_timeout": "ollama.resource_failure",
        "ollama_idle_timeout": "ollama.resource_failure",
        "ollama_total_timeout": "ollama.resource_failure",
        "ollama_connect_timeout": "ollama.server_unreachable",
    }
    return mapping.get(error.failure_class, "ollama.resource_failure")


def _safe_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name


class OllamaCalibrationRunner:
    def __init__(
        self,
        config: CalibrationRunnerConfig | None = None,
        *,
        worker: Any | None = None,
        repo_root: Path | None = None,
    ) -> None:
        self.config = config or CalibrationRunnerConfig()
        self.repo_root = repo_root or Path(__file__).resolve().parents[4]
        self.config = replace(
            self.config,
            output_root=self._repo_path(self.config.output_root),
            profiles_dir=self._repo_path(self.config.profiles_dir),
            calibration_corpus=self._repo_path(self.config.calibration_corpus),
            holdout_corpus=self._repo_path(self.config.holdout_corpus),
        )
        self.worker = worker
        self.issues: list[CalibrationIssue] = []
        self.experiment_root: Path | None = None

    def _repo_path(self, path: Path) -> Path:
        return path if path.is_absolute() else self.repo_root / path

    async def run(self) -> dict[str, Any]:
        config = self.config
        experiment_id = config.experiment_id or _now_id()
        self.experiment_root = config.output_root / experiment_id
        self.experiment_root.mkdir(parents=True, exist_ok=True)
        expected = [
            item
            for item in EXPECTED_MODEL_IDENTITIES
            if not config.model_ids or item.model_id in config.model_ids or item.model_name in config.model_ids
        ]
        profiles = {
            item.model_id or item.model_name: load_calibration_profile(
                config.profiles_dir / self._profile_filename(item.model_id or item.model_name)
            )
            for item in expected
        }
        corpus = _load_json_compatible_yaml(config.calibration_corpus)
        holdout = _load_json_compatible_yaml(config.holdout_corpus)
        experiment = {
            "schema_version": CALIBRATION_SCHEMA_VERSION,
            "experiment_id": experiment_id,
            "endpoint": config.base_url,
            "formal_benchmark_started": False,
            "gemini_called": False,
            "one_active_model_at_a_time": True,
            "base_commit": _git_value(self.repo_root, "rev-parse", "HEAD"),
            "base_branch": _git_value(self.repo_root, "branch", "--show-current"),
            "origin_main_commit": _git_value(self.repo_root, "rev-parse", "origin/main"),
            "origin_divergence": _git_value(self.repo_root, "rev-list", "--left-right", "--count", "origin/main...HEAD"),
            "calibration_cases": [item.get("case_id") for item in corpus.get("cases", [])],
            "holdout_cases": [item.get("case_id") for item in holdout.get("cases", [])],
            "intended_models": [item.model_id for item in expected],
        }
        _write_json(self.experiment_root / "experiment.json", experiment)
        if config.dry_run:
            records = [
                {
                    "model_id": item.model_id,
                    "model": item.model_name,
                    "state": "discovered",
                    "admission": "deferred_for_profile_resolution",
                    "dry_run": True,
                }
                for item in expected
            ]
        else:
            records = await run_models_serially(
                [item.model_id or item.model_name for item in expected],
                lambda model_id: self._calibrate_one(next(item for item in expected if item.model_id == model_id), profiles[model_id], corpus, holdout),
            )
        _write_json(self.experiment_root / "resolution-queue.json", build_resolution_queue(self.issues))
        admission = admission_gate(records, intended_model_ids=[item.model_id for item in expected])
        admission_payload = asdict(admission)
        admission_payload["blocking_model_ids"] = list(admission.blocking_model_ids)
        admission_payload["formal_benchmark_started"] = False
        _write_json(self.experiment_root / "admission.json", admission_payload)
        _write_json(self.experiment_root / "models.json", records)
        return {
            "experiment_id": experiment_id,
            "evidence_root": str(self.experiment_root),
            "models": records,
            "admission": admission_payload,
            "open_errors": build_resolution_queue(self.issues),
        }

    @staticmethod
    def _profile_filename(model_id: str) -> str:
        return {
            "cad-coder": "cad-coder-q8.yaml",
            "procad-coder": "procad-coder-q8.yaml",
            "qwen25-cadquery": "qwen25-cadquery-q4.yaml",
            "qwen25-coder-14b": "qwen25-coder-14b-q5.yaml",
            "deepseek-coder-v2-lite": "deepseek-coder-v2-lite-q4.yaml",
            "c3dv0": "c3dv0.yaml",
        }[model_id]

    async def _calibrate_one(
        self,
        identity: Any,
        profile: CalibrationProfile,
        corpus: dict[str, Any],
        holdout: dict[str, Any],
    ) -> dict[str, Any]:
        """Run one model and always release its Ollama allocation."""
        assert self.experiment_root is not None
        model_root = self.experiment_root / "calibration" / str(identity.model_id)
        model_root.mkdir(parents=True, exist_ok=True)
        provider = OllamaProvider(
            base_url=self.config.base_url,
            model=identity.model_name,
            context_length=profile.context_length,
            temperature=profile.temperature,
            top_p=profile.top_p,
            top_k=profile.top_k,
            max_output_tokens=profile.max_output_tokens,
            keep_alive=profile.keep_alive,
            first_token_timeout_seconds=profile.first_token_timeout_seconds,
            generation_idle_timeout_seconds=profile.idle_timeout_seconds,
            total_generation_timeout_seconds=profile.total_timeout_seconds,
        )
        load_state = {"attempted": False}
        try:
            return await self._calibrate_one_impl(identity, profile, corpus, holdout, provider, load_state)
        except Exception as exc:
            self._add_issue(
                identity.model_name,
                "runner",
                "infrastructure.runner_failure",
                str(exc),
                model_root / "runner" / "failure.json",
            )
            return {
                "model_id": identity.model_id,
                "model": identity.model_name,
                "purpose": identity.purpose,
                "state": "deferred",
                "infrastructure_status": "failed",
                "production_compatibility": "not_tested",
                "native_cad_capability": "not_tested",
                "admission": "deferred_for_adapter_resolution",
                "profile_hash": profile.profile_hash,
                "profile_iterations": 0,
                "structured_output": {},
                "native": [],
                "production_slot": [],
                "holdout": {"status": "blocked"},
            }
        finally:
            if load_state["attempted"]:
                try:
                    await provider.unload_model()
                except Exception as exc:
                    self._add_issue(
                        identity.model_name,
                        "unload",
                        "ollama.resource_failure",
                        str(exc),
                        model_root / "resource" / "unload-failure.json",
                    )

    async def _calibrate_one_impl(
        self,
        identity: Any,
        profile: CalibrationProfile,
        corpus: dict[str, Any],
        holdout: dict[str, Any],
        provider: OllamaProvider,
        load_state: dict[str, bool],
    ) -> dict[str, Any]:
        assert self.experiment_root is not None
        model_root = self.experiment_root / "calibration" / str(identity.model_id)
        model_root.mkdir(parents=True, exist_ok=True)
        record: dict[str, Any] = {
            "model_id": identity.model_id,
            "model": identity.model_name,
            "purpose": identity.purpose,
            "state": "discovered",
            "infrastructure_status": "unresolved",
            "production_compatibility": "not_tested",
            "native_cad_capability": "not_tested",
            "admission": "deferred_for_profile_resolution",
            "profile_hash": profile.profile_hash,
            "profile_iterations": 0,
            "structured_output": {},
            "native": [],
            "production_slot": [],
            "holdout": {"status": "not_started"},
        }
        try:
            actual = await provider.inspect_model_identity()
            _write_json(model_root / "identity" / "tags-and-show.json", actual)
            verified = verify_model_identity(identity, actual)
            record["identity"] = asdict(verified)
            record["state"] = "identity_verified"
        except OllamaProviderError as exc:
            self._add_issue(identity.model_name, "identity", _normalized_ollama_error_code(exc), str(exc), model_root / "identity" / "failure.json")
            record.update(state="deferred", infrastructure_status="failed", admission="deferred_for_adapter_resolution")
            return record
        except ValueError as exc:
            self._add_issue(identity.model_name, "identity", "ollama.identity_mismatch", str(exc), model_root / "identity" / "failure.json")
            _write_json(model_root / "identity" / "failure.json", {"error": str(exc), "expected": asdict(identity)})
            record.update(state="deferred", infrastructure_status="passed", admission="deferred_for_profile_resolution")
            return record

        try:
            load_state["attempted"] = True
            record["resource"] = await provider.preflight(
                "Return only the word ready.",
                warm_runs=2,
                poll_interval_seconds=0.5,
            )
            record["infrastructure_status"] = "passed"
            record["state"] = "operational"
        except OllamaProviderError as exc:
            self._add_issue(identity.model_name, "loading", _normalized_ollama_error_code(exc), str(exc), model_root / "resource" / "failure.json")
            record.update(state="deferred", infrastructure_status="failed", admission="deferred_for_adapter_resolution")
            return record

        structured_prompt = "Return exactly this object with status ok and items [1, 2, 3]."
        try:
            structured_raw = await provider.generate_calibration_response(
                structured_prompt,
                profile=profile,
                structured_schema=TRIVIAL_SCHEMA,
            )
            (model_root / "structured").mkdir(parents=True, exist_ok=True)
            (model_root / "structured" / "raw-response.txt").write_text(structured_raw, encoding="utf-8")
            normalized = normalize_structured_response(structured_raw)
            _write_json(model_root / "structured" / "result.json", {"raw_response": normalized.raw_response, "normalized_response": normalized.normalized_response, "codes": normalized.codes})
            record["structured_output"] = {"classification": classify_structured_output(normalized.normalized_response), "normalization_codes": list(normalized.codes)}
        except (OllamaProviderError, ValueError) as exc:
            code = _normalized_ollama_error_code(exc) if isinstance(exc, OllamaProviderError) else "adapter.response_parse_failed"
            self._add_issue(identity.model_name, "structured", code, str(exc), model_root / "structured" / "failure.json")
            record["structured_output"] = {"classification": "adapter_failure" if isinstance(exc, OllamaProviderError) else "malformed_json"}

        native_results = []
        for case in corpus.get("cases", []):
            native_results.append(await self._run_native_case(provider, profile, identity.model_name, model_root, case))
        record["native"] = native_results
        native_validated = any(item.get("worker", {}).get("topology_validated") for item in native_results)
        record["native_cad_capability"] = "validated" if native_validated else "partially_validated"

        slot_results = []
        for case in corpus.get("cases", [])[:2]:
            slot_results.append(await self._run_slot_case(provider, profile, identity.model_name, model_root, case))
        record["production_slot"] = slot_results
        production_validated = bool(slot_results) and all(item.get("worker", {}).get("topology_validated") for item in slot_results)
        production_partial = any(item.get("worker", {}).get("topology_validated") for item in slot_results)
        capabilities = classify_native_and_production(
            native_validated=native_validated,
            production_validated=production_validated,
            production_partial=production_partial,
            production_tested=bool(slot_results),
        )
        record["production_compatibility"] = capabilities.production_compatibility
        record["admission"] = capabilities.admission
        record["state"] = "admitted" if capabilities.admission.startswith("admitted") else "deferred"

        frozen = freeze_profile(profile)
        record["profile_hash"] = frozen.profile_hash
        record["profile_iterations"] = frozen.iteration
        if self.config.run_holdout and record["state"] == "admitted":
            record["holdout"] = await self._run_holdout(provider, frozen, identity.model_name, model_root, holdout)
            if record["holdout"].get("status") != "validated":
                record["state"] = "holdout_failed"
                record["admission"] = "deferred_for_profile_resolution"
        elif self.config.run_holdout:
            record["holdout"] = {
                "status": "blocked",
                "blocking_reason": "candidate profile was not admitted after calibration; holdout was not used to score it",
                "profile_hash": frozen.profile_hash,
            }
        _write_json(model_root / "summary.json", record)
        return record

    async def _run_native_case(self, provider: OllamaProvider, profile: CalibrationProfile, model: str, root: Path, case: dict[str, Any]) -> dict[str, Any]:
        case_id = str(case.get("case_id"))
        case_root = root / "native" / case_id
        raw = ""
        prompt = "Generate one complete self-contained CadQuery Python script for this request. Return only the script, assign the final CadQuery object to result, and do not use Markdown, files, network, subprocesses, or unapproved imports.\n\nRequest: " + str(case.get("prompt"))
        try:
            raw = await provider.generate_calibration_response(prompt, profile=profile)
            case_root.mkdir(parents=True, exist_ok=True)
            (case_root / "raw-response.txt").write_text(raw, encoding="utf-8")
            normalized = normalize_native_source(raw)
            _write_json(case_root / "response.json", {"raw_response": normalized.raw_response, "normalized_response": normalized.normalized_response, "codes": normalized.codes})
            worker = await self._execute_worker(wrap_native_source_for_worker(normalized.normalized_response), case_root, case_id)
            self._record_worker_finding(model, case_root, worker)
            return {"case_id": case_id, "status": "completed", "normalization_codes": list(normalized.codes), "worker": worker}
        except OllamaProviderError as exc:
            self._add_issue(model, "native", _normalized_ollama_error_code(exc), str(exc), case_root / "failure.json")
            return {"case_id": case_id, "status": "integration_failure", "worker": {"topology_validated": False}}
        except ValueError as exc:
            if "geometry-slots-v1" in raw or '"slots"' in raw:
                code = "profile.response_mode_mismatch"
            elif "multiple plausible" in str(exc):
                code = "model.invalid_structured_response"
            else:
                code = "representation.prose_wrapped"
            self._add_issue(model, "native", code, str(exc), case_root / "failure.json")
            return {"case_id": case_id, "status": "profile_or_representation_failure", "error_code": code, "worker": {"topology_validated": False}}

    async def _run_slot_case(self, provider: OllamaProvider, profile: CalibrationProfile, model: str, root: Path, case: dict[str, Any]) -> dict[str, Any]:
        case_id = str(case.get("case_id"))
        case_root = root / "production-slot" / case_id
        prompt = "Return JSON only using schema_version geometry-slots-v1 and exactly the explicit slots base and features. Each slot must contain only CadQuery statements and a result_symbol. Do not return imports, functions, returns, prose, or Markdown.\n\nRequest: " + str(case.get("prompt"))
        try:
            raw = await provider.generate_calibration_response(prompt, profile=profile, structured_schema=SLOT_SCHEMA)
            case_root.mkdir(parents=True, exist_ok=True)
            (case_root / "raw-response.txt").write_text(raw, encoding="utf-8")
            normalized = normalize_structured_response(raw, expected_slot_ids=SLOT_IDS)
            classification = classify_production_slot_output(normalized.normalized_response, expected_slot_ids=list(SLOT_IDS))
            if classification != "production_slot_compatible":
                raise ValueError("production slot response is incompatible")
            payload = json.loads(normalized.normalized_response)
            statements = [statement for slot in payload["slots"] for statement in slot["statements"]]
            source = "import cadquery as cq\n" + "\n".join(str(statement) for statement in statements)
            native = normalize_native_source(source)
            _write_json(case_root / "response.json", {"raw_response": normalized.raw_response, "normalized_response": normalized.normalized_response, "codes": normalized.codes})
            worker = await self._execute_worker(wrap_native_source_for_worker(native.normalized_response), case_root, case_id)
            self._record_worker_finding(model, case_root, worker)
            return {"case_id": case_id, "status": "completed", "classification": classification, "normalization_codes": list(normalized.codes), "worker": worker}
        except OllamaProviderError as exc:
            self._add_issue(model, "production_slot", _normalized_ollama_error_code(exc), str(exc), case_root / "failure.json")
            return {"case_id": case_id, "status": "integration_failure", "worker": {"topology_validated": False}}
        except (ValueError, json.JSONDecodeError) as exc:
            self._add_issue(model, "production_slot", "model.invalid_structured_response", str(exc), case_root / "failure.json")
            return {"case_id": case_id, "status": "contract_failure", "worker": {"topology_validated": False}}

    async def _run_holdout(self, provider: OllamaProvider, profile: CalibrationProfile, model: str, root: Path, holdout: dict[str, Any]) -> dict[str, Any]:
        results = []
        for case in holdout.get("cases", []):
            case_id = str(case.get("case_id"))
            case_root = root / "holdout" / case_id
            prompt = "Generate one complete self-contained CadQuery Python script for this request. Return only the script, assign the final CadQuery object to result, and do not use Markdown, files, network, subprocesses, or unapproved imports.\n\nRequest: " + str(case.get("prompt"))
            try:
                raw = await provider.generate_calibration_response(prompt, profile=profile)
                case_root.mkdir(parents=True, exist_ok=True)
                (case_root / "raw-response.txt").write_text(raw, encoding="utf-8")
                normalized = normalize_native_source(raw)
                worker = await self._execute_worker(wrap_native_source_for_worker(normalized.normalized_response), case_root, case_id)
                self._record_worker_finding(model, case_root, worker)
                results.append({"case_id": case_id, "worker": worker, "normalization_codes": list(normalized.codes)})
            except (OllamaProviderError, ValueError) as exc:
                self._add_issue(model, "holdout", "model.invalid_structured_response", str(exc), case_root / "failure.json")
                results.append({"case_id": case_id, "status": "failed"})
        return {"status": "validated" if results and all(item.get("worker", {}).get("topology_validated") for item in results) else "failed", "profile_hash": profile.profile_hash, "cases": results}

    async def _execute_worker(self, source: str, root: Path, case_id: str) -> dict[str, Any]:
        worker = self.worker or FilesystemCadWorkerRunner()
        compile_task = asyncio.create_task(
            worker.compile(
                source,
                f"ollama-cal-{case_id}-{int(time.time() * 1000)}",
                requested_outputs=[{"output_id": "native_result", "required": True, "expected_solid_count": 1}],
            )
        )
        if self.worker is None:
            while not compile_task.done():
                await process_next_job(worker.jobs_root)
                await asyncio.sleep(0.05)
        result = await compile_task
        outputs = [item for item in result.outputs if item.output_id == "native_result"]
        topology = outputs[0].topology_metadata if outputs else None
        payload = {
            "success": result.success,
            "error": result.error_message,
            "source_hash": result.source_hash,
            "topology": topology,
            "topology_validated": bool(result.success and isinstance(topology, dict) and topology.get("valid") is True),
            "worker_reached": result.exit_code is not None or result.execution_manifest_path is not None,
            "worker_driver": "in_process_process_next_job" if self.worker is None else type(self.worker).__name__,
            "execution_timing": result.execution_timing,
        }
        _write_json(root / "worker" / "result.json", payload)
        return payload

    def _record_worker_finding(self, model: str, root: Path, worker: dict[str, Any]) -> None:
        if worker.get("success") and worker.get("topology_validated"):
            return
        error = str(worker.get("error") or "")
        if worker.get("worker_reached") is not True:
            code = "cad.worker_runtime_failure"
        elif "solid_count_mismatch" in json.dumps(worker.get("topology"), sort_keys=True):
            code = "cad.topology_failure"
        elif "shape is invalid" in error.casefold() or "invalid construction" in error.casefold():
            code = "cad.invalid_construction"
        else:
            code = "cad.verification_failure"
        self._add_issue(model, "worker", code, error or "worker validation failed", root / "worker" / "finding.json", worker_validated=True)

    def _add_issue(self, model: str, stage: str, error_code: str, message: str, evidence_path: Path, *, worker_validated: bool = False) -> None:
        assert self.experiment_root is not None
        _write_json(evidence_path, {"model": model, "stage": stage, "error_code": error_code, "message": message})
        issue = classify_calibration_failure(
            stage=stage,
            error_code=error_code,
            message=message,
            evidence_path=_safe_path(evidence_path, self.experiment_root),
            worker_validated=worker_validated,
        )
        issue = replace(
            issue,
            model=model,
            issue_id=hashlib.sha256(
                f"{model}:{stage}:{error_code}:{_safe_path(evidence_path, self.experiment_root)}".encode("utf-8")
            ).hexdigest()[:16],
        )
        self.issues.append(
            CalibrationIssue(**asdict(issue))
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Calibrate and admit exact Ollama model adapters")
    parser.add_argument("--base-url", default="http://10.1.20.25:11434")
    parser.add_argument("--model", action="append", dest="model_ids", default=[])
    parser.add_argument("--experiment-id")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-holdout", action="store_true")
    return parser


async def _main_async(args: argparse.Namespace) -> int:
    result = await OllamaCalibrationRunner(
        CalibrationRunnerConfig(
            base_url=args.base_url,
            experiment_id=args.experiment_id,
            model_ids=tuple(args.model_ids),
            dry_run=args.dry_run,
            run_holdout=not args.no_holdout,
        )
    ).run()
    print("OLLAMA BENCHMARK ADMISSION")
    for item in result["models"]:
        print(f"\nModel: {item.get('model')}\nInfrastructure: {item.get('infrastructure_status')}\nProduction compatibility: {item.get('production_compatibility')}\nNative CAD capability: {item.get('native_cad_capability')}\nHoldout: {item.get('holdout', {}).get('status')}\nAdmission: {item.get('admission')}\nOpen errors: {sum(1 for issue in result['open_errors'] if issue.get('model') == item.get('model'))}")
    print(f"\nFormal five-case benchmark authorized: {'yes' if result['admission']['formal_benchmark_authorized'] else 'no'}")
    return 0


def main() -> int:
    return asyncio.run(_main_async(build_arg_parser().parse_args()))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
