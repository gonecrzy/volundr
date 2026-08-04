# Gemini native structured-output experiment

Profile D (profile-d-structured-output) changed response enforcement only:
application/json plus a stage-specific Gemini JSON Schema. Profile D retained
the current prompt, sampling, retry, safety, parser, and downstream evaluator.

The partial Phase 1 record contains 4 of the planned 6 calls. All four were
accepted by the preliminary contract evaluator, and all four passed the
recorded schema gate. The semantic-fidelity average was 0.0 under the
packet-level preliminary score; this score is not a complete Phase 1 estimate
because quota stopped the balanced order before both repetitions per packet.

Structured output is not treated as a guarantee of semantic correctness.
Profile D was not promoted to production.
