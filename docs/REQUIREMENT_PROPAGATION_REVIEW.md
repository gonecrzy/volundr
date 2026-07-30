# Requirement Propagation Review

Date: 2026-07-30

Evidence source: `output/live-benchmarks/live-benchmark-20260730T210531Z-live-smoke-4case-baseline/artifacts/parametric_configurable_organizer/run-001`

Baseline report: `docs/CADQUERY_LIVE_SMOKE_2026-07-30.md`

## Scope

This review traces the `parametric_configurable_organizer` live smoke failure before implementation changes. The goal is to identify where explicit benchmark/user requirements were lost, why redundant clarification was requested, and which corrections can be deterministic rather than prompt-dependent.

## Explicit Requirement Inventory

The organizer benchmark declared these explicit values in `benchmark-input.json` and `backend/tests/fixtures/generation_benchmarks/full.json`:

| Requirement ID | Expected value | Unit | Requirement type | Protected | Evidence |
| --- | ---: | --- | --- | --- | --- |
| `row_count` | 3 | count | explicit count | yes | `rows=3` |
| `column_count` | 4 | count | explicit count | yes | `columns=4` |
| `cell_width` | 35.0 | mm | explicit numeric value | yes | `cell=35x25 mm` |
| `cell_depth` | 25.0 | mm | explicit numeric value | yes | `cell=35x25 mm` |
| `wall_thickness` | 2.0 | mm | explicit numeric value | yes | `wall_thickness=2 mm` |
| `label_tabs` | enabled/requested | boolean feature | explicit feature | yes | `label tabs` |

Allowed defaults were also declared, but only for absent values:

| Requirement ID | Default value | Unit | Source |
| --- | ---: | --- | --- |
| `label_tab_height` | 8.0 | mm | allowed product assumption |
| `corner_radius` | 1.0 | mm | allowed product assumption |

## Stage Trace

| Stage | Observed value state | First mismatch |
| --- | --- | --- |
| Original benchmark request | `input_prompt` says editable row count, column count, cell size, wall thickness, and label tabs. The benchmark metadata separately declares `rows=3`, `columns=4`, `cell=35x25 mm`, and `wall_thickness=2 mm`. | The live requirement prompt used only `input_prompt`; it did not include `required_dimensions`, so the explicit numeric values were not in the rendered requirement prompt. |
| Requirement prompt | `requirements-prompt.txt` contains no `rows=3`, `columns=4`, `cell=35x25 mm`, or `wall_thickness=2 mm`. It does include versioned default `wall_thickness_mm=3.0`. | `row_count`, `column_count`, `cell_width`, `cell_depth`, and `wall_thickness` became unavailable to the requirement extractor as authoritative input. |
| Raw requirement response | Asked for row count, column count, and cell size. Assumed `3x3`, `50mm per cell`, and printer-profile wall thickness `3.0mm`. | Redundant relative to benchmark expectations, but not redundant relative to the actual rendered prompt. The harness had already dropped the benchmark explicit values. |
| Parsed Design Specification | Live harness did not persist a normalized parsed spec artifact for this case. The response was considered `provider_output_collected` even though outcome was `clarification_required`. | The harness did not score explicit requirement match and did not block downstream probes after the requirement outcome contradicted expected clarification `none`. |
| Benchmark fallback Design Specification | For Design Plan probing, `_benchmark_design_specification()` used `required_dimensions` only as unstructured `functional_requirements` strings. It did not create `critical_dimensions`, `parameters`, protected flags, authority ranks, or stable source IDs. | Explicit values reappeared only as strings, not as protected structured requirements. |
| Raw and parsed Design Plan | Produced `row_count=3`, `column_count=3`, `cell_size_mm=50`, `wall_thickness_mm=3.0`. Only `wall_thickness_mm` had a `source_requirement_id`; row, column, and cell values had `null`. | `column_count`, `cell_width`, `cell_depth`, and `wall_thickness` were default-substituted or remapped. Existing validator could not detect unlinked missing values because it only checks values when `source_requirement_id` is present. |
| Source prompt and raw source | Source generation targeted expected parameter names but not expected values. | Parameter-name coverage passed while value preservation failed. |
| Repaired CadQuery source | `ParameterSpec` defaults: `row_count=2`, `column_count=3`, `cell_width=50.0`, `cell_depth=50.0`, `wall_thickness=2.0`. | `row_count`, `column_count`, `cell_width`, and `cell_depth` drifted again. Repair fixed a CadQuery API error and preserved the wrong source defaults. |
| Execution manifest | `parameter_hash` was the hash of `{}` and `parameters` was `null`, so execution used source defaults. Topology was valid with bounds `158 x 108 x 40 mm`. | No resolved execution parameter manifest existed to compare against the approved specification/plan before worker submission. |
| Geometry and printability | One valid solid was produced. Configuration probe preserved source hash and changed parameter hash, but printability blocked on `orientation.overhangs` and `orientation.bridge_spans`. | This printability block is not caused by explicit value propagation. It appears to be generated geometry/orientation risk around unsupported/bridged label-tab geometry and should not be weakened. |

## Per-Requirement Findings

