# Gemini stable-foundation validation

Offline evidence authorized a focused comparison of current production versus
Profile B. The validation used exactly five frozen cases—`case-001`,
`case-002`, `case-003`, `case-006`, and `case-008`—once per arm, for ten
project operations.

Both arms completed five operations. The current arm recorded 20 Gemini
requests and the Profile B arm recorded 15. Every request targeted
`gemini-3.5-flash-lite`. The shared experiment proxy maintained at least five
seconds between starts and never exceeded 15 requests in a rolling minute;
there were no 429 responses and no retries.

The comparison is descriptive, not statistically significant. Both arms
produced mixed downstream outcomes and neither established worker-ready valid
source across at least two cases. The recommendation is
`candidate_promising_but_needs_second_validation`; Profile B was not deployed.

## Offline Phase 2 audit correction

The preserved run was audited without provider, Ollama, worker, or project
calls. It contains 10 project operations and 35 provider records. The prior
zero/zero worker-ready summary was incorrect: corrected counts are 3/5 for
current production and 2/5 for Profile B. Profile B case-006 reached the
worker and failed in CadQuery; that is actionable worker evidence, not CAD
success. Profile B case-001 made a valid clarification request, but its frozen
answer was not submitted, so the end-to-end comparison is asymmetric.

The audited decision is `corrected_second_validation_required`. Production
configuration remains unchanged.
