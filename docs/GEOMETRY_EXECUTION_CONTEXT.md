# Geometry Execution Context

## Status

Implemented in this pass.

## Contract

`geometry-execution-context-v1` is the immutable normalized contract consumed
by geometry generation regardless of planning depth. It contains:

- active requirements;
- current revision delta and preserved requirements;
- components, features, relationships, and proposals;
- coordinate frames;
- validation targets and required outputs;
- optional exposed controls;
- `planning_depth` and the source brief/plan kind, version, and artifact ID.

Direct briefs, compact plans, and detailed plans are normalized into this shape.
The downstream geometry service does not implement separate business lifecycles
for them.

## Consumers and conflict resolution

The context is used by structured geometry prompt construction, source assembly,
worker generation setup, diagnostics, and rerun evidence. The requirement
ledger wins when a derived execution artifact conflicts with active requirements.
The source plan reference and artifact hash make the selected branch recoverable.

The context is persisted through the existing immutable workflow artifact
registry and linked in artifact metadata to the project, workflow run, plan, and
revision where available. It is not stored only in generation-attempt metadata.

## Versioning

The schema version is part of the artifact and its content hash. A new contract
version must preserve the old artifact for diagnostics and reproducibility.
No normalized database table is required while the workflow artifact registry
can restore the payload.

## Derived dependency evidence

The execution context may carry derived metadata for reproducibility, but the
presence of a derived record does not make it an execution obligation. Each
broken dependency is classified as `blocking_required` or `diagnostic_only`
using exposed controls, configurable patterns, scaffold/function obligations,
and assembled-source references. Blocking findings reject assembly;
diagnostic-only findings remain in the scaffold manifest and workflow evidence
for Technical details and debug bundles. Post-worker requirement evidence
continues to outrank source representation for ordinary non-parametric
designs.
