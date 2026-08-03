# Mixed-CAD convergence Batch 1

Batch 1 is frozen. It is the first qualifying unchanged run of the five
mixed-CAD prompts after the generic provider-response convergence pass.

- Label: `mixed-cad-convergence-01`
- Batch ID: `c3179a89-62e2-4d61-b3dc-a36f4b9956b6`
- Raw evidence: `/tmp/volundr-live-e2e.wt83N9/data/debug-sessions/c3179a89-62e2-4d61-b3dc-a36f4b9956b6/`
- Source/build identity: Git HEAD `5ea71c0cd1b1f3538a5106d5aa21077eb0bcbb4c`
- Migration head: `0032_provider_response_lifecycle`
- Provider/model: `gemini_api` / `gemini-3.5-flash-lite`

## Batch metrics

| Metric | Result |
| --- | ---: |
| Projects created and ordered | 5 |
| Provider calls | 18 |
| Provider retries | 0 |
| Bounded content repairs | 4 |
| Requirements completed | 5 |
| Worker reached | 1 |
| Geometry generated | 1 |
| Valid geometry | 0 |
| Source contracts passed | 3 |
| Promotions | 0 |
| Exports | 0 |
| Blocked before worker | 4 |
| Blocked after worker | 1 |

## Project outcomes

1. Wall carrier — blocked before worker after provider-content convergence
   stopped at the design-artifact/source boundary.
2. Portable holder — blocked before worker. The generated drainage-hole
   function failed source extraction; the bounded repair was unchanged and
   correctly stopped.
3. Desktop organizer — blocked before worker after the geometry-body response
   contained invalid JSON escaping and the repair did not produce an accepted
   artifact.
4. Monitor wall mount — blocked before worker after an invalid Design Plan.
5. Screw-lid container — reached the worker but remained blocked by the
   lid-grip-ribs source/worker path and candidate classification.

The monitor project remains a geometry/workflow evaluation only. Nothing in
this result implies load-bearing safety; physical engineering and test review
are required before use.

Screenshots are retained outside Git in the batch `screenshots/` directory,
including initial, clarification, final, drawer, finish-confirmation, and
summary states. The authoritative raw evidence remains local and outside Git.
