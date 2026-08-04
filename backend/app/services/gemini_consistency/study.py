"""API-only runner for the controlled Gemini Flash Lite before/after study."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from app.services.gemini_consistency.corpus import (
    FLASH_LITE_STUDY_CASE_IDS,
    ConsistencyCase,
    ConsistencyCorpus,
    load_flash_lite_study_corpus,
)
from app.services.gemini_consistency.runner import (
    BenchmarkApiClient,
    BenchmarkApiError,
    EvidenceWriter,
    PROPOSAL_ANSWER,
    TERMINAL_MEMBERSHIP_STATES,
    _questions_from_spec,
    clarification_answer_for,
    stable_client_message_id,
)


FLASH_LITE_MODEL = "gemini-3.5-flash-lite"
STUDY_ID = "gemini-flash-lite-study-01"
STUDY_ROUNDS = ("baseline", "validation")
REPETITIONS = 3
QUOTA_STATUS_CODES = {408, 429, 502, 503, 504, 599}


@dataclass(frozen=True)
class FlashLiteStudyConfig:
    corpus_path: Path
    study_id: str = STUDY_ID
    model: str = FLASH_LITE_MODEL
    rounds: tuple[str, ...] = STUDY_ROUNDS
    repetitions: int = REPETITIONS
    dry_run: bool = False
    resume: bool = False
    base_url: str = "http://127.0.0.1:8000"
    timeout_seconds: float = 60.0
    output_root: Path = Path("data/debug-sessions/gemini-flash-lite-study")
    frontend_build_identity: str = "study-runner"
    rate_limit_backoff_seconds: float = 60.0


def validate_flash_lite_study_config(config: FlashLiteStudyConfig) -> ConsistencyCorpus:
    if config.model != FLASH_LITE_MODEL:
        raise ValueError(f"study model must be {FLASH_LITE_MODEL}")
    if config.repetitions != REPETITIONS:
        raise ValueError("study requires exactly three repetitions per round")
    if not config.rounds or any(round_name not in STUDY_ROUNDS for round_name in config.rounds) or len(set(config.rounds)) != len(config.rounds):
        raise ValueError("study rounds must be a non-empty ordered subset of baseline and validation")
    if tuple(STUDY_ROUNDS[: len(config.rounds)]) != config.rounds and config.rounds != ("validation",):
        raise ValueError("study rounds must preserve baseline before validation")
    corpus = load_flash_lite_study_corpus(config.corpus_path)
    if corpus.case_ids != FLASH_LITE_STUDY_CASE_IDS:
        raise ValueError("study corpus case IDs are not frozen")
    return corpus


def _git(*args: str) -> str:
    try:
        result = subprocess.run(["git", *args], check=False, capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def repository_identity() -> dict[str, Any]:
    divergence = _git("rev-list", "--left-right", "--count", "origin/main...HEAD")
    ahead, behind = (divergence.split() + ["unknown", "unknown"])[:2]
    return {
        "head": _git("rev-parse", "HEAD"),
        "branch": _git("branch", "--show-current"),
        "origin_main": _git("rev-parse", "--verify", "origin/main"),
        "divergence": {"ahead": ahead, "behind": behind},
        "origin": _git("remote", "get-url", "origin"),
    }


def _study_project_key(study_id: str, round_name: str, repetition: int, case_id: str) -> str:
    digest = hashlib.sha256(f"{study_id}:{round_name}:{repetition}:{case_id}".encode()).hexdigest()[:20]
    return f"gemini-flash-lite-study:{study_id}:{round_name}:{repetition}:{case_id}:{digest}"


def classify_provider_failure(error: BenchmarkApiError) -> str:
    if error.status_code == 429:
        return "provider_quota_exhausted"
    if error.status_code in {502, 503, 504}:
        return "provider_transport_failure"
    if error.status_code == 408:
        return "provider_timeout"
    if error.status_code == 599:
        return "provider_transport_failure"
    return "provider_content_failure"


class FlashLiteStudyRunner:
    def __init__(self, config: FlashLiteStudyConfig, *, client: BenchmarkApiClient | None = None) -> None:
        self.config = config
        self.client = client
        self.stop_requested = False

    def dry_run_manifest(self, corpus: ConsistencyCorpus) -> dict[str, Any]:
        operations = len(corpus.cases) * len(self.config.rounds) * self.config.repetitions
        return {
            "study_id": self.config.study_id,
            "model": self.config.model,
            "corpus_version": corpus.version,
            "corpus_hash": corpus.content_hash,
            "case_ids": list(corpus.case_ids),
            "case_count": len(corpus.cases),
            "rounds": list(self.config.rounds),
            "repetitions_per_round": self.config.repetitions,
            "project_operations": operations,
            "provider_calls": 0,
            "mode": "study",
        }

    def run(self) -> dict[str, Any]:
        corpus = validate_flash_lite_study_config(self.config)
        if self.config.dry_run:
            return self.dry_run_manifest(corpus)
        self.client = self.client or BenchmarkApiClient(self.config.base_url, timeout_seconds=self.config.timeout_seconds)
        root = self.config.output_root / self.config.study_id
        writer = EvidenceWriter(root, data_root=self.config.output_root)
        study_document = {
            "fixture_version": "gemini-flash-lite-study-v1",
            "study_id": self.config.study_id,
            "label": "Gemini Flash Lite behavior study",
            "model_policy": {"requested_model": self.config.model, "actual_model_must_match": True},
            "corpus_version": corpus.version,
            "corpus_hash": corpus.content_hash,
            "repository": repository_identity(),
            "rounds": list(self.config.rounds),
            "repetitions": self.config.repetitions,
            "project_operations_expected": 60,
            "provider_calls_additional": True,
            "evidence_label": "before-and-after product correction study",
        }
        writer.write_json("study.json", study_document)
        writer.write_json("corpus.json", corpus.to_document())
        identities: dict[str, Any] = {"repository": repository_identity(), "rounds": {}}
        try:
            self._preflight(self.client, corpus, root, writer)
            for round_name in self.config.rounds:
                if self.stop_requested:
                    break
                experiment = self._create_round(self.client, corpus, round_name)
                experiment_id = str(experiment["id"])
                identities["rounds"][round_name] = {
                    "experiment_id": experiment_id,
                    "identity": experiment,
                }
                writer.write_json(f"{round_name}/round.json", experiment)
                for repetition in range(1, self.config.repetitions + 1):
                    self._run_repetition(self.client, experiment, corpus, round_name, repetition, root)
                    if self.stop_requested:
                        break
                if not self.stop_requested:
                    self.client.finish_experiment(experiment_id, "completed")
        finally:
            writer.write_json("identities.json", identities)
            writer.finalize()
            self.client.close()
        return {**study_document, "state": "stopped" if self.stop_requested else "completed", "identities": identities}

    def _preflight(self, client: BenchmarkApiClient, corpus: ConsistencyCorpus, root: Path, writer: EvidenceWriter) -> None:
        readiness = {"ready": client.ready(), "health": client.health(), "capabilities": client.capabilities()}
        models = client.discover_models()
        readiness["models"] = models
        matches = [item for item in models if str(item.get("name", "")).removeprefix("models/") == self.config.model]
        if not matches:
            raise ValueError(f"configured model {self.config.model} is unavailable")
        readiness["configured_model"] = matches[0]
        writer.write_json("readiness/preflight.json", readiness)

    def _create_round(self, client: BenchmarkApiClient, corpus: ConsistencyCorpus, round_name: str) -> dict[str, Any]:
        return client.create_experiment(
            {
                "label": f"Gemini Flash Lite {round_name} {self.config.study_id}",
                "corpus_version": corpus.version,
                "corpus_hash": corpus.content_hash,
                "mode": "study",
                "models": [self.config.model],
                "runs": self.config.repetitions,
                "model_settings": {
                    "study_id": self.config.study_id,
                    "round": round_name,
                    "model": self.config.model,
                    "temperature": 0.2,
                    "thinking_level": "minimal",
                    "max_output_tokens": 8192,
                    "provider_timeout_seconds": 120,
                    "transport_retry_limit": 2,
                    "clarification_round_limit": 2,
                    "provider": "gemini_api",
                },
                "frontend_build_identity": self.config.frontend_build_identity,
            }
        )

    def _run_repetition(
        self,
        client: BenchmarkApiClient,
        experiment: dict[str, Any],
        corpus: ConsistencyCorpus,
        round_name: str,
        repetition: int,
        root: Path,
    ) -> None:
        repetition_writer = EvidenceWriter(
            root / round_name / f"repetition-{repetition:02d}",
            data_root=self.config.output_root,
        )
        try:
            readiness = client.provider_readiness(
                study_id=self.config.study_id,
                round_name=round_name,
                repetition=repetition,
                model=self.config.model,
            )
            repetition_writer.write_json("readiness.json", readiness)
            if readiness.get("actual_model") and readiness["actual_model"] != self.config.model:
                raise ValueError("provider readiness returned a different actual model")
        except BenchmarkApiError as exc:
            repetition_writer.write_json(
                "readiness-failure.json",
                {"category": classify_provider_failure(exc), "status_code": exc.status_code, "message": str(exc)},
            )
            repetition_writer.finalize()
            self.stop_requested = True
            return
        repetition_writer.finalize()
        run = next(
            item for item in experiment.get("runs", [])
            if isinstance(item, dict) and int(item.get("run_index", 0)) == repetition
        )
        for position, case in enumerate(corpus.cases):
            if self.stop_requested:
                break
            self._run_case(client, experiment, run, case, position, round_name, repetition, root)
        if not self.stop_requested:
            client.finish_run(str(experiment["id"]), str(run["id"]), "completed")

    def _run_case(
        self,
        client: BenchmarkApiClient,
        experiment: dict[str, Any],
        run: dict[str, Any],
        case: ConsistencyCase,
        position: int,
        round_name: str,
        repetition: int,
        root: Path,
    ) -> dict[str, Any]:
        experiment_id = str(experiment["id"])
        membership = client.claim_case(experiment_id, str(run["id"]), case, position)
        if membership.get("state") in TERMINAL_MEMBERSHIP_STATES:
            return membership
        project_id = str(membership.get("project_id"))
        project_key = _study_project_key(self.config.study_id, round_name, repetition, case.case_id)
        writer = EvidenceWriter(
            root / round_name / f"repetition-{repetition:02d}" / "projects" / case.case_id / project_id,
            data_root=self.config.output_root,
        )
        writer.write_json("project.json", {"study_id": self.config.study_id, "round": round_name, "repetition": repetition, "case_id": case.case_id, "project_id": project_id, "project_key": project_key})
        responses: list[dict[str, Any]] = []
        workflow_ids: list[str] = []
        clarification_rounds = 0
        current_message = case.initial_prompt
        phase = "initial"
        outcome_category = "completed"
        outcome_state = "unknown"
        final_outcome: Any = None
        retry_count = 0
        try:
            while True:
                try:
                    response = client.send_chat(
                        project_id,
                        self.config.model,
                        current_message,
                        stable_client_message_id(project_key, phase),
                        provider="gemini_api",
                        study_context={
                            "study_id": self.config.study_id,
                            "round": round_name,
                            "repetition": repetition,
                            "case_id": case.case_id,
                        },
                    )
                except BenchmarkApiError as exc:
                    responses.append({"phase": phase, "error": {"status_code": exc.status_code, "path": exc.path, "category": classify_provider_failure(exc)}})
                    if exc.status_code in QUOTA_STATUS_CODES:
                        outcome_category = classify_provider_failure(exc)
                        outcome_state = "incomplete"
                        self.stop_requested = exc.status_code == 429
                        break
                    if retry_count >= 1:
                        raise
                    retry_count += 1
                    continue
                responses.append({"phase": phase, "response": response})
                workflow_id = response.get("workflow_run_id")
                if workflow_id:
                    workflow_ids.append(str(workflow_id))
                    self._poll(client, str(workflow_id))
                if not response.get("input_required"):
                    outcome_state = str(response.get("current_stage") or "completed")
                    final_outcome = response.get("assistant_message")
                    break
                if clarification_rounds >= 2:
                    outcome_category = "clarification_limit"
                    outcome_state = "failed"
                    final_outcome = "Clarification limit reached without a final workflow response."
                    break
                specification = client.get(f"/api/projects/{project_id}/design-specification")
                questions = _questions_from_spec(specification, str(response.get("assistant_message") or ""))
                decisions = [clarification_answer_for(question, case.fact_sheet) for question in questions]
                missing = next((item for item in decisions if item.essential and item.answer is None), None)
                if missing is not None:
                    outcome_category = "unanswered_essential_clarification"
                    outcome_state = "failed"
                    final_outcome = f"No fact-sheet answer was available for essential {missing.category} clarification."
                    break
                current_message = "\n".join(f"{item.category}: {item.answer}" for item in decisions if item.answer is not None) or PROPOSAL_ANSWER
                clarification_rounds += 1
                phase = f"clarification-{clarification_rounds}"
            evidence = client.collect_project_evidence(project_id, workflow_ids)
            observed_models = {
                str(item.get("model"))
                for item in evidence.get("generation_attempts", [])
                if isinstance(item, dict) and item.get("model")
            }
            if observed_models and observed_models != {self.config.model}:
                outcome_category = "provider_model_mismatch"
                outcome_state = "failed"
                final_outcome = f"Provider returned model identity {sorted(observed_models)!r}; expected {self.config.model}."
                self.stop_requested = True
            evidence.update({"study_id": self.config.study_id, "round": round_name, "repetition": repetition, "case_id": case.case_id, "project_id": project_id, "chat_responses": responses, "project_key": project_key, "model": self.config.model, "provider": "gemini_api", "outcome_category": outcome_category, "outcome_state": outcome_state, "final_outcome": final_outcome})
            writer.write_json("conversation.json", {"chat_responses": responses, "workflow_ids": workflow_ids})
            writer.write_json("evidence.json", evidence)
            writer.write_json("summary.json", {"outcome_category": outcome_category, "outcome_state": outcome_state, "final_outcome": final_outcome, "provider_call_count": sum(int(item.get("provider_call_count") or 0) for item in evidence.get("generation_attempts", []) if isinstance(item, dict))})
            writer.finalize()
            client.complete_case(experiment_id, str(run["id"]), case.case_id, {"state": "incomplete" if outcome_state == "incomplete" else ("failed" if outcome_state == "failed" else "completed"), "clarification_rounds": clarification_rounds, "retry_count": retry_count, "outcome_category": outcome_category, "outcome_state": outcome_state, "final_outcome": str(final_outcome) if final_outcome is not None else None, "metrics": {"provider_call_count": sum(int(item.get("provider_call_count") or 0) for item in evidence.get("generation_attempts", []) if isinstance(item, dict)), "provider_failure": outcome_category.startswith("provider_")}, "evidence_path": str((writer.root / "evidence.json").relative_to(self.config.output_root.parent.parent))})
            return evidence
        except Exception as exc:
            writer.write_json("failure.json", {"error_category": type(exc).__name__, "message": str(exc), "responses": responses})
            writer.finalize()
            client.complete_case(experiment_id, str(run["id"]), case.case_id, {"state": "cancelled" if self.stop_requested else "failed", "clarification_rounds": clarification_rounds, "retry_count": retry_count, "outcome_category": type(exc).__name__, "outcome_state": "failed", "final_outcome": str(exc), "metrics": {}, "evidence_path": str((writer.root / "failure.json").relative_to(self.config.output_root.parent.parent))})
            if isinstance(exc, BenchmarkApiError) and exc.status_code in QUOTA_STATUS_CODES:
                self.stop_requested = True
            return {"case_id": case.case_id, "error": str(exc)}

    @staticmethod
    def _poll(client: BenchmarkApiClient, workflow_id: str) -> None:
        for _ in range(8):
            latest = client.get(f"/api/workflow-runs/{workflow_id}")
            if not isinstance(latest, dict) or latest.get("status") not in {"running", "queued", "pending"}:
                return
            time.sleep(0.05)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Gemini Flash Lite behavior study")
    parser.add_argument("--corpus", type=Path, default=Path("benchmarks/gemini-flash-lite-study-v1.json"))
    parser.add_argument("--study-id", default=STUDY_ID)
    parser.add_argument("--round", dest="rounds", choices=STUDY_ROUNDS, action="append")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--output-root", type=Path, default=Path("data/debug-sessions/gemini-flash-lite-study"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    config = FlashLiteStudyConfig(
        corpus_path=args.corpus,
        study_id=args.study_id,
        rounds=tuple(args.rounds or STUDY_ROUNDS),
        dry_run=args.dry_run,
        resume=args.resume,
        base_url=args.base_url,
        timeout_seconds=args.timeout,
        output_root=args.output_root,
    )
    print(json.dumps(FlashLiteStudyRunner(config).run(), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
