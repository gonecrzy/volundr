# Corrected Profile B second-validation plan

The audited decision is `corrected_second_validation_required`. This plan is
design-only; it was not executed in the audit.

Run the same five frozen cases (`case-001`, `case-002`, `case-003`, `case-006`,
and `case-008`) with both `current-production` and `profile-b-sampling` arms.
Use one complete workflow per arm and case, with identical prompts, frozen
facts, case order, worker settings, topology gates, verification gates, and
retry policy. For case-001, submit the same frozen facts to both arms after a
clarification request: 78 mm phone width, 12 mm phone thickness with case,
the explicit case condition represented by that fact, and approximately
65-degree desired angle.

Keep the profile-only generation configuration as the only arm difference.
Use exact model `gemini-3.5-flash-lite`, provider concurrency `1`, default
rate `12 requests per minute`, hard maximum `15 requests per rolling 60
seconds`, at least five seconds between call starts, and no retry of a hard
429. Capture immutable provider records, job IDs, source hashes, manifests,
tracebacks, topology, verification, and candidate-resolution outcomes in one
combined manual-review JSON.

Pre-register the corrected metrics: clarification safety, requirements valid,
Plan valid, source-contract pass, worker-ready source, worker reach, worker
completion, runtime failure, artifact readiness, topology, verification, and
candidate readiness. Do not count worker failure as CAD success, and do not
compare an answered clarification continuation against an unanswered stop.
Do not tune prompts or thresholds between calls. Production deployment remains
disabled until the predefined stable-foundation decision is applied to the
completed evidence.

The separate system-boundary methods study added an offline P3 processing
gate, but its corrected live factorial did not complete because of a hard
429. Any future validation must first complete the preregistered provider ×
processing matrix, then apply this five-case continuation policy; the partial
factorial is not evidence for deployment.
