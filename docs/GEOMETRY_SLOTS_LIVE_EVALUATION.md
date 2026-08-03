# Geometry slots live evaluation

Status: deterministic production gate complete; live validation is recorded
only after the unchanged real-provider batch has completed and been frozen.

## Required batch

The live batch is `geometry-slots-live-01` and uses the five existing mixed-CAD
projects: wall carrier, portable holder, desktop organizer, monitor wall
mount, and screw-lid container. It must use the same prompts and approved fact
sheets throughout, preserve every attempt, and keep raw evidence local under
`data/debug-sessions/geometry-slots-live-01/` outside Git.

The monitor-wall-mount result is not a load-bearing safety determination.
Reports must retain its physical engineering/test-review warning even when
geometry and workflow checks pass.

## Deterministic gate

- Backend: 711 tests passed.
- Geometry-slot contract and frozen fixture replay: 19 contract/fixture tests
  passed within the targeted 39-test integration slice.
- Frontend: 93 unit tests passed; production build passed.
- Playwright: direct and compact chat-first scenarios passed at 1440×900.
- Screenshots: local ignored evidence under
  `data/debug-sessions/geometry-slots-deterministic/`.

The browser scenarios confirmed that the selected contract is visible only in
technical details, direct and compact paths use `volundr-geometry-slots-v1`,
and internal contract work does not create duplicate user-facing progress.

## Live result template

After the batch, fill this section from the frozen report rather than from
memory:

| Project | Route | Slot count | Completion | Fallback | Worker | Outcome | Integrity findings |
| --- | --- | ---: | ---: | ---: | --- | --- | --- |
| wall carrier | pending | — | — | — | — | pending | — |
| portable holder | pending | — | — | — | — | pending | — |
| desktop organizer | pending | — | — | — | — | pending | — |
| monitor wall mount | pending | — | — | — | — | pending | physical review warning |
| screw-lid container | pending | — | — | — | — | pending | — |

The self-review must classify repeated cross-product defects, repeated
same-family defects, provider variability, isolated anomalies, and integrity
or misleading-state defects. It must select exactly one next CAD priority and
write a planning-only correction plan; it must not implement corrections in
the same run.
