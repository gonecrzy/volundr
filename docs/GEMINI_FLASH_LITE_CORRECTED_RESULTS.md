# Corrected Gemini Flash Lite results

These results are derived offline from all 60 captured project records.

The subsequent profile-ablation evidence is a separate experiment and does
not alter these corrected results. Its Phase 1 matrix was quota-interrupted
after 18 of 30 calls; no profile was adopted and no Phase 2 project comparison
ran. See GEMINI_PROFILE_ABLATION_RESULTS.md.

| Metric | Baseline | Validation |
| --- | ---: | ---: |
| Projects | 30 | 30 |
| Captured provider calls | 119 | 117 |
| Worker reached | 13 | 14 |
| Worker completed | 4 | 4 |
| Worker-ready valid source | 13 | 14 |
| Accepted topology-valid revisions | 1 | 2 |
| Candidate-ready or warning | 1 | 2 |
| Measured feature evidence | 0 | 0 |
| Terminal projects | 29 | 28 |
| Earliest blocker signatures | 29 | 28 |

The source metric is intentionally named “worker-ready valid source”: it
requires source-contract validation and worker submission. It does not count a
syntactically valid intermediate response.

## Three-repetition consistency

| Stage | Baseline | Validation | Interpretation |
| --- | ---: | ---: | --- |
| Requirements | 0.125 | 0.050 | materially variable |
| Clarification | 0.850 | 0.825 | comparatively stable |
| Planning | 0.950 | 0.925 | stable |
| Response structure | 0.075 | 0.200 | materially variable |
| Execution | 0.175 | 0.550 | variable |
| Topology | 0.900 | 0.900 | comparatively stable among reached cases |
| Verification | 0.950 | 0.975 | stable as a recorded state |
| Final outcome | 0.475 | 0.625 | variable |

The topology and verification scores are conditional on reaching those stages;
they do not imply that most projects reached them.

## Blocker reconciliation

Every terminal project has exactly one earliest blocker. The corrected reports
contain the normalized categories and totals in
`reports/failure-signatures/{baseline,validation}.json`; each total equals
the terminal-project count for its round.

## Case consistency

Using the eight semantic comparison dimensions, the most consistent baseline
case was case-002 and the least consistent was case-001. In validation, the
most consistent was case-009 and the least consistent was case-001. These are
descriptive rankings of repeated captured behavior, not controlled estimates
of provider variance.
