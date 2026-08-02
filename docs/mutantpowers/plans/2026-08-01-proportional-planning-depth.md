# Proportional Planning Depth

> **Execution mode:** Inline Execution

**Goal:** Route sufficiently specified designs through the smallest safe
planning contract while preserving the existing requirement ledger, workflow
records, geometry generation, source safety, worker, topology, functional,
candidate, persistence, and export gates.

## Architecture

- `PlanningDepthRouter` is the one deterministic route authority. It consumes
  the active requirement ledger, current project/revision state, and revision
  delta. It returns a route, policy version, reasons, missing-information
  evidence, ambiguity, and proposed assumptions.
- Existing `DesignPlan` persistence remains the lifecycle boundary for plan
  artifacts, with explicit `schema_version` discriminators. Direct briefs and
  compact plans are never presented as detailed plans.
- Workflow artifacts are the authoritative immutable copies of route decisions,
  plan/brief payloads, normalized execution contexts, and prompt context packs.
  Generation-attempt and workflow JSON fields contain indexes only.
- All successful routes normalize into `GeometryExecutionContext` before the
  existing geometry pipeline receives them.
- Prompt context packs are generated per geometry/repair/revision attempt,
  hashed, persisted, and passed through the existing `ModelGenerationRequest`.

## Task 1 — RED tests

**Files:**

- `backend/tests/test_planning_depth.py`
- `backend/tests/test_geometry_execution_context.py`
- `backend/tests/test_prompt_context_pack.py`
- `backend/tests/test_chat_workflow.py`
- `backend/tests/test_design_plans.py`

Write failing tests for semantic direct/compact/detailed/clarification routing,
direct provider-call suppression, compact normalization, immutable artifact
records, stable context hashes, context inclusion/exclusion, route reevaluation
after clarification, deterministic narrow revisions, and preserved current
versions after planning failure. Run the focused tests and record the expected
RED failures before production edits.

## Task 2 — deterministic route and direct brief

**Files:**

- `backend/app/services/planning/depth.py`
- `backend/app/services/planning/brief.py`
- `backend/app/services/planning/context.py`
- `backend/app/schemas/project.py`
- `backend/app/services/projects/chat_workflow.py`
- `backend/app/services/projects/service.py`
- `backend/app/services/workflow/observability.py`

Implement route evidence and deterministic brief construction from the active
ledger. Use semantic evidence, not product-name branches. Persist route and
brief as workflow artifacts and create an explicit `cad-brief-v1` plan record
only where the existing generation pipeline requires a plan identity. Mark the
record deterministic/approved without fabricating provider planning evidence.
Normalize the brief into the common execution context and invoke the existing
geometry generation and candidate gates.

## Task 3 — compact planning

**Files:**

- `backend/app/services/ai/provider.py`
- `backend/app/services/ai/gemini_cli.py`
- `backend/app/services/ai/gemini_api.py`
- `backend/app/services/ai/ollama.py`
- `backend/app/services/planning/compact.py`
- `backend/app/services/projects/service.py`
- `backend/tests/test_ai_provider_contracts.py`

Add a versioned compact plan request/normalizer. Keep harmless formatting
variation nonblocking, reject semantic contradictions and missing critical
features, and normalize to the common context. Preserve the existing detailed
Design Plan request and validation path unchanged for detailed routes.

## Task 4 — context packs and revision routing

**Files:**

- `backend/app/services/planning/context.py`
- `backend/app/services/projects/chat_workflow.py`
- `backend/app/services/projects/service.py`
- `backend/app/services/ai/provider.py`
- `backend/app/services/ai/gemini_cli.py`
- `backend/app/services/ai/gemini_api.py`
- `backend/app/services/ai/ollama.py`

Build branch-specific context from active requirements, delta, preserved
requirements, selected plan/brief, affected features, current revision
summary/source, relevant findings, and scaffold contract. Exclude unrelated
history and superseded context. Persist inclusion/exclusion reasons, artifact
IDs, hash, and token evidence. Use deterministic revision briefs for narrow
changes, compact planning for interacting single-component changes, and the
existing detailed revision planner for multipart/assembly/mechanism changes.

## Task 5 — frontend and browser coverage

**Files:**

- `frontend/src/chatWorkspaceView.tsx`
- `frontend/src/main.tsx`
- `frontend/src/chatWorkspace.ts`
- `frontend/src/chatWorkspace.test.ts`
- `frontend/e2e/workflow-gate.spec.ts`
- `frontend/e2e/requirement-driven-revisions.spec.ts`
- new deterministic planning-depth fixture scenario files as needed

Expose only concise proposals and existing progress/clarification/outcome
messages. Keep route names and context packs under Technical details. Add
coverage for direct success, compact success, necessary clarification, ordinary
revision, and blocked planning while preserving staged mode.

## Task 6 — documentation and live evaluation

**Files:**

- `docs/AI_CAD_DIRECTION_ALIGNMENT.md`
- `docs/PLANNING_DEPTH_MODEL.md`
- `docs/CAD_BRIEF_CONTRACT.md`
- `docs/GEOMETRY_EXECUTION_CONTEXT.md`
- `docs/PROMPT_CONTEXT_PACK.md`
- `docs/PLANNING_DEPTH_LIVE_EVALUATION.md`
- existing alignment documents named in the user brief

Run exact spacer, bottle-holder, and two-piece enclosure diagnostics. Record
provider usage, route artifacts, context packs, worker reachability, artifact
readiness, candidate outcomes, and limitations without overstating geometry
quality.

## Verification and rollback points

- RED focused backend tests before production code.
- GREEN focused backend tests after each planning subsystem.
- Full backend suite from repository root with
  `backend/.venv/bin/python -m pytest -q backend/tests`.
- Frontend unit tests and build.
- Chat-first and staged Playwright suites separately.
- Compose config, service health, web/API smoke, and opt-in live diagnostics.
- `git diff --check` and clean worktree.

Commit checkpoints follow the approved implementation order: route/brief,
execution context, compact/context pack, deterministic/browser coverage, live
evaluation, and documentation alignment.
