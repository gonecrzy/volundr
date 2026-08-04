# Gemini secondary-credential continuation

The interrupted factorial was resumed under the same study ID with the
explicit `GEMINI_API_KEY_2` source. The key value was read from the local
environment only, injected into the isolated experiment child process as the
provider credential, and never written to a report, log, hash, or bundle.
Primary credentials were unset for that process; no automatic key rotation or
credential alternation was used.

The preserved A/B P0 arms were validated from operation-level captures and
arm/capture fingerprints, then skipped. Only unfinished C/D P3 work was
eligible. The first required C/P3 request returned HTTP 429; that attempt
recorded the secondary source label and stopped immediately, D was not
started, and the historical 429 was not retried.

After the key was updated, a separate replacement continuation ran C and D.
It replaced only C case-001, the quota-stopped operation, and did not reuse
its provider call. The replacement completed all six C/D project operations
and recorded 19 new captures. Two upstream transport timeouts were preserved
as 502 failures; an offline repair restored their rate-event accounting while
marking their monotonic timestamps unavailable. No new hard 429 occurred.

The final two-system gate found fewer than two clean finalists, so no final
validation call was authorized. The combined current factorial evidence has
43 provider captures; the one preserved quota-stopped call is reported
separately, for 44 study calls in total. All successful calls used
`gemini-3.5-flash-lite`, with concurrency one, a 12/minute default, a hard
15-per-rolling-60-second cap, and at least five seconds between starts. No
Ollama call occurred.

The pre-resume and replacement reports are preserved under
`reports/historical/pre-secondary-credential-resume/`.
