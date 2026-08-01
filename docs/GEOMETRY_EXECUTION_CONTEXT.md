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
