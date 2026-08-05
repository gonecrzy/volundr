# Gemini Provider-Contract Correction Holdout

The corrected H1 holdout was not run in `provider-contract-correction-01`.

The frozen gate requires an independently qualified prompt for every tested
stage. The missing-fit requirements prompt qualified at 6/6 content passes.
The real source-bearing repair study improved from 2/6 with T0 to 4/6 with T2,
but neither prompt reached the required 6/6 gate. The runner therefore wrote a
zero-call holdout gate and did not treat the missing holdout as provider
failure.

The preserved historical holdout used H0 with explicit `thinkingConfig` and is
classified as `holdout_h0_current_stage_specific`; it is not an H1 conclusion.
The future validation must retain H1 provider-default with no
`thinkingConfig`, the selected S0 settings, requirements T2, Plan and geometry
T0, and a newly qualified source-bearing repair prompt before running the
20-operation holdout.
