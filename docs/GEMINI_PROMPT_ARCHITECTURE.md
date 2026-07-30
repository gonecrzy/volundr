# Gemini Prompt Architecture

## Goal

Gemini should not be asked to infer requirements, decide whether to clarify, design a printable product, write CadQuery, revise accepted source, and repair execution failures in one prompt. Volundr uses small versioned stages with structured inputs and outputs.

## CadQuery Transition Status

Gemini API is the primary runtime AI provider. CadQuery prompt modes are the
active product path. OpenSCAD prompt modes in this document are historical
implementation paths retained for context only. Ollama may remain an optional
development adapter, but prompt quality is evaluated against Gemini API first.

## Prompt Stages

### `requirements-v1`

Responsibility: convert user text into a structured Design Specification. Do not generate source.

Input context:

- prompt version
- project name
- original intent
- latest user instruction
- active design record, when revising

Output: valid JSON matching the Design Specification schema in `docs/DATA_MODEL.md`.

Every dimension and requirement must identify one source from `user`, `clarification`, `calculated`, `printer_profile`, `product_default`, or `ai_assumption`. The structured Design Specification must be persisted and associated with the requirement-extraction generation attempt before CadQuery generation starts.

Current implementation: `requirements-v1` is implemented for new initial AI generations. Invalid JSON is classified as `design_spec_invalid`, raw output is preserved, and one bounded schema-repair extraction attempt is allowed.

The persisted Design Specification schema remains strict. Before validation, the backend may normalize common unambiguous provider variants such as `name` to `label`, `default_value` to `value`, string functional requirements to requirement objects, and `assumption` to `description`. This normalization must not invent missing critical dimensions or turn an underspecified request into `generation_ready`.

### `clarification-v1`

Responsibility: decide whether Volundr can safely generate or must ask one or more questions.

Clarify instead of generate when:

- the part must fit an object and a mating dimension is missing
- fasteners are mentioned without size, head style, or spacing
- load-bearing use is implied without load direction or mounting orientation
- dimensions conflict
- axes are ambiguous and affect function
- the request implies inaccessible internal cavities
- the requested shape likely requires severe unsupported spans unless supports are acceptable
- a revision changes a critical dimension and would affect fit or assembly

Output schema:

```json
{
  "stage": "clarification-v1",
  "action": "generate|clarify|reject",
  "questions": ["What is the outside diameter of the hose?"],
  "defaultable_assumptions": [
    {"name": "wall_thickness", "value_mm": 3}
  ],
  "reason": "hose adapter fit cannot be inferred safely"
}
```

### `design-plan-v1`

Responsibility: create a generic immutable Parametric Design Plan from an approved Design Specification. Do not generate source.

Input context:

- approved Design Specification JSON
- original request as secondary intent
- versioned product and printer defaults
- previous Design Plan when replanning
- clarification questions and answers when the plan stage requested them

Output: valid JSON matching the Design Plan schema in `docs/DATA_MODEL.md`.

Required content:

- user-editable parameters and protected parameters
- derived parameters expressed from other parameters
- dependency edges showing what must update when a configuration changes
- direct `source_requirement_id` mappings only when the parameter copies the source requirement value and unit; calculated stack, envelope, and overall dimensions belong in derived parameters
- components and the features that belong to each component
- presets for common configurations when useful
- assembly strategy
- printable outputs, even when there is only one output in this pass
- risks and mitigations
- `design_level` as `single_part`, `product`, or `assembly`
- `plan_ready`, `clarification_required`, and `outcome`

Current implementation: `design-plan-v1` is implemented for ready initial Design Specifications. Invalid JSON is classified as `design_plan_invalid`, raw output is preserved, and one bounded schema-repair planning attempt is allowed. A clarification plan enters `clarification_required`; chat answers are persisted, then planning is rerun with the previous plan and answer context to create a superseding version. A ready plan enters `pending_review`; the user must approve it before CadQuery generation can start, and current UI approval immediately starts generation.

