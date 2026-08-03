# Deterministic feature verification

Status: implemented and frozen live evaluation complete. This document records the frozen evidence
audit that precedes the verifier implementation and defines the evidence
contract used by the geometry-slot path.

## Frozen evidence audit

The audit used the preserved raw evidence outside Git:

- portable holder: `8a81e929-9f8b-410d-9239-393bcaba9b2f`, project
  `9445e7e7-2250-4dc6-b829-a5ce694c2ce8`;
- desktop organizer: `8ea3488d-940b-44de-9ed1-772efef6597f`, project
  `b4a147ea-981c-4db4-8a96-68c5b401ef75`.

The portable output has a successful source contract, one valid solid, and
STEP/STL/BREP artifacts. The organizer output has the same successful artifact
and one-solid topology evidence. Neither preserved worker manifest contains a
per-feature input/output shape trace or a final-geometry measurement record.
Therefore source labels and the valid-solid result are intentionally not
treated as feature verification.

| Project | Requirement | Source function | Executed | Shape before feature | Shape after feature | Final output shape | Existing target/evidence | Measurement | Current finding |
|---|---|---|---:|---|---|---|---|---|---|
| Portable holder | `req_right_handle` | `_ai_feature_feat_carrying_handle` | unknown; no runtime trace | not recorded | not recorded | one valid connected solid; no feature-local handle summary | source declaration and output topology only | not recorded | `feature_trace_missing` (the earlier disconnected-handle run is separate repair evidence) |
| Portable holder | `req_drainage` | `_ai_feature_feat_drainage_openings` | unknown; no runtime trace | not recorded | not recorded | one valid connected solid; no through-opening evidence | source declaration and output topology only | not recorded | `feature_present_but_unmeasured` |
| Portable holder | `req_strap_slots` | `_ai_feature_feat_strap_slots` | unknown; no runtime trace | not recorded | not recorded | one valid connected solid; no slot count or wall-through evidence | source declaration and output topology only | not recorded | `feature_present_but_unmeasured` |
| Desktop organizer | `req_one_piece` | `_ai_feature_main_body` plus component builder | source declared/build path known; per-function execution absent | not recorded | not recorded | one valid connected solid | one-solid topology only; base/wall/divider ownership target absent | one-solid topology only | `feature_present_but_unmeasured` |
| Desktop organizer | `req_phone_slot` | `_ai_feature_phone_slot` | unknown; no runtime trace | not recorded | not recorded | one valid connected solid; no rear-region opening evidence | source declaration and output topology only | not recorded | `feature_present_but_unmeasured` |
| Desktop organizer | `req_pen_compartment` | `_ai_feature_pen_compartment` | unknown; no runtime trace | not recorded | not recorded | one valid connected solid; no front-left bounded-region evidence | source declaration and output topology only | not recorded | `feature_present_but_unmeasured` |
| Desktop organizer | `req_accessory_compartments` | `_ai_feature_accessory_compartments` | unknown; no runtime trace | not recorded | not recorded | one valid connected solid; no two-compartment/divider evidence | source declaration and output topology only | not recorded | `feature_present_but_unmeasured` |
| Desktop organizer | `req_cable_notch` | `_ai_feature_cable_notch` | unknown; no runtime trace | not recorded | not recorded | one valid connected solid; no rear-wall-versus-base-through evidence | source declaration and output topology only | not recorded | `feature_present_but_unmeasured` |

The earlier preserved portable failure also remains a regression fixture:
`_ai_feature_feat_open_side_walls` produced an additive handle whose tangent
placement left two solids (`detected_solid_count=2`, expected `1`). That case is
classified as `feature_generated_but_disconnected`; it must not be “fixed” by
accepting a compound or a broad fallback fuse.

The audit exposes the precise gap: there is enough evidence to prove source
declaration and output-level topology, but not enough to prove a feature's
execution, shape transition, final presence, or requirement semantics.

## Evidence record

Each deterministic record is compact and references the authoritative output:

```json
{
  "requirement_id": "requirement_handle",
  "feature_id": "side_handle",
  "output_id": "portable_holder",
  "source_function_id": "_ai_feature_side_handle",
  "source_executed": true,
  "geometry_presence": "present",
  "measurement_status": "measured",
  "measurements": {
    "connected_to_primary_body": true,
    "minimum_overlap_mm": 2.5
  },
  "requirement_outcome": "satisfied",
  "evidence_method": "brep_topology_measurement"
}
```

The persisted metadata additionally contains measurement inputs, requested
values, semantic operators, applied tolerances, measured values, source trace,
artifact references, and finding IDs. It does not duplicate BREP payloads.
Existing requirement findings remain authoritative records; deterministic
evidence supports and resolves them rather than replacing them.

## Outcome and measurement policy

Supported evidence outcomes are `satisfied`, `satisfied_with_warning`,
`not_satisfied`, `unverifiable`, `feature_absent`, and `measurement_failed`.
Source declaration, execution, geometry presence, and requirement outcome are
separate fields. A valid one-solid output can still be blocked by a missing,
unmeasured, or unsatisfied feature.

Tolerances are attached to each semantic target. Exact dimensions, approximate
dimensions, proposed dimensions, minimum/maximum constraints, topology-only
requirements, and qualitative physical-review requirements are not collapsed
into one global tolerance. Deterministic geometric compliance never certifies
load-bearing strength, fatigue, adhesion, pullout, comfort, watertightness, or
printer/material thread fit.

## Generic primitive boundary

The verifier surface is generic: integral connection, through opening, slot,
cavity/compartment, and one-connected-output topology. Product plans supply
feature IDs, regions, dimensions, counts, and semantic operators. No
portable-holder or organizer verifier class is introduced.

The live result is recorded in `FEATURE_VERIFICATION_LIVE_EVALUATION.md`.
Missing trace remains an explicit unverifiable condition in the evidence
evaluator, while ordinary legacy workflows without a new trace remain
unchanged.

## Bounded repair gate

The staged candidate-review flow now treats a single `geometry_feature`
finding as a bounded repair request only when the request targets exactly one
feature. The repair context carries the source trace, failed measurements,
protected hashes, output identity, and a one-provider-call limit into the
revision plan. The generated candidate is not accepted as a successful repair
unless its authoritative final analysis contains matching, measured feature
evidence with a satisfied or warning-qualified outcome, connected geometry,
and positive material overlap when that measurement is available. Missing
final feature evidence is a blocking integrity result. The active revision is
unchanged until the candidate is separately accepted.

The deterministic browser proof is the staged Playwright scenario
`feature finding repair stays bounded and requires connected final evidence`.
Its screenshot is kept with the local evidence artifacts at
`data/debug-sessions/feature-verification-deterministic/portable-holder-repair-1440x900.png`.
