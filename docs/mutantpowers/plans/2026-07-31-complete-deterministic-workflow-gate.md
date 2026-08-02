# Complete Deterministic Workflow Gate Implementation Plan

> **Execution mode:** Inline Execution

**Goal:** Complete the deterministic browser gate for configuration, component revision, and recoverable blocked candidates using the real project router, persistence, observability, and debug bundles.

**Architecture:** Keep all fixture-specific source, provider, runner, seeded-state, and bounded inspection code under `backend/app/testing`. Browser tests drive Vite through the normal API proxy. Product code changes are limited to regressions first demonstrated by those tests.

### Task 1: Scenario fixture capabilities
**Files:** `backend/app/testing/e2e_fixture_server.py`, `backend/tests/test_e2e_fixture_server.py`
**Intent:** Add controlled organizer, enclosure revision, and blocked-output fixture state plus bounded summaries for source/parameter hashes, artifacts, diagnoses, and provider/worker calls.
**Verification:** Add backend RED tests for each fixture state and run the targeted suite before and after implementation.

### Task 2: Workflow Playwright modules
**Files:** `frontend/e2e/fixtures/workflow.ts`, `frontend/e2e/workflows/configure-organizer.spec.ts`, `frontend/e2e/workflows/revise-enclosure-lid.spec.ts`, `frontend/e2e/workflows/recoverable-blocked-part.spec.ts`
**Intent:** Assert each remaining primary workflow through the real frontend and API, including current/new state, acceptance, export, trace events, and diagnostic bundle download.
**Verification:** Run each spec serially against a fresh fixture server.

### Task 3: Focused failures and responsiveness
**Files:** `frontend/e2e/failures/workflow-failures.spec.ts`, `frontend/e2e/responsive/workflow-responsive.spec.ts`, `frontend/playwright.config.ts`
**Intent:** Add bounded failure-state coverage and desktop/mobile review checks without changing normal UI behavior.
**Verification:** Run the deterministic suite at the required viewports and retain screenshots on failure.

### Task 4: Opt-in live smoke and documentation
**Files:** `frontend/e2e/live/live-gemini.spec.ts`, `docs/DETERMINISTIC_USER_WORKFLOW_GATE.md`, `docs/FRONTEND_USER_TESTING_PLAN.md`, `docs/TEST_STRATEGY.md`, `docs/WORKFLOW_OBSERVABILITY.md`, `docs/CURRENT_STAGE_ROADMAP.md`, `docs/DOCUMENTATION_MAP.md`
**Intent:** Keep live Gemini browser smoke explicitly gated while documenting deterministic completion criteria and current limitations.
**Verification:** Verify the live suite skips without `VOLUNDR_RUN_LIVE_E2E=true`; run only when credentials are explicitly supplied.

### Task 5: Final gate
**Files:** all changed files
**Intent:** Verify the full suite, build, fixture creation, diagnostic ZIP content, clean worktree, and commit logical stages.
**Verification:** Backend, Vitest, production build, deterministic Playwright, and git checks.
