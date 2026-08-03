# Contract complexity and model capability comparison
> **Execution mode:** Inline Execution

**Goal:** Correct the narrow debug-batch lifecycle classification, freeze three
redacted diagnostic input packages from the completed mixed-CAD evidence, run
24 diagnostic attempts across the current contract and a Volundr-owned
simplified execution brief using the configured and stronger Gemini models,
measure source/worker/geometry outcomes, and report one evidence-backed next
direction without implementing it.

**Constraints:** No new production planning/provenance/normalization layer; no
large frontend batch; no product-family generator fixes; no weakening of
source safety, topology, or promotion; diagnostic attempts do not mutate
normal projects or create Current working versions.

## Task 1: Narrow lifecycle-state correction

**Files:** `backend/app/services/debug_batches/lifecycle.py`,
`backend/app/services/debug_batches/reports.py`,
`backend/app/services/debug_batches/service.py`,
`backend/app/schemas/debug_batch.py`, focused backend tests.

**Intent:** Derive one of `no_activity`, `in_progress`, `interrupted`,
`blocked_before_worker`, `blocked_after_worker`, or
`working_version_created` from workflows, attempts, worker events, and active
revision state. Use the same helper for API membership status and materialized
reports. Preserve existing human-readable labels for compatibility while
exposing the canonical state.

**TDD:** Add red tests for each state and specifically for an attempt left in
`started` state with a failed workflow; verify it is not `no_activity`.

**Verification:** Focused lifecycle/report tests and existing debug-batch API
tests. No live pair.

## Task 2: Freeze diagnostic inputs

**Files:** `backend/scripts/freeze_contract_complexity_inputs.py`,
`backend/tests/fixtures/diagnostic_inputs/`.

**Intent:** Extract only allowlisted, redacted fields from the preserved Batch
1 evidence for the wall carrier, desktop organizer, and screw-lid container:
request, approved fact-sheet answers, active ledger rows, provenance, design
specification, components, outputs, features, coordinate frames, required
functional/verification targets, and exposed controls. Write deterministic
package hashes and source evidence identifiers. Do not include provider raw
responses or secrets.

**Verification:** Fixture schema/hash test and secret/path scan.

## Task 3: Diagnostic execution harness

**Files:** `backend/app/services/diagnostics/contract_complexity.py`,
`backend/scripts/run_contract_complexity_experiment.py`, focused tests.

**Intent:** Implement two diagnostic-only strategies:

- current contract: existing GeometryExecutionContext, structured geometry
  bodies, source scaffold, source authority, safety/lexical validation,
  topology, and worker;
- simplified execution brief: deterministic Volundr-owned components,
  outputs, feature/function order, requirements, frames, dimensions, review
  targets, and output requirements; the provider returns only ordered geometry
  implementation statements and never authors identities/provenance.

Use the same provider settings and worker for both strategies. Record exactly
two initial attempts per project, strategy, and model. Permit at most one
worker-informed repair only after a worker traceback names one provider-owned
function; record repair separately and preserve unaffected function hashes.

**Verification:** Fake-provider/fake-worker tests cover the 24-cell matrix,
strategy input boundaries, metrics completeness, and one-repair limit.

## Task 4: Run the diagnostic matrix

**Command:** `backend/scripts/run_contract_complexity_experiment.py` with the
preserved fixtures, current configured model, stronger available Gemini model,
and a durable local data root.

**Matrix:** 3 projects × 2 strategies × 2 models × 2 attempts = 24 initial
attempts. No clarification or requirement extraction calls. Keep temperature,
thinking policy, output tokens, retry limit, worker, and validators identical.

**Verification:** Confirm 24 records, per-attempt metrics, model availability,
raw evidence outside Git, no normal project mutations, and worker logs.

## Task 5: Reports and decision

**Files:** `docs/GENERATION_BLOCKER_ISOLATION.md`,
`docs/CONTRACT_COMPLEXITY_MODEL_COMPARISON.md`,
`docs/SIMPLIFIED_EXECUTION_BRIEF_EXPERIMENT.md`.

**Intent:** Summarize frozen inputs, both strategies, models, all 24 results,
worker/geometry/repair/latency/usage metrics, per-project and cross-project
comparisons, risks, limitations, and exactly one next direction. Do not
implement the selected direction.

**Verification:** Cross-check reports against the immutable experiment JSON,
run focused and full backend tests, migration/config checks as applicable,
`git diff --check`, and confirm a clean repository.

## Rollback points

Commit after Task 1, after Tasks 2–3, after the frozen experiment record, and
after the final reports. Raw diagnostic evidence remains outside Git and is
not a rollback artifact.
