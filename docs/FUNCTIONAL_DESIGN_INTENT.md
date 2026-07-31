# Functional Design Intent

Volundr treats physical function as a separate contract from source syntax,
CAD execution, topology, and printability. A Design Plan may declare
coordinate frames, mounting interfaces, support/containment interfaces, and
retention interfaces in `functional_contract`.

Interfaces use stable IDs and reference existing components, outputs, and
parameters. Mounting contracts distinguish the hole-cutting axis from the
hole arrangement axis. Support contracts state whether a floor is required,
its proposed minimum thickness, and the approved removal direction.

Routine values such as wall thickness and ordinary clearance remain Volundr
proposals. Clarification is reserved for decisions that materially change fit,
function, assembly, safety, printer feasibility, or product architecture.

Plans with a functional contract must resolve alternatives before approval.
An unresolved plane, normal, hole axis, support decision, removal direction,
or required retention strategy is a blocking planning finding.

Functional readiness is independent of structural candidate state:

- `functionally_verified`: supported critical checks pass.
- `functionally_partially_verified`: supported checks pass with explicit noncritical uncertainty.
- `functionally_unverified`: evidence is insufficient.
- `functionally_violated`: a critical check failed.

The UI presents these as Functional checks. Rule IDs and source evidence stay
in technical details and diagnostic bundles.
