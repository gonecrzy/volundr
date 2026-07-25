# Volundr Test Strategy

This document defines the required automated coverage for CAD execution, AI-source extraction, mesh inspection, revision safety, frontend behavior, and regression fixtures.

## Testing Priorities

The highest-risk areas are:

1. untrusted CAD execution
2. revision preservation
3. source extraction from AI output
4. failed-generation recovery
5. filesystem isolation
6. viewer compatibility with generated STL files

## Backend Unit Tests

### CAD runner

Test:

- simple cube compiles
- difference operation compiles
- invalid syntax returns failure
- missing output returns failure
- timeout terminates process
- oversized source is rejected
- forbidden import is rejected
- output metadata is populated
- temporary files are cleaned safely

### Source extraction

Test AI responses containing:

- plain SCAD
- fenced `scad`
- fenced `openscad`
- surrounding explanation
- multiple code blocks
- no valid source
- truncated source

### Mesh inspection

Test:

- watertight cube
- disconnected components
- zero-volume or invalid mesh
- extreme dimensions
- excessive triangle count warning

### Revisions

Test:

- create initial revision
- create child revision
- failed attempt does not replace active revision
- restore old revision
- manual edit creates a new revision
- AI generation creates a candidate instead of replacing the active revision
- ready and ready-with-warnings candidates can be accepted explicitly
- blocked, rejected, and already accepted candidates cannot transition incorrectly
- advisory validation findings can be dismissed without deletion
- blocking validation findings cannot be dismissed into acceptability

## Frontend Tests

Use Vitest for:

- project state
- revision selection
- generation status rendering
- error presentation
- parameter parsing
- printability findings and highlighted regions

Use Playwright for critical workflows:

1. Create project.
2. Enter or paste SCAD.
3. Compile successfully.
4. View model.
5. Download source.
6. Make manual edit.
7. Compile as new revision.
8. Restore previous revision.

After Gemini integration:

1. Create project from prompt.
2. Observe generation progress.
3. Receive model.
4. Request a revision.
5. Restore earlier revision after a failed change.

Candidate stabilization workflow:

1. Open a project with an accepted revision.
2. Generate a deterministic AI candidate.
3. Confirm the active revision remains accessible.
4. Review advisory findings.
5. Accept the candidate.
6. Generate a blocked candidate.
7. Confirm Accept is disabled with a specific blocking reason.
8. Reject the blocked candidate.
9. Confirm the accepted revision remains active.

## Fixture Models

Maintain a small set of SCAD fixtures:

- cube
- mounting plate
- cylindrical holder
- box with lid
- invalid syntax
- runaway/high-complexity pattern
- disconnected components

## Regression Policy

Every AI-generated model that exposes a new compiler or extraction bug should be sanitized and added as a regression fixture when practical.

Printability fixtures should cover zero-volume or empty meshes, non-watertight meshes, disconnected components, build-volume violations, Z-origin violations, low build-plate contact, thin-feature estimates, overhang angle buckets, and simple horizontal bridge spans.

## Generation Benchmark Policy

Use `docs/GENERATION_BENCHMARKS.md` as the canonical prompt benchmark set for generation reliability. Prompt changes should not be considered improvements until they are measured against that set.

Maintain machine-readable fixtures under `backend/tests/fixtures/generation_benchmarks/`:

- `core.json` for frequent deterministic benchmark checks
- `full.json` for full stability evaluation

Track at minimum:

- extraction pass rate
- compile pass rate before and after bounded repair
- clarification precision and recall
- required parameter compliance
- prohibited feature violations
- accepted revisions with blocking validation failures
- revision preservation
- protected design invariant preservation
- repair boundedness

The benchmark harness should persist provider, model, prompt version, request payload, raw output, extracted source, hashes, timing, validation results, and failure class for every run.

Prompt templates must have snapshot tests. Snapshot failures should require an intentional prompt-template version update or explicit snapshot update.

Generation-attempt tests must verify that the structured requirements/design artifact can be persisted before OpenSCAD generation, even before staged requirement extraction is implemented.

Candidate tests must use fake providers and deterministic STL fixtures. Live Gemini runs are not required for candidate-state, validation, or API transition changes.
