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
