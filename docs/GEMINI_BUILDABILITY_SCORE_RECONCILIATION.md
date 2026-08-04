# Gemini buildability-score reconciliation

Two Profile B values were preserved:

| Value | Source | Formula/input evidence | Status |
|---:|---|---|---|
| `0.9123` | `docs/GEMINI_PROFILE_B_STABILITY_REVIEW.md` | undocumented; no record count or weights | stale narrative value |
| `0.9789` | `reports/buildability-scorecard.json` | scorecard v1, all six Profile B records, eight explicit weights | authoritative |
| `0.9789` | `reports/all-responses-manual-review.json` | embedded copy of the scorecard | corroborating copy |

The authoritative value is `0.9789`. It is reproducible from the current
`buildability_scorecard` formula over all six immutable Profile B Phase 1
records with weights for semantic stability, structural stability, identity,
clarification, geometry contract, failure predictability, repairability, and
efficiency. The `0.9123` value has no reproducible formula or input record set
in the preserved repository and is retained only as historical documentation.

The original reports were not rewritten. The full reconciliation is in
`reports/buildability-score-reconciliation.json`, and the audited decision
uses `0.9789`.
