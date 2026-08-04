from pathlib import Path

import pytest

from app.services.gemini_consistency.corpus import load_consistency_corpus
from app.services.gemini_consistency.runner import (
    BenchmarkRunnerConfig,
    BenchmarkRunSelection,
    EvidenceWriter,
    GeminiConsistencyRunner,
    clarification_answer_for,
    filter_cases,
    infer_clarification_category,
    stable_client_message_id,
    stable_project_key,
    validate_run_selection,
)


CORPUS_PATH = Path(__file__).parents[2] / "benchmarks" / "gemini-consistency-v1.json"


def test_clarification_answer_uses_semantic_fact_match() -> None:
    facts = {
        "dimensions": "80 mm wide, 90 mm deep, 100 mm high",
        "mounting": "four 5 mm fastener holes on a 210 by 180 mm pattern",
        "material_process": "FDM PETG",
    }

    decision = clarification_answer_for("What diameter should the mounting holes use?", facts)

    assert decision.category == "mounting"
    assert decision.answer == facts["mounting"]
    assert decision.essential is True


def test_missing_essential_fact_is_not_filled_by_a_guess() -> None:
    decision = clarification_answer_for(
        "What load or safety factor should this wall mount support?",
        {"dimensions": "200 by 160 by 30 mm"},
    )

    assert decision.category == "safety"
    assert decision.answer is None
    assert decision.essential is True


def test_nonessential_clarification_uses_recorded_proposal() -> None:
    decision = clarification_answer_for(
        "Would you prefer rounded or chamfered exterior edges?",
        {"dimensions": "80 by 80 by 30 mm"},
    )

    assert decision.category == "appearance"
    assert decision.answer == "Use a reasonable Volundr proposal and record it as a proposal."
    assert decision.essential is False


def test_clarification_category_is_semantic_and_case_insensitive() -> None:
    assert infer_clarification_category("How thick should the printed walls be?") == "wall_thickness"
    assert infer_clarification_category("What material and process should I use?") == "material_process"
    assert infer_clarification_category("Does this need a load rating?") == "safety"


def test_stable_ids_change_by_run_and_model_but_repeat_exactly() -> None:
    first = stable_project_key("experiment-1", "gemini-2.5-flash", 1, "case-001")

    assert first == stable_project_key("experiment-1", "gemini-2.5-flash", 1, "case-001")
    assert first != stable_project_key("experiment-1", "gemini-2.5-flash", 2, "case-001")
    assert first != stable_project_key("experiment-1", "gemini-2.5-pro", 1, "case-001")
    assert stable_client_message_id(first, "initial") != stable_client_message_id(first, "clarification-1")


def test_filter_cases_supports_case_family_and_specificity_filters() -> None:
    corpus = load_consistency_corpus(CORPUS_PATH)

    selected = filter_cases(
        corpus,
        case_filter=["case-001", "case-011"],
        family_filter=["holders_carriers"],
        specificity_filter=["moderate"],
    )

    assert [case.case_id for case in selected] == ["case-011"]


def test_invalid_full_run_selection_is_rejected() -> None:
    corpus = load_consistency_corpus(CORPUS_PATH)
    selection = BenchmarkRunSelection(
        models=("gemini-2.5-flash",),
        runs=2,
        pilot=False,
        full=True,
    )

    with pytest.raises(ValueError, match="at least two"):
        validate_run_selection(corpus, selection)


def test_dry_run_selection_is_pure_and_does_not_require_http_client() -> None:
    corpus = load_consistency_corpus(CORPUS_PATH)
    selection = BenchmarkRunSelection(
        models=("gemini-2.5-flash", "gemini-2.5-pro"),
        runs=2,
        pilot=True,
        full=False,
    )

    selected = validate_run_selection(corpus, selection)

    assert len(selected) == 10
    assert selected[0].case_id == "case-001"


