# Deterministic Playwright Gate Implementation Plan

> **Execution mode:** Inline Execution

**Goal:** Prove the five user-testing workflows with a real deterministic FastAPI/SQLite fixture backend before observed sessions, and provide an opt-in two-case live-Gemini smoke group.

**Architecture:** A test-only backend launcher owns a disposable SQLite database, real project/workflow services, controlled AI provider, and controlled CAD worker. Playwright drives the existing frontend through Vite's API proxy without route mocks. A test-control endpoint exposes only fixture assertions needed by browser tests, never arbitrary data or production behavior. Live tests use a separate Playwright project and are skipped unless explicitly enabled.

### Task 1: Fixture backend and lifecycle assertions
**Files:** `backend/app/testing/e2e_fixture_server.py`, `backend/app/testing/e2e_fixtures.py`, `backend/tests/test_e2e_fixture_server.py`
**Intent:** Launch the real API with deterministic provider/worker scenarios and expose test-only summaries for provider calls, artifacts, workflow runs, and cleanup.
**Verification:** Write backend RED tests for scenario isolation and fixture summary, then run their expected failing state before implementation and the targeted backend suite after.

### Task 2: Playwright server projects and reusable checks
**Files:** `frontend/playwright.config.ts`, `frontend/e2e/fixtures.ts`, `frontend/e2e/workflow-gate.spec.ts`
**Intent:** Start fixture API plus frontend per deterministic test run, capture browser console/network failures, exercise actual API/persistence, inspect bundle ZIPs, and clean project state between tests.
**Verification:** Add a RED deterministic test that fails without fixture server/control endpoint, then run the focused spec.

### Task 3: Five deterministic workflows and focused failures
**Files:** `frontend/e2e/workflow-gate.spec.ts`, `frontend/e2e/failure-gate.spec.ts`
**Intent:** Cover explicit part, intent-first holder, configuration, lid revision, recoverable failure, and bounded provider/contract/worker/output/duplicate-request paths at the real API boundary.
**Verification:** Run the deterministic Playwright project serially at desktop and compact/mobile viewports; assert workflow trace, bundle manifest, output state, and no unexplained console/network errors.

### Task 4: Optional live Gemini smoke group
**Files:** `frontend/playwright.config.ts`, `frontend/e2e/live-gemini-smoke.spec.ts`, `docs/TEST_STRATEGY.md`, `README.md`
**Intent:** Add two separately selected live tests that validate provider latency, unexpected clarification, repair/progress handling, candidate review, workflow correlation, and bundles without joining normal CI.
**Verification:** Confirm skip/fail-closed behavior without explicit enablement. Run live only when the required runtime is configured; otherwise document the blocked external prerequisite.

### Task 5: Gate documentation and verification
**Files:** `docs/FRONTEND_USER_TESTING_PLAN.md`, `docs/TEST_STRATEGY.md`, `docs/CURRENT_STAGE_ROADMAP.md`
**Intent:** Make the deterministic and live gates explicit prerequisites to observed user testing.
**Verification:** Targeted backend tests, frontend build, deterministic Playwright, redaction/bundle checks, git diff check, clean worktree, and logical commit.
