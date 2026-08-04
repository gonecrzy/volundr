# Ollama holdout failure anatomy

## 1. Review scope

This is a read-only review of the frozen Ollama calibration/admission evidence.
It covers all six models against both untouched holdouts. No provider, Ollama,
Gemini, formal five-case benchmark, recalibration, worker execution, profile,
prompt, normalizer, evaluator, topology, timeout, or admission-record change
was performed. The machine-readable result is outside Git at
`data/debug-sessions/ollama-calibration/calibration-admission-report/holdout-failure-anatomy.json`.

The current repository began at local `b288cc1` with relation to `origin/main`
`0 1`; the local divergence was preserved. The implementation commits remain
local and are not pushed by this review.

## 2. Evidence identity

The authoritative combined evidence is
`data/debug-sessions/ollama-calibration/calibration-admission-report/`.
Five models use the frozen `calibration-admission-final-v2` run. Qwen2.5-Coder
14B uses the later frozen `qwen14-iteration-3` run because it is the run whose
profile hash matches the final admission record. The untouched prompts are in
`benchmarks/ollama-holdout-v1.yaml`.

The experiment records:

- starting base: `b288cc1ea3e19a587e18ac7822b21ef95cc8f7ca`;
- starting `origin/main`: `becccb82916a2777a5e499798f19f9c98a9a22a5`;
- starting divergence: `0 1`;
- Gemini called: `false`;
- formal benchmark started: `false`;
- one active model at a time: `true`;
- resolution queue: 67 unique records, 0 open, all profile hashes present.

### Model identities and frozen profiles

| Model | Exact model name | Full digest | Quantization | Profile hash |
|---|---|---|---|---|
| CAD-Coder | `volundr-cad-coder-native:q8_0` | `78a44226975041264edeee70beb170e2a02f32949f3ea8de51b3fcdc5b73ae51` | `Q8_0` | `d9d01e89cccf4fbece5e0850d1948a7df02f77805ee0c2a6c31117af33156cf5` |
| ProCAD-Coder | `volundr-procad-coder-native:q8_0` | `92d3a018374f3603e6c2a4cc72a8a987c525b0398bea29b7382a19e9ff0a3120` | `Q8_0` | `6edd575bbd0c72336e2f2dc2d17aa0064874004c67d642ba70513cc685569a5b` |
| Qwen2.5 CadQuery | `hf.co/yuvit-batra/qwen2.5-coder-7b-cadquery-gguf:Q4_K_M` | `692bb3cfa2f456c1170a85bfbc28f98be5f5a2df00ccf1be2365304920a06256` | `Q4_K_M` | `6009db8978d94402f2b097832374d08783b658e6ed0c333674b383867ace74e3` |
| Qwen2.5-Coder 14B | `qwen2.5-coder:14b-instruct-q5_K_M` | `05d16c5ac1c126618f66f52d6099514df79bf104fcb889bee9069a751822d3e7` | `Q5_K_M` | `e9a63b02095a1db92ec8ee61db5c4af70033a6a8f1111aab65ccb9c1f4943dd0` |
| DeepSeek-Coder-V2-Lite | `deepseek-coder-v2:16b-lite-instruct-q4_K_M` | `dac6ff6589c90902a8e5b11583492d17e87b6f3ddb25e558c593110a23a547aa` | `Q4_K_M` | `e73b6cc45b570e031bfb3bd626e6eae781dd8f5946000a174694876716e5d750` |
| C3Dv0 | `joshuaokolo/C3Dv0:latest` | `0e44735f72fb7dbb6e28af836e6b365bc44c32007e7b8cb1d8ae31c7a0b574fa` | `Q8_0` | `274b13bbf4535e2505a2deb07c2d1edc66822160dd99996e2a3068abf900c1a7` |

## 3. Complete blocker table

`Raw response class`, normalization, AST, source safety, worker, artifacts,
topology, and geometry are reported from the exact paths listed in the final
column. A blank artifact-manifest result means that the worker result was
preserved but a separate STEP/STL/BREP manifest was not present in the frozen
root; it is not an inferred artifact.

