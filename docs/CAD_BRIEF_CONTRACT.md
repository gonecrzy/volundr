# CAD Brief Contract

## Status

Implemented in this pass.

## Purpose

`cad-brief-v1` is the deterministic execution brief for a sufficiently
specified, single printable component. It gives the existing structured
geometry, worker, verification, artifact, and promotion pipeline enough
information to execute without paying for a planning-provider call.

It is not a replacement requirement store, a provider-approved detailed Design
Plan, or a promise of future configurability.

## Contract shape

A brief contains:

- `schema_version: cad-brief-v1` and `planning_depth: direct_brief`;
- project and revision references;
- ledger-derived `requirements`, revision delta, and preserved requirements;
- distinguishable `proposals` with `source: volundr_proposal`;
- printable `components` and execution `features`;
- coordinate frames, relationships, validation targets, outputs, and
  `exposed_controls` (normally empty);
- optional execution parameters needed by the scaffold, without making them
  reusable controls.

The brief is constructed deterministically from the active requirement ledger.
User requirements, revision requirements, derived necessities, Volundr
proposals, and exposed controls remain distinguishable. A brief can contain
ordinary implementation values, but source sensitivity is required only for an
explicit exposed control.

## Revision and non-goals

Narrow revisions may create a deterministic `cad-revision-brief-v1` linked to
the base revision and current Design Plan. Wider changes use compact or detailed
revision planning. All candidates still pass source, worker, topology,
functional, consistency, and promotion gates.

The brief does not prescribe exact CadQuery source style, generalized patterns,
future controls, provider responses, or a new lifecycle engine.
