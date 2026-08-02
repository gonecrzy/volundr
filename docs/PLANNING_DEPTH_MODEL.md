# Planning Depth Model

## Status

Implemented in this pass. The examples below are illustrative semantic cases,
not product-name mappings.

## Router outcomes

`PlanningDepthRouter` emits one of:

- `clarification_required`
- `direct_brief`
- `compact_plan`
- `detailed_plan`

The decision records policy version, reasons, ambiguous factors, and missing
information in an immutable workflow artifact. It considers requirement-ledger
content and project state: component and output count, assembly/mating/moving
relationships, fit-critical requirements, interacting functional features,
revision scope, preserved relationships, exposed controls, and process limits.
It does not use holder/bracket/enclosure/organizer names as route rules.

## Clarification policy

Ask only when a critical interface, fit value, relationship, or contradiction
cannot be resolved safely from the active ledger and deterministic proposals.
After an answer changes the ledger, routing runs again. A previous
`clarification_required` result is not retained as a permanent project mode.

## Plan contracts

`direct_brief` is deterministic and requires no planning-provider call.
`compact_plan` uses the provider's smaller `compact-cad-plan-v1` contract
(prompt contract `compact-cad-plan-v2`) and deterministically normalizes IDs,
units, printable-component versus integral-feature ownership, fixed/proposed
layouts, outputs, and validation targets. Numeric repeated-feature values do
not become controls unless explicitly requested. `detailed_plan` retains the
existing full Design Plan validation while accepting fixed/proposed one-off
layout values without requiring a reusable spacing identity.
Each plan remains a derived artifact; the requirement ledger remains authoritative.

## Revision routing

Narrow, unambiguous deltas such as one dimension, clearance, hole position, or
simple reinforcement use a persisted deterministic `cad-revision-brief-v1`.
Several interacting changes use compact planning, and multipart, mechanism, or
preserved assembly relationships use detailed planning. A failed route or
generation attempt leaves the previous Current working version unchanged.

## Observability and user experience

Route decisions, reasons, missing-information evidence, plan artifacts,
normalized execution contexts, and prompt context packs are persisted through
the existing workflow artifact registry. Normal chat shows only concise
progress, clarification, change, success, and blocked messages. Route and
artifact evidence is available in technical details and diagnostics.

### Derived metadata quality

Planning may contain incomplete derived metadata that is not needed by the
selected execution contract. The parameter-effect contract classifies each
broken dependency independently. Execution-critical dependencies remain
blocking; unused dependencies are retained as
`planning.derived_dependency_unused_or_incomplete` warning evidence and do not
trigger another planning or geometry-provider call. This keeps proportional
planning requirement-led rather than source-parametric.
