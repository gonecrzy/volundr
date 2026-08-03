# Volundr Current Stage Roadmap

This document records the implementation sequence, current stage status, milestone goals, and exit criteria. Codex should update it whenever a milestone changes state.

## Active Transition

Status: requirement-led revisions implemented; live quality remains separately
gated by actual worker and functional evidence.

The active roadmap is the CadQuery-primary architecture transition defined in
`docs/CADQUERY_BACKEND.md`, planned in
`docs/mutantpowers/plans/2026-07-30-cadquery-primary-transition.md`, and
verified in `docs/CADQUERY_TRANSITION_EVALUATION.md`. The historical stages
below describe how the old OpenSCAD implementation was built; they are not the
current architecture.

Current product-shell checkpoint: proportional planning, persistent chat-first
projects, indefinite revision history, explicit selected-revision export, and
safe Current working version protection are implemented. Archived projects are
preserved by default. The first observed frontend session uses deterministic
fixtures while live CAD-quality evaluation remains a separate track.

V1 multipart support is limited to simple component/output relationships and
printable-part packaging. True assembly mates, ports, kinematics, and mechanism
support remain later work.

Transition order:

1. Establish CadQuery/Gemini/chat-first documentation authority.
2. Replace the idle CAD worker with a real isolated execution boundary.
3. Replace SCAD-shaped persistence with CadQuery-native source and artifact fields.
4. Promote CadQuery source validation into the production `cadquery-v1` contract.
5. Execute single-output and multi-output CadQuery products with STEP/STL artifacts and topology validation.
6. Make Gemini API and the chat-first lifecycle the default generation path under the feature flag.
7. Rebuild deterministic parameter configuration around typed CadQuery execution.
8. Rebuild structured and component-targeted revisions around active requirements, optional controls, and topology evidence.
9. Align the frontend and Playwright workflow with the staged CadQuery lifecycle.
10. Remove OpenSCAD product paths.
11. Run the functional CadQuery/Gemini benchmark gate. Live Gemini API smoke,
    12-case source-gate, Design Plan, configuration, and solid-count
    negative-control runs are recorded in
    `docs/CADQUERY_TRANSITION_EVALUATION.md`.
12. Add workflow observability for real project diagnosis before broad frontend
    user testing. Workflow runs, event logs, artifact registry records,
    first-failure diagnosis, stage traces, frontend correlation, debug bundles,
    and run comparison are defined in `docs/WORKFLOW_OBSERVABILITY.md`.

The compact/detailed interoperability hardening pass is implemented and
documented in `docs/COMPACT_DETAILED_HARDENING_LIVE_EVALUATION.md`.
Normalization now distinguishes printable components from integral features,
fixed/proposed layouts from configurable patterns, and Plan identities from
provider locals. The final five-case live matrix remains gated by genuine
provider/source and detailed-plan failures; continue deterministic chat-first
UX testing in parallel. Do not use a live CAD result as a UX fixture or expand
this into a general analytics platform or another broad CAD validation redesign.

The current frontend checkpoint is complete: the persistent three-region chat
workspace, responsive drawer/tab fallbacks, persisted assistant messages,
recoverable connection state, explicit export drawer, and deterministic UX
coverage are implemented. Observed usability testing may begin with fixtures;
live CAD-quality testing remains separately gated.

The developer-assisted debug-batch correction checkpoint is complete for round
1. Durable evidence, complete build identity, attempt/candidate
classification, generic repair convergence, comparison labeling, deterministic
tests, and one qualifying post-correction five-project batch are recorded in
`LIVE_BATCH_CORRECTION_ROUND_1.md` and
`MIXED_CAD_LIVE_POST_CORRECTION_01.md`. The next gated work is generic
provider/schema/provenance convergence; no product-family CAD correction is
part of the current checkpoint. Observed usability testing remains a separate
track.

## Stage 0 — Foundation Documents

Status: Complete

- Product direction
- MVP scope
- Architecture
- Model-generation contract
- CAD execution security
- Data model
- Codex kickoff prompt

## Stage 1 — Secure CAD Runner

Status: Complete

Goals:

- FastAPI skeleton
- SQLite setup
- OpenSCAD CLI wrapper
- temporary job directories
- compile timeout
- structured compile result
- STL generation
- trimesh metadata
- backend tests
- Docker Compose development environment using `volundr-web`, `volundr-api`, and `volundr-cad-worker`

Exit criteria:

- valid SCAD produces an STL
- invalid SCAD returns structured diagnostics
- timeout behavior is tested
- generated output metadata is stored
- no AI integration is required

