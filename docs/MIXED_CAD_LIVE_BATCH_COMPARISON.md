# Mixed CAD live batch comparison

Batch 2 claims a controlled comparison against Batch 1.

## Control decision

Status: **controlled**.

The comparison artifact is preserved at:

`<VOLUNDR_LIVE_DATA_DIR>/data/debug-sessions/1ec92524-0401-40a2-a0e1-077cb8c52f57/comparison/comparison.json`

All required identities matched and the artifact recorded no mismatches:

- Git HEAD: `unknown` in both runtime captures
- migration head: `0028_debug_batches`
- provider/model policy: `gemini_api` / `gemini-3.5-flash-lite`
- prompt versions: matching
- configuration hash: matching
- backend build: `unknown` in both runtime captures
- frontend build: `frontend-dev`
- worker build: `cad-worker-v1`

All five ordered membership positions matched. The `unknown` Git/backend
values are an observability limitation and should be replaced by release
identities before a future production-quality evaluation.

## Aggregate delta

| Measure | Batch 1 | Batch 2 |
| --- | ---: | ---: |
| Projects | 5 | 5 |
| Requirements completed | 5 | 5 |
| Worker reached | 3 | 1 |
| Blocked after worker | 3 | 1 |
| Blocked before worker | 2 | 4 |
| Valid geometry | 0 | 0 |
| Exports | 0 | 0 |
| Clarification rounds | 0 | 0 |
| Duplicate messages | 0 | 0 |
| Frontend errors | 0 | 0 |

The runs show substantial provider/runtime variability in stopping stage, but
neither produced a successful geometry result. This comparison must not be
interpreted as a product-quality win or regression from two all-failure samples.

The portable-holder prompt reached different failure stages. Organizer and
screw-lid prompts exposed repeated identity/provenance and contract weaknesses
with different manifestations. The monitor mount produced no geometry result
and carries no load-bearing safety implication.

No source, prompt, provider/model, environment, policy, container image,
schema, or retry-policy change was made between the frozen runs.
