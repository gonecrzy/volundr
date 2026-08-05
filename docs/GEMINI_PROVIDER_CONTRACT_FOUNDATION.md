# Gemini Provider Contract Foundation

Study `gemini-provider-contract-foundation-01` evaluates
`gemini-3.5-flash-lite` independently of the current Volundr parser, Plan
normalization, source assembler, worker, topology, and verification code.

The gated selection chose S0 explicit sampling, H0 current stage-specific
thinking, and T0 current provider prompts. These are selection results, not a
production deployment. The 20-operation holdout achieved 17/20 intrinsic
quality passes, so the final provider decision is
`provider_contract_not_yet_stable`. The adapter decision is separately
`provider_contract_requires_revision`.

All calls in this study used only the secondary credential slot and the exact
model identity `gemini-3.5-flash-lite`. No Ollama, worker, or production calls
were made. Evidence is under
`data/debug-sessions/gemini-provider-contract-foundation/gemini-provider-contract-foundation-01/`.

The next step is contract revision and another preregistered holdout, not
deployment or current-build tuning.