### `openscad-generation-v3`

Responsibility: legacy path that produces source-contract-compliant OpenSCAD from an approved Design Specification and ruleset.

Input context:

- requirements object
- persisted Design Specification artifact path or hash
- clarification decision with `action=generate`
- design plan
- archived OpenSCAD ruleset context, only for historical benchmark review
- target printer profile summary

Output:

- exactly one fenced `openscad` block
- no prose outside the block
- strict historical OpenSCAD source skeleton
- protected requirement markers and feature markers as defined in the archived OpenSCAD contract
- source-assisted geometry markers for measurable bounds, holes, hole groups, and wall-thickness regions as defined in `docs/GEOMETRIC_INVARIANT_VALIDATION.md`
- protected values copied exactly from the Design Specification and exposed as named parameters

Current implementation: historical only; product generation uses CadQuery prompt modes.

### `openscad-generation-v5`

Responsibility: legacy path that produces source-contract-compliant OpenSCAD from both an approved Design Specification and an approved Parametric Design Plan.

Input context:

- Design Specification JSON as requirements authority
- approved Design Plan JSON as product-structure authority
- archived OpenSCAD ruleset and source contract
- printer profile/default context
- raw user request as secondary intent only

Output additions compared with `openscad-generation-v3`:

- `@volundr-component <design_plan_component_id>` markers
- `@volundr-feature <design_plan_feature_id>` markers
- `@volundr-dependency <from_parameter_id> -> <to_parameter_id>` markers for derived assignments
- `@volundr-output <output_id> module=<module_name> required=<true|false> filename=<safe_filename.stl> components=<component_ids>` markers
- `selected_output` and `render_selected_output();` dispatch for every printable output, including single-output designs
- editable Design Plan parameters in `USER PARAMETERS`
- derived Design Plan parameters in `DERIVED VALUES`
- assertions for invalid configurations, impossible counts, negative clearances, and too-thin walls

Current implementation: historical only. The dedicated Design Plan generation
endpoint uses CadQuery generation after explicit plan approval.

### CadQuery Prompt Modes

The active CadQuery prompt modes are:

```text
cadquery-generation-v1
cadquery-contract-repair-v1
cadquery-execution-repair-v1
cadquery-component-revision-v1
cadquery-scope-correction-v1
```

CadQuery generation receives the approved Design Specification, approved Design Plan, typed parameter contract, components, features, dependencies, printable outputs, printer profile, source contract, topology expectations, and security restrictions. It must return complete Python source only.

Current implementation: the active `cadquery-generation-v1` prompt uses the
`cadquery-v1` runtime contract. It requires `import cadquery as cq`, `from
volundr_cad.runtime import ParameterSpec, PrintableOutput, Product`, typed
module-level `ParameterSpec` metadata, a single `build(params)` entry point, and
one returned `Product` containing `PrintableOutput` records.

Contract repair may fix schema, entrypoint, import, output declaration, syntax, or API contract issues. Execution repair may fix straightforward CadQuery API or geometry-operation failures. Neither repair path may silently redesign geometry or modify protected requirements.

### `revision-planning-v1`

Responsibility: create an immutable structured Revision Plan from a user request or selected validation finding. Do not generate source.

Input context:

- accepted base revision id
- base Design Specification JSON
- approved Design Plan JSON
- output manifest
- source metadata from source-contract validation
- selected validation/geometric/printability findings, when applicable
- clarification answers and previous Revision Plan when replanning
- user revision instruction

Output: valid JSON matching `revision-plan-v1` in `docs/STRUCTURED_REVISION_PLANNING.md`.

Required content:

- exact requested changes
- targeted parameters, components, features, outputs, and findings
- allowed shared modules and protected interfaces when a structural component change is needed
- allowed parameter/component/feature changes
- required dependency changes from the Design Plan graph
- protected parameters, components, features, and outputs
- prohibited changes
- success criteria
- whether a revised Design Specification or Design Plan snapshot is required
- outcome: `revision_ready`, `clarification_required`, `revision_conflict`, `unsupported_revision`, or `planning_failed`

