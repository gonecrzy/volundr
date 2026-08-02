# Chat-First Workflow and Live Harness Plan
> **Execution mode:** Inline Execution

**Goal:** Repair the live browser harness, add a feature-flagged chat-first progression path using the existing authoritative lifecycle services, convert deterministic browser scenarios, and run the exact bottle-holder request through the real provider/worker path or record a genuine semantic block.

**Safety boundary:** Do not add CAD validation rules or weaken source, topology, consistency, functional, candidate, or promotion gates. Preserve Design Specification, Design Plan, Revision Plan, project history, and explicit export behavior.

## Task 0: Preserve the completed parameter-effect pass

**Files:** Existing parameter-effect implementation and tests in `backend/app/services/cad/`, `backend/tests/`, and `docs/BOTTLE_HOLDER_PARAMETER_EFFECT_LIVE_EVALUATION.md`.

**Intent:** Commit the already verified prior pass as a rollback point before new work.

**Verification:** Reuse the recorded backend/frontend verification, run `git diff --check`, and confirm only the prior-pass files are included.

**Commit:** `Implement parameter-effect contracts`

## Task 1: Repair live and deterministic browser harness isolation

**Files:** `frontend/playwright.config.ts`, `frontend/playwright.live.config.ts`, `frontend/scripts/run-live-e2e.sh`, new harness helper scripts/tests as required, `frontend/e2e/live/liveEnvironment.ts`.

**Intent:** Use explicit loopback hosts, allocated/configurable ports, preflight stale-port detection, owned process groups, deterministic/live data-directory separation, and clear bind failures. Never reuse an unrelated server. Keep the Gemini key in the backend-only environment file and scrub it from browser processes and evidence.

**TDD:** Add a focused port/process/config regression test or executable shell preflight that fails against the current binding/reuse behavior, then implement the correction.

**Verification:** Run shell syntax checks, harness preflight tests, deterministic Playwright configuration checks with live mode disabled, and a controlled live harness startup failure that reports the bind cause without leaving child processes.

**Commit:** `Repair isolated live browser harness`

## Task 2: Add backend chat intent routing and automatic progression

**Files:** `backend/app/core/config.py`, `backend/app/schemas/project.py`, new `backend/app/services/workflow/chat_router.py`, `backend/app/services/workflow/chat_service.py` or equivalent, `backend/app/api/projects.py`, `backend/app/services/projects/service.py`, workflow event definitions/telemetry, and backend tests.

**Intent:** Add `VOLUNDR_CHAT_FIRST` as a backend setting and one primary `POST /api/projects/{project_id}/chat` operation. Persist the user message idempotently, classify deterministic intents from message text and current project state, and route to existing requirement extraction, Design Plan, configuration, Revision Plan, component revision, start-over, and export services.

**Progression rules:**

- Initial chat creates/updates the project request, extracts requirements, pauses only for essential clarification, then internally creates/validates the Design Plan and starts generation.
- A passing revision is promoted through the existing validated acceptance path; a blocked attempt leaves `active_revision_id` unchanged.
- Revision Plan approval is internal to the route; the persisted plan remains validated.
- Parameter changes use configuration preview/generation without a provider call when deterministic routing proves the change is parameter-only.
- Start-over creates a new project branch/version lineage without deleting prior records or artifacts and may retain selected requirement text.
- Duplicate messages use a client-supplied idempotency key or deterministic request fingerprint; stale completions cannot promote older work.

**Response:** Return workflow run ID, action, current stage, input-required flag, concise assistant message, current working revision ID, active run, and blocked-attempt details.

**TDD:** Add RED tests for initial progression, clarification pause/resume, parameter routing, structural/component revision persistence, start-over lineage, promotion/blocking, idempotency, stale completion protection, and export summary before implementation.

**Verification:** Run focused backend chat/API tests plus existing lifecycle, candidate, configuration, revision, consistency, and observability suites.

**Commit:** `Implement chat-first backend orchestration`

## Task 3: Add the frontend feature flag and assistant-first mode

