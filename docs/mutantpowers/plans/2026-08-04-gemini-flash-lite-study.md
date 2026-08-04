# Gemini Flash Lite Behavior Study Implementation Plan
> **Execution mode:** Inline Execution

**Goal:** Build a quota-efficient, API-only Gemini Flash Lite study with ten frozen cases, three baseline repetitions, one evidence-backed offline cleanup/replay round, three validation repetitions, immutable provider-call evidence, and stage-level reporting.

**Architecture:** Extend the existing Gemini consistency benchmark API with a `study` mode that permits one model and three repetitions. Propagate a study context through the normal chat API into the Gemini API provider. The provider writes immutable redacted raw-call envelopes immediately; the runner later writes one canonical record per call, enriched with parsed/normalized lifecycle and downstream evidence. Private evidence stays under `data/debug-sessions/gemini-flash-lite-study/`; only minimized fixtures and documentation are committed.

### Task 1: Add the study contract and frozen corpus
**Files:** `backend/app/schemas/gemini_benchmark.py`, `backend/app/services/gemini_consistency/corpus.py`, `benchmarks/gemini-flash-lite-study-v1.json`, `backend/tests/test_gemini_flash_lite_study_corpus.py`
**Intent:** Add a strict study-mode payload with exactly three runs, exactly one requested Gemini model, and a corpus validator for the ten attachment-defined cases. Preserve the existing two-model benchmark validation unchanged.
**Verification:** Run the corpus and schema tests; assert the case IDs, prompts, fact sheets, hash stability, and exact count.

### Task 2: Add immutable provider-call capture
**Files:** `backend/app/services/gemini_consistency/interaction_capture.py`, `backend/app/api/dependencies.py`, `backend/app/api/projects.py`, `backend/app/services/ai/gemini_api.py`, `backend/tests/test_gemini_interaction_capture.py`, `backend/tests/test_gemini_api_provider.py`
**Intent:** Accept study context headers only for developer-gated runs, record every Gemini HTTP attempt (including rate-limit, transport, timeout, and content failures) as an immutable redacted JSON envelope, and carry request/model/settings/metadata without credentials. Leave normal workflows unchanged when no study context is present.
**Verification:** Test successful calls, retries, quota failures, redaction, file immutability, and absence of capture in ordinary API calls.

### Task 3: Add study persistence and API runner controls
**Files:** `backend/app/schemas/gemini_benchmark.py`, `backend/app/services/gemini_consistency/service.py`, `backend/app/services/gemini_consistency/runner.py`, `backend/tests/test_gemini_flash_lite_study_api.py`
**Intent:** Represent baseline and validation rounds with the existing experiment/run/membership hierarchy while storing study identity, branch/origin/divergence, round, repetition, and corpus/configuration identities in the existing JSON identity fields. Do not add a migration when the current tables already express the required relationships. Add atomic resume-safe claiming and exact duplicate prevention.
**Verification:** Run migration tests, API idempotency tests, and a dry-run manifest proving 60 project operations and zero provider calls.

### Task 4: Add canonical evidence, analysis, and offline replay
**Files:** `backend/app/services/gemini_consistency/study.py`, `backend/app/services/gemini_consistency/replay.py`, `backend/app/services/gemini_consistency/reporting.py`, `backend/scripts/run_gemini_study.py`, `scripts/run-gemini-study`, `backend/tests/test_gemini_flash_lite_replay.py`, `backend/tests/test_gemini_flash_lite_reporting.py`
**Intent:** Capture every provider call in the requested hierarchy; preserve raw, parsed, normalized, repair, contract, downstream, redaction, and identity fields; classify quota/infrastructure failures separately; support replay from raw/parsed/normalized/source/worker with an immediate `--offline-required` provider-call guard. Generate baseline comparison, cleanup selection, replay comparison, validation, consistency, and before/after reports.
**Verification:** Replay representative fixtures from every supported start point and assert no provider construction/call; verify unchanged raw hashes and provenance fields.

### Task 5: Add minimized replay fixtures and documentation
**Files:** `tests/fixtures/gemini-live-responses/*.json`, `docs/GEMINI_FLASH_LITE_*.md`, `docs/TEST_STRATEGY.md`, `docs/WORKFLOW_OBSERVABILITY.md`, `docs/LIVE_BATCH_CORRECTION_PLAN.md`, `docs/CURRENT_STAGE_ROADMAP.md`, `docs/DOCUMENTATION_MAP.md`, `README.md`
**Intent:** Commit only redacted representative fixtures and the required study/replay/cleanup/validation documentation. Do not commit private live evidence or rewrite historical reports.
**Verification:** Run fixture minimization/redaction checks and documentation link/format checks.

### Task 6: Execute and freeze the study
**Files:** `data/debug-sessions/gemini-flash-lite-study/<study-id>/` (ignored private evidence)
**Intent:** Record the initial identity, run provider readiness plus one minimal quota call before each repetition, run baseline three times without code/prompt/config changes, select at most three generic corrections, implement and replay offline, then run validation three times without changes. Use Playwright only for the post-round representative smoke checks.
**Verification:** Backend, frontend/build, replay offline guard, Playwright smoke, Compose, redaction, diff, and clean-worktree checks. If provider quota/infrastructure blocks a round, preserve completed operations and report the exact terminal classification without counting it as CAD quality.

Rollback points are the verified commits requested by the study: capture, replay, corpus, baseline records, cleanup analysis, cleanup implementation, replay comparison, validation records, before/after comparison, and next-direction recommendation. No destructive reset or discard is permitted.
