# Gemini system-boundary methods study

This is an experiment-only evaluation record for
`gemini-system-boundary-methods-01`. It does not change production provider
selection, prompts, schemas, source safety, or deployment settings.

The study keeps three axes separate:

1. intrinsic provider output: requirement safety, clarification decisions,
   semantic completeness, structural stability, and repeatability;
2. deterministic processability: bounded normalization, authoritative
   reconciliation, source-contract eligibility, and explicit failure handling;
3. end-to-end CAD: worker reach, worker completion, artifacts, topology,
   verification, and candidate readiness.

The preserved Profile B evidence remains offline-qualified: 6/6 quality-floor
passes, 3/3 semantic consistency, 3/3 byte-identical consistency, and
authoritative buildability score `0.9789`. The earlier `0.9123` value remains
historical narrative only; it is not silently substituted.

The study root is
`data/debug-sessions/gemini-system-boundary-methods/gemini-system-boundary-methods-01/`.
The prior profile-ablation root is immutable input evidence. The final
manual-review bundle is `reports/all-methods-manual-review.json` under the new
root and contains the source reports, offline replay, all preserved live
attempts, rate evidence, and the final decision.

Current final decision: `insufficient_evidence`. The secondary credential was
explicitly tried: the first unfinished C/P3 attempt received a hard 429 and
stopped before D; a later replacement completed C and D. Two replacement
captures were transport timeouts, leaving only current/P0 as a clean finalist.
The final two-system comparison was therefore not authorized, and no prompt
ablation or deployment followed.

## Independent provider-contract study

The later `gemini-provider-contract-foundation-01` study used only
`GEMINI_API_KEY_2`, exact model `gemini-3.5-flash-lite`, and zero worker calls.
It separated intrinsic provider quality from current-build compatibility. S0,
H0, and T0 won their gated selection stages, but the 20-operation holdout
passed only 17/20. This does not change the historical P3 result or authorize
provider deployment; the independent provider decision is
`provider_contract_not_yet_stable`.
