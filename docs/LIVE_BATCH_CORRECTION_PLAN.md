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
