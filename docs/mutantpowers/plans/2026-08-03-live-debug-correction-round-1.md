# Live debug correction round 1
> **Execution mode:** Inline Execution

**Goal:** Implement only the first generic correction pass from the two frozen
mixed-CAD batches, then run one post-correction verification batch.

**Scope boundary:** durable evidence integrity, reliable identities, accurate
attempt/candidate classification, comparison status, generic provider/schema/
provenance handling, selected frozen-response replay, and one unchanged live
verification batch. No organizer, tray/holder, screw-thread, monitor-specific,
or other product-family CAD code.

## Task 0: Authoritative evidence audit

**Files:** frozen batch roots under `/tmp/volundr-live-e2e.uaonH0/`, current
reports/docs, current tests, current Git state.

**Intent:** Confirm the exact batch IDs, identity/configuration values, all ten
project summaries, selected raw failures, codex-review instructions, current
test counts, and repository state before edits.

**Verification:** `git status`, batch `jq` summaries, selected redaction/path
scans, and current backend/frontend test commands.

## Task 1: Durable evidence normalization and identity

**Files:** `backend/app/services/workflow/redaction.py`,
`backend/app/services/debug_batches/reports.py`,
`backend/app/services/debug_batches/evidence.py`,
`backend/app/services/debug_batches/identity.py`, `backend/app/models/debug_batch.py`,
`backend/app/schemas/debug_batch.py`, `backend/app/core/config.py`, migration if
new identity columns are required, and focused backend tests.

**Intent:** Add generic absolute-path normalization with safe relative paths,
artifact references, and non-secret diagnostic findings. Add complete build
identity fields (Git SHA, dirty state, build timestamp, application/schema
identity) without requiring `.git` in a runtime image. Incomplete identity must
be explicit and cannot claim a controlled comparison.

**TDD:** Add failing tests for registered paths, unknown paths, rendered
evidence, identity capture without `.git`, dirty identity, and incomplete
identity comparison before implementation.

**Verification/commit:** focused backend tests, migration validation, then
commit `Harden durable evidence and build identity`.

## Task 2: Attempt, stage, and candidate classification

**Files:** existing generation-attempt/provider/workflow recording paths,
`backend/app/services/debug_batches/service.py`,
`backend/app/services/debug_batches/reports.py`, schemas, and focused tests.

**Intent:** Report provider calls, provider retries, content repairs,
generation attempts, workflow-stage attempts, and user operations separately.
Use authoritative workflow/revision/worker/artifact state for canonical outcomes.
Prevent blocked or failed worker outputs from being treated as valid geometry,
accepted candidates, current working versions, or export-ready outputs.

**TDD:** Add failing contradictory-record tests, provider/content/repair
count tests, worker-exception tests, and promotion/export gate tests.

**Verification/commit:** focused backend tests and report fixture checks, then
commit `Correct attempt, candidate, and comparison classification`.

## Task 3: Generic provider/schema/provenance repair and frozen fixtures

**Files:** existing provider/repair and workflow validation modules, a committed
redacted fixture directory under `backend/tests/fixtures/debug_batch/`, fixture
replay tests, and `docs/LIVE_BATCH_REGRESSION_CANDIDATES.md` if the selected
subset changes.

**Intent:** Add only meaning-preserving normalization and bounded focused repair
handling. Persist original/repaired forms and findings. Detect unchanged repair
responses by normalized semantic hash and emit `repair.no_effect` without a
repeat call. Cover invalid JSON/schema, provenance, source-contract,
candidate-classification, and unchanged repair responses. Do not add CAD-family
logic.

**TDD:** Add fixture replay tests that fail until each expected classification,
blocking result, and repair eligibility is produced.

**Verification/commit:** fixture replay and affected workflow tests, then
commit `Add focused schema/provenance repair and frozen regressions`.

## Task 4: Authoritative comparison UI and deterministic browser coverage

**Files:** `frontend/src/debugBatch.ts`, `frontend/src/debugBatchView.tsx`,
frontend tests, `frontend/e2e/debug-batch.spec.ts`, and styles only if required.

**Intent:** Render exactly one comparison status from one authoritative status
object. Support controlled, uncontrolled, pending identity,
configuration mismatch, and identity incomplete. Show matched identities for
controlled status and exact mismatches/warnings otherwise. Keep blocked projects
from displaying geometry success/export readiness and keep technical attempt
counts separate from user operations.

**TDD:** Add failing frontend tests and Playwright scenarios for every status,
identity completeness, worker failure, blocked export state, and path-free UI.

**Verification/commit:** frontend tests/build and deterministic Playwright,
then commit `Add deterministic frontend and Playwright coverage`.

## Task 5: Full pre-live verification and post-correction live batch

**Files:** live driver/config only as needed to name and preserve the batch,
then required documentation files.

**Intent:** Run backend tests, frontend tests/build, Playwright, Compose health,
`git diff --check`, and redaction checks. Run exactly one unchanged live batch
named `mixed-cad-live-correction-01` using the original five prompts, fact
sheets, provider/model, environment, schema, and one-retry policy. This is a
post-correction comparison, not a controlled provider-variability comparison.

**Verification/commit:** preserve raw evidence outside Git, inspect all five
projects and codex-review instruction, compare separately to both historical
batches, then commit `Record post-correction live batch and comparison`.

## Task 6: Review and next-priority recommendation

**Files:** `docs/LIVE_BATCH_CORRECTION_ROUND_1.md`,
`docs/MIXED_CAD_LIVE_POST_CORRECTION_01.md`,
`docs/LIVE_BATCH_POST_CORRECTION_COMPARISON.md`, plus the required updates to
`docs/LIVE_BATCH_CORRECTION_PLAN.md`, `docs/LIVE_BATCH_SELF_REVIEW.md`,
`docs/LIVE_BATCH_REGRESSION_CANDIDATES.md`,
`docs/LIVE_DEBUG_BATCH_IMPLEMENTATION.md`, `docs/WORKFLOW_OBSERVABILITY.md`,
`docs/TEST_STRATEGY.md`, `docs/CURRENT_STAGE_ROADMAP.md`, and
`docs/DOCUMENTATION_MAP.md`.

**Intent:** Review each post-correction project, quantify generic failure
movement, record residual risks and evidence limitations, and select exactly
one next primary correction family without implementing it.

**Verification/commit:** docs review, clean repository, full verification
summary, then commit `Record next-priority recommendation`.

## Explicit exclusions

- No product-specific CAD changes.
- No prompt changes to obtain success.
- No weakened source/promotion gates.
- No browser shell/Codex execution.
- No raw live evidence committed to Git.
