# CadQuery Live Smoke Correction

Date: 2026-07-30

Baseline: `docs/CADQUERY_LIVE_SMOKE_2026-07-30.md`

Final targeted rerun: `output/live-benchmarks/live-benchmark-20260730T214755Z-live-smoke-correction-targeted-v5`

## Scope

Only `parametric_configurable_organizer` and `parametric_electronics_enclosure` were rerun. The full 12-case benchmark was not run.

Provider settings matched the baseline: `gemini_api`, `gemini-3.5-flash-lite`, source brief enabled, source probe enabled, one bounded source repair enabled, Design Plan probe enabled, configuration probe enabled.

Prompt versions changed only for CadQuery source generation:

- `cadquery_source`: `cadquery-generation-v2`
- requirements/design-plan/source-brief/repair prompts remained at their prior versions

## Deterministic Corrections

- Added `requirement-trace-v1` helpers for explicit requirement inventory, authority ranks, deterministic default precedence, redundant clarification detection, Design Specification validation, Design Plan validation, source parameter validation, and execution parameter validation.
- Added authority precedence: explicit user, clarification, calculated, user-confirmed preset, printer profile, product default, AI assumption.
- Requirement extraction now builds explicit inventory before provider calls and persists a trace artifact when explicit values exist.
- Redundant clarification questions are suppressed when they restate explicit inventory values.
- Design Specification normalization restores explicit protected values and records source/provenance metadata.
- Design Plan parsing blocks or repairs missing protected requirements, value drift, unit drift, and lost source mappings.
- CadQuery source validation blocks generated source whose `ParameterSpec` defaults drift from protected requirements.
- CadQuery execution manifests now include submitted `parameters` as well as `parameter_hash`.
- Benchmark fixtures now support `expected_explicit_requirements` and source probes score explicit value preservation.
- Source probes now stop before compile when explicit requirement drift is detected.
- Frontend requirement review now labels provenance as `Source: Your request`, `Source: Your clarification`, or distinct default sources, and exposes a recoverable trace-failure state.

## Organizer Result

Baseline failure:

- Requirement prompt omitted fixture dimensions.
- Requirement extraction asked for row count, column count, and cell size.
- Defaults replaced explicit values downstream.
- Repaired source used `row_count=2`, `column_count=3`, `cell_width=50`, `cell_depth=50`, `wall_thickness=2`.

Final rerun:

- Requirement extraction preserved all explicit values and asked no clarification.
- Design Plan preserved all explicit values with source requirement IDs.
- Source parameter trace passed.
- Generated/repaired source exposed all expected parameters.
- Execution manifest parameters:

```json
{
  "cell_depth": 25.0,
  "cell_width": 35.0,
  "column_count": 4,
  "row_count": 3,
  "wall_thickness": 2.0
}
```

- Source repair was required for a CadQuery plane typo (`X_Y` -> `XY`), then compile succeeded.
- Topology passed with one valid solid and expected solid count of 1.
- Configuration probe remained blocked by printability: `orientation.overhangs` and `orientation.bridge_spans`; `orientation.unsupported_ceilings_cavities` remained a warning.

Remaining organizer issue:

- The repaired geometry still appears to use `cell_width` in some length/depth calculations, so the bounding box is larger than the explicit `3 x 25 mm` cell-depth stack implies. This is now visible as a geometry/design-quality issue, not silent requirement propagation loss.

## Enclosure Result

- Added explicit expectations for PCB envelope and standoff requirements.
- Source parameter trace passed for `pcb_width=70`, `pcb_depth=45`, `pcb_height=18`, `standoff_count=4`, and `standoff_hole=2.6`.
- Direct source compile succeeded; no repair was attempted.
- Execution manifest preserved:

```json
{
  "pcb_depth": 45.0,
  "pcb_height": 18.0,
  "pcb_width": 70.0,
  "standoff_count": 4,
  "standoff_hole": 2.6
}
```

- Topology passed for separate `base_body` and `lid_body` outputs.
- Enclosure remains reserved for the next component-targeted revision evaluation; no enclosure redesign was performed.

## Provider Usage

Final targeted rerun:

- Case runs: 2
- Estimated prompt tokens: 14,795
- Live provider calls enabled: true
- Requirement outputs collected: 2
- Source briefs parsed: 2
- Design Plans analyzed: 2
- Source probe statuses: `source_repair_succeeded=1`, `source_parameters_analyzed=1`
- Source probe compile statuses: `compile_failed=1`, `compile_succeeded=1`
- Repair compile successes: 1
- Configuration probes: `configuration_blocked=1`, `disabled=1`

The harness still reports estimated prompt tokens, not actual Gemini token usage or per-call latency.

## Baseline Comparison

| Signal | Baseline | Corrected rerun |
| --- | --- | --- |
| Organizer clarification | Redundant clarification requested | No clarification requested |
| Organizer explicit values in requirements | Lost/omitted | Preserved |
| Organizer Design Plan source IDs | Mostly null/missing | Present for protected values |
| Organizer source defaults | Drifted | Preserved |
| Organizer execution params | Empty/default-driven | Explicit values submitted and manifest-recorded |
| Organizer compile | Repaired compile | Repaired compile |
| Organizer topology | Valid one solid | Valid one solid |
| Organizer printability | Blocked | Still blocked |
| Enclosure compile | Direct or repaired depending run | Direct compile in final rerun |
| Full 12-case benchmark | Not run | Not run |

## Next Task

Use the enclosure for the first real component-targeted revision cycle. Use the organizer separately for a scoped major-redesign Revision Plan that fixes the remaining cell-depth/dependency geometry issue and label-tab printability, without weakening printability blockers.
