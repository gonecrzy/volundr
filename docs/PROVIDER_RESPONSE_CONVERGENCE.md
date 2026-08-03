# Provider response convergence

This document records the Phase 0 reconstruction and the shared contract for
converging provider responses. It does not authorize a product-family CAD
change.

## Reconstructed repeated failures

The source evidence is the frozen post-correction batch
`mixed-cad-live-correction-01`, batch
`0ba9c31b-5d0e-440e-b34b-7b766afa1d39`. The raw provider artifacts remain in
the local data root and outside Git:

`/tmp/volundr-live-e2e.VWUxlv/data/projects/`

| Project | Stage | Raw response valid JSON | Schema valid | Provenance valid | Semantic content complete | Repair result | Worker |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: |
| Desktop organizer `66df4c96-c202-49b7-9ee5-fc6586eac148` | geometry body, attempt `d191c06d-48b9-4526-816f-5b89db8ade9a` | no; approved JSON fence | yes after envelope extraction | yes | no; `accessory_compartments_division` matched multiple Plan features | no repair; protected relationship remained ambiguous | no |
| Monitor wall mount `9a83da2f-3a9b-4ec4-8a02-739989c6296f` | requirements, attempts `53fe1c2d-84f4-46c0-bacb-fad2e1656309` → `885ced70-6764-45e0-bcbd-1e96dba710b3` | no initially; one key was malformed; repair was fenced JSON | no; `assumptions[0].description` missing after syntax repair | not established | no accepted Design Specification | repair made syntax parseable but remained schema-invalid | no |
| Screw-lid container `f96daa7b-e265-4c1a-a799-ba814b00e8fe` | compact Plan, attempts `7b5398a1-db06-46a4-96a7-52c30c8a3951` → `bc7135e5-7d8d-4f47-8f44-58f68fd733a9` | no; approved JSON fence | no; pattern lacked numeric count/radius source | not established for the rejected pattern | no; `lid_grip_ribs` remained incomplete | repair changed the layout identity to `lid_grip_ribs_pattern` but still failed validation; partial/regressive risk | no |

The desktop organizer's provider response was structurally recognizable, but
the downstream identity/provenance contract correctly refused to choose
between multiple features. The monitor response demonstrates two distinct
failures: malformed JSON followed by a schema-invalid assumption record. The
screw-lid response demonstrates a repair that changes one representation but
does not converge the required semantic relationship.

The repeated family is therefore generic provider/schema/provenance
convergence, not a geometry fix. Existing worker-side topology and verification
findings remain separate evidence.

## Shared lifecycle

Each provider stage records the provider-authored raw response, parser output,
deterministic normalization, provider repair response, and final accepted
contract as separate artifacts. Each representation has a hash and the
manifest records changed fields, identity changes, provenance changes, and
findings before and after each boundary.

The lifecycle classification is a summary only; detailed findings remain the
authoritative diagnostics:

`transport_failure`, `provider_timeout`, `provider_rate_limit`,
`empty_response`, `truncated_response`, `invalid_json`,
`syntactically_repairable_json`, `schema_invalid`, `provenance_invalid`,
`semantic_incomplete`, `semantic_contradiction`,
`protected_identity_violation`, `valid`, `valid_after_normalization`,
`valid_after_repair`, `unchanged_repair`, and `regressive_repair`.

Deterministic normalization is limited to approved wrappers, unambiguous
aliases, canonical units/IDs/order, and provenance completion when exactly one
authoritative source matches. Multiple sources, conflicting values, and
identity changes remain blocking.

Repair is bounded to one focused response for the smallest invalid record or
function. Unchanged, regressive, or partially improved repairs remain blocked
and preserve both responses; no repair loop is created.

The browser exposes only concise technical lifecycle labels. Raw JSON,
provenance enum names, schema paths, prompts, and provider credentials remain
outside normal chat.

