# CadQuery Live Smoke Evaluation - 2026-07-30

## Scope

This is the first small controlled live Gemini API baseline after the CadQuery
architecture transition. It intentionally makes no prompt, schema, frontend, or
CAD execution changes.

Run directory:

```text
output/live-benchmarks/live-benchmark-20260730T210531Z-live-smoke-4case-baseline
```

Preflight dry-run:

```text
output/live-benchmarks/live-benchmark-20260730T210517Z-live-smoke-4case-preflight
```

Live command:

```bash
rtk .venv/bin/python scripts/run_live_generation_benchmarks.py \
  --suite tests/fixtures/generation_benchmarks/full.json \
  --output-dir ../output/live-benchmarks \
  --run-label live-smoke-4case-baseline \
  --benchmark-id simple_mounting_plate \
  --benchmark-id parametric_adapter \
  --benchmark-id parametric_electronics_enclosure \
  --benchmark-id parametric_configurable_organizer \
  --provider gemini-api \
  --allow-live \
  --source-probe \
  --source-brief \
  --source-probe-repair \
  --design-plan-probe \
  --configuration-probe \
  --max-runs 4 \
  --max-estimated-tokens 80000
```

The dry-run estimated `24318` prompt tokens. The live harness does not record
actual Gemini usage metadata or per-call latency. The terminal-observed wall
time was about 95 seconds. Worker execution time for final compiled artifacts
ranged from 58.809 ms to 247.101 ms.

## Provider Usage

- Provider: `gemini_api`
- Model: `gemini-3.5-flash-lite`
- Thinking level: `minimal`
- Live provider call artifacts: 18
- Call artifact breakdown: 4 requirements, 4 source briefs, 4 Design Plans, 4
  source generations, 2 source repairs.
- Configuration probe provider calls: 0; it reused generated source.
- Estimated token budget used by harness preflight: `24318`
- Dollar cost: not recorded by the harness.

Artifact integrity:

- `run-manifest.json` SHA-256:
  `a1fb19a10b8b22533b89c7071b722eec28f4354ed0a5fc594fe6faec3003a4eb`
- `aggregate-metrics.json` SHA-256:
  `729edc54d71811312c2a85f1ecb33ede3d4a896ccaeb11f788c709e24e72217f`

## Automated Results

- Case runs: 4
- Requirement outputs collected: 4
- Source briefs parsed: 4
- Design Plans analyzed: 4
- Direct source compile: 2 succeeded, 2 failed
- Repair attempts: 2
- Repair compile: 2 succeeded
- Expected parameter coverage average: 1.0
- Topology rejection count: 0
- Solid-count rejection count: 0
- Disconnected mesh count: 0
- Design Plan component coverage average: 0.8889
- Design Plan feature coverage average: 0.7778
- Design Plan output coverage average: 1.0
- Design Plan dependency coverage average: 0.4444
- Configuration probe: 1 blocked, 3 disabled

The run is a useful baseline, but not a product-quality pass. Two of four direct
source generations required repair, and two cases exposed workflow or
requirements-quality concerns.

## Case Review

| Case | Final compile state | Product-quality classification | Review notes |
| --- | --- | --- | --- |
| `simple_mounting_plate` | Direct compile succeeded | Printable as generated | Dimensions, two holes, parameter coverage, STEP/STL/BREP, and topology are correct. STL visual triangulation looks busy but volume matches the expected rectangular plate minus two holes. |
| `parametric_adapter` | Direct compile failed; repair succeeded | Printable after minor parameter/orientation review | Design Plan coverage is perfect and repaired source is valid. Direct failure was CadQuery loft misuse. Visual review shows a blunt rectangular-to-round duct body with open passage; it likely needs print orientation/support review before calling it print-ready. |
| `parametric_electronics_enclosure` | Direct compile succeeded | Requires targeted revision before acceptance | Requirements correctly returned `clarification_required`, but the forced source probe still generated base/lid artifacts. The geometry is plausible with base, lid, standoffs, and cable opening, but the product workflow should not accept it until standoff placement, cable opening, and snap-fit details are answered. Design Plan missed the explicit `standoffs` component and two expected dependencies. |
| `parametric_configurable_organizer` | Direct compile failed; repair succeeded | Requires major redesign | The original prompt specified rows=3, columns=4, cell=35x25 mm, wall=2 mm. Requirements incorrectly asked for clarification and introduced 3x3/50 mm assumptions. Repaired source defaults to row_count=2, column_count=3, cell_width=50, cell_depth=50. Configuration with `label_tabs_enabled=true` compiled with the same source hash and changed parameter hash, but was blocked by `orientation.overhangs` and `orientation.bridge_spans`. |

