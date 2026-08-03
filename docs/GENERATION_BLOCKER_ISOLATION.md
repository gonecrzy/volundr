# Generation blocker isolation

## Evidence and test boundary

The authoritative machine record is the local redacted file
`data/debug-sessions/contract-complexity-20260803/experiment.json` (SHA-256
`365deb92b3c902559fd823b627e4e30597bfd17e7f9eeeef248f4672f0cefc3a`). Raw prompts, provider responses, assembled source, worker
jobs, and logs remain under that ignored local evidence root and outside Git.
The diagnostic does not create projects, workflow runs, attempts, revisions,
exports, or Current working versions.

The preceding narrow lifecycle correction is committed as `8e64c0d` and its
focused regression suite passed. It corrects the Batch 2 screw-lid reporting
classification; it is not treated as the generation result here.

## Frozen inputs

The packages were extracted from preserved Batch 1 evidence and hash-checked
before every matrix cell. No requirement extraction or clarification calls
were made during this experiment. Approved fact-sheet answers are frozen in the
packages; exposed controls are empty.

| family | source project | source batch | package hash |
|---|---|---|---|
| desktop organizer | `ef3cc600-7230-4477-921d-fc4d76d80a0d` | `c3179a89-62e2-4d61-b3dc-a36f4b9956b6` | `b1e1310e3f4adedaab60cd5c6cd724ce3cb176295784cce3f36f02f277bafb20` |
| five tray wall carrier | `f5264c40-b09d-4c23-adaa-6a1a7e11bce2` | `c3179a89-62e2-4d61-b3dc-a36f4b9956b6` | `a563cdaa0ab0bf0a884a4a75e060c00f15e2f1e7289e4bc569552a0187ef5437` |
| screw lid container | `f2c0c3f1-9647-4321-95c3-2c1627b302a5` | `c3179a89-62e2-4d61-b3dc-a36f4b9956b6` | `18912e963a0fd30357e760e3947154f2da1b6e18232e21b3a405f0c7403d625f` |

## Models and identical settings

- Provider: `gemini_api`.
- Configured geometry model: `gemini-3.5-flash-lite`.
- Stronger available comparison model: `gemini-3.5-flash`.
- Temperature: `0.2`.
- Thinking: `minimal`.
- Output-token allowance: `8192`.
- Provider retry limit: `2`.
- CAD worker, source contract, scaffold, topology, and artifact gates were shared.
- Git HEAD: `ffe1f6abeb02ae7d335d9f6476d87886b472f66a`; migration head: `0032_provider_response_lifecycle`.
- Base configuration hash: `e02d4ec2634bb1438b94334b0b1f5f51fc30a2eeaca642daa87ca21c5180440a`.

## Strategies

### A — current contract pipeline

The existing compact Plan, GeometryExecutionContext, provider contract
manifest, source authority, structured geometry-body schema, scaffold, source
safety, topology, and worker path were reused unchanged.

### B — simplified Volundr-owned execution brief

The provider saw only frozen requirements, proposals, ordered component/output
slots, functional features, frames, dimensions, qualitative review items,
optional controls, and STEP/STL/BREP requirements. Volundr assigned stable
identities, function mappings, signatures, scaffold metadata, validation, and
artifact handling. The response parser accepted only ordered temporary
`function_N` definitions and mapped them to the existing scaffold.

Both strategies retained source safety, lexical validation, worker isolation,
topology checks, and diagnostic-only non-promotion.

## All 24 initial attempt results

The table records every initial cell. A repair is an additional bounded call,
not another matrix cell.

| # | family | strategy | model | response | source | worker | result | repair | solids | artifacts | latency ms | total tokens |
|---:|---|---|---|---|---|---|---|---:|---:|---|---:|---:|
| 1 | desktop organizer | A | configured | invalid contract response | no | not reached | not started | no | 0 | — | 6285 | 46854 |
| 2 | desktop organizer | A | configured | invalid contract response | no | not reached | not started | no | 0 | — | 4068 | 47298 |
| 3 | desktop organizer | A | stronger | invalid contract response | no | not reached | not started | no | 0 | — | 10694 | 47552 |
| 4 | desktop organizer | A | stronger | invalid contract response | no | not reached | not started | no | 0 | — | 7914 | 47590 |
| 5 | desktop organizer | B | configured | valid response | yes | reached | succeeded | no | 1 | STEP/STL/BREP | 3694 | 3906 |
| 6 | desktop organizer | B | configured | valid response | yes | reached | succeeded | no | 1 | STEP/STL/BREP | 4287 | 4138 |
| 7 | desktop organizer | B | stronger | invalid contract response | no | not reached | not started | no | 0 | — | 6596 | 4729 |
| 8 | desktop organizer | B | stronger | invalid contract response | no | not reached | not started | no | 0 | — | 6213 | 4666 |
| 9 | five tray wall carrier | A | configured | valid response | yes | reached | failed | no | 1 | STEP/STL/BREP | 3614 | 42100 |
| 10 | five tray wall carrier | A | configured | valid response | yes | reached | failed | no | 1 | STEP/STL/BREP | 3413 | 42319 |
| 11 | five tray wall carrier | A | stronger | valid response | yes | reached | succeeded | no | 2 | STEP/STL/BREP | 15763 | 42458 |
| 12 | five tray wall carrier | A | stronger | valid response | yes | reached | failed | yes | 0 | — | 15058 | 41897 |
| 13 | five tray wall carrier | B | configured | valid response | yes | reached | succeeded | no | 2 | STEP/STL/BREP | 5426 | 3468 |
| 14 | five tray wall carrier | B | configured | valid response | yes | reached | failed | no | 1 | STEP/STL/BREP | 3785 | 4199 |
| 15 | five tray wall carrier | B | stronger | invalid contract response | no | not reached | not started | no | 0 | — | 13284 | 5112 |
| 16 | five tray wall carrier | B | stronger | invalid contract response | no | not reached | not started | no | 0 | — | 12820 | 5343 |
| 17 | screw lid container | A | configured | invalid contract response | no | not reached | not started | no | 0 | — | 5220 | 41367 |
| 18 | screw lid container | A | configured | valid response | no | not reached | not started | no | 0 | — | 4774 | 41387 |
| 19 | screw lid container | A | stronger | invalid contract response | no | not reached | not started | no | 0 | — | 8300 | 41540 |
| 20 | screw lid container | A | stronger | invalid contract response | no | not reached | not started | no | 0 | — | 9021 | 41731 |
| 21 | screw lid container | B | configured | invalid contract response | no | not reached | not started | no | 0 | — | 2889 | 3508 |
| 22 | screw lid container | B | configured | invalid contract response | no | not reached | not started | no | 0 | — | 4154 | 3901 |
| 23 | screw lid container | B | stronger | invalid contract response | no | not reached | not started | no | 0 | — | 5857 | 4149 |
| 24 | screw lid container | B | stronger | invalid contract response | no | not reached | not started | no | 0 | — | 5645 | 4071 |

