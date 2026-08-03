# Live batch correction round 1

This document records the first correction pass after the frozen
`mixed-cad-live-01` / `mixed-cad-live-02` evaluation. It is implementation
evidence, not a new product-quality claim. The pass intentionally did not
change organizer, tray/holder, screw-thread, or monitor geometry behavior.

## Scope completed

- Durable evidence now normalizes temporary and unregistered absolute paths and
  records non-sensitive integrity findings without retaining removed values.
- Backend, frontend, and worker build identities capture Git SHA, timestamp,
  and dirty state. Incomplete identities cannot claim a controlled comparison.
- Generation attempts separately report provider calls, provider retries,
  content repairs, workflow-stage attempts, and user operations.
- Reports classify candidate creation, post-worker blocking, provider content
  failure, transport failure, and not-started states from the authoritative
  workflow chain.
- Generic repair paths reject unchanged semantic responses and preserve the
  original diagnostic. No product-family repair was added.
- Deterministic fixtures cover invalid JSON, provenance, source contracts,
  candidate classification, unchanged repair, missing artifacts, and report
  redaction.
- The comparison view uses the fetched comparison result as authoritative and
  labels identity mismatch/incompleteness as uncontrolled.

## Verification gates

- Backend correction/frozen/API/comparison tests: 16 passed in the targeted
  gate.
- Frontend tests: 90 passed.
- Frontend production build: passed.
- Deterministic Playwright debug-batch scenarios: 5/5 passed.
- A qualification attempt initially exposed missing live frontend identity
  injection; it was preserved locally and rejected. The final qualifying run
  used pinned identities and Playwright retries disabled.

## Boundary

The correction pass is generic observability, evidence, and provider/schema
handling work. It does not claim that any generated CAD geometry is safe or
production-ready. The monitor-wall-mount case remains geometry/workflow
evaluation only and requires physical engineering and test review before any
load-bearing use.

The next primary correction family is generic provider/schema/provenance
convergence before worker submission. This is selected because the final
post-correction run still stopped three of five projects before the worker;
the integrity and identity defects are no longer the limiting gate.
