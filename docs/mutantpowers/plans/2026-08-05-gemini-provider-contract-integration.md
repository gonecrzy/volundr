# Gemini Provider Contract Integration Plan

> **Execution mode:** Inline Execution

**Goal:** Add an integration-only `gemini_flash_lite_contract_v1` workflow that
uses Volundr's real provider, requirements, Plan, geometry-slot,
source-assembly, worker, artifact, topology, verification, and candidate
decision boundaries while preserving production routing and historical study
evidence.

**Architecture:** A new `app.services.gemini_integration` package owns the
explicit profile, typed stage adapters, secondary-only provider transport,
rate/retry policy, capture records, frozen corpus, replay/counterfactual
analysis, and report generation. Existing production services are called via
small boundary protocols and are never changed to select this profile.

### Task 1: Freeze profile and repository evidence

**Files:** `backend/app/services/gemini_integration/profile.py`,
`backend/app/services/gemini_integration/prompts.py`,
`backend/tests/test_gemini_integration_profile.py`,
`backend/tests/test_gemini_integration_prompts.py`.

**Intent:** Define the versioned profile, exact S0 settings, H1 omission,
stage prompt selection, explicit activation guard, hashes, repository
snapshot, historical evidence inventory, and stage output-token limits.

**Verification:** Write failing profile/prompt-selection tests first; verify
the RED results, then make them pass. Confirm production settings still select
the existing `GeminiModelPolicy` path.

### Task 2: Add typed stage adapters

**Files:** `backend/app/services/gemini_integration/adapters.py`,
`backend/tests/test_gemini_integration_adapters.py`.

**Intent:** Expose `GeminiRequirementsContractAdapter`,
`GeminiPlanContractAdapter`, and `GeminiGeometryContractAdapter` using the
existing generic contract and geometry-slot canonicalizer primitives. Return
typed evidence records containing input/output hashes, normalization actions,
identity/provenance mappings, validation findings, and failure class. Fail
closed on invented fit facts, conflicting readiness, empty semantics,
invalid references, undefined symbols, invalid result assignment, ambiguous
aliases, and semantic geometry changes.

**Verification:** TDD all required requirements, Plan, geometry, identity,
provenance, and deterministic-normalization cases, including numeric literal
and statement-order preservation.

### Task 3: Add secondary-only transport, limiter, and capture primitives

**Files:** `backend/app/services/gemini_integration/transport.py`,
`backend/app/services/gemini_integration/capture.py`,
`backend/app/services/gemini_integration/redaction.py`,
`backend/tests/test_gemini_integration_transport.py`,
`backend/tests/test_gemini_integration_capture.py`.

**Intent:** Implement explicit `GEMINI_API_KEY_2` enforcement, one shared
monotonic limiter, 12/15 rolling-window policy, five-second gap, concurrency
one, exact identical retries, first-429 30-second retry, transport 10-second
retry, no third attempt, redacted durable request/response records, and
idempotent resume keys. Never read or probe the primary key.

**Verification:** TDD all rate/retry/redaction/resume requirements with fake
transport and monotonic clocks; verify no secret value is serialized.

### Task 4: Add frozen ten-project corpus and boundary runner

**Files:** `backend/app/services/gemini_integration/corpus.py`,
`backend/app/services/gemini_integration/workflow.py`,
`backend/tests/test_gemini_integration_corpus.py`,
`backend/tests/test_gemini_integration_workflow.py`.

**Intent:** Freeze deterministic IDs, facts, continuation answers, semantic
obligations, output expectations, unsafe-claim rules, and revision protection
for the ten required projects. Implement an explicit study-ID/provenance
runner that calls the real boundaries through injectable ports, captures every
boundary, stops normal execution at unsafe blockers, and continues forensic
inspection wherever evidence permits. No synthetic replacement workflow is
used; test doubles only stand in for individual external boundaries.

**Verification:** TDD exact corpus shape, clarification continuation,
boundary ordering, worker cap, provider cap, provenance isolation, and
multi-issue coexistence.

### Task 5: Add issue register, causal graph, replay, and counterfactuals

**Files:** `backend/app/services/gemini_integration/forensics.py`,
`backend/tests/test_gemini_integration_forensics.py`.

**Intent:** Record earliest blockers without overwriting latent defects, apply
the complete ownership taxonomy, preserve causal relationships, perform
offline stage validation, construct minimal one-variable counterfactuals,
exclude synthetic evidence from provider-success metrics, and produce
differential replay attribution only for changed outcomes.

**Verification:** TDD multiple independent issues, causal classifications,
offline-only replay, counterfactual exclusion, and advancement-is-not-fix
semantics.

### Task 6: Add report writer and CLI runner

**Files:** `backend/app/services/gemini_integration/reports.py`,
`backend/scripts/run_gemini_provider_contract_integration.py`,
`backend/tests/test_gemini_integration_reports.py`.

**Intent:** Create the required study directory, preregistration, snapshot,
profile, contracts, frozen corpus, per-operation captures, issue reports,
replay reports, rate/retry reports, decision, and redacted combined bundle.
Support `--study-id`, `--profile`, `--root`, `--replay`, `--counterfactual`,
`--dry-run`, `--resume`, and an explicit live-run mode. Reject every profile
except the integration profile before any provider or worker call.

**Verification:** TDD required report inventory, embedded evidence,
idempotent resume, redaction, cap enforcement, and activation guard.

### Task 7: Run offline baseline and live workflow if authorized by evidence

**Files:** generated only under
`data/debug-sessions/gemini-provider-contract-integration/gemini-provider-contract-integration-01/`
and `reports/`.

**Intent:** Snapshot before live work, preserve historical hashes, preregister
the ten projects, replay all available evidence, run the complete workflow
with `GEMINI_API_KEY_2` only when present, run deterministic validation and
worker/artifact/topology/verification boundaries, classify all detectable
issues, rank fixes, and apply only deterministic semantics-preserving
Volundr-owned corrections validated by differential replay.

**Verification:** Run focused integration tests, offline replay, and the
required backend/frontend/build/migration/compile/diff checks. Live calls stop
before starting when the secondary credential is absent and never fall back.

### Rollback and commits

Use verified rollback points matching the requested sequence: profile,
adapters, capture, corpus/runner, forensic replay, reports, and final
evidence. Never modify or overwrite historical study files. Do not push.
