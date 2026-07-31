# Frontend User-Testing Workflow Implementation Plan

> **Execution mode:** Inline Execution

**Goal:** Reframe the existing staged CAD workflow as a user-facing design assistant journey, while retaining observability and technical evidence as secondary details.

**Architecture:** Keep `frontend/src/main.tsx` as the integration point and extract deterministic presentation helpers into small view modules. Existing backend lifecycle calls, revision APIs, and workflow correlation remain unchanged except for telemetry additions and any narrowly required read-only workflow APIs.

### Task 1: Audit and presentation vocabulary
**Files:** `docs/FRONTEND_WORKFLOW_AUDIT.md`, `frontend/src/terminology.ts`, `frontend/src/terminology.test.ts`
**Intent:** Record repository-grounded findings and establish one user-facing terminology source.
**Verification:** Run the terminology unit test after a RED-to-GREEN cycle.

### Task 2: Requirements, clarification, and proposed-design review
**Files:** `frontend/src/designSpecificationView.ts`, `frontend/src/designSpecificationView.test.ts`, `frontend/src/designPlanView.ts`, `frontend/src/designPlanView.test.ts`, `frontend/src/main.tsx`, `frontend/src/styles.css`
**Intent:** Group user-provided values, Volundr proposals, calculated values, and essential decisions into clear review steps without modifying persistence or approval semantics.
**Verification:** Add focused failing tests for grouping and labels, then run the view test subset and Vitest suite.

### Task 3: Progress, new-version, multi-output, Configure/Revise, and recovery
**Files:** `frontend/src/workflowPresentation.ts`, `frontend/src/workflowPresentation.test.ts`, `frontend/src/candidateView.ts`, `frontend/src/candidateView.test.ts`, `frontend/src/configurationView.ts`, `frontend/src/configurationView.test.ts`, `frontend/src/main.tsx`, `frontend/src/styles.css`
**Intent:** Translate stage/status evidence into user language, make candidate-versus-current and multi-output state explicit, describe Configure and Revise, and provide consistent recovery copy.
**Verification:** RED tests for progress/recovery/status helpers, targeted tests, then frontend build.

### Task 4: Correlated user-testing telemetry and technical details
**Files:** `frontend/src/workflowTelemetry.ts`, `frontend/src/workflowTelemetry.test.ts`, `frontend/src/main.tsx`, `frontend/e2e/candidate-workflow.spec.ts`
**Intent:** Extend the fixed event registry for meaningful user actions, add optional safe test-scenario metadata, and keep workflow diagnosis/bundle access in a technical-details disclosure.
**Verification:** RED telemetry tests, Vitest, and Playwright scenarios covering new project, configuration, revision, and recoverable failure fixtures.

### Task 5: User-testing documentation and product docs
**Files:** `docs/FRONTEND_USER_TESTING_PLAN.md`, `README.md`, `docs/PRODUCT_DIRECTION.md`, `docs/ARCHITECTURE.md`, `docs/WORKFLOW_OBSERVABILITY.md`, `docs/TEST_STRATEGY.md`, `docs/CURRENT_STAGE_ROADMAP.md`, `docs/MVP_SCOPE.md`, `docs/DOCUMENTATION_MAP.md`
**Intent:** Define the five observed-user scenarios, evidence to retain, supported vocabulary, and the next activity.
**Verification:** Review links and run `git diff --check`.

### Task 6: Verification and commits
**Files:** all changed files
**Intent:** Run targeted/unit/build/Playwright verification, inspect responsive screenshots at required viewports, then commit logical verified slices.
**Verification:** Vitest, build, Playwright, backend regression subset, git diff check, and clean worktree.

**Rollback points:** Commit the audit/vocabulary, then the user-centered workflow implementation, then user-testing scenarios/documentation after each verification gate.
