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

Pattern normalization additionally persists the original provider record, the
normalized record, the pattern index and ID, and the decision that produced
the canonical form. Findings use typed rules such as
`plan.pattern_alias_normalized`, `plan.pattern_owner_missing`,
`plan.pattern_owner_unknown`, `plan.pattern_type_missing`, and
`plan.pattern_direction_invalid`. A provider response can therefore be
transport-successful while Plan validation is blocked; those are recorded as
separate attempt and workflow outcomes.

For a single connected-solid output, a provider-declared frame, handle, or
retention element may be reclassified as an integral feature only when it has
no independent output, placement, assembly relationship, material, or
manufacturing role and the reclassification does not change a requirement.
Ambiguous or genuinely independent multipart declarations remain blocking.

## Non-goals

This contract does not weaken source safety, protected identities, topology,
functional verification, artifact readiness, or Current working version
promotion gates. It does not prescribe the provider's local CadQuery
implementation.

## Requirement semantics and trace

Compact plans consume the authoritative ledger rather than redefining it.
`exact`, `minimum`, `maximum`, `range`, `up_to`, `at_least`, `present`, and
`absent` semantics remain typed through normalization. A fixed one-off layout
does not need a parameter ID. If one typed feature and measurement target are
the unique compatible path for a measurable requirement, the trace contract
normalizes the link and defers proof to geometry. Ambiguity or an omitted
required implementation path remains blocking.

## Requirement trace boundary

Artifact consistency classifies each active requirement independently. Fixed
counts and dimensions may defer to a Plan validation target and resulting
geometry; they do not require a reusable Plan parameter. Exposed controls and
required printable identities still require source traces. Integral features
may trace to their owning component function without a separate output. See
[`REQUIREMENT_TRACE_CONTRACT.md`](REQUIREMENT_TRACE_CONTRACT.md).
