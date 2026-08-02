# Compact Plan Contract

Status: Implemented in this pass.

Compact plans are derived execution artifacts. The requirement ledger remains
authoritative; the compact plan does not replace it and does not require a
complete reusable parameter graph.

## Components and features

A component is a separately printable part with its own output, placement,
material, or assembly responsibility. A rib, hole, vent, boss, opening, floor,
fillet, chamfer, snap arm, or fused reinforcement is normally an integral
feature owned by its printable component.

For an unambiguous compact single-part plan, Volundr may deterministically
default a missing feature owner to the sole printable component. It may also
reclassify a provider-labelled integral feature component when there is one
printable output, no assembly relationship, no independent output, and the
semantic description clearly identifies an integral feature. The original
payload, normalized payload, reason, and nonblocking finding are retained.

Volundr never invents a multipart owner, silently fuses an explicitly separate
part, or adds an output to repair an ambiguous plan.

## Repeated features

Compact plans may use fixed or proposed positions and numeric one-off layout
values. Count, spacing, radius, and region guidance do not become controls just
because they are numeric. A parameter identity is required only when the user
explicitly requests reusable adjustment or the relationship is explicitly
pattern-driving.

The accepted layout modes are documented in
[`REPEATED_FEATURE_LAYOUTS.md`](REPEATED_FEATURE_LAYOUTS.md).

## Normalization evidence

Normalization is limited to stable IDs, owner defaults in the sole-part case,
numeric/unit representation, pattern aliases, and safe non-parametric layout
interpretation. Every normalization finding is retained in the plan payload
and therefore in the immutable Design Plan artifact and execution context.

## Non-goals

This contract does not weaken source safety, protected identities, topology,
functional verification, artifact readiness, or Current working version
promotion gates. It does not prescribe the provider's local CadQuery
implementation.