| Model | Holdout | Raw response class | Normalization | AST | Source safety | Worker | Artifacts | Topology | Broad geometry | Earliest blocker | Secondary findings | Evidence paths |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CAD-Coder | Angled phone cradle | fenced native script with trailing fence | `representation.markdown_wrapped`; safe wrapper only; worker hash verified | valid | no finding | completed; success | worker output recorded; artifact manifest missing | 1 valid solid, volume 5616 mm³ | bounds `[10.5093,13.4114,78]` vs `[8,12,78]`; rotate marker passed | `dimension_measurement / wrong_overall_dimensions` | none independently authoritative | `data/debug-sessions/ollama-calibration/calibration-admission-final-v2/calibration/cad-coder/holdout/holdout-001/{raw-response.txt,response.json,worker/result.json,worker/finding.json}` |
| CAD-Coder | Mounting spacer | missing/empty response | no normalized response | invalid Python | not reached | not run | not generated | not reached | not measured | `python_ast / invalid_python` | none | `data/debug-sessions/ollama-calibration/calibration-admission-final-v2/calibration/cad-coder/holdout/holdout-002/{raw-response.txt,failure.json}` |
| ProCAD-Coder | Angled phone cradle | native script | no semantic change; worker hash verified | valid | no finding | completed; success | worker output recorded; artifact manifest missing | 1 valid solid, volume 28957.5 mm³ | bounds `[3,125,130]` vs `[8,12,78]`; rotate marker failed | `dimension_measurement / wrong_overall_dimensions` | `support_angle_missing_or_wrong`; no independent angle measurement | `data/debug-sessions/ollama-calibration/calibration-admission-final-v2/calibration/procad-coder/holdout/holdout-001/{raw-response.txt,response.json,worker/result.json,worker/finding.json}` |
| ProCAD-Coder | Mounting spacer | native script | no semantic change; worker hash verified | valid | no finding | completed; invalid output | not generated | solid-count mismatch, 0 of 1 | not measured | `topology / no_solid` | invalid output shape | `data/debug-sessions/ollama-calibration/calibration-admission-final-v2/calibration/procad-coder/holdout/holdout-002/{raw-response.txt,response.json,worker/result.json,worker/finding.json}` |
| Qwen2.5 CadQuery | Angled phone cradle | native script | no semantic change; worker hash verified | valid | no finding | completed with exception | not generated | not reached | not measured | `worker_runtime / unsupported_cadquery_api` | `cq.math.deg_to_rad` is absent in the worker CadQuery API | `data/debug-sessions/ollama-calibration/calibration-admission-final-v2/calibration/qwen25-cadquery/holdout/holdout-001/{raw-response.txt,response.json,worker/result.json,worker/finding.json}` |
| Qwen2.5 CadQuery | Mounting spacer | native script | no semantic change; worker hash verified | no finding | completed; success | worker output recorded; artifact manifest missing | 1 valid solid, bounds exact, volume 28000 mm³ | bounds passed; `hole`/`circle` feature markers failed | `feature_measurement / through_hole_missing` | source creates only the plate; four through-holes are absent | `data/debug-sessions/ollama-calibration/calibration-admission-final-v2/calibration/qwen25-cadquery/holdout/holdout-002/{raw-response.txt,response.json,worker/result.json,worker/finding.json}` |
| Qwen2.5-Coder 14B | Angled phone cradle | fenced native script | `representation.markdown_wrapped`; safe wrapper only; worker hash verified | valid | no finding | completed; success | worker output recorded; artifact manifest missing | 1 valid solid, volume 389577.97 mm³ | bounds `[78,87.5772,111.7617]` vs `[8,12,78]`; rotate marker passed | `dimension_measurement / wrong_overall_dimensions` | no independent support-angle or cable-centering measurement | `data/debug-sessions/ollama-calibration/qwen14-iteration-3/calibration/qwen25-coder-14b/holdout/holdout-001/{raw-response.txt,response.json,worker/result.json,worker/finding.json}` |
| Qwen2.5-Coder 14B | Mounting spacer | fenced native script | `representation.markdown_wrapped`; safe wrapper only; worker hash verified | valid | no finding | completed with exception | not generated | not reached | not measured | `worker_runtime / invalid_workplane_operation` | detached hole workplane; `Cannot find a solid on the stack or in the parent chain` | `data/debug-sessions/ollama-calibration/qwen14-iteration-3/calibration/qwen25-coder-14b/holdout/holdout-002/{raw-response.txt,response.json,worker/result.json,worker/finding.json}` |
| DeepSeek-Coder-V2-Lite | Angled phone cradle | fenced native script | `representation.markdown_wrapped`; safe wrapper only; worker hash verified | valid | no finding | completed with exception | not generated | not reached | not measured | `worker_runtime / invalid_selector` | `.edges("|Z", "CNC")` caused `No Workplane object named CNC` | `data/debug-sessions/ollama-calibration/calibration-admission-final-v2/calibration/deepseek-coder-v2-lite/holdout/holdout-001/{raw-response.txt,response.json,worker/result.json,worker/finding.json}` |
| DeepSeek-Coder-V2-Lite | Mounting spacer | fenced native script | `representation.markdown_wrapped`; safe wrapper only; worker hash verified | valid | no finding | completed with exception | not generated | not reached | not measured | `worker_runtime / unsupported_cadquery_api` | `cq.FACE_TOP` is absent in the worker CadQuery API | `data/debug-sessions/ollama-calibration/calibration-admission-final-v2/calibration/deepseek-coder-v2-lite/holdout/holdout-002/{raw-response.txt,response.json,worker/result.json,worker/finding.json}` |
| C3Dv0 | Angled phone cradle | native script | no semantic change; worker hash verified | source-safety rejection | reached, rejected before geometry | not generated | not reached | not measured | `source_safety / artifact_registration_missing` | generated source explicitly called `cq.exporters.export` | `data/debug-sessions/ollama-calibration/calibration-admission-final-v2/calibration/c3dv0/holdout/holdout-001/{raw-response.txt,response.json,worker/result.json,worker/finding.json}` |
| C3Dv0 | Mounting spacer | fenced native script | `representation.markdown_wrapped`; safe wrapper only; worker hash verified | valid | no finding | completed with exception | not generated | not reached | not measured | `worker_runtime / unsupported_cadquery_api` | `cq.exporters.stl` is absent in the worker CadQuery API | `data/debug-sessions/ollama-calibration/calibration-admission-final-v2/calibration/c3dv0/holdout/holdout-002/{raw-response.txt,response.json,worker/result.json,worker/finding.json}` |

