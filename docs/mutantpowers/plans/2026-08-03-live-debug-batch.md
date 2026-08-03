# Live Debug Batch Implementation Plan
> **Execution mode:** Inline Execution

**Goal:** Add a developer-only, backend-authorized live debug-batch workflow;
validate it deterministically; run two unchanged mixed-CAD live batches; and
produce local redacted evidence, comparison, self-review, and a planning-only
correction plan.

**Constraints:** Keep normal Volundr project/workflow behavior unchanged when
developer tools are disabled. Reuse existing authoritative workflow evidence.
Do not change CAD behavior, prompts, provider/model configuration, schema,
retry policy, or source between the two live batches. Do not implement the
post-batch correction plan.

## Architecture

- `Settings.developer_tools_enabled` is the single backend-authoritative flag,
  defaulting to `False`; it is not added to the minimal `.env.example`.
- `GET /api/capabilities` exposes only `{developer_tools_enabled: boolean}`.
- `DebugBatch` stores immutable run identity, lifecycle, report, redaction,
  integrity, and comparison metadata. `DebugBatchMembership` stores one
  ordered row per project and prevents reassignment.
- Project creation calls a membership helper before its existing commit. The
  helper locks/checks the one active batch and inserts membership in the same
  transaction. Existing projects and revisions never attach retroactively.
- Workflow creation consults membership only to mark existing workflow runs
  as `debug_batch` logging and to preserve the batch ID in workflow metadata;
  it does not create a parallel workflow or event stream.
- Finish is a read-only collector. It snapshots authoritative records into
  `data/debug-sessions/<batch-id>/`, redacts text and metadata, records missing
  files as integrity findings, and emits `session.json`, per-project summaries,
  `report.json`, `report.md`, `codex-review.md`, redaction and integrity
  reports. Frontend debug events are accepted only through a bounded,
  redacting batch endpoint and are stored in the same durable directory.
- Comparison is calculated only from frozen batches and marks itself
  `controlled` when all recorded identity fields match; otherwise it records
  mismatches and remains `uncontrolled`.
- The frontend adds isolated debug-batch types/API/view components and small
  integration points in the existing `main.tsx`; it does not redesign the
  workspace or expose secrets.

## Task 1: Persistence and migration

**Files:**
`backend/app/models/debug_batch.py`, `backend/app/models/__init__.py`,
`backend/alembic/versions/0028_debug_batches.py`,
`backend/tests/test_debug_batch_persistence.py`,
`backend/tests/test_debug_batch_concurrency.py`.

- [ ] RED: test lifecycle enum values, immutable identity fields, ordered
  membership, unique project membership, and database rejection of a second
  active batch.
- [ ] RED: test membership uniqueness and frozen/failed batch exclusion.
- [ ] GREEN: add the two SQLAlchemy models and migration with indexes,
  self-baseline foreign key, membership ordering, and a SQLite-compatible
  partial unique index for active/finishing batches.
- [ ] Verify migration upgrade/downgrade and model tests against a temporary
  database; record migration head `0028_debug_batches`.
- [ ] Commit: `Implement debug-batch backend and evidence lifecycle` (after
  later backend lifecycle/evidence tasks are green; migration is part of it).

## Task 2: Capability and server-side API enforcement

**Files:**
`backend/app/core/config.py`, `backend/app/api/capabilities.py`,
`backend/app/main.py`, `backend/app/api/debug_batches.py`,
`backend/app/schemas/debug_batch.py`,
`backend/tests/test_debug_batch_capability.py`.

- [ ] RED: disabled capability returns only the safe boolean and rejects start,
  finish, detail/report/evidence-download, frontend-evidence, and comparison
  APIs with a consistent forbidden response.
- [ ] RED: normal project creation and chat remain callable while disabled.
- [ ] GREEN: add the advanced setting, safe capability endpoint, dependency,
  router, and common authorization guard. Never serialize settings, provider
  credentials, headers, cookies, or policy secrets.
- [ ] Verify enabled/disabled API behavior through FastAPI tests and ensure the
  flag is absent from the minimal `.env.example`; document it only in advanced
  developer deployment guidance.

## Task 3: Lifecycle and transactional membership

**Files:**
`backend/app/services/debug_batches/service.py`,
`backend/app/services/debug_batches/identity.py`,
`backend/app/services/projects/service.py`,
`backend/app/services/projects/chat_workflow.py`,
`backend/app/api/debug_batches.py`,
`backend/tests/test_debug_batch_lifecycle.py`,
`backend/tests/test_debug_batch_membership.py`,
`backend/tests/test_project_api.py`.

- [ ] RED: start validates trimmed labels, target range, active-label
  duplicates, frozen-only baselines, and rejects concurrent starts.
