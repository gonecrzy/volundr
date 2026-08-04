# Gemini provider × processing factorial

The preregistered factorial was three cases (`case-001`, `case-003`,
`case-006`) across four arms: current/P0, Profile B/P0, current/P3, and
Profile B/P3. The target was 12 complete project operations.

The initial attempt completed the current/P0 arm and Profile B/P0 arm (six
project operations and 24 provider requests, including one terminal hard
429) and stopped before either P3 arm. The first secondary-credential
continuation attempted current/P3 arm C, received HTTP 429 on its first
required request, and stopped immediately; D was not started. After the
credential was updated, a separate replacement continuation ran C and D,
preserving A/B and replacing only the quota-stopped C case-001 operation.
The replacement produced 43 current captures across all four arms; one
historical hard-429 call remains preserved separately, for 44 study calls in
the combined evidence. Two replacement captures are provider transport
timeouts recorded as 502 failures; their missing proxy rate events were
recovered offline with timestamps explicitly unavailable. No hard 429 was
retried and no Ollama call was made.

All successful calls identify as `gemini-3.5-flash-lite`. The continuation
used concurrency 1, a 12/minute default, a 15-per-rolling-60-second hard cap,
and at least five seconds between starts. The preserved A/B arm and capture
hashes are unchanged.

Earlier attempts with missing immutable capture or incomplete clarification
continuation are retained under `reports/historical/` and are not combined
with the corrected result. The current machine-readable reports are
`reports/provider-processing-factorial-results.json`,
`reports/provider-processing-factorial-comparison.json`, and
`reports/gemini-rate-limit-report.json`.

The replacement completed the four-arm matrix, but the preregistered final
two-system gate found only one clean qualified finalist: current/P0. Profile
B/P0 retains the historical quota stop, current/P3 contains a transport
timeout and no valid source progression, and Profile B/P3 contains a
transport timeout. Therefore the factorial remains descriptive evidence and
the final validation was correctly skipped with zero calls. The secondary
credential labels are recorded without the secret value in the factorial
report.