The worker requests and separate source-safety manifests are not present in the
final run roots. Where a normalized source and worker `source_hash` exist, the
recorded hash equals the hash of the existing Volundr worker wrapper around that
normalized source. The wrapper adds only the output contract; it does not add
CAD operations. The missing request manifest is recorded as a limitation, not
as an integration failure.

The exact frozen prompts are available in
`benchmarks/ollama-holdout-v1.yaml`; separately rendered prompt files are not
preserved in the final roots. This is recorded as
`rendered_prompt: evidence_missing` in the machine-readable report and is not
promoted to a profile-rendering blocker because the frozen prompt source and
profile hashes are present and no render mismatch was evidenced.

## 4. Source-normalization audit

All twelve raw responses were inspected. Eleven have a preserved normalized
response and valid Python AST. The CAD-Coder spacer attempt has an empty raw
response and `failure.json` records `model.native_source_invalid`; it therefore
has no normalized source to audit.

The only normalization codes are `representation.markdown_wrapped`. The exact
diffs remove Markdown fence lines or a trailing fence; no executable CAD line
was reordered, indented differently, or truncated. `result` is exported by all
eleven parseable scripts. No reasoning wrapper, slot-order rewrite, or
ambiguous final-result alias was selected. The normalized source hash and the
recorded wrapped worker hash agree for all ten worker-executed parseable cases
and for the two successful source-only cases with worker records; the empty
CAD-Coder spacer case is not verifiable because no normalized source exists.