**Files:** `frontend/src/main.tsx`, `frontend/src/chatWorkflow.ts`, `frontend/src/workflowTelemetry.ts`, `frontend/src/workflowPresentation.ts`, relevant view components/tests, `frontend/.env.example` or equivalent, and frontend tests.

**Intent:** Add `VITE_VOLUNDR_CHAT_FIRST=true`. When enabled, submit messages only to the primary chat operation, render concise automatic-progress states, show conversational clarifications, current working/new/blocked terminology, change summaries, and explicit export summaries. Hide normal-path approval/generate controls while retaining technical details and the staged mode when disabled.

**Safety:** Do not duplicate backend lifecycle logic. Guard stale responses by request sequence/run ID and refresh authoritative project/revision state after each response.

**TDD:** Add RED component tests for flag visibility, progress messages, clarification submission, current-working preservation after block, automatic promotion, start-over display, and export warning summary.

**Verification:** Run frontend unit tests and production build with both flag values represented in tests.

**Commit:** `Add feature-flagged chat-first frontend`

## Task 4: Convert deterministic fixture workflows and add start-over coverage

**Files:** `backend/app/testing/e2e_fixture_server.py`, fixture provider/state helpers, `frontend/e2e/workflow-gate.spec.ts`, `frontend/e2e/configure-organizer.spec.ts`, `frontend/e2e/enclosure-revision.spec.ts`, `frontend/e2e/recoverable-blocked-workflow.spec.ts`, new start-over scenario/spec, and related tests.

**Intent:** Make explicit-part, intent-first, organizer, enclosure revision, and recoverable-failure scenarios use one chat submission/answer path under the flag. Assert no approval buttons, internal Design/Revision Plans, provider-free parameter changes, preserved active revisions after blocks, automatic promotion, correlated events, diagnostic bundles, and idempotent duplicate messages. Add a start-over lineage scenario while keeping staged scenarios passing with the flag disabled.

**Verification:** Run deterministic Playwright with `VITE_VOLUNDR_CHAT_FIRST=true`, then the existing suite with the flag false.

**Commit:** `Convert deterministic workflows to chat-first`

## Task 5: Add backend-only live diagnostic and rerun the exact request

**Files:** New `backend/scripts/run_live_bottle_holder_workflow.py` (or an explicitly named backend command), backend CLI tests, and a new live evaluation document.

**Intent:** Provide a no-browser diagnostic command that uses real `GeminiApiProvider`, real FastAPI routes/services, the real CadQuery worker, isolated temporary data/workspace, provider-key isolation, and the exact request. Capture workflow IDs, provider usage/timing, Design Specification/Plan state, source/effect validation, worker execution, functional checks, blocked/promotion state, and artifact paths without exposing secrets.

**Verification:** Run the backend-only exact request when credentials and CadQuery are available. Then run the exact Playwright bottle-holder request through the repaired harness. A failure is acceptable only when it is a genuine semantic/provider/worker result and leaves the current version unchanged.

**Commit:** `Record bottle-holder chat-first live evaluation`

## Task 6: Update product documentation

**Files:** New `docs/CHAT_FIRST_WORKFLOW.md`; update `README.md`, `docs/PRODUCT_DIRECTION.md`, `docs/ARCHITECTURE.md`, `docs/FRONTEND_WORKFLOW_AUDIT.md`, `docs/FRONTEND_USER_TESTING_PLAN.md`, `docs/WORKFLOW_OBSERVABILITY.md`, `docs/TEST_STRATEGY.md`, `docs/CURRENT_STAGE_ROADMAP.md`, `docs/MVP_SCOPE.md`, and `docs/DOCUMENTATION_MAP.md`.

**Intent:** Document the flag, authoritative API progression, safety/promotion semantics, staged-mode transition plan, deterministic/live test commands, start-over lineage, export behavior, and the actual bottle-holder result.

**Verification:** Review links/commands, run `git diff --check`, and confirm no generated evidence or secrets are tracked.

## Final verification

Run the full backend suite, focused chat/harness tests, frontend tests/build, deterministic Playwright in both modes, the exact backend-only smoke, the exact live browser smoke when the environment permits binding, and inspect `git status` for intended changes only.
