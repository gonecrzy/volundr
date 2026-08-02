# Volundr Test Strategy

This document defines the required automated coverage for CAD execution, AI-source extraction, mesh inspection, revision safety, frontend behavior, and regression fixtures.

## CadQuery Transition Status

The required coverage is CadQuery-primary.

## Testing Priorities

The highest-risk areas are:

1. untrusted CadQuery execution in an isolated worker
2. revision preservation
3. source extraction from AI output
4. failed-generation recovery
5. filesystem isolation
6. viewer compatibility with generated STL files
7. workflow observability, first-failure diagnosis, and debug-bundle redaction
8. durable project reopen, stale-workflow recovery, and explicit export integrity

Requirement-led coverage additionally verifies that ordinary numeric values do
not activate source-effect obligations, explicit controls do, active
requirements remain coherent across long revision chains, physical-test
feedback is retained, and failed or stale revisions cannot replace the Current
working version.

Planning-depth coverage verifies semantic route selection, direct briefs with
zero planning-provider calls, compact-plan normalization, detailed-plan
compatibility, immutable route/context/pack artifacts, stable context hashes,
and deterministic narrow revision briefs. The three live planning cases remain
separate from deterministic UX fixture evidence.

Product Validation Round 1 adds a five-case real-provider matrix and a real
browser spacer/export acceptance record. The matrix is diagnostic: provider,
worker, topology, artifact, and promotion gates remain authoritative, and a
blocked live case is not converted into a UX fixture. See
`docs/LIVE_DESIGN_MATRIX_EVALUATION.md`.

Provider interoperability coverage also asserts contract-manifest identity and
ownership evidence, focused Plan and geometry repair preservation, localized
worker-diagnostic repair, hash-based loop prevention, and accurate blocked
outcomes. See `docs/PROVIDER_INTEROPERABILITY_LIVE_EVALUATION.md`.

Compact and detailed Plan regression coverage additionally checks provider
pattern aliases (`feature_id`, cardinal `direction`, `spacing_mm`, and numeric
fixed `count`), typed normalization findings, fixed-layout acceptance without
parameter IDs, strict configurable-layout behavior, and single-output
component/output consistency. Workflow-observability tests verify that a
provider-successful Plan validation block is not recorded as failure class
`none`, and that diagnosis reports the authoritative Plan finding or blocked
attempt stage rather than reporting no blocking evidence.

The normal chat-first path automatically progresses validated requirements and
plans, generates a first draft, and promotes only passing candidates. Approval
button scenarios remain developer/staged-mode coverage behind the disabled
chat-first flag; they are not the ordinary product workflow.

### Chat workspace

Test the persistent conversation, semantic assistant outcomes, optimistic
submission/retry behavior, exact connection-error copy, empty state, current
version preservation, historical selection, explicit export drawer, and
responsive desktop/drawer/tab layouts. Run chat-first and staged Playwright
suites independently. Use deterministic fixtures for UX evaluation and keep
real-provider/CadQuery live quality runs opt-in and separate.

### Persistence and export

Test:

- project library summaries identify the current/latest revision and printable
  part count
- `/projects/{id}` reopens the authoritative workspace after reload
- interrupted running workflows become abandoned without duplicate provider work
- missing registered artifacts are reported instead of presented as downloadable
- STL, STEP, assembly STEP, printable-parts ZIP, and complete project-package
  exports are deterministic and persisted as `ExportRecord` rows
- blocked revisions cannot be exported
- duplicate export requests return the same completed record
- cross-project revision selection is rejected
- export packages contain history, requirements, source, manifests, and hashes
  without credentials

### Browser persistence and export coverage

The deterministic browser suite verifies stable project URLs, reload/reconnect,
project-library summaries, automatic Current working version promotion,
blocked-attempt preservation, explicit export, and staged-mode compatibility.
Run chat-first and staged suites separately; live browser tests remain opt-in.

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
- old development candidates without analysis are not compatibility targets for the CadQuery-primary test matrix

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
- `cadquery-scope-correction-v1` runs at most once after source scope compliance failure and remains separate from contract/execution repair
- Revision Success Results persist planned success checks after candidate generation
- generated initial candidates link back to the Design Specification that produced them
- create initial revision
- create child revision
- failed attempt does not replace active revision
- restore old revision
- manual edit creates a new revision
- AI generation creates a candidate instead of replacing the active revision

