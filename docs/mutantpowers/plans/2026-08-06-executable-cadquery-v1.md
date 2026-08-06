# Gemini Executable CadQuery v1 Implementation Plan
> **Execution mode:** Inline Execution

**Goal:** Run one isolated Gemini complete-source CadQuery experiment while preserving the reconstructed production workflow and `main`.

**Architecture:** The experimental route is selected only by `VOLUNDR_EXECUTABLE_CADQUERY_FLOW_ENABLED=true`. It creates an authoritative executable design contract, asks Gemini for a complete `cadquery-v1` source response, validates the response without rewriting it, executes the unchanged sandboxed worker, reuses topology/artifact/semantic services, and records bounded repair history in existing workflow provenance JSON. The existing validated route remains the default whenever the flag is false. The Codex adapter remains present and is never selected by this route.

**Persistence decision:** Existing `validated_cadquery_workflows` JSON fields, `validated_cadquery_operations`, provider-attempt rows, `Revision`, and `RevisionOutput` records provide the required durable state. No migration is planned unless an invariant cannot be represented safely; if that occurs, add only `0040_executable_cadquery_repair_sessions` and test all upgrade directions.

### Task 1: Contract and fixture primitives
**Files:** `backend/app/services/executable_cadquery/contract.py`, `backend/app/services/executable_cadquery/fixtures.py`, `backend/tests/test_executable_cadquery_contract.py`, `backend/tests/test_executable_cadquery_fixture.py`

**Intent:** Define `executable-cadquery-design-contract-v1`, `executable-cadquery-response-v1`, the frozen `mounting_bracket` prompt/contract, complete-source response parsing, canonical output checks, source hashes, and AST/source-contract reuse. No source fragments or geometry reconstruction are allowed.

**TDD:** Add failing tests for valid response acceptance, malformed envelope, missing/extra output IDs, syntax failure, unsafe import, artifact export, and complete-source preservation; run the targeted tests red; implement the smallest contract parser; run them green.

**Verification:** `rtk env PYTHONPATH=. backend/.venv/bin/python -m pytest -q backend/tests/test_executable_cadquery_contract.py backend/tests/test_executable_cadquery_fixture.py`.

### Task 2: Provider prompt and feature-gated routing
**Files:** `backend/app/core/config.py`, `backend/app/services/ai/provider.py`, `backend/app/services/ai/gemini_cli.py`, `backend/app/api/dependencies.py`, `backend/app/api/validated_cadquery.py`, `docker-compose.yml`, `.env.example`, `backend/.env.example`, `frontend/.env.example`, `backend/tests/test_executable_cadquery_routing.py`, `backend/tests/test_environment_configuration.py`

**Intent:** Add the disabled-by-default executable-flow flag and a Gemini prompt branch that requests a narrow JSON envelope containing complete source. Build the experimental provider through Gemini only; never route through `CodexProxyProvider`. Preserve existing provider selection and validated-flow behavior when the flag is false.

**TDD:** Add failing flag/routing tests first, including a Codex-configured validated provider that must not be called by the executable route; implement the flag and dependency selection; verify legacy routing tests remain green.

**Verification:** Targeted routing/configuration tests, `rtk docker compose config --quiet`, and `rtk git diff --check`.

### Task 3: Existing-worker execution and durable experimental workflow
**Files:** `backend/app/services/projects/service.py`, `backend/app/services/executable_cadquery/workflow.py`, `backend/app/services/executable_cadquery/semantic.py`, `backend/app/models/validated_cadquery_workflow.py`, `backend/app/schemas/validated_cadquery.py`, `backend/tests/test_executable_cadquery_workflow.py`, `backend/tests/test_executable_cadquery_semantic.py`

**Intent:** Add a dedicated experimental workflow service that materializes complete source through the existing revision/artifact worker pipeline, adapts the contract to existing semantic-verifier inputs without choosing CadQuery operations, preserves the latest valid revision during later failures, and creates immutable child revisions for user changes.

