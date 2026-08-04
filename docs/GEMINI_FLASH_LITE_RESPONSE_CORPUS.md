# Gemini Flash Lite response corpus

The private response corpus is stored outside Git at
`data/debug-sessions/gemini-flash-lite-study/<study-id>/`. It retains raw,
parsed, normalized, repair, contract, downstream, and redaction distinctions.

Only minimized redacted fixtures belong in
`tests/fixtures/gemini-live-responses/`. They are replay regression inputs,
not new live model results. Every live record carries the study, round,
repetition, case, project, workflow, provider-call, and model identities.
