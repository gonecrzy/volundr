# Gemini Provider Contract Foundation Plan
> **Execution mode:** Inline Execution

**Goal:** Create the new `gemini-provider-contract-foundation-01` study, select
Gemini 3.5 Flash-Lite settings/thinking/prompts independently of current
Volundr build compatibility, freeze provider-owned contracts, implement a
generic adapter, replay historical evidence, run the gated holdout, and leave
production unchanged.

**Architecture:** Keep the study runner and evaluator in experiment-scoped
code. Put pure intrinsic scoring, contract signatures, entropy/distance, and
adapter logic in a reusable service module that has no provider, worker,
database, or current-parser dependency. Use one direct Gemini transport runner
with explicit `GEMINI_API_KEY_2`, one monotonic limiter, immutable attempt
records, and phase gates. Write all live evidence under the new ignored study
root; never mutate the three prior study roots.

**Safety invariants:** model is exactly `gemini-3.5-flash-lite`; only the
secondary credential is eligible; no primary fallback or key rotation; one
concurrent request; 12 starts/minute default; 15 starts/rolling 60 seconds
hard cap; five-second minimum gap; maximum two attempts per logical operation;
no readiness probe; no production configuration or deployment changes.

## Task 1: Freeze the study inputs and preregistration

**Files:** `backend/scripts/run_gemini_provider_contract_foundation.py`,
`data/debug-sessions/gemini-provider-contract-foundation/gemini-provider-contract-foundation-01/`

- Capture repository identity, migration head, prior-study report/raw hashes,
  current/Profile B settings hashes, prompt hashes, packet hashes, and parser
  hash into `reports/repository-snapshot.json`.
- Copy the required historical reports into
  `reports/historical/source-evidence/` without changing source files.
- Materialize six frozen selection packets and ten holdout packets, with
  selection/holdout disjointness and hashes recorded before any live call.
- Write `reports/study-preregistration.json` containing candidates, floors,
  metric definitions, tie-break order, credential/rate/retry policy, caps,
  stopping rules, and decision options. Refuse later parameter drift.

**Verification:** deterministic preparation test; preregistration hash and
packet-disjointness test; zero provider/worker calls.

## Task 2: Add pure intrinsic and regularity evaluators (TDD)

**Files:** `backend/app/services/gemini_consistency/provider_contract.py`,
`backend/tests/test_gemini_provider_contract.py`,
`backend/tests/fixtures/gemini_provider_contract/`

- Define provider-owned stage records and independent quality results with the
  exact universal result vocabulary from the objective.
- Implement requirements, Plan, geometry, and repair evaluators from frozen
  packet facts—not parser acceptance, worker results, topology, or candidates.
- Implement semantic, structural, identity, decision, geometry-strategy, and
  byte signatures; reproducible contract entropy; and canonicalization
  distance that excludes semantic repair.
- Add failing tests first for dropped meaning, operators, critical invention,
  empty nested records, empty ready Plans, missing features, wrong output
  count, invalid APIs, undefined symbols, missing result assignment, and the
  separation of semantic versus byte consistency.

**Verification:** focused evaluator tests, including proof that current-build
  fields cannot affect intrinsic scores.

## Task 3: Build the authoritative corpus and offline rescore

**Files:** `backend/scripts/run_gemini_provider_contract_foundation.py`,
`backend/app/services/gemini_consistency/provider_contract.py`

- Import all usable Phase 1 A-E records, Phase 2 calls, system-boundary A-D
  captures, replacement captures, preserved 429, and two 502 transport
  failures with immutable evidence paths and raw hashes.
- Keep transport/quota failures out of content scoring while retaining them in
  retry/rate evidence.
- Generate `intrinsic-quality-offline-rescore.json` and
  `contract-regularity-offline-rescore.json` with per-record and per-stage
  summaries. Record current-build outcomes only under diagnostic metadata.
- Stop or disqualify candidates only through preregistered floors; do not
  select by downstream compatibility.

**Verification:** offline-only execution assertion; corpus completeness and
  duplicate-operation tests; required report schema checks.

## Task 4: Implement secondary-only live runner and gated settings study

**Files:** `backend/scripts/run_gemini_provider_contract_foundation.py`,
`backend/tests/test_gemini_provider_contract.py`

- Render T0/current prompts from existing provider prompt builders and use the
  declared settings candidates S0-S3 with current prompts only.
