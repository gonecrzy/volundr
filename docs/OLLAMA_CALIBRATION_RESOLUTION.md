# Ollama calibration resolution

The resolution phase preserves the original 29 observations and adds precise
reprocessing findings. Evidence is outside Git at
`data/debug-sessions/ollama-calibration/calibration-admission-report/`.

The resolution queue distinguishes:

- representation normalization: Markdown/prose/reasoning wrappers, line
  endings, explicit slot order, and one unambiguous final alias;
- model/contract limitations: truncated or ambiguous native source, native
  scripts in slot mode, missing/unknown/duplicate slots, invalid statements,
  imports, and unsupported helpers;
- CAD findings: only isolated-worker topology, verification, or broad
  expected-geometry failures;
- infrastructure and adapter errors: kept separate and never scored as CAD.

All six profiles are frozen within the three-iteration limit. Holdout prompts
were not changed. No CAD operation, dimension, feature, or relationship was
invented during normalization or slot assembly.

The final report has no unresolved shared infrastructure or adapter error, but
no specialist/generic admission pair passed the fair holdout gate. The formal
five-case benchmark remains unauthorized and was not run.