Current implementation: `revision-planning-v1` is implemented for accepted revisions that have an approved Design Plan. A ready plan enters review and must be explicitly approved before source revision starts. Clarification answers create a superseding plan version.

### `openscad-component-revision-v1`

Responsibility: legacy path that revises selected components, features, outputs, or approved shared modules while returning the complete authoritative OpenSCAD project.

Input context:

- approved Revision Plan JSON
- scoped revision context with target modules, protected modules, allowed shared modules, protected outputs, protected interfaces, and success criteria
- active configuration override manifest when the base revision is configured
- current Design Specification JSON
- current Design Plan JSON
- current output manifest
- selected validation findings and relevant measurements
- full base authoritative OpenSCAD source

Output:

- exactly one fenced `openscad` block
- complete source for the whole product
- no source fragments
- no prose outside the block

Rules:

- edit only approved target components/features/outputs and allowed shared modules
- preserve protected component modules, output mappings, interface parameters, and configuration override parameters
- retain the selected-output dispatcher for every planned output
- do not rename unrelated modules or add undeclared components/outputs
- do not broaden scope when a shared dependency appears necessary

Historical implementation: `openscad-component-revision-v1` was used for
approved Revision Plans that included scoped component/output context. Current
product revisions use `cadquery-component-revision-v1`.

### `scope-correction-v1`

Responsibility: correct one component-scoped revision that exceeded approved source scope. This is not design revision, source-contract repair, or compiler repair.

Input context:

- revised source that exceeded scope
- blocking scope findings
- approved Revision Plan JSON
- scoped revision context
- active configuration context when present

Output:

- exactly one fenced `openscad` block
- complete source for the whole product

Rules:

- revert unauthorized protected component, protected output, protected interface, unapproved shared-module, and unrelated-module edits
- preserve the approved targeted change when it does not conflict with the findings
- do not broaden scope or introduce new components/outputs
- run at most once

### `openscad-revision-v2`

Responsibility: return complete authoritative OpenSCAD revised only within an approved Revision Plan. This remains the broader structured revision mode for compatibility where narrow component ownership cannot be proven.

Input context:

- approved Revision Plan JSON
- current Design Specification JSON
- current Design Plan JSON
- current output manifest
- selected findings addressed by the plan
- full base authoritative OpenSCAD source

Output:

- exactly one fenced `openscad` block
- complete source for the whole product
- no prose outside the block

Rules:

- the Revision Plan is the only authority for what may change
- preserve all protected requirement, component, feature, dependency, geometry, and output markers
- retain every planned printable output and the selected-output dispatcher
- preserve unrelated modules and unaffected output behavior where practical
- do not redesign unrelated components or remove difficult features

Historical implementation: `openscad-revision-v2` was superseded by
`openscad-component-revision-v1` for component-targeted full-source revisions.
Current product revisions use CadQuery prompt modes.

### `compile-repair-v1`

Responsibility: repair source-level compile failures only.

Input context:

- failed source
- compiler stdout/stderr
- source extraction result
- attempt number
- original design summary

Allowed changes:

- syntax fixes
- missing braces, commas, and semicolons
- OpenSCAD-compatible expression rewrites
- zero/negative derived expression fixes when directly proven by diagnostics

Prohibited changes:

- changing user dimensions
- removing modules
- adding features
- reorienting the part
- redesigning geometry

### `contract-repair-v2`

Responsibility: repair static source-contract failures before OpenSCAD compilation. This is separate from compiler repair and must not respond to mesh or printability validation.

Input context:

- failed source
- persisted source-contract findings
- protected Design Specification requirement and feature IDs
- instruction to preserve geometry, protected dimensions, required features, and unrelated modules