**TDD:** Add failing tests for direct worker use, source-hash persistence, required sibling behavior, artifact-root safety, semantic pass/fail/unverifiable states, accepted-parent revision identity, and latest-valid-preview preservation; implement orchestration and provenance JSON persistence; run targeted tests green.

**Verification:** Targeted workflow/semantic/worker tests plus existing validated workflow integrity tests.

### Task 4: Bounded repair ladder
**Files:** `backend/app/services/executable_cadquery/repair.py`, `backend/tests/test_executable_cadquery_repair.py`, `backend/tests/snapshots/executable_cadquery_repair/`

**Intent:** Implement L0 source contract, L1 execution, L2 topology, L3 semantic, and L4 user-revision classification; normalized failure taxonomy; deterministic repair envelope; measurable progress comparison; global stop conditions; and the seven-operation ceiling. Persist logical operation, attempt, source/response hashes, worker/topology/semantic evidence, progress, and terminal state in workflow provenance.

**TDD:** Add failing tests and snapshots for every level plus syntax, unsafe import, API error, timeout, empty/invalid shape, solid mismatch, semantic dimension/position failure, protected regression, sibling failure, progress, repeated error, repeated hash, and user revision preservation; implement pure functions and integrate them into the workflow; run all repair tests green.

**Verification:** Repair tests, snapshot review, and targeted validated persistence tests.

### Task 5: Frontend presentation and offline browser fixtures
**Files:** `frontend/src/main.tsx`, `frontend/src/validatedCadQueryWorkflow.ts`, `frontend/src/ValidatedCadQueryWorkflowView.tsx`, `frontend/src/validatedCadQueryWorkflow.test.ts`, `frontend/e2e/executable-cadquery-workflow.spec.ts`, `frontend/playwright.config.ts`, `frontend/scripts/run-fixture-backend.sh`

**Intent:** Enable the experimental route only when its flag is true, show readable generation/repair/failure labels, preserve the latest valid STL preview while repairs fail, expose requirement/output/artifact/acceptance/revision controls, and keep internal diagnostics redacted.

**Verification:** Frontend unit tests, build, targeted offline Playwright fixture tests, and the existing browser suite.

### Task 6: Offline gate, evidence, and commit cycles
**Files:** `docs/executable-cadquery-v1-reuse-ledger.md`, `data/debug-sessions/executable-cadquery/` evidence manifests (after their stages), `docs/` experiment record

**Intent:** Record the reuse ledger, run all offline fixtures and full suites, validate migrations/Compose/nginx/secret boundaries, commit cycle 1 (routing/worker), cycle 2 (repair ladder), and cycle 3 (frontend/browser), and push the experimental branch. No provider call is permitted before every live gate passes.

**Verification:** Full backend/frontend/browser suites, Alembic current/heads/check, Compose validation, nginx validation, secret scan, diff check, clean worktree, and pushed branch.

### Task 7: One controlled live creation and one user revision
**Files:** `data/debug-sessions/executable-cadquery/gemini-complete-source-01/`, final experiment record

**Intent:** With the frozen fixture and unchanged policy, run exactly one Gemini creation session using `GEMINI_API_KEY_2` first and the existing 429 fallback policy, capture the real workspace screenshot and artifacts, accept the candidate, submit exactly the requested pocket revision, validate the child revision, capture the revised screenshot, and record exactly one final decision.

**Verification:** Live browser session, source/worker/topology/semantic/artifact/package evidence, credential boundary evidence, revision/protected-fact assertions, and provider-operation budget.

### Task 8: Final branch audit
**Files:** evidence manifests and final decision only

**Intent:** Confirm the branch descends from `d4d0bb5`, `main` is unchanged, no credentials/runtime data are tracked, the branch is clean and pushed, and later-review eligibility is recorded without merging.

**Verification:** Fresh `git fetch origin`, branch/main comparison, status, tracked-file secret scan, diff check, and remote branch verification.