Normalization therefore did not alter model meaning and no prior holdout
classification is reclassified as an adapter failure.

## 5. Worker, topology, and geometry results

Worker completion was treated as an execution boundary, not a quality pass.
The successful cases were:

- CAD-Coder cradle: one valid connected solid, but bounds were outside the
  frozen broad tolerance.
- ProCAD cradle: one valid connected solid, but bounds were radically wrong.
- Qwen2.5 CadQuery spacer: one valid connected plate with exact outer bounds,
  but no hole feature markers.
- Qwen2.5-Coder 14B cradle in the final iteration: one valid connected solid,
  but it was a large rotated block rather than a cradle-sized support.

The remaining cases either never produced an executable solid, were rejected
by source safety, raised a model-emitted CadQuery/API exception, or failed the
topology contract. No STEP, STL, or BREP artifact manifest is preserved in the
review roots, so artifact existence is not used to upgrade any quality band.

## 6. Quality bands

| Model | Phone cradle | Spacer |
|---|---|---|
| CAD-Coder | `valid_topology_wrong_shape` | `no_executable_geometry` |
| ProCAD-Coder | `valid_topology_wrong_shape` | `executable_but_invalid` |
| Qwen2.5 CadQuery | `no_executable_geometry` | `partially_satisfies_holdout` |
| Qwen2.5-Coder 14B | `valid_topology_wrong_shape` | `no_executable_geometry` |
| DeepSeek-Coder-V2-Lite | `no_executable_geometry` | `no_executable_geometry` |
| C3Dv0 | `no_executable_geometry` | `no_executable_geometry` |

There is no holdout pass. The Qwen2.5 CadQuery spacer is the closest result:
its plate bounds and topology are valid, but the required through-hole feature
is absent. That is partial satisfaction, not evaluator rejection of correct
geometry.

## 7. Cross-model signature analysis

| Signature family | Recurrence | Determination |
|---|---|---|
| Markdown wrapper removal | 5 models, both holdouts for the affected models | Safe representation adaptation; worker hashes verify the wrapped source. Not a defect. |
| Wrong overall dimensions | 3 models on phone cradle | Independent model geometry, with different oversized or undersized constructions. Does not meet the shared-defect rule because the same missing CAD operation explains the outputs. |
| Unsupported CadQuery/API usage | 3 models, but different APIs (`cq.math`, `cq.FACE_TOP`, `cq.exporters.stl`) | Model-emitted API incompatibility, not one shared Volundr defect. |
| Invalid workplane/selector construction | 3 model families across separate cases | Different source operations and different exceptions; worker behavior is consistent. |
| Topology no-solid | 1 model/case | Isolated model output failure. |
| Evaluator false rejection | 0 proven | No valid geometry with a contradictory expected measurement was found. |
| Shared adapter/worker/artifact/topology-reader defect | 0 signatures meeting all threshold conditions | Not supported by evidence. |

The recurring categories are intentionally not promoted to shared Volundr
defects: each has different source-level operations and the worker reports
those operations consistently. Infrastructure, adapter, and evaluator
failures are not converted into CAD-quality findings.

## 8. Holdout fairness audit

Both holdouts are `fair_with_minor_evaluator_risk`.

- The phone prompt directly specifies width, thickness, approximate angle,
  one-piece intent, and a centered charging opening. The spacer prompt directly
  specifies outer dimensions, thickness, hole diameter/count, and pattern.
- The prompts do not require an unspecified implementation or exact value for
  an approximate angle.
- The frozen broad evaluator measures bounds and source markers. It does not
  independently measure support angle, charging-hole centering, hole count,
  hole diameter, rectangular spacing, or through condition in full.