Allowed changes:

- add missing skeleton sections
- add missing requirement or feature markers
- add or preserve required geometry markers when the source already implements the measurable feature
- remove prohibited source constructs
- make protected constants statically verifiable without changing their specified values
- restore removed protected parameters or markers

Prohibited changes:

- redesigning the model
- changing protected values
- removing unrelated modules
- fixing compiler diagnostics unless they are also listed source-contract failures
- recursive repair attempts

### `validation-feedback-v1`

Responsibility: classify compile, mesh, and printability results.

Output schema:

```json
{
  "stage": "validation-feedback-v1",
  "decision": "accept|candidate_review|repair_compile|request_revision|reject",
  "blocking_failures": ["mesh.empty_or_zero_volume"],
  "warnings": ["orientation.overhangs"],
  "repair_allowed": false,
  "user_visible_summary": "string"
}
```

Current implementation note: staged `validation-feedback-v1` is not yet a Gemini prompt. Volundr now performs deterministic backend validation after compile and mesh inspection, persists non-pass findings, and derives candidate state before any user acceptance action.

## Context Selection

Do not pass the full chat history as authoritative context. Maintain a compact project design record:

- original intent
- accepted requirements
- accepted assumptions
- parameter schema
- active source hash and active source
- latest mesh metadata
- latest printability report summary
- accepted and rejected validation findings

Initial generation should not receive old failed source unless it is explicitly a repair stage. Revision planning should receive compact source metadata, output manifest, Design Plan graph, and selected findings. Bounded source revision should receive the active accepted source plus the approved Revision Plan. Repair should receive failed source and compiler diagnostics, not broad conversation history.

## Token And History Management

- Store large artifacts as files and pass summaries unless the stage requires full source.
- Include full CadQuery source only for revision and repair stages.
- Summarize printability results as rule id, severity, detected value, and suggested correction.
- Keep prompt examples short and canonical.
- Version every prompt independently.

## Prompt Versioning

Use these active stable stage IDs for product generation:

```text
requirements-v1
clarification-v1
design-plan-v1
cadquery-generation-v1
cadquery-contract-repair-v1
cadquery-execution-repair-v1
revision-planning-v1
cadquery-component-revision-v1
cadquery-scope-correction-v1
validation-feedback-v1
```

Historical `openscad-*`, `contract-repair-*`, and `compile-repair-*` stage IDs
may appear in archived generation attempts and benchmark notes, but they are not
active product prompt versions.

Persist per attempt:

- full staged generation chain
- stage id and prompt version
- Gemini ruleset version
- provider and provider model
- non-secret provider settings
- full request payload
- rendered prompt or prompt artifact path
- raw output
- extracted source or parsed JSON
- status
- failure class
- elapsed time
- source hash and output hash
- Design Specification id and content hash when generation uses one
- benchmark id, when applicable

## Initial Generation Flow

```text
user request
  -> requirements-v1
  -> persist immutable Design Specification
  -> if clarify/conflict/unsupported: return state, no revision
  -> user reviews ready Design Specification
  -> design-plan-v1
  -> user reviews and approves Design Plan
  -> cadquery-generation-v1
  -> source contract validation
  -> if hard source/spec violation: cadquery-contract-repair-v1 once, then revalidate or fail attempt
  -> per-output worker execution
  -> mesh inspection, geometric invariant analysis, and printability validation
  -> candidate review, repair, or failed attempt
```

Current implementation note: `design-plan-v1` feeds `cadquery-generation-v1`;
the frontend path requires Design Plan approval before source generation.

The lifecycle for complex configurable products is:

```text
User requirements
  -> Design Specification
  -> Parametric Design Plan
  -> Plan review and approval
  -> CadQuery generation
  -> component/output execution
  -> validation
  -> candidate
```

CadQuery generation uses the approved Design Plan as the structural authority and the Design Specification as the requirements authority.

## Revision Flow

