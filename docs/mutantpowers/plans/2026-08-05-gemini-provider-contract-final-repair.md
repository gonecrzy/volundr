# Gemini Provider Contract Final Repair Plan
> **Execution mode:** Inline Execution

**Goal:** Move unambiguous scaffold alias normalization into Volundr, isolate genuine model-owned repair defects, qualify T3, run the exact H1 holdout, replay qualified records through the adapter, and record the final provider/adapter decisions without changing production behavior.

**Base:** `c3bc0af`; preserve all existing commits and historical evidence.

### Task 1: Audit repair ownership and preserve evidence
**Files:** `backend/scripts/run_gemini_provider_contract_correction.py`, `backend/tests/test_gemini_provider_contract_correction.py`; generated correction reports.
**Intent:** Audit all twelve prior repair records, classify packet/evaluator/model ownership, and preserve the prior reports and hashes. No provider or worker calls.
**Verification:** Offline audit report has 12 records, zero calls, and identifies repair-correction-02 as mixed/under-specified because its union is vacuous.

### Task 2: Add deterministic geometry-slot canonicalization
**Files:** `backend/app/services/gemini_consistency/geometry_slot_canonicalizer.py`, `backend/app/services/gemini_consistency/provider_contract.py`, tests.
**Intent:** Implement `GeometrySlotContractCanonicalizer` with AST validation, sole-authoritative-input alias replacement, numeric/order/method preservation, action logs, semantic self-union rejection, and fail-closed ambiguity handling. Keep it experiment-scoped and do not alter production provider settings.
**Verification:** Focused canonicalizer tests cover safe R2A, ambiguous aliases, numeric/order preservation, and R2B `body.union(body)` rejection.

### Task 3: Replace mixed repair fixtures with genuine model-owned packets
**Files:** `backend/scripts/run_gemini_provider_contract_correction.py`, tests; generated `repair-packets-v2.json` and canonicalization report.
**Intent:** Add offline R2A/R2B classification and M1 result assignment, M2 invalid CadQuery keyword, and M3 missing subtractive operation packets with complete source, protected items, dimensions, responsibilities, and defect patterns.
**Verification:** R2A canonicalizes without Gemini; R2B remains rejected; each M packet passes validity checks.

### Task 4: Add and run T3 executable-replacement study
**Files:** correction runner, tests; generated T3 reports.
**Intent:** Add `T3-repair-executable-replacement-v1`, compare only T2 and T3 on M1–M3 × two repetitions, and use executable-payload scoring. Correct the retry implementation to retry a first 429 once after at least 30 seconds, never a second 429, and retry transport failures at most once.
**Verification:** T3 reaches 6/6 before holdout authorization; all attempts are recorded, actual model is exact, H1 omits `thinkingConfig`, and focused retry tests pass.

### Task 5: Freeze the complete stage-specific provider contract
**Files:** correction runner, tests; generated `final-stage-profile.json` and versioned correction contracts.
**Intent:** Freeze S0, H1, requirements T2, Plan/geometry T0, repair T3, and deterministic canonicalization ownership with packet/profile hashes and forbidden semantic repairs.
**Verification:** Profile report is complete and immutable within the correction evidence root.

### Task 6: Run corrected H1 holdout
**Files:** correction runner, tests; generated H1 holdout reports.
**Intent:** Run exactly ten holdout intentions × two repetitions with final profiles, shared limiter, secondary key only, real repair source, and no workers/Ollama.
**Verification:** 20/20 content passes, exact model, no `thinkingConfig`, separate transport/quota counts, and semantic repeatability before adapter replay.

### Task 7: Replay qualified records through adapter
**Files:** correction runner, adapter/canonicalizer tests; generated adapter reports.
**Intent:** Replay requirements T2, historical qualified Plan/geometry T0, repair T3, and corrected H1 holdout. Adapter may normalize only documented representation aliases and must fail closed on ambiguity.
**Verification:** Zero provider/worker calls during replay; all intrinsically valid final records accepted; actions and semantic hashes preserved.

### Task 8: Record final decisions and verify
**Files:** correction runner, required docs, tests; final combined bundle.
**Intent:** Write required reports, retry/rate reports, redacted combined bundle, final provider/adapter decisions, and update documentation. Keep production unchanged.
**Verification:** Required report names exist, redaction passes, prior evidence hashes match, focused tests pass, `git diff --check` passes, and worktree is clean.

Use separate commits at each verified task boundary, matching the objective’s requested sequence.