## Stage 2 — Browser CAD Workspace

Status: Complete

Implemented:

- manual project creation API
- manual OpenSCAD revision compile API
- persisted source, STL, compile log, and metadata files
- browser workspace with OpenSCAD editor, compile action, revision list, STL preview, metadata, and STL download
- SCAD download
- compile diagnostics display
- active revision restore for successful manual revisions

Goals:

- React/Vite application
- project list
- Monaco editor
- compile action
- Three.js STL viewer
- model metadata panel
- SCAD/STL download

Exit criteria:

- user can manually author or paste OpenSCAD
- user can compile it
- user can inspect and download the result

## Stage 3 — Gemini CLI Generation

Status: Complete as a basic integration; stabilization required

Current status:

- provider abstraction added
- Gemini CLI subprocess adapter added
- SCAD source extraction added
- initial generation endpoint added
- browser generation prompt added
- live generation works with API-key based Gemini CLI authentication
- failed extraction and compile attempts are preserved as failed revisions
- compile failures trigger one bounded AI repair attempt

Goals:

- Gemini CLI authentication documentation
- provider abstraction
- generation prompt
- SCAD extraction
- initial model generation
- error display
- one bounded repair attempt

Exit criteria:

- plain-English prompt creates a compilable model
- raw AI output and extracted source are preserved
- failures are visible and recoverable

Stabilization gap:

- generation is currently one-step and prompt-mode mixed
- clarification is not representable
- prompt versions and full request payloads are not persisted
- compile success can accept functionally weak or critically unprintable AI models
- `docs/GENERATION_RELIABILITY_PLAN.md` now defines the required stabilization work before generation quality can be called dependable

Approved stabilization amendments:

- persist the full staged generation chain and intermediate artifacts
- use a structured Design Specification with dimension and requirement source labels
- implement candidate revisions during stabilization so AI results do not replace the active accepted revision automatically
- use candidate review states: `ready`, `ready_with_warnings`, `blocked`, `rejected`, `accepted`
- separate blocking validations from advisory warnings
- split source-contract hard rejections from quality findings
- use a stable failure taxonomy
- reject repair output that changes protected design invariants
- split benchmarks into core and full stability suites
- track clarification recall and clarification precision

Next implementation boundary:

- Priority 0 only: settings handling, failure taxonomy, generation-attempt persistence, machine-readable benchmark fixtures, deterministic benchmark harness, and prompt snapshot infrastructure.
- Do not implement staged requirement extraction until Priority 0 is complete, tested, and committed.

Priority 0 completion:

- Commit `f7cadb2` completed enough observability and fixture infrastructure to support candidate stabilization work.

Candidate stabilization pass:

- AI-generated successful revisions now become explicit candidates instead of automatically replacing the active accepted revision.
- Candidate states are `ready`, `ready_with_warnings`, `blocked`, `rejected`, and `accepted`.
- Validation findings are persisted and split into blocking findings and advisory warnings.
- Accept, reject, finding dismissal, candidate listing, candidate findings, and active accepted revision endpoints are available.

Requirement extraction pass:

- New initial AI generations now pass through `requirements-v1` before CadQuery generation.
- Design Specifications are immutable, versioned, persisted, and linked to requirement-extraction attempts and generated revisions.
- Clarification, conflicting requirements, and unsupported requests are normal states rather than failed generation revisions.
- A ready Design Specification must be explicitly continued before CadQuery generation starts.
- Legacy active-revision AI edits remain supported during the transition and attach the latest Design Specification as context when available.

Source-contract validation pass:

- New AI source is statically checked before CAD execution.
- Security, hard source structure, and protected Design Specification compliance violations block compilation and persist as generation-attempt findings.
- Quality issues such as missing assertions, missing print notes, excessive `$fn`, and repeated magic numbers remain advisory and attach to candidates after successful compile/validation.
- Generated source now uses `source-contract-v1` markers documented in `docs/MODEL_GENERATION_CONTRACT.md`.
- Contract repair is a bounded `cadquery-contract-repair-v1` mode and remains separate from execution repair.
- Earlier stabilization passes allowed accepted OpenSCAD-era source to remain usable. The CadQuery-primary transition no longer treats old development source as a compatibility target.

Geometric invariant validation pass:

