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

### 2. Persist generation attempt artifacts

- Dependency: none.
- Risk: medium because it touches persistence.
- Expected benefit: failed and successful generations can be reproduced.
- Required tests: provider failure creates attempt record; extraction failure records raw output and prompt payload; compile failure records failed source and diagnostics.
- Exit criteria: every provider call has prompt version, model, rendered request, raw output or error, status, failure class, and timing.

### 3. Add benchmark fixture structure

- Dependency: none.
- Risk: low.
- Expected benefit: prompt changes can be compared using the same cases.
- Required tests: deterministic fake-provider benchmark runner can load `docs/GENERATION_BENCHMARKS.md` or a machine-readable companion fixture.
- Exit criteria: all 15 required benchmark cases exist as runnable test data.

## Priority 1: Prompt And Contract Stabilization

### 4. Split prompt modes

- Dependency: prompt version identifiers.
- Risk: medium.
- Expected benefit: repairs stop acting like revisions; revisions preserve intent better.
- Required tests: snapshot rendered initial, revision, and repair prompts; repair prompt labels failed source correctly.
- Exit criteria: no prompt path calls failed source "current accepted source."

### 5. Enforce source-contract checks before compile

- Dependency: `docs/GEMINI_RULESET.md`.
- Risk: medium.
- Expected benefit: missing skeleton sections, forbidden constructs, missing assertions, and top-level geometry fail before expensive compile.
- Required tests: malformed AI outputs, comments containing `main_model();`, missing `USER PARAMETERS`, missing assertions, forbidden constructs.
- Exit criteria: contract failures become classified failed attempts, not accepted revisions.

### 6. Add requirement extraction and clarification decision

- Dependency: generation attempt records.
- Risk: medium-high because it changes API flow.
- Expected benefit: vague/conflicting prompts stop becoming weak generic models.
- Required tests: vague, conflicting, fit-critical, fastener-missing, and inaccessible-cavity benchmarks return clarification.
- Exit criteria: 100% benchmark clarification cases avoid SCAD generation.

## Priority 2: Validation And Acceptance

### 7. Add automatic validation summary after compile

- Dependency: printability profile default.
- Risk: medium.
- Expected benefit: acceptance decisions can use mesh and printability results.
- Required tests: zero volume, non-watertight, below build plate, build-volume violation, critical bridge.
- Exit criteria: validation results are persisted with severity and acceptance decision.

### 8. Introduce candidate revision state for AI generations

- Dependency: validation summary.
- Risk: product decision required.
- Expected benefit: users review assumptions and warnings before active revision changes.
- Required tests: successful AI generation with warnings is candidate; accepted prior revision remains active; user can accept candidate.
- Exit criteria: compile success no longer automatically means active design for all AI paths.

### 9. Feed validation into revision context

- Dependency: persisted validation.
- Risk: medium.
- Expected benefit: revisions can address printability and mesh risks explicitly.
- Required tests: revision prompt includes latest validation summary; repair prompt does not receive broad printability warnings.
- Exit criteria: validation-driven user revisions preserve existing intent and target named findings.

## Priority 3: Product Confidence

### 10. Add generation run timeline

- Dependency: generation run state model.
- Risk: frontend/API medium.
- Expected benefit: users see whether Volundr is clarifying, generating, compiling, repairing, validating, or failed.
- Required tests: frontend state rendering and API state transitions.
- Exit criteria: UI no longer shows only `Sending` for the whole pipeline.

### 11. Add assumptions and parameter review UI

- Dependency: requirement/design-plan artifacts.
- Risk: medium.
- Expected benefit: users can catch silent assumptions before printing.
- Required tests: assumptions render; critical parameters render; accepted assumptions persist.
- Exit criteria: assumptions are visible without opening raw AI output.

### 12. Add dirty-source handling

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
- Every generation has a reproducible run record.