## Cross-cell summary

| family | strategy | model | attempts | valid response | valid source | worker reached | worker success | candidates | repairs | valid solids |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| desktop organizer | A — current contract | stronger | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| desktop organizer | A — current contract | configured | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| desktop organizer | B — simplified brief | stronger | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| desktop organizer | B — simplified brief | configured | 2 | 2 | 2 | 2 | 2 | 2 | 0 | 2 |
| five tray wall carrier | A — current contract | stronger | 2 | 2 | 2 | 2 | 1 | 1 | 1 | 2 |
| five tray wall carrier | A — current contract | configured | 2 | 2 | 2 | 2 | 0 | 0 | 0 | 2 |
| five tray wall carrier | B — simplified brief | stronger | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| five tray wall carrier | B — simplified brief | configured | 2 | 2 | 2 | 2 | 1 | 1 | 0 | 3 |
| screw lid container | A — current contract | stronger | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| screw lid container | A — current contract | configured | 2 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| screw lid container | B — simplified brief | stronger | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| screw lid container | B — simplified brief | configured | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Repair behavior

Only one initial attempt met the bounded probe rule: a worker traceback named
one provider-owned function. It was matrix cell 12 (wall carrier, Strategy A,
stronger model). The single repair reached the worker successfully and yielded
a diagnostic geometry candidate. No larger autonomous loop was enabled.

Required-feature evidence is intentionally conservative: the record proves
source-function presence and records worker/topology outputs, but it does not
claim semantic feature verification where the existing diagnostic run had no
independent feature measurement.

## Decision

**Classification: inconclusive.** Neither strategy nor model capability met the cross-model/cross-strategy decision threshold.

Primary observed blocker: the provider-to-contract boundary remains the
dominant failure surface—15 responses failed before source assembly, and only
8 of 24 initial cells reached the worker. However, the configured model showed
clear benefit from the simplified brief while the stronger model did not
produce usable simplified responses and did not dominate under the current
contract. That is not enough evidence to claim a contract architecture winner
or a model-capability winner across both models.

**Exactly one next direction: collect more evidence.**

The smallest useful follow-up is a bounded, repeated diagnostic comparison
focused on model/account availability and the two response-boundary patterns
seen here; it must remain outside normal project workflows. This is a data
collection decision, not an implementation decision in this run.


## Per-project comparison

| family | attempts | valid source | worker reached | worker success | candidates | primary observation |
|---|---:|---:|---:|---:|---:|---|
| desktop organizer | 8 | 2 | 2 | 2 | 2 | B/configured succeeded twice; A/configured and both stronger cells stopped at response/contract validation. |
| five tray wall carrier | 8 | 6 | 6 | 2 | 2 | A and B reached the worker for configured; stronger A reached twice and one succeeded; B/stronger stopped at response validation. |
| screw lid container | 8 | 0 | 0 | 0 | 0 | Only one configured A response reached source assembly, but failed source validation before worker; no screw-lid cell produced a worker submission. |

## Findings and limitations

| finding/error | count |
|---|---:|
| `diagnostic.response_contract` | 15 |
| `geometry_body.unbound_name` | 3 |
| `cadquery.contract` | 2 |
| Geometry body references undeclared parameter `corner_radius`. | 4 |
| simplified function function_1 has unsupported arguments | 4 |
| simplified response function count does not match ordered function slots | 2 |
| Geometry body references undeclared parameter `base_thickness`. | 2 |
| simplified functions may not contain imports | 2 |
| Geometry function `_ai_feature_lid_grip_ribs_feature` cannot declare functions, classes, or imports. | 1 |

- The two successful configured simplified organizer cells and four total
  worker-successful simplified/current cells are evidence of reachability, not
  product acceptance; no normal revision was promoted.
- The stronger model’s invalid ordered-function responses are a model/contract
  interaction signal, not proof that the account model is intrinsically weaker.
- The worker-successful geometry candidates do not establish functional
  correctness, print suitability, load-bearing safety, or watertightness.
- The monitor-wall-mount safety boundary is retained: geometry/workflow
  evaluation never implies physical load-bearing safety.
- No screenshots or frontend network evidence belong to this diagnostic;
  those categories are explicitly marked not applicable in the record.