### Workflow observability

Test:

- initial generation creates a root workflow run with trace configuration
- requirement, Design Plan, source, repair, worker, candidate, acceptance, configuration, component revision, output retry, and export stages emit structured events
- two nearly simultaneous events retain deterministic `sequence_number` order
- retried submissions use deterministic deduplication keys
- failed repair and worker retry evidence remains visible after later success
- output retry snapshots preserve the earlier worker result before mutating latest output state
- stale running workflows can be classified as `abandoned`
- first-failure diagnosis separates root failures from downstream symptoms
- stage trace reports protected/default/explicit value drift and source/output hashes
- debug bundles include expected manifests and exclude large geometry by default
- fake API keys, authorization headers, cookies, provider tokens, signed URLs, and database secrets are redacted or cause bundle refusal
- unknown frontend event names and oversized/unowned frontend event batches are rejected
- run comparison detects parameter regressions without treating every metric reduction as an improvement
- project deletion removes workflow trace rows and generated debug bundles
- observability records do not alter candidate classification or lifecycle behavior
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

1. Start from a prompt that requires requirement clarification.
2. Answer the clarification from chat and reach `requirements_ready`.
3. Create, review, approve, and generate from a Design Plan.
4. Confirm the generated CadQuery candidate exposes Python source, printable outputs, and geometric checks.
5. Open an accepted staged CadQuery project.
6. Confirm Python source and multi-output artifacts are visible.
7. Plan a scoped revision from chat.
8. Confirm generation is disabled before Revision Plan approval.
9. Approve the plan and generate the scoped candidate.
10. Confirm the active revision remains accessible until candidate acceptance.
11. Review Revision Plan compliance, success criteria, printable outputs, and advisory findings.
12. Accept the scoped candidate.
13. Plan a second revision that violates protected scope.
14. Confirm the rejected-before-compile scope findings are shown and the active revision remains unchanged.
15. Open a blocked CadQuery candidate with one successful required output and one failed required output.
16. Confirm solid-count topology rejection is visible, Accept is disabled, and the active accepted revision remains unchanged.

### Deterministic browser gate

`frontend/e2e/workflow-gate.spec.ts` starts a disposable FastAPI fixture server
with the production project router, project service, workflow recorder, SQLite
persistence, controlled provider, and controlled CAD worker. It does not route
mock API responses in the browser. The fixture summary endpoint is test-only
and exposes bounded run, event, artifact, provider-call, frontend-event, and
revision assertions.

The deterministic gate covers the explicit part, intent-first holder,
configurable organizer, enclosure lid revision, and recoverable blocked
candidate workflows. Scenario 5 uses separate multiple-solid and worker-failure
fixtures and asserts that the accepted revision remains safe, blocked
acceptance is rejected, topology recovery is routed to a part-specific
revision request, and worker retry uses unchanged source and parameter hashes
without a provider call. Both blocked paths assert correlated frontend events
and diagnostic-bundle evidence. The gate is run serially because the summary
endpoint is scoped to disposable fixture projects.

Live Gemini browser smoke tests are implemented under `frontend/e2e/live/` and
remain opt-in. Run them with:

```bash
VOLUNDR_RUN_LIVE_E2E=true npm --prefix frontend run test:e2e:live
```

The wrapper creates disposable SQLite/CAD workspace state, upgrades the real
API database, starts the real CAD worker with blank Gemini variables, and
sources the API key only in the backend process. It scans generated evidence
for the exact key before cleanup. The two live cases assert durable lifecycle
behavior, workflow correlation, provider latency, topology evidence, and
diagnostic-bundle redaction without asserting Gemini wording or exact geometry.
They are not part of the deterministic Playwright suite or normal CI.

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
8. Confirm pre-execution rejection when generated source changes a protected component or unapproved shared helper.

