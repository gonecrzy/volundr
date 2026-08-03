# Provider-response convergence implementation plan
> **Execution mode:** Inline Execution

**Goal:** Harden the generic provider-response lifecycle without weakening
semantic validation, replay selected preserved live responses, then run and
compare two unchanged controlled convergence batches.

**Evidence:** The Phase 0 source is the preserved batch
`/tmp/volundr-live-e2e.VWUxlv/data/debug-sessions/0ba9c31b-5d0e-440e-b34b-7b766afa1d39`
and its authoritative generation-run files under the same live data root.

## Task 1: Reconstruct and document the repeated failures

**Files:** `docs/PROVIDER_RESPONSE_CONVERGENCE.md`,
`docs/PROVIDER_CONVERGENCE_REGRESSION_FIXTURES.md`

**Intent:** Record all three affected projects individually, including batch,
project, route, attempt, raw-response validity, schema/provenance/semantic
findings, repair result, hashes, and worker reachability. Do not implement
until the table distinguishes syntax, schema, provenance, semantic, and
provider variability causes.

**Verification:** Cross-check every row against `attempts.json`, raw output,
request/prompt, normalized artifacts, repair comparison, workflow events, and
the report.

## Task 2: Add the shared response lifecycle and immutable artifacts

**Files:** create `backend/app/services/provider_response.py`; modify
`backend/app/models/generation_attempt.py`,
`backend/app/services/projects/service.py`, schemas, and add migration
`0032_provider_response_lifecycle.py`.

**Intent:** Add one shared lifecycle classification and bounded JSON syntax
normalizer. Persist lifecycle metadata on each generation attempt and write
separate raw, parser-normalized, deterministic-normalized, provider-repaired,
and final contract artifacts without overwriting prior files. Preserve hashes,
changed fields, identity changes, provenance changes, findings, and final
stage outcome.

**TDD:** Add failing unit tests first for classification, fence/prose/trailing
comma normalization, ambiguous syntax, hashes, and immutable artifact paths.

**Verification:** Targeted lifecycle tests and migration upgrade from a fresh
database.

## Task 3: Add focused provenance/schema normalization and repair convergence

**Files:** `backend/app/services/provider_response.py`,
`backend/app/services/projects/plan_provenance.py`,
`backend/app/services/provider_interoperability.py`,
`backend/app/services/projects/service.py`, provider prompt request builders,
and backend tests.

**Intent:** Use only named, unambiguous normalization rules with rule IDs,
guards, protected fields, and evidence. Complete provenance only when exactly
one authoritative matching source exists. Make provider repair record scope,
accepted alternatives, protected identities, unchanged fields, and prohibited
additions. Reject unchanged, regressive, and unrelated-record changes; allow
partial improvement to remain blocked without looping.

**Verification:** Red/green tests for valid authoritative provenance,
ambiguous provenance, user/proposal misclassification, focused record scope,
stable unaffected hashes, unchanged repair, regressive repair, and partial
repair.

## Task 4: Add frozen real-response fixtures and report/frontend accuracy

**Files:** `backend/tests/fixtures/provider_convergence/`,
`backend/tests/test_provider_response_convergence.py`, report/API schemas,
`frontend/src/main.tsx`, `frontend/src/debugBatch*`, technical-details views,
and frontend tests.

**Intent:** Commit only small redacted fixture slices from the three affected
projects. Add deterministic replay expectations for invalid JSON, schema
invalidity, missing/conflicting provenance, unchanged/regressive repair, and
successful normalization. Expose technical details as concise lifecycle facts
without raw JSON, provenance enums, schema paths, or prompt contents.

**Verification:** Backend replay/report tests, frontend unit tests, and no
duplicate progress messages.

## Task 5: Pre-live gates and controlled convergence pair

**Files:** `frontend/e2e/live/mixed-cad-convergence.live.spec.ts`, live harness
helpers, and dated evidence documents.

**Intent:** Run full backend, frontend, build, chat-first Playwright, staged
Playwright, debug-batch Playwright, replay, migration, Compose, and diff
checks. Then run exactly two unchanged batches named
`mixed-cad-convergence-01` and `mixed-cad-convergence-02` using the original
five prompts/fact sheets/clarification/retry policy. Freeze both and require
complete identities before controlled comparison.

**Verification:** The comparison must report matched identities and compare
calls, repairs, syntax/schema/provenance outcomes, worker reach, geometry,
promotion, anomalies, and frontend state accuracy.

## Task 6: Final review and one deferred priority

**Files:** `docs/MIXED_CAD_CONVERGENCE_BATCH_01.md`,
`docs/MIXED_CAD_CONVERGENCE_BATCH_02.md`,
`docs/MIXED_CAD_CONVERGENCE_COMPARISON.md`,
`docs/PROVIDER_CONVERGENCE_NEXT_PRIORITY.md`, plus required documentation
updates.

**Intent:** Inspect all ten new projects individually and compare them with
the original two batches and post-correction batch. Select exactly one next
priority and do not implement it. Preserve explicit monitor safety warnings
and keep observed usability testing separate.

**Verification:** Full suites, Compose health, migration head, diff check, and
clean Git status.

Rollback points are the seven required commits: lifecycle/evidence,
normalization/repair, frozen fixtures, frontend/Playwright, Batch 1, Batch 2
comparison, and final priority recommendation.
