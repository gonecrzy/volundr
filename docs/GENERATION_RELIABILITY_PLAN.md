# Generation Reliability Plan

## Goal

Make Volundr's Gemini generation measurable, reproducible, and harder to accept when it produces invalid, unprintable, or functionally weak models.

## Priority 0: Evaluation Blockers

### 1. Fix settings handling for repository-root test runs

- Dependency: none.
- Risk: low.
- Expected benefit: test and benchmark commands are reliable from common working directories; secret-like `.env` extras do not leak in pydantic validation errors.
- Required tests: backend suite from `backend/` and repo root.
- Exit criteria: both test commands collect and run the same tests.

### 2. Define stable failure taxonomy

- Dependency: none.
- Risk: low.
- Expected benefit: failures can be compared across prompts, providers, and benchmark runs.
- Required tests: taxonomy contains approved stable classes and persistence/evaluation helpers reject unknown classes.
- Exit criteria: provider, extraction, contract, compile, mesh, printability, revision, repair, clarification, benchmark, and observability failures use one shared vocabulary.

Stable failure classes:

```text
none
provider_failure
provider_timeout
source_extraction_failure
source_contract_hard_rejection
openscad_compile_failure
openscad_timeout
mesh_invalid
mesh_empty_or_zero_volume
mesh_non_watertight
validation_blocker
printability_blocker
clarification_missed
clarification_overasked
requirements_misread
unsafe_assumption
design_spec_missing
design_spec_invalid
revision_regression
repair_overreach
benchmark_fixture_invalid
observability_gap
unknown_failure
```

### 3. Persist generation attempt artifacts

- Dependency: none.
- Risk: medium because it touches persistence.
- Expected benefit: failed and successful generations can be reproduced.
- Required tests: provider failure creates attempt record; extraction failure records raw output and prompt payload; compile failure records failed source and diagnostics.
- Exit criteria: every provider call has prompt version, model, rendered request, raw output or error, status, failure class, and timing.

Persist the entire staged generation chain. During the legacy one-step phase this still records a single legacy OpenSCAD-generation stage plus any compile-repair stage. Each run record must include:

- prompt-template version
- Gemini ruleset version
- provider name, model, timeout, and non-secret provider settings
- rendered prompt
- request payload
- raw output
- extracted source
- intermediate artifacts
- source and output hashes
- validation summary
- failure class
- started/completed timestamps

### 4. Add benchmark fixture structure

- Dependency: none.
- Risk: low.
- Expected benefit: prompt changes can be compared using the same cases.
- Required tests: deterministic fake-provider benchmark runner can load `docs/GENERATION_BENCHMARKS.md` or a machine-readable companion fixture.
- Exit criteria: all 15 required benchmark cases exist as runnable test data.

Split benchmark fixtures into:

- core suite: frequent smoke coverage for common generation, one revision, one clarification, one conflict
- full stability suite: all benchmark categories, including support-risk and inaccessible-cavity cases

### 5. Add prompt snapshot infrastructure

- Dependency: prompt version identifiers.
- Risk: low.
- Expected benefit: prompt changes become intentional and reviewable.
- Required tests: rendered legacy initial, revision, and repair prompts match stored snapshots.
- Exit criteria: prompt snapshots fail when prompt text, context ordering, prompt-template version, or Gemini ruleset version changes unexpectedly.

### 6. Persist structured requirements/design artifacts before generation

- Dependency: generation attempt records.
- Risk: medium.
- Expected benefit: later staged generation can prove which requirement/design object produced the source.
- Required tests: a generation attempt can store and retrieve a structured design artifact before OpenSCAD generation.
- Exit criteria: the persistence layer supports structured requirements/design artifacts without invoking Gemini requirement extraction.

This Priority 0 item only implements storage and tests for the artifact shape. It does not implement the staged requirement-extraction prompt.

## Priority 1: Prompt And Contract Stabilization

### 7. Split prompt modes

- Dependency: prompt version identifiers.
- Risk: medium.
- Expected benefit: repairs stop acting like revisions; revisions preserve intent better.
- Required tests: snapshot rendered initial, revision, and repair prompts; repair prompt labels failed source correctly.
- Exit criteria: no prompt path calls failed source "current accepted source."

### 8. Enforce source-contract checks before compile

- Dependency: `docs/GEMINI_RULESET.md`.
- Risk: medium.
- Expected benefit: missing skeleton sections, forbidden constructs, missing assertions, and top-level geometry fail before expensive compile.
- Required tests: malformed AI outputs, comments containing `main_model();`, missing `USER PARAMETERS`, missing assertions, forbidden constructs.
- Exit criteria: contract failures become classified failed attempts, not accepted revisions.

