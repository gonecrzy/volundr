# Gemini deterministic processing-method ablation

The offline replay used all 30 preserved Phase 1 records and all 35 preserved
Phase 2 provider calls. It made zero provider calls and zero worker calls.
Each method was evaluated against preserved responses without mutating the
historical experiment.

| Method | Scope | Result |
| --- | --- | --- |
| P0 | current processing baseline | not qualified |
| P1 | safe contract canonicalization | not qualified |
| P2 | canonicalization plus authoritative metadata | not qualified |
| P3 | proven geometry-slot/scaffold adapter | qualified and selected |
| P4 | P3 plus preserved trace/verification reconciliation | not qualified |
| P5 | combined bounded processing | not qualified |

P3 produced 12 bounded source-stage actions, zero semantic-hash changes, zero
integrity regressions, and preserved known blocked responses. Its rewrite is
allowed only when the slot manifest proves the prior-shape alias and result
symbol are equivalent. It does not alter numeric values, slot order, feature
operations, or verification evidence; source validation remains a downstream
gate.

The machine-readable evidence is `reports/offline-processing-replay.json`,
`reports/processing-method-scorecard.json`, and
`reports/processing-method-decision.json`. The live factorial was authorized
only because exactly one bounded method qualified offline.