def test_five_case_dry_run_is_limited_to_the_ollama_corpus(tmp_path) -> None:
    runner = GeminiConsistencyRunner(
        BenchmarkRunnerConfig(
            corpus_path=Path(__file__).parents[2] / "benchmarks" / "ollama-consistency-v1.json",
            models=("gemini-3.5-flash-lite", "procad:Q4_K_M"),
            five_case=True,
            pilot=False,
            full=False,
            dry_run=True,
            output_root=tmp_path / "data" / "debug-sessions" / "model-consistency",
        )
    )

    manifest = runner.run()

    assert manifest["mode"] == "five_case"
    assert manifest["case_count"] == 5
    assert manifest["case_ids"] == [f"ollama-case-{index:03d}" for index in range(1, 6)]
    assert manifest["provider_calls"] == 0


def test_five_case_run_initializes_api_client_before_execution(tmp_path, monkeypatch) -> None:
    runner = GeminiConsistencyRunner(
        BenchmarkRunnerConfig(
            corpus_path=Path(__file__).parents[2] / "benchmarks" / "ollama-consistency-v1.json",
            models=("gemini-3.5-flash-lite", "ollama-discovery"),
            five_case=True,
            pilot=False,
            full=False,
            output_root=tmp_path / "data" / "debug-sessions" / "model-consistency",
        )
    )
    monkeypatch.setattr(runner, "_run_five_case", lambda corpus: {"client_initialized": runner.client is not None})

    result = runner.run()

    assert result == {"client_initialized": True}


def test_ollama_only_five_case_never_discovers_gemini(tmp_path, monkeypatch) -> None:
    class OllamaOnlyClient(_FakeBenchmarkClient):
        def __init__(self):
            super().__init__()
            self.discovery_calls = []

        def ready(self):
            return {"status": "ready"}

        def health(self):
            return {"status": "ok"}

        def capabilities(self):
            return {"developer_tools_enabled": True}

        def discover_models(self, provider="gemini"):
            self.discovery_calls.append(provider)
            if provider != "ollama":
                raise AssertionError("Ollama-only runner attempted a Gemini discovery")
            return [
                {"name": "joshuaokolo/C3Dv0:latest", "size": 7_303_625_707, "digest": "sha-c3d"},
                {"name": "qwen2.5-coder:14b", "size": 8_988_124_298, "digest": "sha-qwen"},
            ]

        def ollama_preflight(self, model, prompt):
            return {
                "model": model,
                "context_completed": True,
                "warm_throughput_collapse": False,
                "max_size_vram": 12_000_000_000,
            }

        def create_experiment(self, payload):
            return self._experiment()

        def experiment(self, experiment_id):
            return self._experiment()

        def _experiment(self):
            models = [
                {"id": "m1", "requested_model": "joshuaokolo/C3Dv0:latest", "provider": "ollama"},
                {"id": "m2", "requested_model": "qwen2.5-coder:14b", "provider": "ollama"},
            ]
            runs = [
                {"id": f"{model['id']}-run-{index}", "model_config_id": model["id"], "run_index": index}
                for model in models
                for index in (1, 2)
            ]
            return {"id": "experiment-ollama", "models": models, "runs": runs}

        def record_model_availability(self, *args, **kwargs):
            return {}

    fake = OllamaOnlyClient()
    runner = GeminiConsistencyRunner(
        BenchmarkRunnerConfig(
            corpus_path=Path(__file__).parents[2] / "benchmarks" / "ollama-consistency-v1.json",
            models=("joshuaokolo/C3Dv0:latest", "qwen2.5-coder:14b"),
            five_case=True,
            ollama_only=True,
            pilot=False,
            full=False,
            output_root=tmp_path / "data" / "debug-sessions" / "ollama-only",
        ),
        client=fake,
    )
    monkeypatch.setattr(
        runner,
        "_run_case",
        lambda *args, **kwargs: {"state": "completed", "case_id": args[3].case_id},
    )

    result = runner.run()

    assert fake.discovery_calls == ["ollama"]
    assert result["gemini_calls"] == 0
    assert result["models"] == ["joshuaokolo/C3Dv0:latest", "qwen2.5-coder:14b"]


