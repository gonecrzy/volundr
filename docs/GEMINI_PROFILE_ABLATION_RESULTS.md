# Gemini profile ablation results

The experiment stopped after 18 of 30 Phase 1 calls because the provider
returned a hard quota failure. The readiness call was separate and succeeded
on the exact requested model. Phase 2 was correctly skipped.

| Profile | Runs | Accepted | Semantic fidelity | Repeat-consistent packets | Schema passes | Provenance passes | Slot passes | Source-contract passes | Tokens | Latency ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A current | 3 | 3 | 0.1429 | 0 | 3 | 3 | 3 | 3 | 19,911 | 8,202 |
| B sampling/seed | 4 | 4 | 0.0714 | 1 | 4 | 4 | 4 | 4 | 30,478 | 10,833 |
| C concise prompt | 3 | 1 | 0.1429 | 0 | 1 | 3 | 3 | 3 | 12,022 | 5,361 |
| D structured output | 4 | 4 | 0.0000 | 0 | 4 | 4 | 4 | 4 | 27,987 | 5,485 |
| E combined | 4 | 3 | 0.0000 | 0 | 3 | 3 | 3 | 3 | 12,572 | 7,271 |

These are partial descriptive counts, not estimates of full-profile quality.
Provider failures are excluded from semantic/provenance regression counts.
The machine-readable records are:

- reports/phase-1-scorecard.json;
- reports/phase-1-packet-results.json;
- reports/phase-1-consistency.json;
- reports/phase-1-causal-comparison.json;
- reports/phase-1-decision.json;
- reports/final-decision.json.

Decision: prompt_configuration_improvement_not_established,
evaluation_status: phase_1_incomplete_quota_interruption. No profile is
eligible for production adoption and no Phase 2 project comparison ran.

## Buildability reanalysis addendum

The text above is the preserved historical automated report. A corrected
offline evaluator rescored all 30 immutable records using absolute
packet-specific quality floors. Profile B passed 6/6 floors, retained
acceptance, and improved semantic repeatability from 0/3 to 3/3 packets.
The corrected decision is `profile_b_stable_foundation_candidate`.

The authorized focused validation completed ten project operations, five per
arm, but did not establish worker-ready improvement across at least two cases.
The final engineering recommendation is
`candidate_promising_but_needs_second_validation`; production behavior remains
unchanged. See `GEMINI_BUILDABILITY_EVALUATION.md`.
