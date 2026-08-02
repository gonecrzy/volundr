# Geometry-body symbol contract

Status: Implemented 2026-08-02.

## 1. Purpose

Structured geometry bodies are provider-owned statements inserted into a
Volundr-owned CadQuery function. Requirement flexibility permits literals,
locals, expressions, and scaffold parameters, but every loaded Python name
must still resolve in that function’s lexical scope.

## 2. Scaffold-owned function signature

Component bodies receive exactly `(params)`. Feature bodies receive exactly
`(body, params)`. Volundr appends the one deterministic return statement after
validating the provider statements and `result_symbol`.

## 3. Allowed symbol categories

The validator accepts function arguments, locals definitely assigned before a
use, comprehension and loop bindings in their active scope, approved module
aliases, approved scaffold helpers, approved safe builtins, and explicit
scaffold constants. The current CadQuery module alias is `cq`.

The exact inventory is persisted per function in the geometry-function
inventory and prompt context. It is not inferred from every Plan field.

## 4. Parameter access

Plan and requirement IDs are metadata, not Python globals. Provider code must
use the supplied `params[...]` or `params.get(...)` interface, or assign a
local from that interface first. A bare `plate_width` is invalid even when a
Plan value with that ID exists.

## 5. Local assignment rules

Straight-line assignments, annotated assignments, tuple/list unpacking, and
walrus bindings are tracked. A load before assignment is rejected. Assigning
a name somewhere in the function is not enough.

## 6. Branch and definite-assignment rules

An assignment introduced in only one branch is conditional and cannot be used
after the branch unless every path assigns it. Simple `if`/`else` paths are
merged conservatively. Unverifiable paths remain blocking source findings.

## 7. Comprehension scope

Comprehension targets are available inside the comprehension and do not leak
into the surrounding function scope. Loop targets are available inside their
loop body; post-loop use is conservative when the loop may execute zero times.

## 8. Approved modules and helpers

The scaffold exposes the approved CadQuery alias and registered deterministic
pattern helpers. Unsafe imports are still prohibited. The symbol inventory
and existing source-safety rules jointly determine what can reach the worker.

## 9. Prohibited symbols

Dynamic Python access, filesystem/process modules, prohibited builtins, global
mutation, imports, nested declarations, and scaffold-owned redefinitions
remain blocked. A prohibited operation is not converted into a geometry or
worker finding.

## 10. Result-symbol interaction

Each function declares one local `result_symbol`. It must be assigned on every
required path and be statically verifiable as a supported CadQuery shape.
Provider `return` statements remain forbidden; Volundr emits exactly one
return after validation.

## 11. Pre-worker findings

The canonical body validator emits targeted findings including:

- `geometry_body.unbound_name`;
- `geometry_body.conditionally_bound_name`;
- `geometry_body.prohibited_name`;
- `geometry_body.invalid_parameter_access`.

Findings retain function ID, symbol, source location, source statement when
available, available-name evidence, likely parameter ID, approved access form,
and repair eligibility. They remain in attempt diagnostics and debug bundles;
normal chat receives only the concise blocked outcome.

## 12. Runtime fallback classification

The worker remains isolated and is defensively checked for `NameError` and
`UnboundLocalError`. A traceback is repair-eligible only when it identifies one
provider-owned geometry function and one symbol. Otherwise the attempt remains
blocked with diagnostic evidence and Volundr does not guess a repair target.

## 13. Bounded repair

The existing structured-body repair receives the rejected JSON, affected
function, symbol finding, exact signature, parameter access contract, allowed
inventory, and preserved function context. A repair may change only the
affected provider function. Unaffected function-record hashes must remain
identical, and an identical rejected response is not retried.

## 14. Immutable evidence

Raw provider response, parsed body JSON, original statements, canonical bodies,
assembled source, scaffold manifest, symbol classifications, repair response,
and worker traceback remain separate artifacts linked to the workflow and
generation attempt. Canonical hashes make validation and repair evidence
reproducible.

## 15. Examples

Valid:

```python
width = params["plate_width"]
body = cq.Workplane("XY").box(width, 40, 6)
```

Invalid:

```python
body = cq.Workplane("XY").box(plate_width, 40, 6)
```

The second form is rejected before worker submission, even for an ordinary
non-parametric design. That is a Python scope contract, not a requirement for
future configurability.

## 16. Non-goals

This contract does not make ordinary dimensions parametric, add a new CAD
validation layer, infer physical compliance from source style, perform full
Python theorem proving, or replace topology, artifact, functional, or
post-worker requirement checks.

Pattern-consuming statements are also checked against the canonical pattern
coordinate space. A component/world 3D point set cannot be passed directly to
`pushPoints()`; safe conversion and placement evidence is retained separately.
