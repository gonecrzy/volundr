# Gemini Provider Contract Foundation

Study `gemini-provider-contract-foundation-01` evaluates
`gemini-3.5-flash-lite` independently of the current Volundr parser, Plan
normalization, source assembler, worker, topology, and verification code.

The settings gate chose S0 explicit sampling. The thinking and prompt matrices
were resumed under the same frozen operation IDs; H1 was the completed
thinking winner in the final matrix, while no prompt candidate cleared the
universal quality floor. These are study results, not a production
deployment. The separate 20-operation holdout achieved 17/20 intrinsic
quality passes, so the final provider decision is
`provider_contract_not_yet_stable`. The adapter decision is separately
`provider_contract_requires_revision`.

All calls in this study used only the secondary credential slot and the exact
model identity `gemini-3.5-flash-lite`. No Ollama, worker, or production calls
were made. Evidence is under
`data/debug-sessions/gemini-provider-contract-foundation/gemini-provider-contract-foundation-01/`.

The next step is contract revision and another preregistered holdout, not
deployment or current-build tuning.
