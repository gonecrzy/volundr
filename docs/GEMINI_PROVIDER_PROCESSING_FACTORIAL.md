# Gemini provider × processing factorial

The preregistered factorial was three cases (`case-001`, `case-003`,
`case-006`) across four arms: current/P0, Profile B/P0, current/P3, and
Profile B/P3. The target was 12 complete project operations.

The corrected attempt is incomplete. It completed the current/P0 arm and
Profile B/P0 arm (six project operations and 24 provider requests, including
one terminal hard 429) and stopped before either P3 arm. All 24 provider
captures are present, and successful calls identify as
`gemini-3.5-flash-lite`; the run used concurrency 1, a 12/minute default, a
15-per-rolling-60-second hard cap, and at least five seconds between starts.
No hard 429 was retried and no Ollama call was made.

Earlier attempts with missing immutable capture or incomplete clarification
continuation are retained under `reports/historical/` and are not combined
with the corrected result. The current machine-readable reports are
`reports/provider-processing-factorial-results.json`,
`reports/provider-processing-factorial-comparison.json`, and
`reports/gemini-rate-limit-report.json`.

Because P3 was never live-tested and the four-arm matrix is incomplete, the
factorial is descriptive evidence only. It cannot select a provider,
processing method, or end-to-end system.
