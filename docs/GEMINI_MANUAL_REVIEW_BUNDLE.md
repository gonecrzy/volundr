# Gemini manual-review bundle

The complete redacted denormalized review file is:

`data/debug-sessions/gemini-profile-ablation/gemini-profile-ablation-01/reports/all-responses-manual-review.json`

It embeds all 30 Phase 1 records and the later Phase 2 arm records, including
requests, raw response text where available, parsed and normalized outputs,
original and corrected scores, quality-floor findings, buildability findings,
provider metadata, token/latency fields, response hashes, and source capture
paths.

The bundle retains the historical decision separately and records the live
rate-limit policy. API keys, authorization headers, cookies, and private
absolute temporary paths are redacted. Normal immutable capture files remain
alongside the bundle.
