# Mixed CAD live Batch 2

Batch 2 is frozen and preserved outside Git under:

`<VOLUNDR_LIVE_DATA_DIR>/data/debug-sessions/1ec92524-0401-40a2-a0e1-077cb8c52f57/`

Raw evidence remains local and outside Git. The repository contains only this
summary and the implementation/reporting code.

## Run identity

- Label: `mixed-cad-live-02`
- Batch ID: `1ec92524-0401-40a2-a0e1-077cb8c52f57`
- Baseline: Batch 1; state: frozen
- Provider/model: `gemini_api` / `gemini-3.5-flash-lite`
- Migration head: `0028_debug_batches`
- Configuration hash: `76d0ab528fa8eba60a8cb272c80ab3ad1afcd5fa54862bea020f0d788fae55d3`
- Git HEAD: `unknown`; backend build: `unknown`
- Frontend build: `frontend-dev`; worker build: `cad-worker-v1`
- Retry policy: one configured retry (`max_retries: 1`)
- Memberships: five, ordered by creation

The same five prompts ran in the same order. Each project received one prompt
message; duplicate-message groups: `0`.

## Results

| Position | Prompt family | Result | Worker reached | Primary evidence |
| ---: | --- | --- | ---: | --- |
| 0 | five-tray wall carrier | Blocked before worker | no | invalid design specification |
| 1 | two-tray portable holder | Blocked after worker | yes | candidate classification |
| 2 | desktop organizer | Blocked before worker | no | source extraction; contract repair |
| 3 | fixed monitor wall mount | Blocked before worker | no | design-plan generation/provenance |
| 4 | screw-lid container | Blocked before worker | no | source contract validation |

Funnel totals: 5 projects created, 5 requirements completed, 0 plans
completed, 0 geometry results, 0 valid geometry results, 1 worker reached, 0
snapshots, 0 exports, and 0 promoted working versions. No project reached the
success condition, so the successful-project export inspection was unavailable.

Failure distribution: one each of candidate classification, contract repair,
design-plan generation, source-contract validation, and source extraction. The
report’s `retries: 18` has the same attempt-count caveat as Batch 1.

The monitor-wall-mount result is a geometry/workflow evaluation only. Nothing
in this report establishes load-bearing safety; physical engineering and test
review remain required.

## Evidence checks

- Generated `codex-review.md` was followed and every member was inspected.
- Report generation made no provider or worker calls.
- Redaction status: `confirmed`; no API key, authorization header, or cookie
  value was found.
- Generated integrity findings: none.
- Self-review found absolute temporary job paths in raw failure traces. This is
  recorded as an integrity/redaction defect despite the report status.
- Frontend errors: `0`; missing assistant outcomes: `0`.

Screenshots are in the batch `screenshots/` directory.
