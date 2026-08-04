# Local model next actions

Planning only. No corrections are implemented by this document.

Priority order:

1. **P0 — failure-path integrity.** Fix the undefined `user_message_id` in the
   failed AI revision path. The failure should be persisted as a normal,
   inspectable workflow outcome with no secondary 500 and with an integrity
   finding when required.
2. **P0 — report eligibility.** Treat transport failures, provider 500s, and
   missing artifacts as incomplete pairs. Exclude them from consistency means,
   mark the quality comparison inconclusive, and retain the failure evidence.
3. **P1 — Ollama execution contract.** Investigate sustained remote latency and
   invalid/non-JSON geometry responses. Preserve the one-retry/two-clarification
   limits, use bounded structured-output validation, and record provider
   variability separately from product defects.
4. **P1 — admission gate.** Add a sustained-throughput/timeout preflight gate;
   cold and warm context completion alone did not predict the formal run's
   read-timeouts.
5. **P1 — rerun.** After the above repairs, repeat the exact five cases twice
   per admitted model with identical prompts, policy, environment, schema, and
   retry settings. Do not apply corrections during that run.

The correction plan must keep these categories separate: repeated
cross-product defects, same-family defects, provider variability, isolated
anomalies, and integrity/misleading-state defects. The wall-mount case must
retain its physical safety warning. Observed usability testing remains
distinct from developer-assisted live model evaluation.
