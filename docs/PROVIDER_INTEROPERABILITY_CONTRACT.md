# Provider Interoperability Contract

Volundr treats provider output as content that must conform to an already
approved execution contract. The requirement ledger, Plan,
GeometryExecutionContext, source scaffold, and downstream gates remain
authoritative.

## Plan/provider boundary

The provider may select implementation details and provider-local calculation
names. It may not create or rename protected component, feature, printable
output, exposed-control, or scaffold identities. Fixed and proposed layouts
remain one-off design evidence unless the Plan explicitly exposes a reusable
control.

Each source-generation attempt persists a `provider-contract-manifest-v1`.
The manifest records approved components, feature owners and roles, layouts,
outputs, exposed controls, function inventory, permitted local names, and the
repair boundary. Its hash is included in attempt evidence and the prompt
context pack.

## Repair boundaries

Plan repair receives the rejected Plan, normalized findings, valid existing
identities, affected feature/layout IDs, and prohibited changes. It may repair
only the affected feature or relationship. A field-level comparison records
preserved, changed, removed, added, resolved, and repeated content. Equivalent
layout aliases are compared by execution meaning; an actual change to an
unaffected layout remains blocking.

Geometry-body repair receives the exact function, scaffold signature, symbol
inventory, diagnostic, and preserved function hashes. It may change only the
named provider function. The structured-body contract still owns statement
ordering, result symbols, imports, and final returns.

Worker-diagnostic repair is limited to one safely localized provider statement
and one repair attempt. The traceback, source statement, CadQuery exception,
original source, repaired source, and second worker result are retained.

## Safety and preservation

Repairs cannot modify requirements, the GeometryExecutionContext, Plan
identities, output count, exposed controls, scaffold signatures, or unrelated
function bodies. Identical rejected content is not retried. A failed repair
never promotes a candidate or changes the Current working version.

## Non-goals

This contract does not add a new Plan schema, make ordinary layouts
parametric, provide product-specific CAD generators, hide provider output, or
replace topology, functional, artifact, or promotion gates.
