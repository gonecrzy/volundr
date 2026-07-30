# Volundr Test Strategy

This document defines the required automated coverage for CAD execution, AI-source extraction, mesh inspection, revision safety, frontend behavior, and regression fixtures.

## CadQuery Transition Status

The required final coverage is CadQuery-primary. Existing OpenSCAD tests should be preserved only while they keep transitional commits testable, then removed or replaced when OpenSCAD product paths are deleted.

## Testing Priorities

The highest-risk areas are:

1. untrusted CadQuery execution in an isolated worker
2. revision preservation
3. source extraction from AI output
4. failed-generation recovery
5. filesystem isolation
6. viewer compatibility with generated STL files

## Backend Unit Tests

### CAD runner and worker

Test:

- simple CadQuery solid executes
- worker runs as non-root
- worker environment lacks provider credentials
- worker has no network access where testable
- path traversal is rejected
- duplicate job completion is prevented
- artifact writes are atomic
- timeout kills descendant processes
- malformed manifests fail safely
- API receives structured worker failure results
- worker restart does not corrupt completed jobs
- STEP and STL artifacts are exported and hashed
- B-Rep topology is validated before STL mesh checks
- solid-count mismatch blocks required outputs
- intentional disconnected outputs require explicit policy

Transitional OpenSCAD coverage remains until removal:

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

- fenced `python`
- fenced `cadquery`
- strict raw CadQuery source when configured
- surrounding explanation
- multiple code blocks
- no valid source
- truncated source

### Source-contract validation

CadQuery tests must reject generated code that imports `os`, imports `subprocess`, imports network libraries, calls `open`, inspects environment variables, escapes job directories, writes arbitrary artifact paths, mutates interpreter/global state, or uses arbitrary top-level execution.

Transitional OpenSCAD tests:

Test:

- tokenizer ignores prohibited-looking text inside comments and strings
- real `import()`, `surface()`, `include`, `use`, suspicious paths, oversized source, missing legacy `main_model` or planned `render_selected_output`, missing final call, top-level geometry, unbalanced braces/parentheses, and empty final-output body block before compile
- new initial AI source requires the contract skeleton and Design Specification requirement/feature markers
- protected numeric values are statically verified with safe constant arithmetic
- unverifiable or mismatched protected values block before compile
- missing assertions, missing print notes, high `$fn`, repeated magic numbers, and unclear parameterization create quality findings rather than universal hard rejections
- contract repair is attempted at most once and remains distinct from compile repair
- compile repair starts only after source-contract hard checks pass
- source-contract failures create generation-attempt findings and no candidate

### Mesh inspection

Test:

- watertight cube
- disconnected components
- zero-volume or invalid mesh
- extreme dimensions
- excessive triangle count warning

### Geometric invariant validation

Test:

- exact protected bounds verify against mesh AABB
- absolute and relative dimension tolerance boundaries
- protected bounds, hole diameter, hole count, and hole spacing violations block only when confidence is high
- unverifiable protected holes warn rather than block
- build-plate violations remain blocking
- wall-thickness estimates use representative evidence or bounded approximations instead of a single noisy minimum
- analyzer failures become unverifiable findings and do not crash candidate creation
- geometric result artifacts persist analyzer version, tolerance-profile version, mesh hash, source hash, and linked validation findings
- geometric findings are available to candidate review and revision-from-finding context
- legacy candidates without analysis remain loadable

### Revisions

Test:

- complete initial AI request creates a ready Design Specification before CadQuery generation
- missing mating dimensions create clarification questions and no candidate
- conflicting dimensions and unsupported requests do not generate CadQuery source
- clarification answers create a new immutable Design Specification version
- invalid requirement-extraction JSON is persisted and gets at most one schema-repair attempt
- CadQuery generation cannot begin before a Design Specification is ready
- ready Design Specifications can create immutable `design-plan-v1` records
- plan clarification is represented as a planning state, not a failed revision
- invalid Design Plan JSON is persisted and repaired at most once
- CadQuery generation from the new initial flow cannot begin before the Design Plan is approved
- planned generation uses the Design Specification as requirements authority and the approved Design Plan as product-structure authority
- approved Design Plan printable outputs execute through the canonical multi-output pipeline in `docs/MULTI_OUTPUT_GENERATION.md`
- single-output plans produce one output artifact through the same pipeline
- multi-output plans persist one output artifact per declared printable output
- failed required outputs block the assembly candidate while preserving successful component artifacts
- failed optional outputs create advisory assembly findings when required outputs remain usable
- output retry executes the same source hash, parameter hash, and output ID and does not call the provider
- output manifests match persisted artifacts and exports include only the selected revision's files
- structured revision planning creates immutable `revision-plan-v1` records from the accepted Design Specification, approved Design Plan, output manifest, source metadata, and selected findings
- ambiguous revision requests create revision-plan clarification questions and no source generation
- CadQuery revision generation cannot begin before Revision Plan approval
- `cadquery-component-revision-v1` receives the approved Revision Plan, scoped revision context, active configuration context, selected findings, output manifest, and full base source
- revision compliance validation blocks unauthorized protected parameter, component, feature, dependency, output, shared helper, and interface changes before execution
- protected output preservation compares topology and mesh metadata after execution and blocks confirmed drift
- configured-base component revisions preserve parameter manifests and execute with the same resolved values
- `scope-correction-v1` runs at most once after source scope compliance failure and remains separate from contract/compile repair
- Revision Success Results persist planned success checks after candidate generation
- generated initial candidates link back to the Design Specification that produced them
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

### Live Generation Evaluation Harness

Test:

- dry-run benchmark runs write `run-manifest.json`, `aggregate-metrics.json`, `prompt-version-comparison.json`, per-case reports, prompt artifacts, and human scoring forms
- live Gemini mode is rejected unless explicitly enabled with the live-provider flag
- total run count and estimated prompt tokens are capped before provider calls
- repeated runs produce distinct case-run IDs
- prompt-version comparisons are report-only and cannot promote prompts
- run artifacts preserve benchmark input, prompt-template versions, provider settings, ruleset version, prompt hashes, status, and failure class

## Frontend Tests

Use Vitest for:

- project state
- revision selection
- generation status rendering
- error presentation
- parameter parsing
- printability findings and highlighted regions
- geometric check grouping for verified, violated, and unverifiable invariants
- blocked Accept reason when a geometric invariant blocks acceptance
- Design Plan stage labels, approval gating, and generic product-model summary counts
- Revision Plan stage labels, approval gating, scoped-change summary counts, compliance buckets, and success-result buckets

Use Playwright for critical workflows:

1. Open an accepted staged CadQuery project.
2. Confirm Python source and multi-output artifacts are visible.
3. Plan a scoped revision from chat.
4. Confirm generation is disabled before Revision Plan approval.
5. Approve the plan and generate the scoped candidate.
6. Confirm the active revision remains accessible until candidate acceptance.
7. Review Revision Plan compliance, success criteria, printable outputs, and advisory findings.
8. Accept the scoped candidate.
9. Plan a second revision that violates protected scope.
10. Confirm the rejected-before-compile scope findings are shown and the active revision remains unchanged.

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
7. Confirm source checks pass but geometric hole spacing blocks acceptance.
8. Start a revision from the geometric finding.
9. Reject the blocked candidate.
10. Confirm the accepted revision remains active.

Design Plan workflow coverage:

1. Extract requirements from an incomplete prompt.
2. Answer clarification and reach `requirements_ready`.
3. Create a Design Plan.
4. Review parameters, derived dependencies, components, printable outputs, and risks.
5. Approve the Design Plan.
6. Continue to CadQuery generation from the approved plan.
7. Confirm the resulting candidate does not replace the active accepted revision until accepted.

Structured revision workflow coverage:

1. Open a project with an accepted multi-output revision.
2. Submit a revision request and receive a Revision Plan.
3. Confirm source generation is disabled before approval.
4. Approve the Revision Plan.
5. Generate a scoped candidate.
6. Confirm active accepted revision remains unchanged until candidate acceptance.
7. Confirm revision compliance and success checks render.
8. Trigger a protected-scope compliance rejection before compile.
9. Confirm no new candidate is created and the active revision remains unchanged.

Component-targeted revision workflow coverage:

1. Open an accepted multi-output configured product.
2. Request a change to one component.
3. Review Revision Plan scope.
4. Approve revision.
5. Confirm Gemini returns complete source and the target output changes.
6. Confirm protected outputs remain equivalent or warn if preservation is unverifiable.
7. Confirm configuration overrides remain active.
8. Confirm pre-compile rejection when generated source changes a protected component or unapproved shared module.

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
- source-contract hard pass rate
- protected parameter mapping compliance
- required feature mapping compliance
- geometric invariant verification rates by supported invariant type
- geometric analyzer latency
- false-positive geometric blocking rate
- geometric unverifiable rate
- quality finding counts by rule
- Design Plan schema success rate
- Design Plan repair rate
- approved-plan-to-generation rate
- CadQuery generation attempts started without an approved Design Plan in the new flow

The benchmark harness should persist provider, model, prompt version, request payload, raw output, extracted source, hashes, timing, validation results, and failure class for every run.

Prompt templates must have snapshot tests. Snapshot failures should require an intentional prompt-template version update or explicit snapshot update.

Generation-attempt tests must verify that the structured requirements/design artifact can be persisted before CadQuery generation.

Candidate tests must use fake providers and deterministic STL fixtures. Live Gemini runs are not required for candidate-state, validation, or API transition changes.

Requirement-extraction tests must use fake providers and deterministic JSON fixtures. They must assert that clarification is not represented as a failed revision and that no candidate exists before explicit Continue to generation.

Design Plan tests must use fake providers and deterministic JSON fixtures. They must assert immutable persistence, supersession, approval/rejection, prompt/model/ruleset metadata, plan artifact hashes, and `openscad-generation-v5` prompt context.

Multi-output tests must use fake providers and deterministic STL fixtures. They must cover required and optional outputs, selected-output compiler invocation, component-scoped findings, assembly candidate classification, output manifest reproducibility, retry without provider calls, and ZIP export contents.

Structured revision tests must use fake providers and deterministic source/output fixtures. They must cover plan readiness, clarification, approval gating, finding-driven planning, superseding plans from clarification answers, prompt/model/ruleset persistence, revision compliance rejection before compile, success criteria, and active-revision preservation.

Component-targeted revision tests must use fake providers and deterministic source/output fixtures. They must cover full-source prompt mode, source ownership markers, normalized module fingerprints, allowed versus unapproved shared-module changes, protected module drift, output preservation blocking, interface parameter checks, component revision summaries, and active configuration preservation.
They must also cover that scope correction runs at most once and compilation begins only after corrected source passes scope compliance.

Parameter configuration tests must use deterministic accepted-source fixtures and must not call a provider. They must cover editable parameter listing, number/integer/boolean/enum validation, non-editable and derived-parameter rejection, preset preview, dependency impact expansion, `-D` override compilation, active-revision preservation, configuration-linked candidates, retry/export manifest behavior, and UI rendering for ready/invalid/requires-revision states.