- Explicitly read `GEMINI_API_KEY_2` into the child environment, unset primary
  aliases, and persist only safe credential labels.
- Use one shared limiter for all settings/thinking/prompt/holdout calls.
- Implement identical-payload retries: one retry after a 30-second monotonic
  wait for the first 429; one retry after at least 10 seconds for timeout/502/
  503/504; never a third attempt; preserve attempt IDs, hashes, waits, and
  final outcome.
- Run S0 and S1 first. Run S2/S3 only when the preregistered unresolved-seed
  gate authorizes them. Write results and decision reports even when a phase
  is gated off.

**Verification:** mocked retry/limiter/credential tests before any live call;
  inspect the preregistration and first live manifest; stop safely on quota or
  unfairness.

## Task 5: Select thinking configuration and prompts through gates

**Files:** runner, pure evaluator, `backend/tests/test_gemini_provider_contract.py`

- After settings selection, run H0/H1 on four frozen representative packets;
  run H2 only if the declared tradeoff gate authorizes it.
- After thinking selection, run T0/T1 on the six selection packets; run T2
  only for a repeated checklist-addressable defect; run T3 only for material
  structural variation after hardened-schema fixture tests pass.
- Apply the strict intrinsic/regularity ordering and record all skipped phases
  as `{run:false, reason:...}`.

**Verification:** profile-diff tests prove settings/thinking/prompt changes
  are isolated; gated-phase tests prove no premature live calls.

## Task 6: Freeze four provider contracts

**Files:** `contracts/gemini-flash-lite-*-contract-v1.json` under the new study
  root; report writers; docs

- Freeze requirements, Plan, geometry, and repair contracts with invariants,
  allowed/forbidden variation, canonical semantic representation, ownership
  map, and real selected-profile examples including known bad examples.
- Ensure Volundr-owned IDs/provenance/slots/scaffold symbols are explicitly
  separated from provider-owned semantic content.
- Generate the four required report files and include contract hashes in the
  final bundle.

**Verification:** contract-schema tests, ownership tests, and selected winning
  evidence examples.

## Task 7: Implement and test `GeminiProviderContractAdapter`

**Files:** `backend/app/services/gemini_consistency/provider_contract.py`,
`backend/tests/test_gemini_provider_contract.py`

- Parse raw responses, strip fences, validate invariants, normalize only
  allowed aliases/optional fields/generated identities, attach authoritative
  Volundr IDs/provenance/slots/result symbols, and emit typed action records.
- Reject missing meaning, ambiguity, protected-dimension changes, numeric
  changes, operation-order changes, invalid APIs, and unsupported repair.
- Never add geometry, invent semantic content, or manufacture verification.

**Verification:** TDD adapter tests for all required restrictions, action
  classes, semantic-hash preservation, deterministic rejection, and known bad
  responses.

## Task 8: Replay historical winners and run holdout validation

**Files:** runner, adapter, reports under the new study root

- Replay every intrinsically qualifying winning response offline and write
  `adapter-replay-results.json` and `adapter-decision.json`.
- Run the ten frozen holdout packets twice only after the provider contract and
  adapter gates authorize it; do not run full project workflows.
- Write provider and adapter decisions separately. Select one exact decision
  from the allowed vocabularies; never deploy it.

**Verification:** holdout disjointness, zero-call replay tests, adapter
  acceptance/rejection accounting, and holdout report completeness.

## Task 9: Bundle, document, and verify

**Files:** required `reports/*.json`,
`reports/all-provider-contract-responses.json`, eight new Gemini contract docs,
listed existing docs, tests

- Build the self-contained redacted manual-review bundle with every executed
  attempt, retry, request, response, score, signature, adapter action, and
  evidence path.
- Update documentation with provider/Volundr ownership and the separate
  provider/adapter decisions; state that production remains unchanged.
- Run redaction scanning and verify the secondary key value is absent from all
  artifacts.
- Run focused tests, full backend tests, frontend tests/build, migration-head,
  compile, `git diff --check`, and clean-worktree checks.
- Commit at verified rollback points matching the objective’s phase sequence;
  never rewrite existing commits or push.

**Final acceptance:** all required reports exist, gated phases are explicit,
  all executed attempts are bundled, provider/adapter decisions are separate,
  production files are unchanged, tests pass, and the worktree is clean.
