# Scaffold-owned geometry-function returns
> **Execution mode:** Inline Execution

**Goal:** Change structured CadQuery geometry bodies from provider-authored
returns to provider-authored statements plus a deterministic `result_symbol`.

**Architecture:** `assemble_geometry_bodies` will parse `statements`, reject
provider `return` statements, prove the result symbol is assigned on every
reachable path, append exactly one return, and retain raw/parsed/canonical/
assembled artifacts. The existing source/effect validators will inspect the
assembled function, preserving current CAD and parameter gates.

### Task 1: RED contract tests

**Files:** `backend/tests/test_cadquery_parameter_effects.py`,
`backend/tests/test_cadquery_source_scaffold.py`, new focused tests if needed.

- Add component and feature fixtures using `statements` and `result_symbol`.
- Add failures for missing, invalid, scaffold-owned, and unassigned symbols.
- Add failures for provider `return`, conditional result assignment, and
  discarded feature results.
- Verify the RED tests fail for the expected contract reason.

### Task 2: Deterministic assembly

**Files:** `backend/app/services/cad/geometry_bodies.py`,
`backend/app/services/projects/service.py`.

- Parse the new payload shape while rejecting legacy provider returns.
- Validate result-symbol identifiers and assignments.
- Reject unsafe or scaffold-owned symbols and non-guaranteed result paths.
- Append the single deterministic return before AST/effect validation.
- Preserve raw statements, parsed payload, canonical statements, assembled
  functions, and function hashes in existing generation artifacts.

### Task 3: Prompt and repair contract

**Files:** `backend/app/services/ai/gemini_cli.py`, focused prompt tests.

- Require `statements` and `result_symbol` in generation and repair prompts.
- Explicitly prohibit `return` statements from provider output.
- Bump only affected geometry-body prompt versions.

### Task 4: Verification and commits

- Run focused backend tests, full backend suite, frontend tests/build, and
  deterministic chat-first/staged Playwright suites with their correct flags.
- Commit the contract correction.
- Run the exact bottle-holder request once.
- If it reaches worker or fails for a different basic geometry contract,
  record the evidence without adding another broad validator.
- Commit live evidence separately and finish with `git diff --check` and a
  clean worktree.