Split source-contract results into:

- hard rejections: unsafe constructs, no valid source, empty source, no `main_model()`, multiple top-level model calls, top-level geometry outside `main_model()`, forbidden file access, source over size limit
- quality findings: missing assertions, missing print notes, weak parameter names, sparse assumptions, poor module boundaries, advisory `$fn` issues

Missing assertions alone should create a quality finding unless paired with invalid or unsafe dimensions.

### 9. Add requirement extraction and clarification decision

- Dependency: generation attempt records.
- Risk: medium-high because it changes API flow.
- Expected benefit: vague/conflicting prompts stop becoming weak generic models.
- Required tests: vague, conflicting, fit-critical, fastener-missing, and inaccessible-cavity benchmarks return clarification.
- Exit criteria: 100% benchmark clarification cases avoid SCAD generation.

Requirement extraction must produce a structured Design Specification. Every dimension and requirement must identify its source:

```text
user
calculated
profile_default
ai_assumption
```

Clarification evaluation must track both recall and precision so Volundr avoids both missed clarifications and excessive questioning.

## Priority 2: Validation And Acceptance

### 10. Add automatic validation summary after compile

- Dependency: printability profile default.
- Risk: medium.
- Expected benefit: acceptance decisions can use mesh and printability results.
- Required tests: zero volume, non-watertight, below build plate, build-volume violation, critical bridge.
- Exit criteria: validation results are persisted with severity and acceptance decision.

### 11. Introduce candidate revision state for AI generations

- Dependency: validation summary.
- Risk: product decision required.
- Expected benefit: users review assumptions and warnings before active revision changes.
- Required tests: successful AI generation with warnings is candidate; accepted prior revision remains active; user can accept candidate.
- Exit criteria: compile success no longer automatically means active design for all AI paths.

During stabilization, AI-generated results must not replace the active accepted revision automatically. Candidate review states are:

```text
ready
ready_with_warnings
blocked
rejected
accepted
```

### 12. Feed validation into revision context

- Dependency: persisted validation.
- Risk: medium.
- Expected benefit: revisions can address printability and mesh risks explicitly.
- Required tests: revision prompt includes latest validation summary; repair prompt does not receive broad printability warnings.
- Exit criteria: validation-driven user revisions preserve existing intent and target named findings.

## Priority 3: Product Confidence

### 13. Add generation run timeline

- Dependency: generation run state model.
- Risk: frontend/API medium.
- Expected benefit: users see whether Volundr is clarifying, generating, compiling, repairing, validating, or failed.
- Required tests: frontend state rendering and API state transitions.
- Exit criteria: UI no longer shows only `Sending` for the whole pipeline.

### 14. Add assumptions and parameter review UI

- Dependency: requirement/design-plan artifacts.
- Risk: medium.
- Expected benefit: users can catch silent assumptions before printing.
- Required tests: assumptions render; critical parameters render; accepted assumptions persist.
- Exit criteria: assumptions are visible without opening raw AI output.

### 15. Add dirty-source handling

- Dependency: none.
- Risk: low-medium.
- Expected benefit: AI revisions do not silently ignore uncompiled editor edits.
- Required tests: dirty source indicator; AI action warns or offers compile-first path.
- Exit criteria: user can tell whether Gemini will revise active source or local edited source.

## Metrics

Track per benchmark:

- extraction pass rate
- compile pass rate before repair
- compile pass rate after repair
- repair invocation rate
- repair success rate
- accepted-with-blocking-validation rate
- required parameter compliance
- prohibited feature violation rate
- clarification precision and recall
- protected design invariant preservation
- revision preservation score
- median provider latency
- median compile time
- source size
- triangle count
- printability severity counts

## Stability Exit Criteria

Volundr's generation pipeline is stable enough for prompt iteration when:

- 95% or better extraction success on non-clarification benchmark outputs.
- 90% or better compile success before repair.
- 95% or better compile success after bounded repair.
- 0 accepted models with blocking validation failures.
- 95% or better required-parameter compliance.
- 90% or better revision benchmarks preserve unrelated critical dimensions and modules.
- 100% vague/conflicting benchmark prompts produce clarification instead of accepted SCAD.
- Clarification precision remains high enough that clear core-suite prompts are not over-clarified.
- Every generation has a reproducible run record.
