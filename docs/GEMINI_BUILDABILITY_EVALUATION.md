# Gemini buildability evaluation

This is a reanalysis of the immutable `gemini-profile-ablation-01` Phase 1
matrix. It preserves the historical automated decision and changes only the
offline evaluator and experiment-scoped validation harness.

The corrected offline result is:

- Profile B clears all six response quality floors.
- Profile B is semantically noninferior to Profile A within a 0.02 absolute
  margin, retains acceptance, and improves repeat-consistent packets from 0
  to 3.
- Profile B is therefore a stable-foundation candidate, not a production
  adoption decision.
- The focused validation used five frozen cases per arm and ten project
  operations total. Both arms completed five operations; the result was mixed
  and did not establish worker-ready improvement across at least two cases.

Machine-readable reports are under the experiment `reports/` directory,
including `corrected-phase-1-decision.json`, `buildability-scorecard.json`,
`phase-2-comparison.json`, and `final-buildability-decision.json`.

Final engineering recommendation: `candidate_promising_but_needs_second_validation`.
No production setting was changed.