- Compiled AI candidates with Design Specifications now run `geometric-invariants-v1` after mesh inspection and before candidate classification.
- Supported checks include protected overall bounds, build-plate placement, common axis-aligned cylindrical holes, hole count, two-hole spacing, and coarse wall thickness.
- Confirmed high-confidence protected invariant violations block acceptance; unverifiable protected features create warnings for human review.
- Source markers now include `@volundr-geometry` metadata for measurable features in `openscad-generation-v3`.
- Earlier stabilization passes labeled candidates without geometric analysis as not evaluated. The CadQuery-primary transition uses fresh CadQuery candidates with topology, mesh, and printability evidence.

Next implementation boundary:

Completed in this pass:

- immutable `design-plan-v1` records are persisted and linked to ready Design Specifications and planning generation attempts
- Design Plans capture product parameters, derived parameters, dependency edges, components, component features, presets, assembly strategy, printable outputs, risks, and design level
- plan states are explicit: `clarification_required`, `pending_review`, `approved`, and `rejected`
- the frontend now creates a Design Plan from ready requirements, presents it for review, and starts CadQuery generation when the user approves the plan
- `openscad-generation-v5` uses the Design Specification as requirements authority and the approved Design Plan as product-structure authority
- source metadata now recognizes `@volundr-component`, `@volundr-dependency`, and `@volundr-output` markers in addition to requirement, feature, and geometry markers
- approved Design Plan printable outputs now compile into per-output STL artifacts through the selector contract in `docs/MULTI_OUTPUT_GENERATION.md`
- the candidate review workflow now exposes assembly status, component output states, per-output downloads, SCAD download, manifest download, ZIP export, and safe retry for failed outputs
- blocker review now uses typed recovery actions for the first common cases: build-volume findings can route the user to printer-profile review, and mesh/geometry blockers can prepare scoped revision prompts from the selected finding
- requirement, Design Plan, and revision-plan clarification can now be answered from the main chat input; each message fills the next unanswered clarification question and submits when the answer set is complete

Next implementation boundary:

Structured revision planning pass:

- `revision-planning-v1` now creates immutable scoped plans from the accepted Design Specification, approved Design Plan, output manifest, source metadata, and selected findings
- revision-plan states are explicit: `clarification_required`, `pending_review`, `approved`, and `rejected`
- revision source generation uses the approved Revision Plan only after explicit plan approval; current UI approval immediately starts source revision when the plan has no unresolved clarification
- revision compliance validation blocks unauthorized protected parameter, component, feature, dependency, and output changes before compile
- success criteria are persisted as Revision Success Results after candidate generation

Component-targeted revision pass:

- approved Revision Plans currently feed `openscad-component-revision-v1`; the CadQuery transition replaces this with `cadquery-component-revision-v1`
- Gemini must return the complete authoritative CadQuery source in the target architecture; Volundr does not splice source fragments
- source metadata now includes shared-module ownership and normalized module fingerprints
- protected component modules, output mappings, interface parameters, and shared modules are checked before compile
- one bounded `cadquery-scope-correction-v1` attempt can revert unauthorized source-scope changes before execution
- active configuration override manifests are preserved through component AI revisions
- all required outputs compile through the canonical multi-output pipeline
- protected outputs are compared with `output-preservation-v1` after compile; confirmed drift blocks candidates and unverifiable preservation warns
- candidate review now exposes component revision summaries

Next implementation boundary:

- run real-world generation-quality testing with varied functional products before expanding revision intelligence
- do not begin slicer integration, source-fragment generation, or automatic geometry correction

Live generation-quality evaluation pass:

- `live-benchmark-harness-v1` creates controlled run manifests, artifact directories, prompt-version comparisons, per-case reports, human scoring forms, aggregate metrics, and quota gates
- dry-run mode verifies benchmark selection and artifact capture without provider calls
- live Gemini mode requires explicit opt-in and remains bounded by run and token limits
- prompt promotion is intentionally disabled; results must be reviewed manually to decide whether the next work belongs in prompt quality, Design Plan quality, component decomposition, parameter modeling, geometry generation, printability, revision preservation, or UX
- full behavior is defined in `docs/LIVE_GENERATION_EVALUATION.md`

Source-derived parameter discovery pass:

- accepted CadQuery source can now expose typed `ParameterSpec` metadata before adding richer editing UX
- `GET /api/revisions/{revision_id}/parameters` returns read-only controls derived from persisted typed parameter metadata
- this is a phase gate for evaluating whether AI output exposes useful creative and functional knobs without forcing generated models into one fixed template
- CadQuery source probes now run through an AST-based `cadquery-v1` contract before execution; this keeps the probe focused on `import cadquery as cq`, typed module-level `PARAMETERS`, `build(params)`, `Product`, and `PrintableOutput` while rejecting unsafe imports, top-level geometry execution, and dynamic Python calls
- `cadquery-generation-v1` tightens live-generation guidance around recurring CadQuery failures: no `math`/`map()`/string parsing, numeric `thread_spec`, closed profiles before `extrude()`, and fused creative one-piece geometry instead of loose decorative bodies