def test_evidence_writer_redacts_prompts_responses_source_worker_screenshot_and_network_metadata(tmp_path) -> None:
    writer = EvidenceWriter(tmp_path / "evidence")
    writer.write_json(
        "all-surfaces.json",
        {
            "rendered_prompt": "Authorization: Bearer top-secret",
            "provider_response": "AIzaSyA1234567890-secret",
            "source": "api_key = 'secret-value'\nprint('/root/private/source.py')",
            "worker_output": "database_url=postgresql://user:pass@host/db",
            "screenshots_metadata": {"path": "/tmp/private-shot.png"},
            "frontend_network_evidence": {"headers": {"authorization": "Bearer another-secret"}},
        },
    )
    writer.finalize()

    rendered = (tmp_path / "evidence" / "all-surfaces.json").read_text()
    assert "top-secret" not in rendered
    assert "1234567890-secret" not in rendered
    assert "secret-value" not in rendered
    assert "postgresql://" not in rendered
    assert "/root/private" not in rendered
    assert "Bearer another-secret" not in rendered


def test_redaction_preserves_nonsecret_token_metrics_and_limits(tmp_path) -> None:
    writer = EvidenceWriter(tmp_path / "evidence")
    writer.write_json("metrics.json", {"max_output_tokens": 8192, "prompt_tokens": 12, "output_tokens": 34})

    rendered = (tmp_path / "evidence" / "metrics.json").read_text()
    assert "8192" in rendered
    assert "12" in rendered
    assert "34" in rendered


def test_metrics_records_rate_limit_events_without_persisting_provider_error_text() -> None:
    metrics = GeminiConsistencyRunner._metrics(
        {
            "generation_attempts": [
                {"estimated_prompt_tokens": 10, "estimated_output_tokens": 5}
            ],
            "chat_responses": [
                {
                    "response": {
                        "blocked_attempt": {
                            "error_message": "Quota exceeded; please retry in 60 seconds.",
                            "failure_class": "provider_failure",
                        }
                    }
                }
            ],
            "workflow_events": {},
            "workspace": {},
        },
        clarification_rounds=0,
        retry_count=0,
        workflow_run_ids=[],
    )

    assert metrics["rate_limit_events"] == 1
    assert "error_message" not in metrics


def test_runner_applies_recorded_rate_limit_backoff_between_cases(tmp_path, monkeypatch) -> None:
    fake = _FakeBenchmarkClient()
    runner = GeminiConsistencyRunner(
        BenchmarkRunnerConfig(
            corpus_path=CORPUS_PATH,
            models=("model-a", "model-b"),
            pilot=True,
            full=False,
            case_filter=("case-001",),
            rate_limit_backoff_seconds=17.0,
            output_root=tmp_path / "data" / "debug-sessions" / "gemini-consistency",
        ),
        client=fake,
    )
    sleeps: list[float] = []
    monkeypatch.setattr("app.services.gemini_consistency.runner.time.sleep", sleeps.append)
    monkeypatch.setattr(
        runner,
        "_run_case",
        lambda *args, **kwargs: {"state": "completed", "rate_limit_events": 1},
    )

    result = runner.run()

    assert len(result["results"]) == 4
    assert sleeps == [17.0, 17.0, 17.0, 17.0]


