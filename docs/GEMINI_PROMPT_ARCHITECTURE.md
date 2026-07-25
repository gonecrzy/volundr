# Gemini Prompt Architecture

## Goal

Gemini should not be asked to infer requirements, decide whether to clarify, design a printable part, write OpenSCAD, revise accepted source, and repair compiler failures in one prompt. Volundr should use small versioned stages with structured inputs and outputs.

## Prompt Stages

### `requirements-v1`

Responsibility: convert user text into a structured Design Specification. Do not generate OpenSCAD.

Input context:

- prompt version
- project name
- original intent
- latest user instruction
- active design record, when revising

Output: valid JSON matching the Design Specification schema in `docs/DATA_MODEL.md`.

Every dimension and requirement must identify one source from `user`, `clarification`, `calculated`, `printer_profile`, `product_default`, or `ai_assumption`. The structured Design Specification must be persisted and associated with the requirement-extraction generation attempt before OpenSCAD generation starts.

Current implementation: `requirements-v1` is implemented for new initial AI generations. Invalid JSON is classified as `design_spec_invalid`, raw output is preserved, and one bounded schema-repair extraction attempt is allowed.

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

Responsibility: create a bounded CAD plan from approved requirements and assumptions. Do not generate OpenSCAD.

Output schema:

```json
{
  "stage": "design-plan-v1",
  "design_summary": "string",
  "parameter_plan": [
    {
      "name": "wall_thickness",
      "value_mm": 3,
      "role": "critical|assumption|editable",
      "bounds": {"min_mm": 1.6, "max_mm": 8}
    }
  ],
  "module_plan": [
    {"name": "main_body", "responsibility": "solid base plate"},
    {"name": "mounting_holes", "responsibility": "two M4 clearance holes"}
  ],
  "geometry_strategy": ["string"],
  "print_strategy": {
    "orientation": "largest flat face on Z=0",
    "supports": "avoid",
    "layer_strength_notes": ["string"]
  },
  "validation_plan": ["string"],
  "prohibited_features": ["unrequested vents", "decorative cutouts"]
}
```

### `openscad-generation-v2`

Responsibility: produce only source-contract-compliant OpenSCAD from an approved Design Specification and ruleset.

Input context:

- requirements object
- persisted Design Specification artifact path or hash
- clarification decision with `action=generate`
- design plan
- `docs/GEMINI_RULESET.md` version
- target printer profile summary

Output:

- exactly one fenced `openscad` block
- no prose outside the block
- strict source skeleton from `docs/GEMINI_RULESET.md`
- protected requirement markers and feature markers as defined in `docs/MODEL_GENERATION_CONTRACT.md`
- protected values copied exactly from the Design Specification and exposed as named parameters

Current implementation: `openscad-generation-v2` is implemented for ready initial Design Specifications. `design-plan-v1` remains deferred.

### `revision-v1`

Responsibility: make the smallest source change that satisfies the user revision.

Input context:

- original accepted requirements
- accepted assumptions
- active source
- current parameter schema
- mesh metadata
- latest validation warnings
- user revision instruction
- preserve list

Output schema before code generation, persisted internally:

```json
{
  "stage": "revision-v1",
  "affected_parameters": ["slot_width"],
  "affected_modules": ["tray_rails"],
  "preserved_parameters": ["wall_thickness", "tray_height"],
  "risk_notes": ["changing slot width affects clearance"]
}
```

Final output is complete revised OpenSCAD only.

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

### `contract-repair-v1`

Responsibility: repair static source-contract failures before OpenSCAD compilation. This is separate from compiler repair and must not respond to mesh or printability validation.

Input context:

- failed source
- persisted source-contract findings
- protected Design Specification requirement and feature IDs
- instruction to preserve geometry, protected dimensions, required features, and unrelated modules

Allowed changes:

- add missing skeleton sections
- add missing requirement or feature markers
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

Initial generation should not receive old failed source unless it is explicitly a repair stage. Revision should receive only the active accepted source plus compact design record. Repair should receive failed source and compiler diagnostics, not broad conversation history.

## Token And History Management

- Store large artifacts as files and pass summaries unless the stage requires full source.
- Include full OpenSCAD only for revision and repair stages.
- Summarize printability results as rule id, severity, detected value, and suggested correction.
- Keep prompt examples short and canonical.
- Version every prompt independently.

## Prompt Versioning

Use stable stage IDs:

```text
requirements-v1
clarification-v1
design-plan-v1
openscad-generation-v1
openscad-generation-v2
revision-v1
contract-repair-v1
compile-repair-v1
validation-feedback-v1
```

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
  -> explicit Continue to generation
  -> openscad-generation-v2
  -> source contract validation
  -> if hard source/spec violation: contract-repair-v1 once, then revalidate or fail attempt
  -> compile
  -> mesh and printability validation
  -> candidate review, repair, or failed attempt
```

Current implementation note: `design-plan-v1` remains deferred. A ready Design Specification is sent directly to `openscad-generation-v2` as the authoritative design source. Raw user text is included only as secondary intent.

## Revision Flow

```text
active design record + active source + user change
  -> revision-v1 legacy path
  -> complete revised OpenSCAD
  -> compile and validation
  -> candidate or failed revision
```

Current implementation note: full structured revision planning is not implemented in this pass. Existing active-revision AI edits continue through the legacy revision path and attach the latest Design Specification as context when one exists.

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
  -> SCAD extraction
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