## Artifact Review Paths

Visual contact sheets:

- `output/live-benchmarks/live-benchmark-20260730T210531Z-live-smoke-4case-baseline/manual-review/simple_mounting_plate-contact.png`
- `output/live-benchmarks/live-benchmark-20260730T210531Z-live-smoke-4case-baseline/manual-review/parametric_adapter-contact.png`
- `output/live-benchmarks/live-benchmark-20260730T210531Z-live-smoke-4case-baseline/manual-review/parametric_electronics_enclosure-contact.png`
- `output/live-benchmarks/live-benchmark-20260730T210531Z-live-smoke-4case-baseline/manual-review/parametric_configurable_organizer-contact.png`

Final source artifacts:

- `artifacts/simple_mounting_plate/run-001/source-extracted.py`
- `artifacts/parametric_adapter/run-001/source-repair-extracted.py`
- `artifacts/parametric_electronics_enclosure/run-001/source-extracted.py`
- `artifacts/parametric_configurable_organizer/run-001/source-repair-extracted.py`

Final execution manifests:

- `artifacts/simple_mounting_plate/run-001/source-compile-workspace/source-probe/execution-manifest.json`
- `artifacts/parametric_adapter/run-001/source-repair-compile-workspace/source-repair/execution-manifest.json`
- `artifacts/parametric_electronics_enclosure/run-001/source-compile-workspace/source-probe/execution-manifest.json`
- `artifacts/parametric_configurable_organizer/run-001/source-repair-compile-workspace/source-repair/execution-manifest.json`
- `artifacts/parametric_configurable_organizer/run-001/configuration-compile-workspace/configuration-probe/execution-manifest.json`

## Deterministic Configuration Evidence

Only `parametric_configurable_organizer` has fixture configuration overrides in
this four-case set.

- Source hash remained unchanged:
  `182e9292e16d1a413ee4a4b7ada25e2665deb332a878b941929bb3cfb7087e16`
- Default parameter hash:
  `44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a`
- Configuration parameter hash:
  `e076c8c368e341a21615278da4e733a0a77a986568e75a3ca0a8972f423e8a7f`
- Configuration compile succeeded and topology remained valid.
- Configuration state was blocked by printability rules:
  `orientation.overhangs`, `orientation.bridge_spans`.
- This proves provider-free regeneration mechanics for the probe, but the
  generated model itself is not product-quality.

## Follow-Up Buckets

1. Requirement prompts: organizer should not ask for clarification when rows,
   columns, cell size, and wall thickness are already present.
2. Design Plan decomposition: enclosure should keep standoffs as an explicit
   component and preserve dependency names close enough for downstream scoring.
3. CadQuery source generation: adapter and organizer direct source should not
   require repair for common CadQuery API usage.
4. Parameter modeling: organizer defaults must match explicit request values.
5. Printability: organizer label tabs create blocked bridge/overhang findings.
6. Product workflow discipline: forced source probes after
   `clarification_required` are benchmark evidence only, not acceptance-ready
   candidates.

## Next Recommended Validation

Use `simple_mounting_plate` as the strongest generated model for the first full
acceptance-to-revision cycle, or use the electronics enclosure only after
answering its clarification questions. Do not expand to the full 12-case live
benchmark until the organizer requirement/default failure is understood.