def test_runner_cancellation_during_rate_limit_backoff_closes_active_run(tmp_path, monkeypatch) -> None:
    fake = _FakeBenchmarkClient()
    runner = GeminiConsistencyRunner(
        BenchmarkRunnerConfig(
            corpus_path=CORPUS_PATH,
            models=("model-a", "model-b"),
            pilot=True,
            full=False,
            case_filter=("case-001",),
            rate_limit_backoff_seconds=17.0,
            output_root=tmp_path / "data" / "debug-sessions" / "gemini-consistency",
        ),
        client=fake,
    )

    def interrupt(_seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("app.services.gemini_consistency.runner.time.sleep", interrupt)
    monkeypatch.setattr(
        runner,
        "_run_case",
        lambda *args, **kwargs: {"state": "completed", "rate_limit_events": 1},
    )

    result = runner.run()

    assert result["results"] == [{"state": "completed", "rate_limit_events": 1}]
    assert fake.finished_runs == [("m1-run-1", "cancelled")]
    assert fake.finished_experiments == [("experiment-1", "cancelled")]


class _FakeBenchmarkClient:
    def __init__(self) -> None:
        self.history = []
        self.chat_calls = []
        self.completed = []
        self.finished_runs = []
        self.finished_experiments = []

    def ready(self):
        return {"ready": True}

    def health(self):
        return {"status": "ok"}

    def capabilities(self):
        return {"developer_tools_enabled": True}

    def discover_models(self):
        return [{"name": "model-a"}, {"name": "model-b"}]

    def create_experiment(self, payload):
        return self._experiment()

    def experiment(self, experiment_id):
        return self._experiment()

    def _experiment(self):
        models = [{"id": "m1", "requested_model": "model-a"}, {"id": "m2", "requested_model": "model-b"}]
        runs = [
            {"id": f"{model['id']}-run-{index}", "model_config_id": model["id"], "run_index": index}
            for model in models
            for index in (1, 2)
        ]
        return {"id": "experiment-1", "models": models, "runs": runs}

    def claim_case(self, experiment_id, run_id, case, position):
        return {"state": "claimed", "project_id": f"project-{run_id}-{case.case_id}"}

    def send_chat(self, project_id, model, message, client_message_id):
        self.chat_calls.append((project_id, model, message, client_message_id))
        return {"workflow_run_id": f"workflow-{project_id}", "input_required": False, "current_stage": "requirements"}

    def get(self, path):
        if path.startswith("/api/workflow-runs/"):
            return {"status": "completed"}
        if path.endswith("/workspace"):
            return {"artifact_integrity": {"missing_count": 0}}
        if path.endswith("/workflow-runs"):
            return []
        if path.endswith("/exports") or path.endswith("/revisions") or path.endswith("/generation-attempts"):
            return []
        if path.endswith("/messages") or path.endswith("/requirements/active"):
            return []
        return {}

    def collect_project_evidence(self, project_id, workflow_run_ids):
        return {"workspace": {"artifact_integrity": {"missing_count": 0}}, "chat_responses": []}

    def complete_case(self, experiment_id, run_id, case_id, payload):
        self.completed.append((run_id, case_id, payload))
        return {"state": payload["state"]}

    def finish_experiment(self, experiment_id, state="completed"):
        self.finished_experiments.append((experiment_id, state))
        return {"state": state}

    def finish_run(self, experiment_id, run_id, state="completed"):
        self.finished_runs.append((run_id, state))
        return {"id": run_id, "state": state}

    def generate_report(self, experiment_id):
        return {"experiment_id": experiment_id, "membership_count": 4}

    def record_model_availability(self, experiment_id, requested_model, actual_model, availability_state):
        return {"requested_model": requested_model, "actual_model": actual_model, "availability_state": availability_state}


def test_runner_uses_only_api_client_and_stable_ids_for_each_paired_case(tmp_path) -> None:
    fake = _FakeBenchmarkClient()
    runner = GeminiConsistencyRunner(
        BenchmarkRunnerConfig(
            corpus_path=CORPUS_PATH,
            models=("model-a", "model-b"),
            pilot=True,
            full=False,
            case_filter=("case-001",),
            output_root=tmp_path / "data" / "debug-sessions" / "gemini-consistency",
        ),
        client=fake,
    )

    result = runner.run()

    assert len(result["results"]) == 4
    assert len(fake.chat_calls) == 4
    assert len({call[3] for call in fake.chat_calls}) == 4
    assert all(item["state"] == "completed" for item in result["results"])