## Fixture Models

Maintain a small set of CadQuery fixtures:

- cube
- mounting plate
- cylindrical holder
- box with lid
- invalid Python/source-contract cases
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

Design Plan tests must use fake providers and deterministic JSON fixtures. They must assert immutable persistence, supersession, approval/rejection, prompt/model/ruleset metadata, plan artifact hashes, and CadQuery generation prompt context.

Multi-output tests must use fake providers and deterministic STEP/STL fixtures.
They must cover required and optional outputs, requested-output worker execution,
component-scoped findings, assembly candidate classification, output manifest
reproducibility, retry without provider calls, and ZIP export contents.

Structured revision tests must use fake providers and deterministic source/output fixtures. They must cover plan readiness, clarification, approval gating, finding-driven planning, superseding plans from clarification answers, prompt/model/ruleset persistence, revision compliance rejection before compile, success criteria, and active-revision preservation.

Component-targeted revision tests must use fake providers and deterministic source/output fixtures. They must cover full-source prompt mode, source ownership metadata, allowed versus unapproved shared-helper changes, protected component drift, output preservation blocking, interface parameter checks, component revision summaries, and active configuration preservation.
They must also cover that scope correction runs at most once and compilation begins only after corrected source passes scope compliance.

Functional design regressions cover explicit interface validation, protected-parameter data flow, feature invocation, mounting direction, support floors, typed revision criteria, and the failed holder evidence.

Parameter configuration tests must use deterministic accepted-source fixtures and must not call a provider. They must cover editable parameter listing, number/integer/boolean/enum validation, non-editable and derived-parameter rejection, preset preview, dependency impact expansion, `-D` override compilation, active-revision preservation, configuration-linked candidates, retry/export manifest behavior, and UI rendering for ready/invalid/requires-revision states.

## Frontend User Workflows

Frontend unit tests cover user-facing vocabulary, provenance grouping, progress labels, current/new-version distinction, multi-output blocking explanation, recovery language, and fixed telemetry names. Playwright covers the vertical new-project path, deterministic configuration, scoped revision, and a blocked multi-output candidate. The five observed-user scenarios and required diagnostic evidence are in `docs/FRONTEND_USER_TESTING_PLAN.md`.

Chat-first backend tests cover automatic progression, clarification resume,
provider-free parameter routing, persisted revision plans, idempotent chat
submission, stale-promotion protection, working-version promotion, blocked
attempt preservation, and export summaries. Playwright runs the chat-first
scenarios with `VITE_VOLUNDR_CHAT_FIRST=true`; the staged suite remains
available through `npm run test:e2e:staged` during transition.

Snapshot tests cover deterministic camera metadata, stable raster output,
durable packet and image registration, artifact ownership, conservative section
omission, worker-retry capture, and revision geometry/finding deltas.
`snapshot-evidence.spec.ts` exercises standard views and comparison evidence;
`multi-view-snapshot.live.spec.ts` is opt-in and uses the real provider and
worker.

Derived dependency tests cover both sides of the execution boundary: malformed
unused metadata must reach assembly and remain a warning, while broken
exposed-control, configurable-pattern, scaffold, and generated-source paths
must remain blocking. Tests also inspect persisted scaffold-manifest evidence,
warning severity, classification reasons, and mixed blocking/diagnostic
findings. The exact spacer live case verifies that this diagnostic does not
invoke geometry repair or prevent worker and snapshot evaluation.

Geometry-body source-scope tests cover lexical bindings, conservative definite
assignment, comprehension/exception scope, approved aliases/helpers, bare
parameter diagnostics, deterministic scaffold scope, result symbols, repair
scope preservation, and defensive runtime `NameError` classification. The
exact live spacer case is also the worker/snapshot regression for the previous
unbound `plate_width` defect.

Requirement-trace tests cover integral features implemented by component
functions, fixed counts deferred to geometry verification, owner aliases,
ambiguous owners, exposed-control source traces, missing required features,
single-output integral features, multipart/output conflicts, and typed
diagnosis evidence. The exact tackle-tray rerun is retained as a live
artifact-consistency regression.
