# Requirement Trace Contract

Status: Implemented in this pass.

## Purpose

The requirement trace answers whether each active user requirement has a
legitimate implementation or evidence path. It is an artifact-consistency
contract, not a demand that ordinary geometry expose reusable source
parameters.

The requirement ledger remains authoritative. The original trace manifest
preserves the ledger-derived items and provider Plan declarations. The
normalized trace manifest records deterministic aliases, owners, functions,
outputs, validation targets, classifications, and blocking decisions.

## Trace classifications

### `source_trace_required`

Use this for an explicitly exposed control, a required printable component or
output, an assembly relationship, or another protected scaffold identity. The
approved identity must be present in the corresponding Plan and generated
source metadata. A missing trace blocks before worker execution.

### `source_or_geometry_trace`

Use this for an explicitly required integral feature that may be implemented
by a dedicated feature function or inside its owning component builder. A
separate output is not required for an integral feature. If neither source
ownership nor a supported geometry-verification target exists, the required
feature remains blocking.

### `geometry_verification_required`

Use this for fixed dimensions, counts, positions, spacing, fit, clearance,
orientation, and similar requirements whose strongest evidence is the
resulting B-Rep or mesh. A fixed count or one-off layout does not become a
parametric source obligation. When a validation target exists, the trace is
recorded as `geometry_verification_deferred` and is nonblocking before the
worker.

### `human_review`

Use this for qualitative behavior that cannot be conclusively proven from
source metadata, such as comfort, practical retention force, or one-handed
operation. The evidence is retained as a warning or review item; absence of a
source symbol is not treated as definitive failure.

## Integral features and outputs

An integral handle, rib, lip, slot, pocket, hole, or support may be owned by a
single printable component and implemented by that component's function. A
dedicated feature decorator and a separate output are optional when the Plan
declares the feature as integral and the component lists responsibility for
it. A dedicated feature function is preferred when available because it gives
more precise evidence.

Multiple genuinely printable components cannot be collapsed into one
incomplete single output. One connected output may contain integral features,
or components explicitly declared as fused under the existing Plan semantics.
Ambiguous multipart ownership remains blocking.

## Deterministic normalization

Safe normalization includes a known owner-field alias, a feature implemented
inside the sole owning component, and a sole printable component when the
feature has no independent output, placement, assembly, material, or
manufacturing role. The original and normalized manifests are separate files
under revision metadata and are registered with the workflow artifact
registry.

Normalization never invents a missing required feature, output, component, or
verification target, and never chooses among multiple plausible owners.

## Blocking boundaries

Blocking findings include:

- `design_artifact.required_feature_missing`
- `design_artifact.feature_owner_mismatch`
- `design_artifact.feature_function_trace_missing`
- `design_artifact.output_trace_missing`
- `design_artifact.component_output_conflict`
- `design_artifact.requirement_trace_unverifiable` when its classification is
  source-trace-required or a required feature has no implementation/evidence
  path.

Nonblocking evidence includes:

- `design_artifact.trace_alias_normalized`
- `design_artifact.geometry_verification_deferred`
- `design_artifact.requirement_trace_unverifiable` for human-review items.

Assembly rejects only blocking findings. All findings retain requirement,
feature, component, function, output, classification, and normalization
metadata in the consistency result, database finding metadata, Technical
details, and redacted debug bundles.

## Diagnosis

Diagnosis uses typed artifact findings and the authoritative blocked workflow
event. It reports the exact requirement and trace stage instead of collapsing a
feature-owner, function, output, or geometry-deferred issue into the generic
`design_artifact.requirement_trace_failed` rule. Older records retain the
generic fallback behavior.

## Non-goals

This contract does not implement symbolic geometry reasoning, require every
numeric value to be a Python parameter, add product-specific generators, or
weaken source safety, worker isolation, topology, functional verification,
artifact readiness, or Current working version protection.