Source-probe benchmark pass:

- phase-validation runs can now include `--source-probe` to ask the provider for direct CAD source without accepting a candidate
- source-probe runs use the CadQuery path; `--source-language cadquery` is the only supported product source language
- source-probe runs can add `--source-brief` to force a compact structured understanding pass before source generation, then compare the brief's intended body count/features against compile and mesh artifacts
- source probe artifacts capture raw source output, extracted source when valid, exact expected-parameter coverage from `ParameterSpec` metadata, CadQuery execution logs, STEP/STL/BREP output, topology metadata, and mesh metadata
- source-probe repair can now be enabled with `--source-probe-repair` to run one bounded repair pass after failed source extraction, failed source-probe compile, or a source-brief connected-body mismatch while keeping first-pass and repaired metrics separate
- bounded source-probe repair uses `cadquery-contract-repair-v1` or execution diagnostics with the failed Python source and traceback as context
- Gemini API is the primary live benchmark provider; Ollama remains optional comparison only, and every provider must pass the same CadQuery source-probe validation loop
- prompt syntax guardrails now explicitly reject pseudo-CAD method chaining, recursive modules, lowercase `pi`, invalid `circle(r1/r2)` usage, and unbounded thread/knurl tricks
- source-probe parameter targets must be emitted as exact top-level identifiers rather than renamed aliases, arrays, indexed values, or derived-only values
- this provides a cheap in-between signal for prompt/model changes before spending time on full CAD geometry review

Correct trajectory from the geometric invariant checkpoint:

```text
1. Parametric Product Model and Design Plan
2. Multi-component and multi-output generation
3. Structured revision planning
4. Component-targeted full-source revisions
5. Parameter controls and preset switching
6. Live generation-quality evaluation
7. Evidence-driven prompt, planning, decomposition, parameter, geometry, printability, revision, or UX improvements
8. Assembly instructions and export packaging
9. Slicer integration and deeper printability checks
```

Deferred stabilization work:

- source-fragment revisions and AST module splicing
- automatic continue policies
- full protected-invariant geometry proof for arbitrary features
- geometric proof that feature markers correspond to complex physical geometry such as angled holes, threads, snap fits, or internal cavities

## Stage 4 — Projects and Revision History

Status: Complete for legacy revisions, structured revision planning, deterministic configuration, and component-targeted full-source revisions

Current status:

- immutable revision records are persisted
- parent revision IDs are stored for manual, AI, and repair revisions
- active revision is updated only by explicit candidate acceptance or restore of an accepted revision
- AI-generated successful compiles create candidate revisions rather than active revisions
- successful prior revisions can be restored
- failed AI attempts remain visible and are not accepted
- projects can be renamed and archived
- project messages are persisted and shown in the workspace

Goals:

- immutable revisions
- parent-child history
- active revision
- restore workflow
- accepted versus failed attempts
- project messages

Exit criteria:

- every successful generation is recoverable
- no working model is overwritten

## Stage 5 — Conversational Revisions

Status: Complete

Current status:

- generation uses the active revision source as current-source context
- follow-up AI revisions are labeled `ai_revision`
- failed follow-up generations use the same preservation and bounded repair path as initial generations
- selected child revisions show a unified source diff against their parent
- new structured AI revisions require an approved Revision Plan before source generation
- revision compliance validation rejects unauthorized protected changes before compile

Goals:

- revision prompt built from original intent, current source, and new instruction
- minimal-edit prompting
- revision diff
- compile and repair
- restore after bad revision
- structured plan that names targeted parameters, features, components, outputs, protected invariants, dependencies, and success checks

Exit criteria:

- common dimensional and feature changes preserve unrelated geometry

## Stage 6 — Parameter Controls

Status: Complete

Current status:

- browser parses simple numeric and boolean assignments in the marked `USER PARAMETERS` section
- parameter controls execute accepted CadQuery source with validated parameter values
- existing Compile action recompiles parameter edits without AI
- invalid numeric edits are ignored instead of being written into source
- approved Design Plan parameters now have a separate Configure workflow
- configuration previews persist immutable `configuration-change-v1` records
- configuration candidates execute accepted CadQuery source with validated parameter manifests and no Gemini call
- project-local presets and Design Plan presets can feed configuration previews
- configuration exports include `configuration.json` and `parameter-overrides.json`