- That evaluator limitation lowers confidence in a near miss, but none of the
  preserved successful outputs is geometrically close enough with a
  contradictory finding to establish `valid_geometry_marked_failed`, an
  evaluator crash, or an invalid holdout.

The holdouts remain untouched and are not corrected during this review.

## 9. Native-adaptation assessment

No production native-script experiment is justified by this evidence. At least
two models produce executable native CAD, but their failures are predominantly
missing or wrong geometry, invalid CadQuery construction, unsupported
model-emitted APIs, or explicit artifact-writing calls. Safe wrapper removal
already succeeds. A future native diagnostic path may be useful as a separate
capability experiment, but it is not the explanation for these twelve failures
and must not add holes, extrusions, dimensions, support geometry, or other CAD
operations.

Native-script capability and production-slot compatibility remain separate. The
production slot was not used to upgrade any native holdout result.

## 10. Admission reassessment

The persisted admission report is unchanged. The following are proposals only:

| Model | Current disposition | Proposed disposition | Evidence | Confidence |
|---|---|---|---|---|
| CAD-Coder | `operational_low_cad_quality` | `operational_low_cad_quality_confirmed` | Valid topology but wrong cradle dimensions; spacer never parsed | high |
| ProCAD-Coder | `operational_low_cad_quality` | `operational_low_cad_quality_confirmed` | Wrong cradle bounds; spacer has no valid solid | high |
| Qwen2.5 CadQuery | `operational_low_cad_quality` | `operational_low_cad_quality_confirmed` | Unsupported API on cradle; valid plate missing all holes | high |
| Qwen2.5-Coder 14B | `operational_low_cad_quality` | `operational_low_cad_quality_confirmed` | Oversized cradle block; spacer workplane runtime failure | high |
| DeepSeek-Coder-V2-Lite | `operational_low_cad_quality` | `operational_low_cad_quality_confirmed` | Two distinct model-source API/construction failures | high |
| C3Dv0 | `operational_low_cad_quality` | `operational_low_cad_quality_confirmed` | Artifact-writing source rejection and unsupported exporter API | high |

No model is native-diagnostic admitted, deferred for integration, or deferred
for evaluator review. The formal gate remains blocked because no specialist and
generic baseline pair is admitted.

## 11. Primary conclusion — D. Insufficient model CAD capability

The six models failed for independent source and geometry reasons under fair,
frozen profiles. Volundr integration reached and validated topology wherever
the model supplied executable compatible source; normalization preserved
meaning; and no evaluator contradiction was found. The repeated failure
signatures are not the same missing operation or the same downstream defect.

## 12. Rejected alternatives

- **A, shared Volundr integration defect:** rejected because no adapter, worker,
  artifact, topology-reader, or evaluator signature meets the three-model
  threshold with independently plausible sources and a common cause.
- **B, native-output adaptation opportunity:** rejected as the primary cause;
  safe fence removal works and the remaining failures require CAD operations or
  corrections that adaptation may not invent.
- **C, holdout/evaluator defect:** rejected because no valid geometry was
  contradicted by the frozen checks. Minor measurement gaps are limitations,
  not a demonstrated false failure.
- **E, mixed and inconclusive:** rejected because the evidence converges on
  independent model-source and model-geometry failures; the minor evaluator
  risk does not materially change the admission result.

## 13. Exact next action

Do not run the formal five-case benchmark. Test stronger or different
specialist/generic models under a separately approved experiment, or stop
local-model investment for now. Preserve this report as the baseline; do not
change the frozen profiles, prompts, holdouts, worker, topology gates,
normalizers, or verification rules as part of this conclusion.

## 14. Limitations

The final evidence roots do not contain separate worker request manifests or
artifact manifests, so the report cannot provide those absent files. Worker
source equivalence is verified from the normalized source and recorded wrapped
hash where possible. The broad evaluator does not measure every named feature,
and no new calls were made to resolve that limitation. Raw responses, source,
and artifacts remain outside Git; the analysis JSON is also outside Git.
