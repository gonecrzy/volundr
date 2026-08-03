# Mixed-CAD convergence Batch 2

Batch 2 is frozen. It repeated the same five prompts, fact-sheet answers,
provider/model, policy, schema, retry settings, and component identities as
Batch 1 without applying fixes between runs.

- Label: `mixed-cad-convergence-02`
- Batch ID: `2d3b976c-ea46-4f37-9ecf-659c6b7a8510`
- Raw evidence: `/tmp/volundr-live-e2e.wt83N9/data/debug-sessions/2d3b976c-ea46-4f37-9ecf-659c6b7a8510/`
- Baseline: `c3179a89-62e2-4d61-b3dc-a36f4b9956b6`

## Batch metrics

| Metric | Result |
| --- | ---: |
| Projects created and ordered | 5 |
| Provider calls | 17 |
| Provider retries | 0 |
| Bounded content repairs | 2 |
| Requirements completed | 5 |
| Worker reached | 1 |
| Geometry generated | 1 |
| Valid geometry | 0 |
| Source contracts passed | 3 |
| Promotions | 0 |
| Exports | 0 |
| Reported blocked before worker | 3 |
| Reported blocked after worker | 1 |
| Reported not started | 1 |

## Project outcomes

1. Wall carrier — blocked before worker after a semantic-incomplete
   requirements response and later design-artifact/source inconsistency.
2. Portable holder — reached the worker but failed output-shape/topology checks;
   the candidate was blocked.
3. Desktop organizer — blocked before worker after a source-generation
   provider-content failure.
4. Monitor wall mount — blocked before worker after provenance-invalid Plan
   content and a regressive bounded repair.
5. Screw-lid container — the report says `Not started`, but preserved attempt
   evidence contains source-generation attempts, including a final attempt that
   remained `started`. This is recorded as an integrity/misleading-state
   finding, not as evidence that no work occurred.

The monitor project remains a geometry/workflow evaluation only and does not
carry a load-bearing safety claim.

Screenshots are retained outside Git in the batch `screenshots/` directory,
including initial, clarification, final, drawer, finish-confirmation, summary,
and comparison states. Raw evidence stays local and outside Git.