- [ ] RED: project creation and membership commit/rollback together; drafts
  created while active attach, unrelated existing projects do not, and a
  frozen batch cannot accept membership.
- [ ] RED: finish is idempotent, freezes membership, records active workflows
  as incomplete, and never changes project history; failed report generation
  can be regenerated without changing membership.
- [ ] GREEN: implement start/detail/finish/list-frozen service methods and
  transactional project membership hook. Capture Git HEAD/branch when
  available, migration head, provider/model policy, prompt versions, safe
  configuration hash, and backend/frontend/worker identities without secrets.
- [ ] GREEN: mark batch workflows through existing `logging_mode` and
  `workflow_metadata_json`; do not add batch IDs to unrelated tables.
- [ ] Verify archive/delete of a member project leaves a report integrity
  finding rather than crashing and does not corrupt membership rows.

## Task 4: Evidence materialization and redaction

**Files:**
`backend/app/services/debug_batches/evidence.py`,
`backend/app/services/workflow/redaction.py` (only narrowly shared helpers if
needed), `backend/app/api/debug_batches.py`,
`backend/tests/test_debug_batch_evidence.py`,
`backend/tests/test_debug_batch_redaction.py`, `.gitignore`.

- [ ] RED: report collection is proven not to call the AI provider, CAD worker,
  workflow submission, retry, promotion, or export services.
- [ ] RED: missing authoritative artifacts become integrity findings; all
  sensitive text categories and frontend network evidence are redacted, and
  raw headers/cookies/credentials are absent.
- [ ] GREEN: collect existing messages, ledgers, plans, prompts, attempts,
  source, worker results, findings, snapshots, revisions, exports, and
  frontend telemetry into the durable batch folder, preserving correlation
  IDs and recording missing paths.
- [ ] GREEN: add bounded frontend-event ingestion using only safe endpoint
  path, IDs, status, event kind, and visible error metadata. Exclude drafts,
  keystrokes, pointers, cookies, headers, and unrelated activity.
- [ ] Verify redaction scans rendered prompts, provider responses, generated
  source, worker output, screenshot metadata, and frontend network evidence.

## Task 5: Reports, review instruction, and comparison

**Files:**
`backend/app/services/debug_batches/reports.py`,
`backend/app/services/debug_batches/comparison.py`,
`backend/app/schemas/debug_batch.py`,
`backend/tests/test_debug_batch_reports.py`,
`backend/tests/test_debug_batch_comparison.py`.

- [ ] RED: generated report contains funnel, routes, outcomes, failure
  distribution, provider behavior, user-facing behavior, repeated signatures,
  one section per project, and explicit monitor-mount safety warnings.
- [ ] RED: generated `codex-review.md` contains the required identity,
  per-project inspection, classification, repeated-signature, variability,
  regression-fixture, and no-implementation instructions.
- [ ] RED: comparison marks identity mismatch as uncontrolled and provides
  field-level mismatch details; matching frozen batches are controlled.
- [ ] GREEN: implement deterministic report and comparison builders without
  modifying authoritative records. Expose summary/detail/download paths and a
  local path/instruction suitable for copying, never shell execution.
- [ ] Verify report regeneration is stable, read-only, redacted, and safe when
  projects/artifacts are missing.

## Task 6: Frontend controls

**Files:**
`frontend/src/debugBatch.ts`, `frontend/src/debugBatchView.tsx`,
`frontend/src/main.tsx`, `frontend/src/styles.css`,
`frontend/src/debugBatch.test.ts`, `frontend/src/debugBatchView.test.ts`.

- [ ] RED: capability controls visibility; modal validates name/count; active
  banner survives refresh/navigation; drawer preserves creation order and
  high-level labels; finish confirmation/result/comparison states render only
  from API data.
- [ ] RED: frontend evidence capture sends only allowed redacted metadata and
  does not include drafts, keys, headers, cookies, or arbitrary browser data.
- [ ] GREEN: add Projects-screen action, start modal, persistent banner,
  drawer, finish dialog, completed result, comparison view, polling/refresh,
  and safe copy instruction action. Keep normal workspace unchanged when the
  capability is false.
- [ ] Verify TypeScript/build and focused Vitest tests at 1440x900 layout.
- [ ] Commit: `Add developer-only frontend controls`.

## Task 7: Deterministic Playwright and screenshots

**Files:**
`frontend/e2e/debug-batch.spec.ts`, fixture-server support under
`backend/app/testing/e2e_fixture_server.py` only where required,
`frontend/playwright.config.ts`, documentation under
`docs/LIVE_DEBUG_BATCH_PLAYWRIGHT_EVALUATION.md`.

