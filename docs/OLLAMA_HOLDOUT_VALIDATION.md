# Ollama holdout validation

The holdout corpus is frozen in `benchmarks/ollama-holdout-v1.yaml` and is not
used while selecting or refining profiles.

In the final pass, CAD-Coder reached the frozen-profile holdout and failed it;
the other five models were blocked from holdout because their calibration
profiles did not reach admission. Their evidence records the blocking reason
instead of treating an unrun holdout as a model-quality failure.

Any profile change after holdout begins changes the profile hash and raises a
holdout-freeze error. A fresh holdout case or documented calibration iteration
is required before validation can resume.