```text
accepted design record + user change or selected finding
  -> revision-planning-v1
  -> clarification/conflict/unsupported or explicit plan approval
  -> cadquery-component-revision-v1
  -> source-contract validation
  -> revision compliance validation
  -> output preservation and interface checks
  -> per-output compile and validation
  -> candidate or failed revision
```

Current implementation note: structured revision planning is implemented for
accepted revisions with approved Design Plans.

Next quality gate: structured revision planning feeds component-targeted
full-source CadQuery revisions. Live benchmark evidence should guide further
revision intelligence.

## Compile-Repair Flow

```text
failed source + compiler diagnostics
  -> source contract validation must already have passed
  -> compile-repair-v1
  -> source contract validation
  -> compile once
  -> stop after bounded attempt
```

Repair failure should remain a failed attempt. It should not trigger an unbounded design rewrite.

## Source-Contract Validation Flow

```text
Gemini raw response
  -> Python/CadQuery extraction
  -> source normalization
  -> security validation
  -> hard contract validation
  -> protected Design Specification compliance validation
  -> quality analysis
  -> compile only if hard checks pass
```

Hard violations are persisted on the generation attempt and block compilation. Quality findings are persisted and, after successful compile/mesh validation, are attached to the candidate for review.

## Validation Feedback Flow

Validation should feed revisions, not source-level repair, unless the failure is a compile/source-contract failure. Printability warnings become user-visible context and revision context. Printability blockers become candidate/reject decisions depending on user override policy.

## Evaluation Strategy

Prompt changes are improvements only when benchmark metrics improve:

- extraction success
- compile success before and after repair
- source-contract compliance
- required parameter compliance
- critical dimension accuracy
- prohibited feature rate
- accepted-with-blocking-validation rate
- clarification precision and recall
- revision preservation
- repair boundedness
- protected design invariant preservation

Run the deterministic fake-provider suite on every commit. Run one Gemini smoke per benchmark after prompt changes. Run 5 normal-part generations and 10 clarification/revision generations before declaring stability.

## Failure Classification

Use these failure classes:

```text
clarification_missed
requirements_misread
unsafe_assumption
contract_violation
source_extraction_failure
openscad_compile_failure
mesh_invalid
printability_blocker
revision_regression
repair_overreach
provider_failure
provider_timeout
observability_gap
```

Clarification recall measures whether Volundr asks when it must. Clarification precision measures whether it avoids asking on prompts that already contain sufficient dimensions and constraints.

## Candidate Revisions

During stabilization, AI-generated results produce candidate revisions. They do not replace the active accepted revision automatically.

Candidate review states:

```text
ready
ready_with_warnings
blocked
rejected
accepted
```

`ready` means no blocking validations or unresolved assumptions. `ready_with_warnings` means advisory warnings exist. `blocked` means at least one blocking validation or unresolved clarification exists. `rejected` means the user or system rejected the candidate. `accepted` means the user accepted the candidate and it may become the active revision.

Implemented transition guard:

```text
compile succeeds
  -> mesh metadata exists
  -> validation findings persist
  -> review_state derived
  -> user accepts or rejects
```

The service layer blocks `blocked -> accepted`, `rejected -> accepted`, `accepted -> rejected`, and restore of blocked or rejected candidates.

## Repair Invariants

Repair mode must preserve protected design invariants:

- user-provided dimensions
- required functional features
- mating geometry
- fastener geometry
- print orientation
- unrelated module names and behavior

A repair that changes protected invariants must be rejected and classified as `repair_overreach`.

## Configuration Path

Direct parameter editing and preset switching do not use a Gemini prompt. The approved Design Plan and accepted CadQuery source are the authority. Volundr validates editable parameters, persists a `configuration-change-v1` record, then executes the unchanged source with a typed parameter manifest in the isolated worker.

If a request cannot be represented as existing editable parameter values, the product should route to structured revision planning instead of asking Gemini to improvise inside the configuration path.