- [ ] RED/GREEN scenarios: visibility, start, membership, drawer, finish,
  redaction, comparison, and normal deployment.
- [ ] Assert browser did not execute Codex or arbitrary shell commands.
- [ ] Capture repository-convention screenshots at 1440x900 for all seven
  deterministic states; keep generated raw screenshots outside Git unless
  existing conventions require curated evidence.
- [ ] Commit: `Add deterministic Playwright and screenshot coverage`.

## Task 8: Documentation and pre-live gate

**Files:**
`docs/LIVE_DEBUG_BATCH_IMPLEMENTATION.md`,
`docs/LIVE_DEBUG_BATCH_PLAYWRIGHT_EVALUATION.md`,
`docs/MIXED_CAD_LIVE_BATCH_01.md`,
`docs/MIXED_CAD_LIVE_BATCH_02.md`,
`docs/MIXED_CAD_LIVE_BATCH_COMPARISON.md`,
`docs/LIVE_BATCH_SELF_REVIEW.md`,
`docs/LIVE_BATCH_CORRECTION_PLAN.md`,
`docs/LIVE_BATCH_REGRESSION_CANDIDATES.md`,
`docs/WORKFLOW_OBSERVABILITY.md`, `docs/TEST_STRATEGY.md`,
`docs/FRONTEND_USER_TESTING_PLAN.md`, `docs/DOCUMENTATION_MAP.md`,
`docs/ENVIRONMENT_VARIABLES.md`, `README.md` only where authority links need
  updating.

- [ ] Document raw evidence as local/outside Git, advanced setting location,
  observed-usability distinction, read-only reporting, and planning-only
  correction plan.
- [ ] Run backend suite, frontend unit suite, production build, chat-first and
  staged Playwright, debug-batch Playwright, migration upgrade test, Compose
  config/health, API/worker readiness, and `git diff --check`.
- [ ] Commit documentation with the appropriate preceding implementation
  commit or as part of the deterministic-test checkpoint.

## Task 9: Batch 1 live evaluation

**Files:** durable external data root only plus
`docs/MIXED_CAD_LIVE_BATCH_01.md`.

- [ ] Record fixed identity/configuration snapshot before starting.
- [ ] Start `mixed-cad-live-01` through the frontend with target 5 and the
  exact specified notes.
- [ ] Submit the five exact prompts, answer only approved fact-sheet
  clarifications, enforce two clarification rounds and one retry, and preserve
  every attempt.
- [ ] Capture required batch/project screenshots and confirm at least one
  selected-revision export through the normal UI.
- [ ] Finish, verify frozen membership, redaction, integrity, reports, and
  generated Codex review instruction. Do not fix any issue discovered.
- [ ] Commit: `Record Mixed CAD Live Batch 1 evidence and review` (docs and
  references only; raw data stays outside Git).

## Task 10: Batch 2, comparison, and self-review

**Files:** durable external data root only plus
`docs/MIXED_CAD_LIVE_BATCH_02.md`,
`docs/MIXED_CAD_LIVE_BATCH_COMPARISON.md`,
`docs/LIVE_BATCH_SELF_REVIEW.md`,
`docs/LIVE_BATCH_CORRECTION_PLAN.md`,
`docs/LIVE_BATCH_REGRESSION_CANDIDATES.md`.

- [ ] Confirm no source/prompt/config/image/schema change and all identity
  hashes match Batch 1 before starting.
- [ ] Start `mixed-cad-live-02` with Batch 1 as baseline and repeat the exact
  five prompts and policy. Stop as uncontrolled if identity differs.
- [ ] Finish and verify frozen membership, then compare every matching project
  and relevant field.
- [ ] Read and follow both generated `codex-review.md` files; inspect all ten
  projects individually; classify repeated cross-family defects, same-family
  repeats, provider variability, isolated anomalies, and integrity/UI risks.
- [ ] Produce planning-only correction priorities and proposed frozen
  regression fixtures. Do not modify source, prompts, configuration, or
  product behavior during review.
- [ ] Commit: `Record Mixed CAD Live Batch 2 evidence and comparison` and
  `Record consolidated self-review and correction plan`.

## Final verification

- [ ] Confirm no active batch remains; both batches are frozen or explicitly
  uncontrolled/failed with evidence.
- [ ] Confirm reports, review files, redaction and integrity scans, normal
  project usability, batch isolation, configuration identity, focused tests,
  report tests, and `git diff --check`.
- [ ] Inspect final diff/status and report exact test results, screenshot paths,
  batch outcomes, controlled-comparison status, repeated/isolated findings,
  correction priorities, commits, and repository cleanliness. Do not claim
  formal observed usability testing occurred.
