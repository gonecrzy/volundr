# Ollama holdout validation

The holdout corpus is frozen in `benchmarks/ollama-holdout-v1.yaml` and is not
used while selecting or refining profiles.

In the final disposition pass, every operational native profile was given the
untouched holdout corpus. CAD-Coder, ProCAD, Qwen CadQuery, Qwen 14B,
DeepSeek, and C3Dv0 have explicit holdout outcomes in
`data/debug-sessions/ollama-calibration/calibration-admission-final-v2/`.
Successful topology without broad expected-geometry checks does not count as
a holdout pass; a second holdout failure remains evidence.

Any profile change after holdout begins changes the profile hash and raises a
holdout-freeze error. A fresh holdout case or documented calibration iteration
is required before validation can resume.

## Failure anatomy review

`OLLAMA_HOLDOUT_FAILURE_ANATOMY.md` reconstructs all twelve attempts and assigns
one earliest authoritative blocker per pair. Both holdouts are
`fair_with_minor_evaluator_risk`: their broad requirements are derivable, but
the frozen evaluator does not independently measure every feature named in the
prompts. No valid geometry was found to be contradicted by the evaluator. The
review concluded that the six failures are independent model CAD/source
failures, not a shared holdout defect. The holdouts remain untouched.
