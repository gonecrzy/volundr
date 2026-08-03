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

| Project | Requirement | Source function | Executed | Geometry evidence | Measurement | Current finding |
|---|---|---|---:|---|---|---|
| Portable holder | `req_right_handle` | `_ai_feature_feat_carrying_handle` | unknown in frozen manifest; build path calls the slot | final output is one solid; no feature-local body/overlap evidence | not recorded | `feature_trace_missing`; the earlier disconnected-handle run is repair evidence, not proof of the current final handle |
| Portable holder | `req_drainage` | `_ai_feature_feat_drainage_openings` | unknown in frozen manifest; build path calls the slot | final output is one solid; no through-opening or support evidence | not recorded | `feature_present_but_unmeasured` |
| Portable holder | `req_retention_strap_slots` | `_ai_feature_feat_strap_slots` | unknown in frozen manifest; build path calls the slot | final output is one solid; no count, wall-through, or usability evidence | not recorded | `feature_present_but_unmeasured` |
| Desktop organizer | `req_one_piece` | `_ai_feature_main_body` plus component builder | source function declared and build path calls it; per-function execution absent | authoritative topology reports one solid, but base/wall/divider ownership is not measured | one-solid topology only | `feature_present_but_unmeasured` |
| Desktop organizer | `req_phone_slot` | `_ai_feature_phone_slot` | unknown in frozen manifest; build path calls the slot | valid final solid/artifacts; no open-top rear-region evidence | not recorded | `feature_present_but_unmeasured` |
| Desktop organizer | `pen_compartment` | `_ai_feature_pen_compartment` | unknown in frozen manifest; build path calls the slot | valid final solid/artifacts; no front-left bounded-region evidence | not recorded | `feature_present_but_unmeasured` |
| Desktop organizer | `accessory_compartments` | `_ai_feature_accessory_compartments` | unknown in frozen manifest; build path calls the slot | valid final solid/artifacts; no two-compartment/divider evidence | not recorded | `feature_present_but_unmeasured` |
| Desktop organizer | `cable_notch_width` | `_ai_feature_cable_notch` | unknown in frozen manifest; build path calls the slot | valid final solid/artifacts; no rear-wall-through versus base-through evidence | not recorded | `feature_present_but_unmeasured` |

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
