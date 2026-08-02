# Requirement Trace Normalization

Trace normalization connects authoritative requirements to Plan features,
components, outputs, and verification targets without requiring the provider
to repeat every requirement ID perfectly.

## Resolution order

1. Explicit requirement, feature, component, and validation-target IDs.
2. Known safe aliases and canonical identifier normalization.
3. Typed semantics: kind, operator, numeric value, unit, and object type.
4. Feature/layout semantic compatibility and component ownership.
5. Measurement compatibility between the requirement and validation target.
6. Text similarity only as low-confidence diagnostic evidence, never as the
   sole authoritative pass or block.

The selected match is safe only when exactly one compatible feature remains,
values and units agree, ownership is consistent, and no explicit conflicting
link exists. Candidate, rejected, selected, confidence-basis, and rule
metadata are persisted with the normalized manifest.

## Alias and deferred-obligation examples

An explicit capacity requirement with `kind=capacity`, `operator=up_to`,
`value=5`, and `unit=tray` may match one `slot_array` feature and one
capacity-compatible target even if the provider omitted one of the IDs. The
normalized obligation preserves the canonical requirement ID and creates a
deferred target when the existing measurement contract supports it:

```json
{
  "requirement_id": "tray_capacity",
  "feature_id": "tray_slots",
  "verification_target_id": "val_tray_capacity",
  "measurement": "supported_capacity",
  "operator": "up_to",
  "expected_value": 5,
  "unit": "tray"
}
```

The original provider records are retained separately. Creating this
obligation does not claim that geometry satisfies it before worker execution.

## Ambiguity and blocking

Multiple compatible features or targets remain ambiguous and blocking when the
choice could change the product. Unknown explicit owners, contradictory
values, missing required printable components/outputs, missing exposed-control
traces, and required features with neither a source path nor a supported
verification target remain blocking. Missing provider bookkeeping alone is not
blocking when the semantic match is unique.

Integral features may point to their owning component function without a
separate output. Fixed one-off positions and layouts do not require pattern
parameters. Configurable controls and execution-critical identities retain
strict source tracing.

## Evidence and diagnosis

The original and normalized manifests are immutable revision evidence. Findings
include `design_artifact.trace_alias_normalized`,
`design_artifact.geometry_verification_deferred`,
`requirement.verification_obligation_created`, and typed blocking findings for
missing, conflicting, or ambiguous traces. Diagnosis reports the specific
requirement and stage; normal chat receives only a concise safe summary.

## Non-goals

This is not a symbolic geometry reasoner, product vocabulary matcher, source
parameter generator, second ledger, or substitute for worker, topology,
functional, artifact, or human physical verification.
