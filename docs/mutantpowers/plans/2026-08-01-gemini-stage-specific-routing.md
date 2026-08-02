# Gemini Stage-Specific Routing Implementation Plan
> **Execution mode:** Inline Execution

**Goal:** Route Gemini requests by prompt stage, persist the selected routing
evidence on every generation attempt, and run a controlled geometry-model
comparison without changing CAD validation or workflow lifecycle behavior.

**Architecture:** `GeminiModelPolicy` will resolve a provider-neutral prompt
mode to a configured model, with the general Gemini model as the documented
fallback. Gemini transports will use that decision for the request and return
usage, latency, actual-model, and fallback metadata. `ProjectService` will
persist the decision and result metadata on the existing `GenerationAttempt`.
The existing safe attempt-evidence endpoint will expose only non-secret
routing metadata for Technical details.

### Task 1: Add failing routing and persistence tests
**Files:** `backend/tests/test_gemini_model_policy.py`, `backend/tests/test_gemini_api_provider.py`, `backend/tests/test_gemini_cli_provider.py`, `backend/tests/test_config.py`, `backend/tests/test_design_plans.py`, `backend/tests/test_project_api.py`
**Intent:** Prove stage selection, fallback selection, operational/content
failure distinction, actual provider model metadata, and attempt evidence
before implementation.
**Verification:** Run the focused tests and confirm each new behavior fails
for the expected missing-policy or missing-field reason.

### Task 2: Implement stage-specific policy and provider routing
**Files:** `backend/app/core/config.py`, `backend/app/services/ai/model_policy.py`, `backend/app/services/ai/provider.py`, `backend/app/services/ai/gemini_cli.py`, `backend/app/services/ai/gemini_api.py`, `backend/app/api/dependencies.py`
**Intent:** Add the six stage-specific settings, a validated policy with a
general-model fallback, prompt-mode resolution, model override at the actual
Gemini transport boundary, operational fallback recording, and provider
usage/latency metadata. Keep provider credentials and policy out of worker
requests.
**Verification:** Focused provider/config tests plus existing provider tests.

### Task 3: Persist routing evidence on generation attempts
**Files:** `backend/app/models/generation_attempt.py`, `backend/alembic/versions/0024_generation_attempt_routing.py`, `backend/app/schemas/project.py`, `backend/app/api/projects.py`, `backend/app/services/projects/service.py`, `backend/tests/test_generation_api.py`, `backend/tests/test_workflow_observability.py`
**Intent:** Persist prompt mode, provider, selected model, policy version,
routing reason, fallback chain, actual model, token usage, and provider
latency in the existing attempt record and expose safe diagnostic fields.
Update all requirement, plan, revision-plan, geometry, repair, and component
revision attempt constructors through the shared routing helper.
**Verification:** Focused service/API tests and migration-compatible test DB
creation.

### Task 4: Add frozen controlled geometry comparison and report
**Files:** `backend/scripts/run_live_geometry_model_comparison.py`, `backend/tests/test_live_geometry_model_comparison.py`, `docs/GEMINI_GEOMETRY_MODEL_EVALUATION.md`
**Intent:** Reuse the latest successful upstream artifacts without rerunning
requirements or planning, execute two geometry attempts for the configured
fast and stronger models under identical inputs, record all requested
structured/source/worker/functional metrics, and then rerun the complete
chat-first holder request with the selected routing policy.
**Verification:** Dry-run/fake-provider comparison tests; exact live command
when credentials and a stronger configured model are available.

### Task 5: Show routing evidence only in Technical details
**Files:** `frontend/src/*` technical evidence types/components, frontend unit tests, `frontend/e2e/*` only where existing technical-details assertions need updates
**Intent:** Keep the ordinary workflow model-agnostic while rendering selected
stage model, provider calls, repair count, token usage, and latency in the
existing secondary diagnostics surface.
**Verification:** Frontend unit tests, build, deterministic chat-first and
staged Playwright suites.

### Task 6: Review, full verification, and separate commits
**Files:** all changed files
**Intent:** Review the diff for secret leakage, worker configuration leakage,
prompt drift, and accidental CAD-validator changes; run the complete backend,
frontend, deterministic browser, focused live, and formatting checks.
**Verification:** `git diff --check`, full suites, exact holder rerun, clean
worktree. Commit routing implementation separately from the evaluation report.
