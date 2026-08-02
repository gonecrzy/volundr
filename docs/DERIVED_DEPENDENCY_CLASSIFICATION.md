# Derived Dependency Classification

Volundr retains every derived-parameter dependency finding because planning
quality and execution evidence must remain reproducible. A malformed derived
record is not, by itself, proof that the generated geometry is unusable.

## Classification

Each broken dependency is classified independently in the parameter-effect
contract and persisted with the generation attempt:

| Classification | Finding | Severity | Assembly behavior |
| --- | --- | --- | --- |
| `blocking_required` | `geometry_body.derived_dependency_broken` | critical | Reject the geometry body before worker execution |
| `diagnostic_only` | `planning.derived_dependency_unused_or_incomplete` | warning | Preserve evidence and continue assembly |

The finding includes `dependency_status`, `blocking`, `classification`, a
classification version, and machine-readable `reasons`.

## When a dependency blocks

A broken dependency is blocking when it is part of the executable contract:

- it is an exposed control or supports one transitively;
- it drives a configurable pattern;
- it is required by a geometry-function obligation or scaffold-owned
  operation;
- the assembled geometry source references it, directly or through a
  referenced derived value; or
- an approved execution-critical relationship depends on it.

The source check runs after structured body assembly, so a value that was only
planning metadata becomes blocking if the provider actually consumes it.

## When a dependency is diagnostic-only

An unused malformed record is diagnostic-only when no exposed control,
configurable pattern, scaffold obligation, required geometry function, or
assembled source references it. Fixed one-off layouts and ordinary numeric
requirements do not create future sensitivity obligations. Their resulting
geometry is evaluated after worker execution instead.

Diagnostic-only evidence remains in the parameter-effect contract, the
scaffold manifest, workflow event metadata, Technical details, and debug
bundles. It does not invoke geometry repair and does not create a blocking
chat outcome.

## Evidence and lifecycle

The scaffold manifest stores the complete classified findings for the attempt.
When diagnostic findings are present, Volundr also records a nonblocking
`planning.derived_dependency_classified` workflow event. A blocking finding
still retains all sibling diagnostic findings in the rejection details, so a
mixed contract is not reduced to its first error.

Source-authority validation filters only the blocking classification into its
hard checks. On a passing source validation it returns diagnostic findings
separately, preserving their warning severity and classification.

## Examples

An ordinary spacer may contain an incomplete unused `hole_y_position` record.
That record is retained as `diagnostic_only`, while measured hole positions,
diameter, topology, and artifacts are checked from the worker result.

An explicitly exposed bottle diameter whose derived cavity diameter has a
broken dependency remains `blocking_required`. A configurable uniform pattern
with a broken count or spacing path remains blocking as well. A fixed pair of
holes does not require count sensitivity unless the active plan explicitly
promises that reusable control.

## Non-goals

This classification does not remove dependency validation, relax exposed
control or configurable-pattern validation, add product-specific branches, or
replace topology and post-worker requirement checks. It also does not trigger
an additional provider retry for unused planning metadata.
