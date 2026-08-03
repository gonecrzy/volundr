# Next live-batch correction priority

Planning only. This document does not authorize product-family CAD changes or
another live run.

## Result of the controlled convergence pair

The generic provider/schema/provenance convergence pair is complete and
controlled. The sole deferred next priority is integrity/misleading-state
reconciliation in batch reporting: Batch 2 called the screw-lid project
`Not started` even though preserved generation attempts show source-generation
activity and a non-terminal final attempt.

## Expected repair scope

1. Reconcile report outcomes with the complete workflow and attempt chain.
2. Preserve non-terminal attempt evidence as an integrity finding rather than
   converting it to `Not started`.
3. Make all report/frontend/self-review surfaces use the same lifecycle status.
4. Add deterministic coverage proving regeneration is read-only and stable.
5. Only then decide whether a new controlled pair is warranted.

## Explicit non-goals

This priority does not repair individual CAD features, infer load-bearing
safety for the monitor mount, redesign the workspace, capture additional
browser activity, or convert the unpaired post-correction batch into a
controlled comparison.
