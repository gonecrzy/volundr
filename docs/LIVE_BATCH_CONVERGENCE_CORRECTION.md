# Live batch convergence correction

Planning and implementation record for the generic provider-response
convergence pass. This pass does not implement organizer, screw-thread,
tray/holder, monitor-mount, or other product-family CAD corrections.

## Boundary

The correction boundary is between a provider response and the existing
requirements, Plan, geometry-body, and worker-diagnostic contracts. Existing
chat messages, requirement ledgers, Plans, GeometryExecutionContext, provider
attempts, source, worker results, findings, revisions, snapshots, and exports
remain authoritative.

Raw evidence remains local and outside Git under the durable data root. The
debug-session path is not an authoritative source for normal project history.
Evidence materialization may redact and copy records into a batch folder, but
does not create a competing workflow or event stream.

## Implemented generic boundary

- `GenerationAttempt` now records response stage, classification, immutable
  response artifact paths, hashes, findings, and a preservation manifest.
- Parser envelope normalization retains the raw response and writes parsed and
  normalized artifacts separately.
- `label` is accepted as the description of an assumption only when it is the
  sole unambiguous display representation. Missing assumption meaning is not
  replaced with invented text.
- Canonical authoritative provenance sources are recognized across Plan
  normalization. Legacy aliases are observable; conflicting or misclassified
  sources remain blocking.
- Plan repair comparisons preserve the existing protected component, feature,
  output, and unaffected-layout boundary while recording focused repair outcome
  metadata.
- Unchanged, regressive, and partial repairs stop without a repair loop.

## Required behavior for the live pair

The next two batches must use the same prompts, fact sheets, provider/model,
configuration, schema, retry policy, images, and build identities. No fixes may
be applied during or between those batches. The comparison is controlled only
when every required identity matches; otherwise it is recorded as uncontrolled
and the live pair stops.

The primary metric is the number of projects blocked by generic
schema/provenance convergence before worker submission. CAD promotion is not a
required success condition. The monitor-wall-mount project remains a geometry
and workflow evaluation only and must retain its explicit physical engineering
and test-review warning.

