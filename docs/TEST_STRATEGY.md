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

### Source-contract validation

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

- complete initial AI request creates a ready Design Specification before OpenSCAD generation
- missing mating dimensions create clarification questions and no candidate
- conflicting dimensions and unsupported requests do not generate SCAD
- clarification answers create a new immutable Design Specification version
- invalid requirement-extraction JSON is persisted and gets at most one schema-repair attempt
- OpenSCAD generation cannot begin before a Design Specification is ready
- ready Design Specifications can create immutable `design-plan-v1` records
- plan clarification is represented as a planning state, not a failed revision
- invalid Design Plan JSON is persisted and repaired at most once
- OpenSCAD generation from the new initial flow cannot begin before the Design Plan is approved
- planned generation uses the Design Specification as requirements authority and the approved Design Plan as product-structure authority
- approved Design Plan printable outputs compile through the canonical multi-output pipeline in `docs/MULTI_OUTPUT_GENERATION.md`
- single-output plans produce one output artifact through the same pipeline
- multi-output plans persist one output artifact per declared printable output
- failed required outputs block the assembly candidate while preserving successful component artifacts
- failed optional outputs create advisory assembly findings when required outputs remain usable
- output retry recompiles the same source hash and does not call the provider
- output manifests match persisted artifacts and exports include only the selected revision's files
- structured revision planning creates immutable `revision-plan-v1` records from the accepted Design Specification, approved Design Plan, output manifest, source metadata, and selected findings
- ambiguous revision requests create revision-plan clarification questions and no source generation
- OpenSCAD revision generation cannot begin before Revision Plan approval
- `openscad-revision-v2` receives the approved Revision Plan as its change authority
- revision compliance validation blocks unauthorized protected parameter, component, feature, dependency, and output changes before compile
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
6. Continue to OpenSCAD generation from the approved plan.
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
- OpenSCAD generation attempts started without an approved Design Plan in the new flow

The benchmark harness should persist provider, model, prompt version, request payload, raw output, extracted source, hashes, timing, validation results, and failure class for every run.

Prompt templates must have snapshot tests. Snapshot failures should require an intentional prompt-template version update or explicit snapshot update.

Generation-attempt tests must verify that the structured requirements/design artifact can be persisted before OpenSCAD generation, even before staged requirement extraction is implemented.

Candidate tests must use fake providers and deterministic STL fixtures. Live Gemini runs are not required for candidate-state, validation, or API transition changes.

Requirement-extraction tests must use fake providers and deterministic JSON fixtures. They must assert that clarification is not represented as a failed revision and that no candidate exists before explicit Continue to generation.

Design Plan tests must use fake providers and deterministic JSON fixtures. They must assert immutable persistence, supersession, approval/rejection, prompt/model/ruleset metadata, plan artifact hashes, and `openscad-generation-v5` prompt context.

Multi-output tests must use fake providers and deterministic STL fixtures. They must cover required and optional outputs, selected-output compiler invocation, component-scoped findings, assembly candidate classification, output manifest reproducibility, retry without provider calls, and ZIP export contents.

Structured revision tests must use fake providers and deterministic source/output fixtures. They must cover plan readiness, clarification, approval gating, finding-driven planning, superseding plans from clarification answers, prompt/model/ruleset persistence, revision compliance rejection before compile, success criteria, and active-revision preservation.

Parameter configuration tests must use deterministic accepted-source fixtures and must not call a provider. They must cover editable parameter listing, number/integer/boolean/enum validation, non-editable and derived-parameter rejection, preset preview, dependency impact expansion, `-D` override compilation, active-revision preservation, configuration-linked candidates, retry/export manifest behavior, and UI rendering for ready/invalid/requires-revision states.
