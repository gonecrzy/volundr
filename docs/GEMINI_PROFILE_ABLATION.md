# Gemini Flash Lite profile ablation

This is the experiment-scoped protocol and handoff for
gemini-profile-ablation-01. It tests only gemini-3.5-flash-lite and does not
change production prompts, schemas, routing, adapters, or processing gates.

Phase 1 was designed as three frozen provider packets by five profiles by two
repetitions (30 experimental calls), with one separate readiness call. The
packets were selected deterministically from the completed
gemini-flash-lite-study-01 evidence before Profile A ran:

- packet 01: requirements/provenance, case-001;
- packet 02: compact-plan structure, case-003;
- packet 03: source-symbol/geometry-contract context, case-006.

Each outgoing request records the rendered prompt, generation configuration,
schema, profile hash, packet hash, repetition, model identity, raw response,
usage, latency, parser/contract result, and redaction state. Provider-call
records are write-once and remain outside Git at
data/debug-sessions/gemini-profile-ablation/gemini-profile-ablation-01/.

The readiness call returned gemini-3.5-flash-lite and accepted the minimal
structured-output probe. Phase 1 stopped safely at the first hard quota
failure after 18 experimental POSTs (17 successful responses and one 429).
No quota retry was issued and Phase 2 was not started.

The final decision is prompt_configuration_improvement_not_established,
with evaluation_status: phase_1_incomplete_quota_interruption. This is a
conservative incomplete result, not evidence that the missing 12 calls would
have failed. Do not adopt a profile or change production behavior from this
partial run.
