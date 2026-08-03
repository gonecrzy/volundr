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
