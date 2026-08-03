# Mixed CAD live batch self-review

This review was performed after both batches were frozen. Each project was
inspected individually, each generated `codex-review.md` was followed, and no
correction was implemented during this run.

## Repeated cross-product defects

- Workflow outputs frequently stopped at schema, provenance, source-contract,
  or candidate-classification boundaries instead of producing usable geometry.
- Candidate classification was the repeated Batch 1 signature (three projects)
  and also occurred in Batch 2.
- Report retry numbers derive from recorded attempts rather than actual provider
  retry events.
- Git and backend identity capture recorded `unknown`, weakening provenance.

## Repeated same-family defects

- Organizer: requirement-to-feature identity collisions, an unbound feature
  during geometry, and an ineffective repair response.
- Screw lid: thread/feature identity collisions and a source-contract rejection
  involving an unsupported circular-pattern call.
- Tray/holder family: geometry and carry/retention feature generation produced
  downstream classification or CAD execution failures.

## Provider variability

The controlled identity comparison is valid, but workers were reached for 3/5
projects in Batch 1 and 1/5 in Batch 2. The same portable-holder prompt reached
different failure stages, while Batch 2 exposed more early JSON/contract
failures. This is provider/runtime variability, not proof of a deterministic
code regression.

## Isolated anomalies

- One portable-holder attempt produced `gp_VectorWithNullMagnitude`.
- One organizer repair returned an unchanged rejected response.
- One monitor attempt exposed a plan provenance/identity collision.
- One screw-lid attempt used unsupported `circular_pattern_points`.

## Integrity and misleading-state defects

These are the highest-priority follow-up items:

1. Absolute temporary job paths remain in portions of raw failure evidence,
   despite `redaction-status=confirmed`. No API key, authorization header, or
   cookie value was found, but the path leak violates the evidence boundary.
2. Retry counts need a real retry-event definition separate from stage attempts.
3. The completed comparison UI can briefly show an “uncontrolled” summary label
   while the loaded detail says controlled.
4. Unknown Git/backend identities should be rejected or explicitly marked
   insufficient for a future controlled live run.

The monitor-wall-mount warning remains explicit: geometry/workflow evaluation
does not establish load-bearing safety; physical engineering and test review are
required.

Raw evidence remains local and outside Git. Reports reuse the existing
authoritative workflow chain, and report generation made no provider or worker
calls. No same-run corrections were applied.
