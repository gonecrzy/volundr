# Live batch correction plan

Planning-only document. This file records how post-batch findings will be
prioritized; it does not authorize or contain same-run corrections.

After both frozen batches and the self-review, every finding will be classified
as one of:

- repeated cross-product defect;
- repeated same-family defect;
- provider variability;
- isolated anomaly;
- integrity or misleading-state defect.

Priority will be assigned in this order: integrity or misleading-state defects,
repeated cross-product defects, repeated same-family defects, provider
variability investigations, then isolated anomalies. Each proposed correction
will name the authoritative evidence, affected workflow stage, regression test,
scope risk, and whether it requires a separate controlled run. No correction is
implemented during or between the two live batches.

## Findings from the frozen mixed-CAD run

Priority 1 is integrity/state correctness: absolute temporary job paths remain
in portions of raw failure evidence despite a confirmed redaction status;
retry counts conflate workflow attempts with provider retries; the comparison
result can briefly display conflicting controlled/uncontrolled labels; and Git
and backend build identities were captured as `unknown`. These require a
separate correction and verification run before another controlled live claim.

Priority 2 is repeated cross-product behavior: invalid JSON/schema/provenance
outputs and candidate classification repeatedly stop the workflow before a
valid geometry artifact. Priority 3 is same-family behavior in organizer,
screw-lid, and tray/holder feature contracts. Priority 4 is provider/runtime
variability between the otherwise controlled runs. Priority 5 is the isolated
CadQuery sweep, unchanged repair, unsupported pattern call, and monitor plan
provenance anomalies.

The evidence supporting these priorities is summarized in
`MIXED_CAD_LIVE_BATCH_01.md`, `MIXED_CAD_LIVE_BATCH_02.md`,
`MIXED_CAD_LIVE_BATCH_COMPARISON.md`, and
`LIVE_BATCH_REGRESSION_CANDIDATES.md`. This remains planning only: no fixes
from the self-review were applied in the same run.

## Correction round 1 result

The integrity, identity, metric, classification, comparison-label, and
generic unchanged-repair items above were implemented in the first correction
pass. The detailed implementation record is
`LIVE_BATCH_CORRECTION_ROUND_1.md`. Product-family CAD behavior was not
changed.

The single qualifying post-correction batch is recorded in
`MIXED_CAD_LIVE_POST_CORRECTION_01.md`. Its three pre-worker stops establish
the next primary family: generic provider/schema/provenance convergence. The
next run must remain planning-only until that family has a focused contract,
fixtures, deterministic replay, and a separately authorized controlled pair.

## Geometry-slot live evaluation addendum

This addendum records the planning result for the frozen
`geometry-slots-live-01` batch. It does not authorize a same-run correction,
and it does not authorize another model comparison.

Classification from the five-project batch:

- Repeated cross-product: compact-plan normalization blocked the wall carrier
  and screw-lid projects before worker submission.
- Repeated same-family: portable-holder and desktop-organizer slot responses
  initially completed only one of six slots; both then reached the worker but
  failed to become valid final geometry.
- Provider variability: the bounded completion calls produced different
  compile, topology, snapshot, and artifact-consistency outcomes under the
  unchanged provider configuration. A second batch is required before calling
  this a controlled variability result.
- Isolated anomaly: the detailed monitor route stopped on artifact
  inconsistency. It remains geometry/workflow evaluation only and requires
  physical engineering and test review; no load-bearing safety conclusion is
  permitted.
- Integrity or misleading-state: the preliminary live manifest labeled the
  desktop organizer `candidate` while the authoritative frozen report labeled
  it `Blocked after worker`. The report integrity scan itself found no raw
  evidence corruption, so the repair target is outcome-source consistency.

Regression-candidate list, for a later separately authorized fixture pass:

1. Partial six-slot response with one completed and five invalid slots, plus a
   focused completion restricted to those five slots.
2. Nine-slot response with all slots invalid and a bounded completion that
   cannot produce a valid artifact.
3. Worker output with separate solids where connected topology is required.
4. Snapshot-producing revision that remains blocked by final verification.
5. Detailed-route artifact inconsistency with the monitor physical-safety
   warning retained.
6. Authoritative-report versus preliminary-manifest outcome disagreement.

Exactly one next CAD priority was selected in
`docs/GEOMETRY_SLOTS_LIVE_EVALUATION.md`: improve deterministic feature
verification. The expected correction scope is to make topology, valid
geometry, candidate, and final-blocked states deterministic; reconcile the
manifest from the frozen report; preserve missing-artifact integrity findings;
and keep the monitor's physical engineering warning visible. No correction
has been implemented here. Any implementation must add deterministic backend,
frontend, and Playwright regressions before a separate validation run.