| Requirement | Requirement extraction | Design Specification | Design Plan | Source contract | Execution | Classification |
| --- | --- | --- | --- | --- | --- | --- |
| `row_count=3` | Not supplied to prompt; model asked clarification and also assumed `3`. | Not represented as protected structured value in benchmark spec. | Present as `row_count=3`, but unprotected and source ID missing. | Changed to default `2`. | Used source default `2`. | Not extracted from authoritative input, source mapping lost, overridden by generated default. |
| `column_count=4` | Not supplied to prompt; model asked clarification and assumed `3`. | Not represented as protected structured value. | Present as `column_count=3`, unprotected and source ID missing. | Present as `column_count=3`. | Used source default `3`. | Not extracted, replaced by default, value mismatch not detected. |
| `cell_width=35 mm` | Not supplied to prompt; model asked for cell dimensions and assumed a square `50mm` cell. | Only unstructured `cell=35x25 mm` string in benchmark spec. | Collapsed into `cell_size_mm=50`, losing width/depth distinction. | Present as `cell_width=50.0`. | Used source default `50.0`. | Remapped to another parameter, replaced by default, source mapping lost. |
| `cell_depth=25 mm` | Not supplied to prompt; model asked for cell dimensions and assumed a square `50mm` cell. | Only unstructured `cell=35x25 mm` string in benchmark spec. | Collapsed into `cell_size_mm=50`, losing width/depth distinction. | Present as `cell_depth=50.0`. | Used source default `50.0`. | Remapped to another parameter, replaced by default, source mapping lost. |
| `wall_thickness=2 mm` | Not supplied to prompt; model used printer-profile default `3.0`. | Only unstructured `wall_thickness=2 mm` string in benchmark spec. | Present as `wall_thickness_mm=3.0` and incorrectly linked to `wall_thickness_mm`. | Present as `wall_thickness=2.0`. | Used source default `2.0`. | Replaced by default in requirements/plan; source later happened to recover expected value without trace. |
| `label_tabs` | Extracted as a functional requirement. | Preserved as unstructured purpose/feature. | Present as `label_tabs` component/feature. | Present as `label_tabs_enabled=True`. | Used source default `True`. | Feature survived, but provenance/protection were not preserved. |

## Clarification Defect

Clarification was requested because the rendered requirement prompt omitted the explicit benchmark dimensions and the model treated row count, column count, and cell size as critical missing information. The product defect is broader: even when explicit values are available in surrounding benchmark metadata or a user request, there is no deterministic explicit requirement inventory used to reject questions that restate known values.

The current pipeline would have allowed redundant questions to reach the user if the model asked about a value present in the request, because clarification acceptance is based on schema validity and derived outcome, not on comparison with a protected explicit inventory.

Stable finding needed: `clarification_redundant`.

## Validator Coverage

Current validation could detect only one narrow class of drift: a numeric Design Plan parameter with a `source_requirement_id` that points to a numeric Design Specification value and has a mismatching value or unit.

It could not detect this failure because:

- requirement extraction had no explicit inventory to compare against;
- benchmark `required_dimensions` were not included in the requirement request;
- fallback benchmark Design Specification stored explicit dimensions as strings in `functional_requirements`;
- Design Plan validation did not require every protected explicit requirement to appear;
- Design Plan validation did not require source IDs for protected values;
- source parameter analysis checked expected parameter names and types, not default/current values or provenance;
- execution used an empty parameter-value manifest and relied on generated defaults;
- benchmark scoring did not include stage-by-stage explicit requirement preservation.

## Failure Type

This is a combination failure:

- Harness/orchestration: benchmark `required_dimensions` were not propagated into requirement extraction and were later represented as unstructured strings.
- Schema/modeling: Design Specification lacks a normalized explicit requirement inventory and authority rank metadata.
- Validation: validators do not require protected explicit requirements to be represented, linked, and value-matched at every stage.
- Prompting: prompts do not yet require stable source requirement IDs or prohibit redundant clarification/default replacement strongly enough.

Prompt changes alone are insufficient. Deterministic merge and validation must be established first.

## Deterministic Fixes

The following fixes can be deterministic and should precede prompt changes:

- Parse and normalize an explicit requirement inventory before provider output is accepted.
- Merge defaults into a resolved requirement set using the authority order: user explicit, clarification, calculated, confirmed preset, printer profile, product default, AI assumption.
- Reject or repair requirement outputs that ask clarification about an already-known explicit value.
- Persist a versioned `requirement-trace-v1` artifact with inventory, resolved values, stage findings, and block status.
- Validate Design Specifications against the inventory before marking them generation-ready.
- Validate Design Plans against protected explicit requirements before approval or generation.
- Validate generated CadQuery `ParameterSpec` defaults/metadata against the approved plan before worker execution.
- Submit explicit resolved parameter values to execution instead of relying on source defaults for protected values.
- Extend benchmark fixtures with `expected_explicit_requirements` and score every stage.

## Prompt Changes Deferred

Prompt changes are warranted after deterministic validation exists, but they should be narrow:

- include explicit requirement inventory in requirement, plan, and source prompts;
- require stable source requirement IDs;
- require authority/source/protected metadata;
- prohibit defaults from replacing explicit values;
- prohibit clarification for supplied values;
- increment prompt versions and update snapshots.

## Configuration Probe Determination

The organizer configuration probe correctly changed the parameter hash while preserving the source hash, which confirms deterministic configuration did not call the provider or rewrite source. The printability block appears to be caused by poor generated geometry and/or orientation strategy for the label tabs, not by the configured values themselves. The blocking rules reported `orientation.overhangs` and `orientation.bridge_spans`; these should remain blocking until geometry or orientation improves.

## Immediate Correction Scope

Implement a generic requirement authority layer, not organizer-specific logic:

1. Add explicit requirement inventory and authority rank metadata.
2. Add deterministic default merge and trace artifact generation.
3. Suppress redundant clarification and add one bounded requirement-output repair path.
4. Block Design Specification, Design Plan, source, and execution drift before CadQuery execution.
5. Extend benchmark expected requirement scoring and add organizer regression coverage from this exact case.
6. Add frontend provenance/default rendering and trace failure state.

Do not run the full 12-case benchmark during this pass.
