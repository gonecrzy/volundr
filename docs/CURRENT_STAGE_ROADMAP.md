# Volundr Current Stage Roadmap

This document records the implementation sequence, current stage status, milestone goals, and exit criteria. Codex should update it whenever a milestone changes state.

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

- New initial AI generations now pass through `requirements-v1` before OpenSCAD generation.
- Design Specifications are immutable, versioned, persisted, and linked to requirement-extraction attempts and generated revisions.
- Clarification, conflicting requirements, and unsupported requests are normal states rather than failed generation revisions.
- A ready Design Specification must be explicitly continued before OpenSCAD generation starts.
- Legacy active-revision AI edits remain supported during the transition and attach the latest Design Specification as context when available.

Source-contract validation pass:

- New AI source is statically checked before OpenSCAD compilation.
- Security, hard source structure, and protected Design Specification compliance violations block compilation and persist as generation-attempt findings.
- Quality issues such as missing assertions, missing print notes, excessive `$fn`, and repeated magic numbers remain advisory and attach to candidates after successful compile/validation.
- Generated source now uses `source-contract-v1` markers documented in `docs/MODEL_GENERATION_CONTRACT.md`.
- Contract repair is a bounded `contract-repair-v2` mode and remains separate from compile repair.
- Legacy accepted source remains usable and is not retroactively rejected.

Geometric invariant validation pass:

- Compiled AI candidates with Design Specifications now run `geometric-invariants-v1` after mesh inspection and before candidate classification.
- Supported checks include protected overall bounds, build-plate placement, common axis-aligned cylindrical holes, hole count, two-hole spacing, and coarse wall thickness.
- Confirmed high-confidence protected invariant violations block acceptance; unverifiable protected features create warnings for human review.
- Source markers now include `@volundr-geometry` metadata for measurable features in `openscad-generation-v3`.
- Legacy candidates without geometric analysis remain loadable and are labeled as not evaluated.

Next implementation boundary:

Completed in this pass:

- immutable `design-plan-v1` records are persisted and linked to ready Design Specifications and planning generation attempts
- Design Plans capture product parameters, derived parameters, dependency edges, components, component features, presets, assembly strategy, printable outputs, risks, and design level
- plan states are explicit: `clarification_required`, `pending_review`, `approved`, and `rejected`
- the frontend now creates a Design Plan from ready requirements, presents it for review, requires explicit approval, and generates OpenSCAD from the approved plan
- `openscad-generation-v5` uses the Design Specification as requirements authority and the approved Design Plan as product-structure authority
- source metadata now recognizes `@volundr-component`, `@volundr-dependency`, and `@volundr-output` markers in addition to requirement, feature, and geometry markers
- approved Design Plan printable outputs now compile into per-output STL artifacts through the selector contract in `docs/MULTI_OUTPUT_GENERATION.md`
- the candidate review workflow now exposes assembly status, component output states, per-output downloads, SCAD download, manifest download, ZIP export, and safe retry for failed outputs

Next implementation boundary:

Structured revision planning pass:

- `revision-planning-v1` now creates immutable scoped plans from the accepted Design Specification, approved Design Plan, output manifest, source metadata, and selected findings
- revision-plan states are explicit: `clarification_required`, `pending_review`, `approved`, and `rejected`
- revision source generation uses `openscad-revision-v2` only after explicit plan approval
- revision compliance validation blocks unauthorized protected parameter, component, feature, dependency, and output changes before compile
- success criteria are persisted as Revision Success Results after candidate generation

Next implementation boundary:

- implement component-targeted revisions that use the approved Revision Plan to constrain Gemini to specific components/outputs where practical
- do not begin direct parameter editing, preset switching, or full Design Plan regeneration until component-targeted revision behavior is stable

Correct trajectory from the geometric invariant checkpoint:

```text
1. Parametric Product Model and Design Plan
2. Multi-component and multi-output generation
3. Structured revision planning
4. Component-targeted revisions
5. Parameter controls and preset switching
6. Assembly instructions and export packaging
7. Complex real-world benchmark testing
8. Slicer integration and deeper printability checks
```

Deferred stabilization work:

- component-targeted AI revisions after structured revision planning exists
- automatic continue policies
- full protected-invariant geometry proof for arbitrary features
- geometric proof that feature markers correspond to complex physical geometry such as angled holes, threads, snap fits, or internal cavities

## Stage 4 — Projects and Revision History

Status: Complete for legacy revisions; structured revision planning implemented; component-targeted revisions pending

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
- parameter controls update the OpenSCAD source directly
- existing Compile action recompiles parameter edits without AI
- invalid numeric edits are ignored instead of being written into source

Goals:

- parse marked user parameters
- display numeric and boolean controls
- recompile without AI
- validate parameter edits

Exit criteria:

- critical dimensions can be changed without spending an AI generation request

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

## Stage 8 — Advanced Interaction

Status: Future

Possible goals:

- screenshot or image feedback
- annotations
- SVG import
- reusable feature library
- CadQuery/build123d provider
- STEP export
