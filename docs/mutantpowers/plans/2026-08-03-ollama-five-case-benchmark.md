# Ollama Five-Case Benchmark Implementation Plan
> **Execution mode:** Inline Execution

**Goal:** Extend the existing API-driven benchmark harness to run a fresh five-case, two-run Gemini Flash Lite anchor and every admitted exact remote Ollama model, then generate controlled within-model and cross-model reports without changing CAD product behavior.

**Scope boundary:** Do not run the historical ten/fifty-case corpus, do not use Playwright for submission, do not tune prompts or retry policy, and do not implement CAD/product corrections. Historical Gemini runs remain `historical_noncontrolled_reference`.

## Architecture

- Keep `GeminiConsistencyService`, the public benchmark API, normal project/chat/workflow APIs, and existing evidence/redaction infrastructure.
- Add an Ollama transport with safe structured metadata, `/api/tags`, `/api/show`, `/api/ps`, `/api/chat` or `/api/generate`, request settings, timeout/cancellation, and optional auth read only from the existing secret mechanism.
- Generalize benchmark model configuration and runner identity to include provider, requested model, actual model, digest, run settings, and resource profile without exposing credentials.
- Add a separate immutable five-case corpus with IDs `ollama-case-001` through `ollama-case-005`; formal selection rejects the older Gemini corpus and any selection other than exactly five cases and two runs.
- Add a developer-only provider/model benchmark override on the server; both provider and model are validated, and ordinary project workflows remain unchanged when the capability is disabled.
- Run one active operation at a time. Resource admission precedes formal cases; only exact installed models are admitted. Native diagnostic mode, if implemented, is isolated and excluded from primary ranking.
- Materialize raw evidence under `data/debug-sessions/model-consistency/<experiment-id>/`, outside Git, redacted across prompts, responses, source, worker output, screenshots metadata, and frontend network evidence.

## Tasks

### 1. Baseline and corpus freeze
**Files:** `benchmarks/ollama-consistency-v1.json`, `backend/app/services/gemini_consistency/corpus.py`, `backend/app/services/gemini_consistency/runner.py`, tests under `backend/tests/`.

- Add the exact five frozen cases and fact sheets from the revised goal.
- Add a corpus loader/hash and selection mode that accepts only five cases for this benchmark.
- Write tests first for exact IDs, order, prompts, fact sheets, corpus hash stability, and rejection of ten/fifty-case selections.
- Verify RED, implement, verify targeted tests, and commit the corpus/selection rollback point.

### 2. Ollama provider adapter
**Files:** `backend/app/services/ai/ollama.py`, `backend/app/services/ai/provider.py`, `backend/app/core/config.py`, `backend/app/api/dependencies.py`, tests under `backend/tests/`.

- Extend the adapter with exact model selection, context length, temperature, top-p, top-k, seed, maximum output tokens, timeout, keep-alive, optional secret-backed auth, and structured JSON-schema output when supported.
- Preserve provider call timing, token accounting, returned model identity, digest, and safe settings in result metadata.
- Add discovery methods for `/api/tags` and `/api/show`, resource polling for `/api/ps`, and safe error/timeout/cancellation behavior.
- Write failing adapter tests for discovery fields, digest/quantization/size capture, settings, structured output, token/timing accounting, timeout, cancellation, and header redaction before implementation.
- Verify targeted tests and commit.

### 3. Benchmark persistence/API generalization
**Files:** `backend/app/models/gemini_benchmark.py`, new Alembic migration, `backend/app/schemas/gemini_benchmark.py`, `backend/app/api/gemini_consistency.py`, `backend/app/services/gemini_consistency/service.py`, `backend/app/services/gemini_consistency/reporting.py`, tests under `backend/tests/`.

- Store provider, requested/actual model, digest, quantization, model size, settings, resource admission, and safe timing/token metadata.
- Add discovery/preflight endpoints or service calls behind the existing developer capability; keep reports read-only and API-only.
- Enforce provider/model overrides server-side; no client credentials and no arbitrary shell execution.
- Preserve idempotent claim/completion/finish/report behavior and historical run exclusion.
- Add migration and API tests for capability enforcement, exact model identity, no credentials in responses/evidence, and normal workflows unchanged.
- Verify migration and targeted tests, then commit.

### 4. Runner and resource admission
**Files:** `backend/app/services/gemini_consistency/runner.py`, `backend/scripts/run_gemini_consistency_benchmark.py`, `scripts/run-gemini-consistency-benchmark`, tests under `backend/tests/`.

- Add provider-aware stable IDs, `--provider`, Ollama base URL/model filters, preflight, exact-model admission, one-generation concurrency, model unload/keep-alive behavior where supported, resumability, cancellation, and safe evidence paths.
- Run Gemini Flash Lite as two fresh complete runs; do not require or substitute a stronger Gemini model.
- Run every admitted Ollama model Run A then Run B, with seeds 101 and 202 and identical settings otherwise.
- Record resource classes `preferred_gpu_resident`, `allowed_under_16gb`, `cpu_heavy`, and `rejected`, including reasons.
- Add failing runner tests for no duplicate projects/messages, resume, one active generation, resource classification, Gemini anchor completion, unavailable stronger model exclusion, and historical evidence exclusion.
- Verify dry-run, deterministic tests, and commit.

### 5. Paired comparison and reports
**Files:** `backend/app/services/gemini_consistency/comparison.py`, `backend/app/services/gemini_consistency/reporting.py`, new docs listed in the goal, tests under `backend/tests/`.

- Calculate within-model Run A/Run B consistency across requirements, route, slots, source, worker, topology, verification, candidate state, blocker, latency, and resources.
- Compare cross-model quality by verified requirements, valid geometry, topology, paired consistency, source contract, artifacts, repair success, candidate outcome, and resource profile—not JSON or speed alone.
- Generate all six required reports and label historical evidence exactly `historical_noncontrolled_reference`.
- Ensure report generation makes no provider/worker calls and missing artifacts become integrity findings.
- Verify controlled/uncontrolled identity rules, redaction scans, and report regeneration, then commit.

### 6. Runtime execution and smoke verification
**Files:** `docs/*` reports, `data/debug-sessions/model-consistency/<experiment-id>/` (ignored raw evidence), no product source changes.

- Verify duplicate-message correction is deployed and run the five-case dry-run and deterministic adapter tests.
- Run fresh Gemini Flash Lite Run A and Run B; freeze evidence.
- Discover and preflight each exact remote Ollama model, transparently exclude rejected/unavailable models, then run each admitted model A/B sequentially.
- Generate paired and cross-model reports, select exactly one next direction, and do not implement it.
- Use Playwright only after API completion to inspect at most three projects: successful/furthest-progressed, blocked-before-worker, blocked-after-worker. Confirm no duplicate initial messages and report/UI agreement.
- Run final backend/frontend tests, build, migration verification, diff check, and clean-repository verification. Commit reports and recommendation separately from code.

## Verification commands

- `rtk bash -lc 'cd backend && .venv/bin/pytest -q <targeted tests>'`
- `rtk bash -lc 'cd backend && .venv/bin/pytest -q'`
- `rtk bash -lc 'cd frontend && npm test'`
- `rtk bash -lc 'cd frontend && npm run build'`
- `rtk git diff --check`
- `rtk git status --short --branch`
- `rtk ./scripts/run-gemini-consistency-benchmark --dry-run ...` with the five-case corpus only.

## Rollback and commit points

Commit only after the corresponding RED/GREEN targeted verification: corpus, provider, persistence/API, runner, comparison/reporting, then each fresh result/report set. Never commit raw evidence, credentials, generated CAD source, or artifacts.
