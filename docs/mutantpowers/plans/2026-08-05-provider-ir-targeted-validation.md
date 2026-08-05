# Provider IR Targeted Validation Plan
> **Execution mode:** Inline Execution

**Goal:** Measure exact Gemini emission of `volundr-geometry-ir-experimental-v1` for six frozen semantic tasks, paired with frozen `T5-geometry-exact-slot-contract-v1`, without changing production routing or authorizing Wave 02.

**Architecture:** Add a research-only frozen task corpus and study harness under `app.services.research` and `backend/scripts`. Reuse `GeminiFlashLiteContractV1`, `SecondaryGeminiClient`, `SharedIntegrationRateLimiter`, the existing T5 renderer/validator, and the experimental IR validator/compiler. Persist immutable raw attempts and derived boundary reports under `reports/provider-ir-targeted-validation-01/`; resume from existing operation captures without re-calling completed logical operations.

### Task 1: Freeze the paired corpus and contracts
**Files:** `backend/app/services/research/provider_ir_validation.py`, `backend/scripts/run_provider_ir_targeted_validation.py`, `backend/tests/test_provider_ir_targeted_validation.py`

- Define six deterministic task IDs, authoritative facts, obligations, output IDs, and matching T5/IR request contexts.
- Render the existing T5 prompt through `render_geometry_prompt_v2` without modification.
- Render one T6 prompt version from the IR schema and immutable contract text; hash it before calls.
- Generate and persist a deterministic shuffled 12-operation order before live mode.
- Freeze `gemini-3.5-flash-lite`, profile, S0 settings, H1 omission, credential policy, caps, and retry policy.

**Verification:** RED tests for immutable arm selection, identical task semantics, frozen prompt/profile, preregistered order, and Wave-02 closure; then targeted tests.

### Task 2: Add strict provider-boundary scoring
**Files:** `backend/app/services/research/provider_ir_validation.py`, `backend/tests/test_provider_ir_targeted_validation.py`

- Parse T5 and T6 responses without semantic repair, renaming, dependency insertion, or inferred frames.
- Validate T5 with the existing exact-slot validator and IR with `validate_geometry_ir` plus task obligations.
- Record first incorrect boundaries and separate provider contract, semantic, API/runtime, compiler, worker, topology, verification, normalization, and ambiguity classifications.
- Ensure malformed IR, CadQuery method names in typed operation names, unknown operations, missing dependencies, ambiguous frames, and raw escape violations fail closed.
- Keep synthetic/counterfactual records out of provider metrics and prevent downstream success from overriding upstream contract failure.

**Verification:** TDD tests for all required rejection and classification invariants.

### Task 3: Add deterministic downstream assembly and selective worker evidence
**Files:** `backend/app/services/research/provider_ir_validation.py`, `backend/scripts/run_provider_ir_targeted_validation.py`, `backend/tests/test_provider_ir_targeted_validation.py`

- Compile provider-valid IR only through the existing experimental compiler.
- Assemble provider-valid T5 slot statements through a research-owned deterministic wrapper preserving exact statements; do not normalize them into IR.
- Run static validation, CadQuery worker, topology, and task obligation checks only when their upstream boundary is valid and within the 12-job cap.
- Record source, compiler, worker, topology, and semantic-equivalence evidence separately.

**Verification:** Offline fixtures with zero provider calls; focused worker tests using known-good synthetic responses excluded from provider-success rates.

### Task 4: Add transport execution, resume, and evidence reports
**Files:** `backend/app/services/research/provider_ir_validation.py`, `backend/scripts/run_provider_ir_targeted_validation.py`, `backend/tests/test_provider_ir_targeted_validation.py`

- Require `GEMINI_API_KEY_2` through `SecondaryGeminiClient`; never access or probe the primary credential.
- Use the shared 12/15/5-second limiter, exact-request retry policy, one concurrency, and 12 logical-operation/18-attempt caps.
- Persist every attempt and idempotently resume completed operations without re-calling them.
- Emit every required report plus combined evidence with redacted credential metadata and hashes.

**Verification:** Transport/rate/retry tests, offline replay, resume-idempotence test, report completeness/redaction test, and live preflight with zero calls when secondary credential is absent.

### Task 5: Execute the authorized paired study
**Files:** `data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01/reports/provider-ir-targeted-validation-01/*`

- Run offline preregistration/replay first.
- Run exactly the preregistered 12 logical operations in fixed order, allowing only the specified transport retries.
- Run no representative Wave 02 and make no production routing changes.

**Verification:** Provider-attempt count, attempt cap, order, credential redaction, and no-production-import checks.

### Task 6: Analyze, decide, and complete verification
**Files:** `backend/app/services/research/provider_ir_validation.py`, `backend/scripts/run_provider_ir_targeted_validation.py`, report directory

- Calculate per-arm and paired-task rates and first-boundary summaries.
- Choose exactly one provider-IR decision and explicitly gate Wave 02.
- Run targeted study tests, IR/compiler/T5/source/worker/topology/verification regressions, full backend suite, migration-head, compile, stale-reference, diff-check, and clean-worktree checks.
- Commit at a verified rollback point; do not deploy, push, or alter production routing.

**Rollback:** Remove only the research module/script/tests/report commit; preserve prior `aaa161d` and existing historical evidence untouched.
