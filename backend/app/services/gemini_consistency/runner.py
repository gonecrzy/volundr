"""API-only runner for the paired Gemini consistency benchmark.

The runner intentionally talks to the same public application API that a
normal client uses.  It never invokes a provider or CAD worker directly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import httpx

from app.services.gemini_consistency.corpus import (
    PILOT_CASE_IDS,
    ConsistencyCase,
    ConsistencyCorpus,
    load_consistency_corpus,
)
from app.services.workflow.redaction import RedactionService


PROPOSAL_ANSWER = "Use a reasonable Volundr proposal and record it as a proposal."
TERMINAL_MEMBERSHIP_STATES = {"completed", "failed", "cancelled", "incomplete"}
ESSENTIAL_CATEGORIES = {
    "dimensions",
    "orientation",
    "mounting",
    "material_process",
    "output_count",
    "clearance",
    "fit",
    "wall_thickness",
    "safety",
}


@dataclass(frozen=True)
class ClarificationDecision:
    category: str
    answer: str | None
    essential: bool
    fact_key: str | None = None


@dataclass(frozen=True)
class BenchmarkRunSelection:
    models: tuple[str, ...]
    runs: int = 2
    pilot: bool = False
    full: bool = True


@dataclass(frozen=True)
class BenchmarkRunnerConfig:
    corpus_path: Path
    models: tuple[str, ...]
    runs: int = 2
    pilot: bool = False
    full: bool = True
    experiment_id: str | None = None
    dry_run: bool = False
    resume: bool = False
    max_concurrency: int = 1
    base_url: str = "http://127.0.0.1:8000"
    timeout_seconds: float = 60.0
    output_root: Path = Path("data/debug-sessions/gemini-consistency")
    case_filter: tuple[str, ...] = ()
    family_filter: tuple[str, ...] = ()
    specificity_filter: tuple[str, ...] = ()
    frontend_build_identity: str = "benchmark-runner"
    label: str | None = None


class BenchmarkApiError(RuntimeError):
    def __init__(self, status_code: int, message: str, *, path: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.path = path


def _normalized(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.removeprefix("models/").strip())


def infer_clarification_category(question: str) -> str:
    text = question.casefold()
    category_patterns: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "safety",
            (
                "safe",
                "safety",
                "load",
                "weight",
                "factor",
                "rating",
                "certif",
                "pressure",
                "electrical",
                "voltage",
                "watertight",
                "waterproof",
                "food safe",
            ),
        ),
        (
            "wall_thickness",
            ("wall thickness", "thickness", "thick", "section"),
        ),
        (
            "mounting",
            ("mount", "fastener", "screw", "hole", "wall", "attachment", "pattern"),
        ),
        (
            "material_process",
            ("material", "process", "print", "pla", "petg", "tpu", "fabricat"),
        ),
        (
            "output_count",
            ("output", "outputs", "part", "parts", "piece", "pieces", "separate", "printable"),
        ),
        (
            "clearance",
            ("clearance", "tolerance", "gap", "fit", "sliding", "diameter", "bore", "opening"),
        ),
        (
            "dimensions",
            (
                "dimension",
                "size",
                "wide",
                "width",
                "deep",
                "depth",
                "height",
                "long",
                "length",
                "diameter",
                "measure",
            ),
        ),
        ("orientation", ("orientation", "orient", "portrait", "landscape", "vertical", "horizontal", "angle", "tilt")),
        ("appearance", ("round", "rounded", "chamfer", "edge", "color", "colour", "finish")),
    )
    for category, patterns in category_patterns:
        if any(pattern in text for pattern in patterns):
            return category
    return "appearance"


def _fact_category(key: str, value: Any) -> str:
    return infer_clarification_category(f"{key} {value}")


def clarification_answer_for(question: str, fact_sheet: dict[str, Any]) -> ClarificationDecision:
    category = infer_clarification_category(question)
    for key, value in fact_sheet.items():
        if _fact_category(str(key), value) == category:
            if isinstance(value, (dict, list)):
                answer = json.dumps(value, sort_keys=True)
            else:
                answer = str(value)
            return ClarificationDecision(
                category=category,
                answer=answer,
                essential=category in ESSENTIAL_CATEGORIES,
                fact_key=str(key),
            )
    if category in ESSENTIAL_CATEGORIES:
        return ClarificationDecision(category=category, answer=None, essential=True)
    return ClarificationDecision(category=category, answer=PROPOSAL_ANSWER, essential=False)


def stable_project_key(experiment_id: str, model: str, run_index: int, case_id: str) -> str:
    model_digest = hashlib.sha256(model.encode("utf-8")).hexdigest()[:16]
    return f"gemini-consistency:{experiment_id}:run-{run_index}:{_normalized(case_id)}:model-{model_digest}"


def stable_client_message_id(project_key: str, phase: str) -> str:
    digest = hashlib.sha256(f"{project_key}:{phase}".encode("utf-8")).hexdigest()
    return f"gemini-consistency-{digest[:56]}"


def filter_cases(
    corpus: ConsistencyCorpus,
    *,
    case_filter: Sequence[str] = (),
    family_filter: Sequence[str] = (),
    specificity_filter: Sequence[str] = (),
) -> list[ConsistencyCase]:
    case_ids = set(case_filter)
    families = set(family_filter)
    specificities = set(specificity_filter)
    return [
        case
        for case in corpus.cases
        if (not case_ids or case.case_id in case_ids)
        and (not families or case.family in families)
        and (not specificities or case.specificity in specificities)
    ]


def validate_run_selection(
    corpus: ConsistencyCorpus,
    selection: BenchmarkRunSelection,
    *,
    case_filter: Sequence[str] = (),
    family_filter: Sequence[str] = (),
    specificity_filter: Sequence[str] = (),
) -> list[ConsistencyCase]:
    if len(selection.models) < 2:
        raise ValueError("benchmark selection requires at least two models")
    if len(set(selection.models)) != len(selection.models):
        raise ValueError("benchmark models must be unique")
    if selection.runs != 2:
        raise ValueError("benchmark selection requires exactly two runs")
    if selection.pilot == selection.full:
        raise ValueError("select exactly one of pilot or full")
    if any(not model.strip() for model in selection.models):
        raise ValueError("benchmark models cannot be blank")
    selected = filter_cases(
        corpus,
        case_filter=case_filter,
        family_filter=family_filter,
        specificity_filter=specificity_filter,
    )
    if selection.pilot:
        pilot = set(PILOT_CASE_IDS)
        selected = [case for case in selected if case.case_id in pilot]
    if not selected:
        raise ValueError("case filters selected no benchmark cases")
    if selection.full and not case_filter and not family_filter and not specificity_filter and len(selected) != len(corpus.cases):
        raise ValueError("full selection must include the complete corpus")
    return selected


class BenchmarkApiClient:
    """Small, credential-free HTTP client for the application API."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 60.0, client: Any | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.client = client or httpx.Client(timeout=timeout_seconds)
        self.history: list[dict[str, Any]] = []

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if close:
            close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        started = time.monotonic()
        try:
            response = self.client.request(method, f"{self.base_url}{path}", **kwargs)
        except Exception as exc:  # pragma: no cover - transport-specific errors
            self.history.append(
                {"method": method, "path": path, "status_code": None, "error": type(exc).__name__}
            )
            raise BenchmarkApiError(599, f"request failed: {type(exc).__name__}", path=path) from exc
        self.history.append(
            {
                "method": method,
                "path": path,
                "status_code": response.status_code,
                "duration_ms": round((time.monotonic() - started) * 1000),
            }
        )
        if response.status_code >= 400:
            try:
                detail = response.json()
            except Exception:
                detail = response.text[:1000]
            raise BenchmarkApiError(response.status_code, str(detail), path=path)
        if not response.content:
            return None
        content_type = response.headers.get("content-type", "")
        if "json" in content_type:
            return response.json()
        return response.text

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        return self._request("POST", path, json=payload)

    def ready(self) -> Any:
        return self.get("/ready")

    def health(self) -> Any:
        return self.get("/health")

    def capabilities(self) -> Any:
        return self.get("/api/capabilities")

    def discover_models(self) -> list[dict[str, Any]]:
        result = self.get("/api/gemini-consistency/models")
        if not isinstance(result, list):
            raise BenchmarkApiError(502, "model discovery returned an invalid response", path="/api/gemini-consistency/models")
        return result

    def create_experiment(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.post("/api/gemini-consistency/experiments", payload)

    def experiment(self, experiment_id: str) -> dict[str, Any]:
        return self.get(f"/api/gemini-consistency/experiments/{experiment_id}")

    def claim_case(self, experiment_id: str, run_id: str, case: ConsistencyCase, position: int) -> dict[str, Any]:
        return self.post(
            f"/api/gemini-consistency/experiments/{experiment_id}/runs/{run_id}/cases/{case.case_id}/claim",
            {"position": position, "title": case.title, "original_intent": case.initial_prompt},
        )

    def complete_case(self, experiment_id: str, run_id: str, case_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.post(
            f"/api/gemini-consistency/experiments/{experiment_id}/runs/{run_id}/cases/{case_id}/complete",
            payload,
        )

    def finish_experiment(self, experiment_id: str, state: str = "completed") -> dict[str, Any]:
        return self.post(f"/api/gemini-consistency/experiments/{experiment_id}/finish", {"state": state})

    def record_model_availability(
        self, experiment_id: str, requested_model: str, actual_model: str | None, availability_state: str
    ) -> dict[str, Any]:
        return self.post(
            f"/api/gemini-consistency/experiments/{experiment_id}/model-availability",
            {
                "requested_model": requested_model,
                "actual_model": actual_model,
                "availability_state": availability_state,
            },
        )

    def send_chat(self, project_id: str, model: str, message: str, client_message_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/projects/{project_id}/chat",
            headers={"X-Volundr-Benchmark-Model": model},
            json={"message": message, "client_message_id": client_message_id},
        )

    def collect_project_evidence(self, project_id: str, workflow_run_ids: Iterable[str]) -> dict[str, Any]:
        evidence: dict[str, Any] = {}
        paths = {
            "workspace": f"/api/projects/{project_id}/workspace",
            "messages": f"/api/projects/{project_id}/messages",
            "workflow_runs": f"/api/projects/{project_id}/workflow-runs",
            "design_specification": f"/api/projects/{project_id}/design-specification",
            "requirements": f"/api/projects/{project_id}/requirements/active",
            "generation_attempts": f"/api/projects/{project_id}/generation-attempts",
            "revisions": f"/api/projects/{project_id}/revisions",
            "exports": f"/api/projects/{project_id}/exports",
        }
        for name, path in paths.items():
            try:
                evidence[name] = self.get(path)
            except BenchmarkApiError as exc:
                evidence[name] = {"integrity_finding": "endpoint_unavailable", "status_code": exc.status_code}
        all_run_ids = set(workflow_run_ids)
        for run in evidence.get("workflow_runs", []) if isinstance(evidence.get("workflow_runs"), list) else []:
            if isinstance(run, dict) and run.get("id"):
                all_run_ids.add(str(run["id"]))
        evidence["workflow_events"] = {}
        for run_id in sorted(all_run_ids):
            try:
                evidence["workflow_events"][run_id] = self.get(f"/api/workflow-runs/{run_id}/events")
            except BenchmarkApiError as exc:
                evidence["workflow_events"][run_id] = {"integrity_finding": "events_unavailable", "status_code": exc.status_code}
        return evidence


class EvidenceWriter:
    def __init__(self, root: Path, *, data_root: Path | None = None) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.data_root = (data_root or root).resolve()
        self.redactor = RedactionService()
        self.findings: list[dict[str, Any]] = []

    def write_json(self, relative_path: str, payload: Any) -> Path:
        safe, findings = self.redactor.redact_evidence_value(
            payload,
            data_root=self.data_root,
            evidence_root=self.root,
        )
        self.findings.extend(findings)
        self.redactor.assert_json_redacted(safe)
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(safe, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        return path

    def write_text(self, relative_path: str, text: str, *, field_name: str = "text") -> Path:
        safe, findings = self.redactor.redact_evidence_value(
            {field_name: text}, data_root=self.data_root, evidence_root=self.root
        )
        self.findings.extend(findings)
        value = safe[field_name]
        self.redactor.assert_text_redacted(str(value))
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(value), encoding="utf-8")
        return path

    def finalize(self) -> None:
        self.write_json(
            "redaction-report.json",
            {
                "schema_version": "gemini-consistency-redaction-v1",
                "redaction_version": self.redactor.version,
                "status": "confirmed",
                "normalization_findings": self.findings,
            },
        )


def _questions_from_spec(specification: Any, fallback: str) -> list[str]:
    if isinstance(specification, dict):
        questions = specification.get("clarification_questions")
        if isinstance(questions, list):
            result = [
                str(item.get("question"))
                for item in questions
                if isinstance(item, dict) and item.get("question")
            ]
            if result:
                return result
    return [fallback] if fallback else []


class GeminiConsistencyRunner:
    def __init__(self, config: BenchmarkRunnerConfig, *, client: BenchmarkApiClient | None = None) -> None:
        self.config = config
        self.client = client
        self.stop_requested = False

    def request_stop(self) -> None:
        self.stop_requested = True

    def dry_run_manifest(self, corpus: ConsistencyCorpus) -> dict[str, Any]:
        selection = BenchmarkRunSelection(
            models=self.config.models,
            runs=self.config.runs,
            pilot=self.config.pilot,
            full=self.config.full,
        )
        selected = validate_run_selection(
            corpus,
            selection,
            case_filter=self.config.case_filter,
            family_filter=self.config.family_filter,
            specificity_filter=self.config.specificity_filter,
        )
        return {
            "dry_run": True,
            "corpus_version": corpus.version,
            "corpus_hash": corpus.content_hash,
            "models": list(self.config.models),
            "runs": self.config.runs,
            "mode": "pilot" if self.config.pilot else "full",
            "case_ids": [case.case_id for case in selected],
            "max_concurrency": self.config.max_concurrency,
            "network_calls": 0,
            "provider_calls": 0,
            "worker_calls": 0,
        }

    def run(self) -> dict[str, Any]:
        corpus = load_consistency_corpus(self.config.corpus_path)
        if self.config.dry_run:
            return self.dry_run_manifest(corpus)
        if self.config.max_concurrency < 1 or self.config.max_concurrency > 2:
            raise ValueError("max concurrency must be between 1 and 2")
        if self.client is None:
            self.client = BenchmarkApiClient(self.config.base_url, timeout_seconds=self.config.timeout_seconds)
        client = self.client
        readiness = client.ready()
        health = client.health()
        capabilities = client.capabilities()
        if not capabilities.get("developer_tools_enabled", False):
            raise ValueError("developer tools capability is disabled")
        discovered = client.discover_models()
        available = {
            str(item.get("name", "")).removeprefix("models/")
            for item in discovered
            if isinstance(item, dict) and item.get("name")
        }
        selection = BenchmarkRunSelection(
            models=tuple(model.removeprefix("models/") for model in self.config.models),
            runs=self.config.runs,
            pilot=self.config.pilot,
            full=self.config.full,
        )
        selected_cases = validate_run_selection(
            corpus,
            selection,
            case_filter=self.config.case_filter,
            family_filter=self.config.family_filter,
            specificity_filter=self.config.specificity_filter,
        )
        unavailable = [model for model in selection.models if model not in available]
        model_names = {
            str(item.get("name", "")).removeprefix("models/"): str(item.get("name", "")).removeprefix("models/")
            for item in discovered
            if isinstance(item, dict) and item.get("name")
        }
        experiment = self._get_or_create_experiment(client, corpus, selection)
        experiment_id = str(experiment["id"])
        experiment_root = self.config.output_root / experiment_id
        root_writer = EvidenceWriter(experiment_root, data_root=self.config.output_root)
        root_writer.write_json("experiment.json", {
            "experiment": experiment,
            "readiness": readiness,
            "health": health,
            "developer_tools_enabled": True,
        })
        root_writer.write_json("corpus.json", corpus.raw)
        root_writer.write_json("models/discovered.json", discovered)
        root_writer.write_json("identities.json", {
            "experiment_id": experiment_id,
            "models": list(selection.models),
            "runs": selection.runs,
        })
        for model in selection.models:
            client.record_model_availability(
                experiment_id,
                model,
                model_names.get(model),
                "available" if model in available else "unavailable",
            )
        if unavailable:
            raise ValueError(f"requested Gemini models are unavailable: {', '.join(unavailable)}")
        result: dict[str, Any] = {
            "experiment_id": experiment_id,
            "mode": "pilot" if selection.pilot else "full",
            "case_count": len(selected_cases),
            "models": list(selection.models),
            "runs": selection.runs,
            "results": [],
            "readiness": readiness,
        }
        for model in selection.models:
            for run_index in range(1, selection.runs + 1):
                run = self._find_run(experiment, model, run_index)
                if run is None:
                    raise ValueError(f"experiment is missing run {model}/{run_index}")
                for position, case in enumerate(selected_cases):
                    if self.stop_requested:
                        break
                    result["results"].append(self._run_case(experiment_id, model, run, case, position, corpus))
                if self.stop_requested:
                    break
            if self.stop_requested:
                break
        if not self.stop_requested:
            client.finish_experiment(experiment_id, "completed")
        root_writer.finalize()
        return result

    def _get_or_create_experiment(
        self, client: BenchmarkApiClient, corpus: ConsistencyCorpus, selection: BenchmarkRunSelection
    ) -> dict[str, Any]:
        if self.config.experiment_id:
            return client.experiment(self.config.experiment_id)
        return client.create_experiment(
            {
                "label": self.config.label or f"Gemini consistency {corpus.version}",
                "corpus_version": corpus.version,
                "corpus_hash": corpus.content_hash,
                "mode": "pilot" if selection.pilot else "full",
                "models": list(selection.models),
                "runs": selection.runs,
                "model_settings": {"max_concurrency": self.config.max_concurrency},
                "frontend_build_identity": self.config.frontend_build_identity,
            }
        )

    @staticmethod
    def _find_run(experiment: dict[str, Any], model: str, run_index: int) -> dict[str, Any] | None:
        model_configs = {item.get("id"): item for item in experiment.get("models", []) if isinstance(item, dict)}
        model_id = next(
            (item_id for item_id, item in model_configs.items() if item.get("requested_model", "").removeprefix("models/") == model),
            None,
        )
        for run in experiment.get("runs", []):
            if isinstance(run, dict) and run.get("model_config_id") == model_id and run.get("run_index") == run_index:
                return run
        return None

    def _run_case(
        self,
        experiment_id: str,
        model: str,
        run: dict[str, Any],
        case: ConsistencyCase,
        position: int,
        corpus: ConsistencyCorpus,
    ) -> dict[str, Any]:
        assert self.client is not None
        client = self.client
        run_id = str(run["id"])
        project_key = stable_project_key(experiment_id, model, int(run["run_index"]), case.case_id)
        membership = client.claim_case(experiment_id, run_id, case, position)
        if membership.get("state") in TERMINAL_MEMBERSHIP_STATES:
            if self.config.resume:
                return {"case_id": case.case_id, "model": model, "run_index": run["run_index"], "state": "skipped", "membership": membership}
            raise ValueError(f"case {case.case_id} is already terminal; use --resume to preserve it")
        project_id = membership.get("project_id")
        if not project_id:
            raise ValueError(f"claimed benchmark case has no project: {case.case_id}")
        writer = EvidenceWriter(
            self.config.output_root / experiment_id / "models" / _normalized(model) / f"run-{int(run['run_index']):02d}" / case.case_id,
            data_root=self.config.output_root,
        )
        writer.write_json("case.json", case.raw)
        responses: list[dict[str, Any]] = []
        workflow_run_ids: list[str] = []
        clarification_rounds = 0
        retry_count = 0
        outcome_category = "completed"
        outcome_state = "unknown"
        final_outcome = None
        try:
            phase = "initial"
            current_message = case.initial_prompt
            while True:
                try:
                    response = client.send_chat(project_id, model, current_message, stable_client_message_id(project_key, phase))
                    responses.append({"phase": phase, "response": response})
                except BenchmarkApiError as exc:
                    responses.append({"phase": phase, "error": {"status_code": exc.status_code, "path": exc.path}})
                    if retry_count >= 1:
                        raise
                    retry_count += 1
                    phase = f"{phase}:retry-1"
                    continue
                workflow_run_id = response.get("workflow_run_id")
                if workflow_run_id:
                    workflow_run_ids.append(str(workflow_run_id))
                    self._poll_workflow(str(workflow_run_id))
                if not response.get("input_required"):
                    outcome_state = str(response.get("current_stage") or "completed")
                    final_outcome = response.get("assistant_message")
                    break
                if clarification_rounds >= 2:
                    outcome_category = "clarification_limit"
                    outcome_state = "failed"
                    final_outcome = "Clarification limit reached without a final workflow response."
                    break
                specification = None
                try:
                    specification = client.get(f"/api/projects/{project_id}/design-specification")
                except BenchmarkApiError as exc:
                    responses.append({"phase": "clarification-context", "error": {"status_code": exc.status_code, "path": exc.path}})
                questions = _questions_from_spec(specification, str(response.get("assistant_message") or ""))
                decisions = [clarification_answer_for(question, case.fact_sheet) for question in questions]
                missing = next((decision for decision in decisions if decision.essential and decision.answer is None), None)
                if missing is not None:
                    outcome_category = "unanswered_essential_clarification"
                    outcome_state = "failed"
                    final_outcome = f"No fact-sheet answer was available for essential {missing.category} clarification."
                    break
                answer = "\n".join(
                    f"{decision.category}: {decision.answer}" for decision in decisions if decision.answer is not None
                ) or PROPOSAL_ANSWER
                clarification_rounds += 1
                current_message = answer
                phase = f"clarification-{clarification_rounds}"
            evidence = client.collect_project_evidence(project_id, workflow_run_ids)
            evidence["chat_responses"] = responses
            evidence["network_history"] = client.history
            evidence["project_key"] = project_key
            evidence["model"] = model
            writer.write_json("evidence.json", evidence)
            metrics = self._metrics(evidence, clarification_rounds, retry_count, workflow_run_ids)
            writer.write_json("metrics.json", metrics)
            writer.finalize()
            evidence_path = str((writer.root / "evidence.json").relative_to(self.config.output_root.parent.parent))
            payload = {
                "state": "completed" if outcome_state != "failed" else "failed",
                "clarification_rounds": clarification_rounds,
                "retry_count": retry_count,
                "outcome_category": outcome_category,
                "outcome_state": outcome_state,
                "final_outcome": final_outcome,
                "metrics": metrics,
                "evidence_path": evidence_path,
            }
            completed = client.complete_case(experiment_id, run_id, case.case_id, payload)
            return {"case_id": case.case_id, "model": model, "run_index": run["run_index"], "state": completed.get("state"), "membership": completed}
        except (Exception, KeyboardInterrupt) as exc:
            if isinstance(exc, KeyboardInterrupt):
                self.request_stop()
            writer.write_json("failure.json", {"error_category": type(exc).__name__, "message": str(exc), "responses": responses, "network_history": client.history})
            writer.finalize()
            try:
                client.complete_case(
                    experiment_id,
                    run_id,
                    case.case_id,
                    {
                        "state": "cancelled" if self.stop_requested else "failed",
                        "clarification_rounds": clarification_rounds,
                        "retry_count": retry_count,
                        "outcome_category": type(exc).__name__,
                        "outcome_state": "cancelled" if self.stop_requested else "failed",
                        "final_outcome": str(exc),
                        "metrics": {"workflow_run_count": len(set(workflow_run_ids)), "integrity_findings": []},
                        "evidence_path": str((writer.root / "failure.json").relative_to(self.config.output_root.parent.parent)),
                    },
                )
            except BenchmarkApiError:
                pass
            return {"case_id": case.case_id, "model": model, "run_index": run["run_index"], "state": "cancelled" if self.stop_requested else "failed", "error": str(exc)}

    def _poll_workflow(self, workflow_run_id: str) -> dict[str, Any] | None:
        assert self.client is not None
        latest = None
        for _ in range(8):
            try:
                latest = self.client.get(f"/api/workflow-runs/{workflow_run_id}")
            except BenchmarkApiError:
                return latest
            if not isinstance(latest, dict) or latest.get("status") not in {"running", "queued", "pending"}:
                return latest
            time.sleep(0.05)
        return latest

    @staticmethod
    def _integrity_findings(evidence: dict[str, Any]) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        workspace = evidence.get("workspace")
        if isinstance(workspace, dict):
            integrity = workspace.get("artifact_integrity")
            if isinstance(integrity, dict) and integrity.get("missing_count", 0):
                findings.append({"kind": "missing_artifacts", "details": integrity})
        for name, value in evidence.items():
            if isinstance(value, dict) and value.get("integrity_finding"):
                findings.append({"kind": value["integrity_finding"], "source": name})
        return findings

    @classmethod
    def _metrics(
        cls,
        evidence: dict[str, Any],
        clarification_rounds: int,
        retry_count: int,
        workflow_run_ids: list[str],
    ) -> dict[str, Any]:
        attempts = evidence.get("generation_attempts")
        attempts = attempts if isinstance(attempts, list) else []
        prompt_tokens = sum(
            int(item.get("estimated_prompt_tokens") or 0)
            for item in attempts
            if isinstance(item, dict)
        )
        output_tokens = sum(
            int(item.get("estimated_output_tokens") or 0)
            for item in attempts
            if isinstance(item, dict)
        )
        provider_latency = sum(
            int(item.get("provider_latency_ms") or 0)
            for item in attempts
            if isinstance(item, dict)
        )
        events = evidence.get("workflow_events")
        event_values = [
            event
            for value in events.values()
            for event in (value if isinstance(value, list) else [])
            if isinstance(event, dict)
        ] if isinstance(events, dict) else []
        event_types = {str(event.get("event_type")) for event in event_values}
        stages = {str(event.get("stage")) for event in event_values}
        workspace = evidence.get("workspace") if isinstance(evidence.get("workspace"), dict) else {}
        revisions = evidence.get("revisions") if isinstance(evidence.get("revisions"), list) else []
        return {
            "clarification_rounds": clarification_rounds,
            "retry_count": retry_count,
            "workflow_run_count": len(set(workflow_run_ids)),
            "provider_attempt_count": len(attempts),
            "prompt_tokens": prompt_tokens,
            "output_tokens": output_tokens,
            "provider_latency_ms": provider_latency,
            "worker_reached": "worker.submitted" in event_types or "worker" in stages or "cad_execution" in stages,
            "topology_observed": "topology_validation" in stages,
            "verification_observed": any("verification" in stage for stage in stages),
            "candidate_outcome": workspace.get("current_working_revision_id") is not None or bool(revisions),
            "integrity_findings": cls._integrity_findings(evidence),
        }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the API-only Gemini consistency benchmark")
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--runs", type=int, default=2)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pilot", action="store_true")
    mode.add_argument("--full", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--experiment-id")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--case-filter", nargs="*", default=[])
    parser.add_argument("--family-filter", nargs="*", default=[])
    parser.add_argument("--specificity-filter", nargs="*", default=[])
    parser.add_argument("--output-root", type=Path, default=Path("data/debug-sessions/gemini-consistency"))
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--frontend-build-identity", default="benchmark-runner")
    parser.add_argument("--label")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    split_values = lambda values: tuple(item for value in values for item in value.split(",") if item.strip())
    config = BenchmarkRunnerConfig(
        corpus_path=args.corpus,
        models=split_values(args.models),
        runs=args.runs,
        pilot=args.pilot,
        full=args.full,
        experiment_id=args.experiment_id,
        dry_run=args.dry_run,
        resume=args.resume,
        max_concurrency=args.max_concurrency,
        base_url=args.base_url,
        timeout_seconds=args.timeout,
        output_root=args.output_root,
        case_filter=split_values(args.case_filter),
        family_filter=split_values(args.family_filter),
        specificity_filter=split_values(args.specificity_filter),
        frontend_build_identity=args.frontend_build_identity,
        label=args.label,
    )
    runner = GeminiConsistencyRunner(config)
    try:
        result = runner.run()
    except (BenchmarkApiError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
