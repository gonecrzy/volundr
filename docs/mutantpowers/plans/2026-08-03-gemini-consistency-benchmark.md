# Gemini Consistency Benchmark Implementation Plan

> **Execution mode:** Inline Execution

**Goal:** Build and execute an API-only Gemini consistency benchmark with a frozen 50-case corpus, ten-case pilot gate, paired two-model Run A/Run B experiments, resumable evidence, stage-level comparison, reports, and a three-project post-benchmark Playwright smoke check.

**Architecture:** Reuse the existing `/api/projects` and `/api/projects/{id}/chat` workflow APIs for all project operations. Add developer-gated benchmark experiment metadata and corpus-membership endpoints only for experiment orchestration, stable claims, status recording, cancellation, model discovery, and report retrieval. Persist no duplicate workflow events or provider records. Store raw benchmark evidence under the durable data root outside Git, using the existing redaction utilities.

**Primary files:**
- `benchmarks/gemini-consistency-v1.json`: frozen 50-case corpus and fact sheets.
- `backend/app/models/gemini_benchmark.py`, `backend/app/schemas/gemini_benchmark.py`, `backend/alembic/versions/0035_gemini_consistency_benchmark.py`: narrow experiment/model/run/membership persistence.
- `backend/app/services/gemini_consistency/{corpus,identity,runner,comparison,reports}.py`: validation, identity capture, API-facing orchestration helpers, paired comparison, redacted reports.
- `backend/app/api/gemini_consistency.py`: developer-gated model discovery and experiment lifecycle endpoints.
- `backend/scripts/run_gemini_consistency_benchmark.py`, `scripts/run-gemini-consistency-benchmark`: dry-run/API runner with pilot/full, resume, filters, conservative concurrency, cancellation, and local evidence.
- `backend/tests/test_gemini_consistency_*.py`: TDD coverage for corpus, identity, persistence/API, idempotency/resume, comparison, redaction, reports, and capability enforcement.
- `frontend/e2e/gemini-consistency-smoke.spec.ts`: no-corpus-replay smoke check over three supplied project IDs.
- `docs/GEMINI_CONSISTENCY_BENCHMARK.md` and result/action reports: operational contract and recorded evidence.

### Task 1: Corpus and schema contract
**Files:** corpus JSON, corpus loader/validators, schemas, tests.
**Intent:** Define all 50 stable cases, required metadata, specificity/family/scale distributions, ten-case pilot subset, semantic clarification categories, and stable hashing.
**Verification:** RED corpus-validation tests first; then loader tests prove 50 IDs, distribution counts, pilot membership, required families, stable hash, and no case exceeds five per narrow family.

### Task 2: Experiment persistence and migration
**Files:** benchmark model module, migration, model registration, persistence tests.
**Intent:** Store experiment → model config → run → corpus membership relationships, stable project keys, run state, identities, report paths, and completion state without duplicating workflow data.
**Verification:** RED transaction tests for duplicate claims, stable IDs, resume-safe lookups, run matrix, and cancellation; migration upgrade/downgrade on a clean database.

### Task 3: Provider model discovery and benchmark model override
**Files:** Gemini API provider/model policy/dependency wiring, API schemas/endpoints, tests.
**Intent:** Discover actual account models through the provider, record exact returned identities, support a server-enforced developer-only per-request benchmark model override applied consistently to all workflow stages, and preserve normal behavior without the header.
**Verification:** RED mocked discovery/override tests; verify unsupported stronger model is recorded as unavailable rather than silently substituted; capability-disabled requests reject.

### Task 4: API lifecycle and authoritative workflow integration
**Files:** benchmark API/service, normal project/chat integration only where required, tests.
**Intent:** Add experiment creation, run/membership claim, completion/status, cancellation, report generation, and result retrieval endpoints. Claim creates a project and membership atomically; subsequent operations use the existing project/chat API with stable client message IDs. Reports inspect authoritative workflow records and never invoke provider/worker services.
**Verification:** RED API tests for capability enforcement, atomic claim, duplicate prevention, idempotent completion, no duplicate messages, normal project behavior, and read-only report generation.

### Task 5: Resumable API runner
**Files:** runner CLI/script and tests.
**Intent:** Validate readiness, create/resume experiments, discover/validate models, submit frozen cases through HTTP APIs, answer up to two fact-sheet clarifications semantically, preserve attempts, poll workflow state, enforce one user-visible retry, handle cancellation, throttle to at most two active projects per model, and write redacted local evidence.
**Verification:** RED runner tests for dry-run/no network, stable identities, resume skipping complete cases, interrupted case continuation, concurrency limit, filters, pilot gate, invalid corpus/full-run refusal, cancellation, and token accounting.

### Task 6: Paired comparison and reports
**Files:** comparison/report services, result docs, tests.
**Intent:** Compare every paired stage field per model using identical/semantic/variable/materially inconsistent/one-sided/both-failed classes; calculate separate structure, requirements, planning, execution, and outcome scores; report model/family/specificity/scale breakdowns, latency/tokens, normalized failure signatures, limitations, regression candidates, and exactly one next direction.
**Verification:** RED comparison/report tests with controlled fixtures; ensure raw response files are redacted and never committed, and report generation performs no provider or worker calls.

### Task 7: Dry-run, pilot, full paired benchmark, and smoke check
**Files:** local evidence root, reports, smoke spec.
**Intent:** Run dry-run validation, then ten cases twice per selected model and pass the pilot gate. Freeze the corpus and run 50 cases twice per model without code/config/prompt/model changes. Run a maximum-three-project Playwright smoke check against recorded project IDs only.
**Verification:** Preserve experiment IDs and raw evidence paths outside Git; verify all memberships correlate, no duplicates exist, resumes are safe, identities match paired runs, reports are complete, smoke check matches API evidence, and repository diff is clean.

### Commit checkpoints
1. Corpus/schema contract.
2. Persistence and model override.
3. API lifecycle and runner.
4. Comparison/reporting and tests.
5. Recorded pilot/full results and documentation.

### Rollback boundary
Each checkpoint is independently revertible. Raw evidence remains outside Git. No product CAD generation or prompt correction is implemented from benchmark findings during this goal.

