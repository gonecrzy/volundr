# External CAD comparison specifications

`external-cad-50-v1.1` qualifies reference comparison separately from the
historical v1 `reference_specification` inputs. Version 1 remains unchanged.

## Three input concepts

- `premise_only` is the normal user request. It is reference-isolated and may
  stop for clarification.
- v1 `reference_specification` is retained for historical/intermediate testing.
- v1.1 `comparison_specification` is an evaluator input used only when enough
  design-driving facts exist for fair geometric interpretation.

Reference meshes, source CAD, and dense geometry data are never serialized to
comparison prompts.

## Frozen extraction method

`external-cad-comparison-extraction-v1` starts with the frozen user-like
premise and explicitly selected canonical part membership. It preserves the
existing provenance-tagged facts, adds only coarse per-output envelopes from
the persisted derived reference record, and records the selected variant and
reference authority. Measured facts carry the method
`external-cad-reference-derived-v1.geometry.bounding_box_mm`.

A project is `comparison_ready` only when output identity, selected variant,
major envelope, principal mating geometry, critical interface/hardware
constraints, and multi-part relationships where applicable are explicit.
Ambiguity fails closed. Similarity is reported as
`specification_underconstrained` unless the project is ready; replacement
targets are excluded from quantitative comparison.

## Holdout handling

The same method is applied generically to validation and holdout projects.
Holdout comparison specifications are not emitted into development-visible
records. Only neutral identity metadata and sealed specification hashes are
persisted until the explicit holdout gate.

The v1.1 development audit is in
`benchmarks/external/cad-50-v1.1/development-audit-30.json`. No live CAD
generation, provider call, repair, or worker execution is part of this
qualification checkpoint.