Goals:

- parse marked user parameters
- display numeric and boolean controls
- recompile without AI
- validate parameter edits

Exit criteria:

- critical dimensions can be changed without spending an AI generation request
- accepted source remains immutable during parameter configuration
- invalid or structural parameter changes route to structured revision planning

Next implementation boundary:

- component-targeted revisions using structured Revision Plans and configuration/geometric findings as context.

## Stage 7 — Printability Assistance

Status: In progress; validation-backed candidate acceptance implemented

Goals:

- orientation-aware printability inspector
- configurable FDM printer profile
- structured Pass, Notice, Warning, and Critical results
- affected-geometry highlighting where practical
- model orientation suggestions
- basic wall-thickness warnings
- overhang heuristics

Stabilization note:

- AI and post-active manual compile results run deterministic validation before candidate state is exposed.
- Build-volume, below-build-plate, floating, zero-volume, and hard feature-size findings block acceptance.
- Support-related findings remain advisory unless future validation can prove a hard machine limit.

Excluded from this increment:

- slicer CLI integration
- filament and print-time estimates

## Stage 8 — Frontend Workflow And User Testing

Status: Chat-first deterministic gate passed; observed UX testing may proceed

Current status:

- the primary UI follows Describe, essential Clarify, automatic planning and generation, Current working version, revision, and explicit Export
- user-provided values, Volundr proposals, calculated values, and essential decisions are distinct in review
- Current working version and blocked/new attempts remain distinct; passing versions promote automatically under the flag
- multi-output and recoverable blocked states have user-facing explanations
- diagnostic bundles and workflow IDs remain secondary Technical details

Next activity:

- conduct observed UX sessions with deterministic known-good and known-failure fixtures
- preserve event traces, diagnosis, and redacted debug bundles
- address the highest repeated user consequence before further architecture work

## Stage 9 — Advanced Interaction

Status: Future

Possible goals:

- screenshot or image feedback
- annotations
- SVG import
- reusable feature library
- CadQuery/build123d provider
- STEP export

## Current workflow gate

Planning depth is implemented in the existing workflow engine: direct briefs,
compact plans, and detailed plans converge on one GeometryExecutionContext.
Every design remains revisionable through chat; exposed controls remain
optional and explicitly requested. The next quality gate is evidence from the
three exact planning-depth live cases, not a new user-facing planning mode.

The current product pass is the feature-flagged chat-first workflow, durable
project/export path, and separate real-provider live diagnostics. Keep the
staged/developer workflow only for diagnostic coverage. See
`docs/CHAT_FIRST_WORKFLOW.md`, `docs/PROJECT_PERSISTENCE.md`, and
`docs/EXPORTS.md`.

The current evidence pass adds deterministic post-worker multi-view packets,
component thumbnails, conservative sections, and revision comparisons. The
next visual step is advisory review design, not an automatic image gate.

Derived dependency classification is implemented: ordinary designs are not
blocked by unused malformed planning metadata, while exposed controls,
configurable patterns, scaffold obligations, and generated-source dependencies
retain hard gates. The exact spacer live evaluation is the evidence check for
worker reachability and resumed snapshot/export behavior.

The current source-correctness checkpoint also includes a generic
geometry-body symbol contract: provider-loaded names must resolve within the
scaffold-owned function scope, and one safely targeted runtime repair is
allowed. This does not restore source-parametric obligations for ordinary
requirements.

Requirement-trace classification is now the artifact-consistency checkpoint:
ordinary fixed requirements can reach the worker with geometry-verification
evidence, while exposed controls, protected identities, and genuinely missing
required features remain hard gates. See
[`REQUIREMENT_TRACE_CONTRACT.md`](REQUIREMENT_TRACE_CONTRACT.md).

The requirement-pipeline audit is implemented: semantic operators and
capacity object types remain authoritative through planning, unique trace
links normalize deterministically, measurable ordinary requirements may defer
to worker verification, and exposed-control/source identity gates remain
strict. The next live evidence item is the preserved tackle-holder worker
failure or an honest requirements clarification, not another source-style
gate.

Pattern coordinate-space validation and chat-message identity correction are
implemented. The tackle-tray project remains a valid blocked live-quality
case: the latest attempt was stopped before worker execution because the
provider still tried to consume component-space placements as planar points.
