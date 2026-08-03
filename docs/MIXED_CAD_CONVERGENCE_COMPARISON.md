# Mixed-CAD convergence comparison

The qualifying pair is controlled.

- Baseline: `mixed-cad-convergence-01`
  (`c3179a89-62e2-4d61-b3dc-a36f4b9956b6`)
- Candidate: `mixed-cad-convergence-02`
  (`2d3b976c-ea46-4f37-9ecf-659c6b7a8510`)
- Comparison status: `controlled`
- Identity match: `true`
- Mismatches: none

The comparison matched Git HEAD, migration head, provider, configured model,
stage model policy, prompt versions, configuration hash, and backend, frontend,
and worker build identities. Both batches contained the same five ordered
prompt positions. The captured identity used Git HEAD
`5ea71c0cd1b1f3538a5106d5aa21077eb0bcbb4c`, migration head
`0032_provider_response_lifecycle`, and clean component builds.

The pair shows no valid geometry or promotion in either run. Both reached the
worker once, so worker reach was not the differentiator. Batch 1 had four
pre-worker blocks and one post-worker block. Batch 2 reported three
pre-worker blocks, one post-worker block, and one `Not started` outcome, while
the preserved attempt chain proves that the fifth project had generation
activity. That discrepancy is an integrity/state-classification defect and is
the only controlled-pair result that should be treated as a misleading-state
candidate rather than a product-family CAD finding.

This comparison is evidence collection only. It does not authorize fixes,
provider retries, workflow reruns, geometry regeneration, or a new live run.
