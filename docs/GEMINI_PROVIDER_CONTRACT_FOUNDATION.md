# Gemini Provider Contract Foundation

Study `gemini-provider-contract-foundation-01` evaluates
`gemini-3.5-flash-lite` independently of the current Volundr parser, Plan
normalization, source assembler, worker, topology, and verification code.

The original settings report was corrected offline and its one missing S1
multislot operation was completed once. Both S0 and S1 now have 12/12
content-bearing passes; the corrected content-only decision selects S0 by the
frozen entropy tie-break. The original holdout records were actually H0 with
explicit MINIMAL thinking, so the historical H1 conclusion is retained as
historical evidence but is not an H1 holdout conclusion.

The correction tested a narrow missing-fit requirements prompt (T2, 6/6)
against T0 (4/6), and real source-bearing repair packets (T2, 4/6) against T0
(2/6). Because no repair prompt cleared the 6/6 gate, the corrected H1
holdout and adapter replay were not authorized. The corrected final decision
is `corrected_second_validation_required`; this is not a production
deployment.

All calls in this study used only the secondary credential slot and the exact
model identity `gemini-3.5-flash-lite`. No Ollama, worker, or production calls
were made. Evidence is under
`data/debug-sessions/gemini-provider-contract-foundation/gemini-provider-contract-foundation-01/`.

The next step is contract revision and another preregistered holdout, not
deployment or current-build tuning.
